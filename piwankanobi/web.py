"""Image chat and a stateless JSON-RPC 2.0 interface to one warm Hailo VLM."""

from __future__ import annotations

import atexit
import base64
import binascii
from concurrent.futures import Future, TimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
import json
import logging
import math
from pathlib import Path
from queue import Queue
import re
import tempfile
from threading import Lock, Thread
import time

from flask import Flask, Response, jsonify, request, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge

from . import __version__
from .models import DEFAULT_MODEL, MODELS

LOG = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 12 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_MESSAGES = 16
MAX_TEXT_CHARS = 6000
MAX_BATCH = 8
_IMAGE_URI = re.compile(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)\Z")
_FORMATS = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}


class RPCError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def response(self, request_id):
        error = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[dict, ...]
    image: bytes | None
    max_tokens: int
    temperature: float


def validate_chat(params: dict) -> ChatRequest:
    if set(params) - {"messages", "image", "max_tokens", "temperature"}:
        raise RPCError(-32602, "Unknown chat parameter")
    messages = params.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise RPCError(-32602, f"messages must contain 1–{MAX_MESSAGES} messages")
    total = 0
    normalized = []
    for message in messages:
        if (not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")
                or not isinstance(message["content"], str)
                or not message["content"].strip()):
            raise RPCError(-32602, "Each message needs role user/assistant and nonempty text content")
        total += len(message["content"])
        normalized.append({"role": message["role"], "content": message["content"]})
    if messages[0]["role"] != "user" or messages[-1]["role"] != "user":
        raise RPCError(-32602, "The first and last messages must be from the user")
    if total > MAX_TEXT_CHARS:
        raise RPCError(-32602, f"Conversation exceeds {MAX_TEXT_CHARS} characters")
    max_tokens = params.get("max_tokens", 128)
    if type(max_tokens) is not int or not 1 <= max_tokens <= 256:
        raise RPCError(-32602, "max_tokens must be an integer from 1 to 256")
    temperature = params.get("temperature", 0.2)
    if type(temperature) not in (int, float) or not 0.05 <= temperature <= 1.0:
        raise RPCError(-32602, "temperature must be a number from 0.05 to 1.0")

    image_bytes = None
    image = params.get("image")
    if image is not None:
        if not isinstance(image, str) or len(image) > 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 32:
            raise RPCError(-32602, "image must be a PNG, JPEG or WebP data URI of at most 8 MiB")
        match = _IMAGE_URI.fullmatch(image)
        if match is None:
            raise RPCError(-32602, "image must be a base64 PNG, JPEG or WebP data URI")
        try:
            image_bytes = base64.b64decode(match[2], validate=True)
            if len(image_bytes) > MAX_IMAGE_BYTES:
                raise ValueError("image too large")
            with Image.open(BytesIO(image_bytes)) as decoded:
                if decoded.format != _FORMATS[match[1]]:
                    raise ValueError("image MIME type does not match its contents")
                if decoded.width * decoded.height > MAX_IMAGE_PIXELS:
                    raise ValueError("image exceeds 16 megapixels")
                decoded.verify()
            # verify() does not fully decode every format (notably JPEG).
            with Image.open(BytesIO(image_bytes)) as decoded:
                decoded.load()
        except (ValueError, binascii.Error, UnidentifiedImageError, OSError,
                Image.DecompressionBombError) as error:
            raise RPCError(-32602, "Invalid image; use PNG/JPEG/WebP, at most 8 MiB and 16 megapixels") from error
    return ChatRequest(tuple(normalized), image_bytes, max_tokens, float(temperature))


class _ContextResetError(Exception):
    pass


@contextmanager
def _open_default_session(*, model):
    # Import and native device initialization both happen on the inference thread.
    from .vlm import open_vlm
    with open_vlm(model=model) as session:
        yield session


