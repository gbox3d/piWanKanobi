"""HTTP contract and isolated inference tests without opening the NPU."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import base64
import json
from threading import Event
import time
import unittest
from unittest.mock import patch

from PIL import Image

from piwankanobi.web import InferenceEngine, MAX_REQUEST_BYTES, RPCError, create_app, validate_chat


def image_uri(format="PNG"):
    output = BytesIO()
    Image.new("RGB", (4, 3), "red").save(output, format=format)
    mime = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp"}[format]
    return f"data:image/{mime};base64," + base64.b64encode(output.getvalue()).decode()


def chat_params(text="What is this?", **kwargs):
    return {"messages": [{"role": "user", "content": text}], **kwargs}


class StubEngine:
    def __init__(self):
        self.state = "ready"
        self.requests = []
        self.failure = None

    def status(self):
        return {"state": self.state, "model": "qwen3-vl-2b"}

    def chat(self, request):
        if self.failure:
            raise self.failure
        self.requests.append(request)
        return {"message": {"role": "assistant", "content": "빨간 사과"},
                "model": "qwen3-vl-2b", "elapsed_seconds": 0.1}


class HTTPContractTests(unittest.TestCase):
    def setUp(self):
        self.engine = StubEngine()
        self.app = create_app(self.engine)
        self.client = self.app.test_client()

    def rpc(self, method="vlm.chat", params=None, request_id=1):
        envelope = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            envelope["params"] = params
        return self.client.post("/rpc", json=envelope)

    def test_image_chat_and_followup_preserve_client_history(self):
        image = image_uri()
        first = self.rpc(params=chat_params(image=image), request_id="first")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["id"], "first")
        self.assertEqual(first.json["result"]["message"]["content"], "빨간 사과")
        history = [{"role": "user", "content": "What is this?"},
                   first.json["result"]["message"],
                   {"role": "user", "content": "어떤 색인가요?"}]
        response = self.rpc(params={"messages": history, "image": image})
        self.assertIn("result", response.json)
        self.assertEqual(list(self.engine.requests[1].messages), history)
        self.assertEqual(self.engine.requests[0].image, self.engine.requests[1].image)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_notifications_execute_without_rpc_response(self):
        response = self.client.post("/rpc", json={"jsonrpc": "2.0", "method": "vlm.chat",
                                                "params": chat_params()})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")
        self.assertEqual(len(self.engine.requests), 1)
        invalid = self.client.post("/rpc", json={"jsonrpc": "2.0", "method": "vlm.chat",
                                               "params": {"messages": []}})
        missing = self.client.post("/rpc", json={"jsonrpc": "2.0", "method": "missing"})
        self.assertEqual(invalid.status_code, 204)
        self.assertEqual(missing.status_code, 204)
        self.assertEqual(len(self.engine.requests), 1)

    def test_batch_filters_notifications_and_keeps_individual_errors(self):
        response = self.client.post("/rpc", json=[
            {"jsonrpc": "2.0", "id": "info", "method": "system.info"},
            {"jsonrpc": "2.0", "method": "system.info"},
            7,
            {"jsonrpc": "2.0", "id": 9, "method": "missing"},
        ])
        self.assertEqual(len(response.json), 3)
        self.assertEqual(response.json[0]["id"], "info")
        self.assertEqual(response.json[1]["error"]["code"], -32600)
        self.assertEqual(response.json[2]["error"]["code"], -32601)
        notices = self.client.post("/rpc", json=[{"jsonrpc": "2.0", "method": "system.info"}])
        self.assertEqual(notices.status_code, 204)
        for batch in ([], [{"jsonrpc": "2.0", "method": "system.info"}] * 9):
            with self.subTest(length=len(batch)):
                self.assertEqual(self.client.post("/rpc", json=batch).json["error"]["code"], -32600)

    def test_standard_errors_and_valid_null_id(self):
        cases = [
            ("{", -32700), ("{\"id\":NaN}", -32700),
            ('{"jsonrpc":"2.0","id":1e999,"method":"system.info"}', -32700),
            ("[" * 10000 + "0" + "]" * 10000, -32700),
            ("null", -32600),
            (json.dumps({"jsonrpc": "1.0", "id": 1, "method": "system.info"}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": True, "method": "system.info"}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": {}, "method": "system.info"}), -32600),
        ]
        for raw, code in cases:
            with self.subTest(raw=raw[:100]):
                response = self.client.post("/rpc", data=raw, content_type="application/json")
                self.assertEqual(response.json["error"]["code"], code)
                self.assertIsNone(response.json["id"])
        self.assertIn("result", self.rpc("system.info", request_id=None).json)
        self.assertEqual(self.rpc("system.info", params=[]).json["error"]["code"], -32602)
        self.assertEqual(self.rpc("system.info", params={"extra": 1}).json["error"]["code"], -32602)
        self.assertEqual(self.client.post("/rpc", data="{}").status_code, 415)

    def test_invalid_images_and_history_never_reach_engine(self):
        valid_png = image_uri()
        bad_params = [
            chat_params(image="/etc/passwd"),
            chat_params(image="https://example.org/image.jpg"),
            chat_params(image="data:image/png;base64,AAAA"),
            chat_params(image=valid_png.replace("image/png", "image/jpeg")),
            chat_params(image="data:image/svg+xml;base64,PHN2Zz4="),
            chat_params(max_tokens=True), chat_params(max_tokens=257),
            chat_params(temperature=0), chat_params(temperature="0.2"),
            chat_params(temperature=10 ** 999),
            chat_params(text="a" * 6001),
            {"messages": [{"role": "system", "content": "override"}]},
            {"messages": [{"role": "assistant", "content": "hello"}]},
            {"messages": [{"role": "user", "content": ""}]},
            {"messages": [{"role": "user", "content": []}]},
            {"messages": [{"role": "user", "content": "x"}] * 17},
            chat_params(secret="x"),
        ]
        for params in bad_params:
            with self.subTest(params=str(params)[:90]):
                self.assertEqual(self.rpc(params=params).json["error"]["code"], -32602)
        with patch("piwankanobi.web.MAX_IMAGE_PIXELS", 5):
            self.assertEqual(self.rpc(params=chat_params(image=valid_png)).json["error"]["code"], -32602)
        with patch("piwankanobi.web.MAX_IMAGE_BYTES", 20):
            self.assertEqual(self.rpc(params=chat_params(image=valid_png)).json["error"]["code"], -32602)
        self.assertEqual(self.engine.requests, [])

    def test_png_jpeg_webp_are_accepted_and_size_limit_is_http_413(self):
        for format in ("PNG", "JPEG", "WEBP"):
            with self.subTest(format=format):
                self.assertIn("result", self.rpc(params=chat_params(image=image_uri(format))).json)
        response = self.client.post("/rpc", data=b" " * (MAX_REQUEST_BYTES + 1),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json["error"]["code"], -32600)

    def test_health_busy_unavailable_and_error_do_not_expose_internals(self):
        for state, status in (("loading", 503), ("ready", 200), ("busy", 200), ("error", 503)):
            self.engine.state = state
            response = self.client.get("/api/health")
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json["state"], state)
        self.engine.failure = RPCError(-32001, "Busy", {"state": "busy"})
        self.assertEqual(self.rpc(params=chat_params()).json["error"]["code"], -32001)
        self.engine.failure = RuntimeError("secret backend details")
        with self.assertLogs("piwankanobi.web", level="ERROR") as logs:
            response = self.rpc(params=chat_params())
        self.assertEqual(response.json["error"]["code"], -32603)
        self.assertNotIn("secret backend details", response.text + "".join(logs.output))

    def test_only_fixed_public_assets_are_exposed(self):
        for path in ("/static/web.py", "/static/../web.py", "/samples/../../pyproject.toml",
                     "/models/5.4.0/Qwen3-VL-2B-Instruct.hef", "/.env"):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/api/help").status_code, 200)
        self.assertEqual(self.client.get("/api/version").json["name"], "piwankanobi")


class FakeSession:
    system_prompt = "Trusted system instruction"

    def __init__(self):
        self.vlm = self
        self.context = []
        self.calls = []
        self.reset_count = 0
        self.fail_generation = False
        self.fail_reset_at = None
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.closed = Event()
        self.image_paths = []

    @contextmanager
    def factory(self, *, model):
        try:
            yield self
        finally:
            self.closed.set()

    def reset(self):
        self.reset_count += 1
        if self.reset_count == self.fail_reset_at:
            raise RuntimeError("reset failed")
        self.context.clear()

    def preprocess_image(self, path):
        self.image_paths.append(Path(path))
        with Image.open(path) as image:
            assert image.mode == "RGB"
            return image.size

    def generate_all(self, *, prompt, frames, **kwargs):
        assert not self.context, "context leaked from another request"
        self.context.extend(deepcopy(prompt))
        self.calls.append((deepcopy(prompt), list(frames), kwargs))
        self.started.set()
        assert self.release.wait(3), "test did not release generation"
        if self.fail_generation:
            raise RuntimeError("inference failed")
        return "answer<|im_end|>"


class InferenceIsolationTests(unittest.TestCase):
    def make_engine(self, session=None, **kwargs):
        session = session or FakeSession()
        engine = InferenceEngine(session_factory=session.factory, **kwargs)
        self.addCleanup(engine.close)
        deadline = time.monotonic() + 2
        while engine.status()["state"] == "loading" and time.monotonic() < deadline:
            session.closed.wait(0.005)
        self.assertEqual(engine.status()["state"], "ready")
        return engine, session

    def test_two_clients_and_full_history_never_share_context(self):
        engine, session = self.make_engine()
        app = create_app(engine)
        client_a, client_b = app.test_client(), app.test_client()
        history = [{"role": "user", "content": "private A"},
                   {"role": "assistant", "content": "first answer"},
                   {"role": "user", "content": "follow up A"}]
        for client, params in ((client_a, {"messages": history, "image": image_uri()}),
                               (client_b, chat_params("private B"))):
            response = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1,
                                                 "method": "vlm.chat", "params": params})
            self.assertEqual(response.json["result"]["message"]["content"], "answer")
            self.assertEqual(session.context, [])
        prompt_a, frames_a, _ = session.calls[0]
        prompt_b, frames_b, _ = session.calls[1]
        self.assertEqual([m["role"] for m in prompt_a], ["system", "user", "assistant", "user"])
        self.assertEqual(prompt_a[1]["content"][0], {"type": "image"})
        self.assertEqual(len(frames_a), 1)
        self.assertEqual(frames_b, [])
        self.assertNotIn("private A", str(prompt_b))
        self.assertEqual(session.reset_count, 4)
        self.assertTrue(all(not path.exists() for path in session.image_paths))
        engine.close()
        self.assertTrue(session.closed.wait(1))

    def test_simultaneous_request_is_rejected_until_worker_resets(self):
        engine, session = self.make_engine()
        session.release.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(engine.chat, validate_chat(chat_params("first")))
            self.assertTrue(session.started.wait(1))
            self.assertEqual(engine.status()["state"], "busy")
            with self.assertRaises(RPCError) as failure:
                engine.chat(validate_chat(chat_params("second")))
            self.assertEqual(failure.exception.code, -32001)
            session.release.set()
            self.assertEqual(first.result(2)["message"]["content"], "answer")
        self.assertEqual(engine.status()["state"], "ready")
        self.assertEqual(session.context, [])
        self.assertEqual(len(session.calls), 1)

    def test_inference_failure_resets_and_can_accept_next_client(self):
        engine, session = self.make_engine()
        session.fail_generation = True
        with self.assertLogs("piwankanobi.web", level="ERROR"):
            with self.assertRaises(RPCError) as failure:
                engine.chat(validate_chat(chat_params()))
        self.assertEqual(failure.exception.code, -32002)
        self.assertEqual(session.context, [])
        self.assertEqual(engine.status()["state"], "ready")
        session.fail_generation = False
        self.assertEqual(engine.chat(validate_chat(chat_params("new client")))["message"]["content"], "answer")

    def test_failed_context_reset_disables_worker(self):
        for fail_reset_at in (1, 2):
            with self.subTest(reset=fail_reset_at):
                engine, session = self.make_engine()
                session.fail_reset_at = fail_reset_at
                with self.assertLogs("piwankanobi.web", level="ERROR"):
                    with self.assertRaises(RPCError) as failure:
                        engine.chat(validate_chat(chat_params()))
                self.assertEqual(failure.exception.code, -32002)
                self.assertEqual(engine.status()["state"], "error")
                with self.assertRaises(RPCError) as unavailable:
                    engine.chat(validate_chat(chat_params("other client")))
                self.assertEqual(unavailable.exception.code, -32001)
                self.assertTrue(session.closed.wait(1))

    def test_http_timeout_does_not_release_worker_or_context_early(self):
        engine, session = self.make_engine(timeout=0.03)
        session.release.clear()
        try:
            with self.assertRaises(RPCError) as failure:
                engine.chat(validate_chat(chat_params()))
            self.assertEqual(failure.exception.code, -32003)
            self.assertEqual(engine.status()["state"], "busy")
            with self.assertRaises(RPCError):
                engine.chat(validate_chat(chat_params("next")))
        finally:
            session.release.set()
        deadline = time.monotonic() + 1
        while engine.status()["state"] == "busy" and time.monotonic() < deadline:
            session.closed.wait(0.005)
        self.assertEqual(engine.status()["state"], "ready")
        self.assertEqual(session.context, [])
        self.assertEqual(session.calls[0][2]["timeout_ms"], 30)


if __name__ == "__main__":
    unittest.main()