class InferenceEngine:
    """The worker owns all SDK calls; one request is admitted at a time."""

    def __init__(self, model=DEFAULT_MODEL, *, session_factory=None, timeout=180):
        if model not in MODELS:
            raise ValueError(f"Unknown model: {model}")
        self.model = model
        self.timeout = timeout
        self._factory = session_factory or _open_default_session
        self._lock = Lock()
        self._state = "loading"
        self._closed = False
        self._jobs = Queue(maxsize=1)
        self._thread = Thread(target=self._work, name="piwankanobi-inference", daemon=True)
        self._thread.start()

    def status(self):
        with self._lock:
            return {"state": self._state, "model": self.model}

    def chat(self, chat: ChatRequest):
        future = Future()
        with self._lock:
            if self._state != "ready" or self._closed:
                raise RPCError(-32001, "Model is not available for a new request", {"state": self._state})
            self._state = "busy"
            self._jobs.put_nowait((chat, future))
        try:
            return future.result(timeout=self.timeout)
        except TimeoutError as error:
            # The worker finishes/reset its current request before accepting another.
            raise RPCError(-32003, "Inference timed out; retry when the model is ready") from error

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._state = "stopped"
            # No queued user jobs exist once busy work has begun.
            if self._jobs.empty():
                self._jobs.put_nowait(None)
        self._thread.join(timeout=10)

    def _work(self):
        try:
            with self._factory(model=self.model) as session:
                with self._lock:
                    if self._closed:
                        return
                    self._state = "ready"
                while True:
                    job = self._jobs.get()
                    if job is None:
                        break
                    chat, future = job
                    fatal = False
                    try:
                        result = self._infer(session, chat)
                        failure = None
                    except _ContextResetError:
                        LOG.error("VLM context reset failed; model worker disabled")
                        failure = RPCError(-32002, "Model context reset failed; restart the service")
                        fatal = True
                    except Exception as error:
                        LOG.error("VLM inference failed (%s)", type(error).__name__)
                        failure = RPCError(-32002, "Inference failed; shorten the conversation or retry")
                    with self._lock:
                        self._state = "error" if fatal else ("stopped" if self._closed else "ready")
                        closed = self._closed
                    if failure is not None:
                        future.set_exception(failure)
                    else:
                        future.set_result(result)
                    if fatal or closed:
                        break
        except Exception as error:
            LOG.error("VLM initialization/shutdown failed (%s)", type(error).__name__)
            with self._lock:
                self._state = "stopped" if self._closed else "error"

    def _infer(self, session, chat: ChatRequest):
        start = time.monotonic()
        try:
            session.reset()
        except Exception as error:
            raise _ContextResetError from error
        try:
            prompt = [{"role": "system", "content": [
                {"type": "text", "text": session.system_prompt},
            ]}]
            for index, message in enumerate(chat.messages):
                content = [{"type": "text", "text": message["content"]}]
                if index == 0 and chat.image is not None:
                    content.insert(0, {"type": "image"})
                prompt.append({"role": message["role"], "content": content})
            frames = []
            if chat.image is not None:
                with tempfile.TemporaryDirectory(prefix="piwankanobi-image-") as directory:
                    path = Path(directory) / "image.png"
                    with Image.open(BytesIO(chat.image)) as image:
                        ImageOps.exif_transpose(image).convert("RGB").save(path, format="PNG")
                    frames.append(session.preprocess_image(path))
            raw = session.vlm.generate_all(
                prompt=prompt, frames=frames, temperature=chat.temperature,
                max_generated_tokens=chat.max_tokens, seed=42, do_sample=True,
                top_p=None, top_k=None, frequency_penalty=None,
                timeout_ms=int(self.timeout * 1000),
            )
            # Keep the SDK wrapper's output cleanup without importing it in HTTP tests.
            for marker in ("<|im_end|>", ". [{'type'", "<|endoftext|>"):
                raw = raw.split(marker, 1)[0]
            return {
                "message": {"role": "assistant", "content": raw.strip()},
                "model": self.model,
                "elapsed_seconds": round(time.monotonic() - start, 3),
            }
        finally:
            try:
                session.reset()
            except Exception as error:
                raise _ContextResetError from error


def create_app(engine=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.json.ensure_ascii = False
    if engine is None:
        engine = InferenceEngine()
        atexit.register(engine.close)
    app.extensions["inference_engine"] = engine
    project = Path(__file__).resolve().parent.parent
    static = Path(__file__).resolve().parent / "static"

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api/") or request.path == "/rpc":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return send_from_directory(static, "index.html")

    @app.get("/static/<filename>")
    def static_file(filename):
        if filename not in {"app.css", "app.js"}:
            return "Not found", 404
        return send_from_directory(static, filename)

    @app.get("/samples/apple.png")
    def sample_image():
        return send_from_directory(project / "samples", "apple.png")

    def information():
        return {"name": "piwankanobi", "version": __version__,
                "jsonrpc": "2.0", "methods": ["system.info", "vlm.chat"],
                "limits": {"max_messages": MAX_MESSAGES, "max_text_chars": MAX_TEXT_CHARS,
                           "max_image_bytes": MAX_IMAGE_BYTES, "max_image_pixels": MAX_IMAGE_PIXELS,
                           "max_tokens": 256, "max_batch": MAX_BATCH},
                **engine.status()}

    @app.get("/api/health")
    def health():
        status = engine.status()
        ok = status["state"] in ("ready", "busy")
        return jsonify({"ok": ok, "version": __version__, **status}), 200 if ok else 503

    @app.get("/api/version")
    def version():
        return jsonify({"name": "piwankanobi", "version": __version__})

    @app.get("/api/help")
    def help_page():
        return Response(_HELP, content_type="text/html; charset=utf-8")

    def dispatch(envelope):
        if (not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0"
                or not isinstance(envelope.get("method"), str)):
            return RPCError(-32600, "Invalid Request").response(None)
        request_id = envelope.get("id")
        if (request_id is not None and type(request_id) not in (str, int, float)):
            return RPCError(-32600, "Invalid Request id").response(None)
        notification = "id" not in envelope
        try:
            params = envelope.get("params", {})
            if not isinstance(params, dict):
                raise RPCError(-32602, "Named object params are required")
            if envelope["method"] == "system.info":
                if params:
                    raise RPCError(-32602, "system.info takes no parameters")
                result = information()
            elif envelope["method"] == "vlm.chat":
                result = engine.chat(validate_chat(params))
            else:
                raise RPCError(-32601, "Method not found")
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RPCError as error:
            response = error.response(request_id)
        except Exception as error:
            LOG.error("RPC dispatch failed (%s)", type(error).__name__)
            response = RPCError(-32603, "Internal error").response(request_id)
        return None if notification else response

    @app.post("/rpc")
    def rpc():
        if not request.is_json:
            return jsonify(RPCError(-32600, "Use Content-Type: application/json").response(None)), 415
        try:
            def reject_constant(value):
                raise ValueError("Non-finite JSON number")
            def finite_float(value):
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("Non-finite JSON number")
                return number
            envelope = json.loads(request.get_data(), parse_constant=reject_constant,
                                  parse_float=finite_float)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return jsonify(RPCError(-32700, "Parse error").response(None))
        if isinstance(envelope, list):
            if not envelope or len(envelope) > MAX_BATCH:
                return jsonify(RPCError(-32600, f"Batch must contain 1–{MAX_BATCH} requests").response(None))
            responses = [result for item in envelope if (result := dispatch(item)) is not None]
            return jsonify(responses) if responses else ("", 204)
        response = dispatch(envelope)
        return jsonify(response) if response is not None else ("", 204)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify(RPCError(-32600, "Request exceeds 12 MiB").response(None)), 413

    return app


_HELP = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PiWanKanobi RPC API</title>
<style>body{max-width:850px;margin:40px auto;padding:0 20px;font:16px/1.65 system-ui}
pre{background:#f3f5f6;padding:18px;overflow:auto}code{font-size:14px}</style>
<a href="../">← 이미지 채팅</a><h1>PiWanKanobi JSON-RPC 2.0</h1>
<p>동일 서비스의 <code>POST /rpc</code>에 JSON을 보냅니다. WorkGate 경로로 접근할 때는
서비스 경로 뒤에 <code>rpc</code>를 붙이세요. 인증 토큰 없이 사용하는 공개 데모 API입니다.</p>
<h2>vlm.chat</h2><pre>{
  "jsonrpc": "2.0", "id": 1, "method": "vlm.chat",
  "params": {
    "messages": [{"role": "user", "content": "이 이미지에 무엇이 있나요?"}],
    "image": "data:image/png;base64,...",
    "max_tokens": 128, "temperature": 0.2
  }
}</pre>
<p><code>image</code>는 생략할 수 있습니다. PNG/JPEG/WebP, 최대 8 MiB·16메가픽셀입니다.
후속 질문은 같은 이미지와 전체 대화 기록(user/assistant)을 다시 보냅니다.
이미지는 첫 user 메시지에 연결됩니다. 서버는 요청 사이에 대화를 보관하지 않습니다.
대화는 16개 메시지·총 6,000자, 출력은 1~256토큰입니다. 실제 모델 문맥 한도가 더 작을 수 있습니다.</p>
<pre>{"jsonrpc":"2.0","id":1,"result":{
  "message":{"role":"assistant","content":"빨간 사과입니다."},
  "model":"qwen3-vl-2b","elapsed_seconds":2.3
}}</pre>
<h2>Python 예제</h2><pre>import base64, json, urllib.request

base_url = "http://192.168.0.213/piwankanobi/"  # 데모의 주소, 마지막 / 포함
with open("image.png", "rb") as image:
    image_uri = "data:image/png;base64," + base64.b64encode(image.read()).decode()
payload = {"jsonrpc": "2.0", "id": 1, "method": "vlm.chat", "params": {
    "messages": [{"role": "user", "content": "사진을 설명해 주세요."}],
    "image": image_uri}}
request = urllib.request.Request(base_url + "rpc", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=180) as response:
    print(json.load(response))
</pre>
<h2>상태 조회</h2><pre>curl -X POST "$BASE_URL/rpc" -H 'Content-Type: application/json' \\
  --data '{"jsonrpc":"2.0","id":1,"method":"system.info"}'</pre>
<p>HTTP 상태: <code>GET /api/health</code>, 버전: <code>GET /api/version</code>.
오류 -32001은 로딩/다른 요청 처리 중/사용 불가, -32002는 추론 실패,
-32003은 시간 초과입니다. 준비된 상태에서 다시 요청하세요.</p>
<p>동시에 한 요청을 처리합니다. batch는 최대 8개를 순서대로 처리합니다.
id를 생략한 notification에는 HTTP 204를 반환합니다.</p>
<p><a href="https://www.jsonrpc.org/specification">JSON-RPC 2.0 공식 명세</a></p></html>"""
