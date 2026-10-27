"""piWanKanobi CLI — Hailo-10H 위에서 Qwen VLM 추론."""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .models import DEFAULT_MODEL, MODELS, download_instructions, runtime_version

if TYPE_CHECKING:
    from .vlm import GenerationConfig


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="piwankanobi",
        description="Hailo-10H NPU 위에서 Qwen3-VL 을 돌리는 VLM 챗봇.",
    )
    p.add_argument("--model", choices=MODELS, default=DEFAULT_MODEL, help="사용할 Qwen VLM")
    p.add_argument("--hef", help="직접 준비한 호환 HEF 경로 (기본: SDK 버전에 맞는 경로)")
    p.add_argument("--list-models", action="store_true", help="모델별 공식 HEF 빌드 목록")
    p.add_argument("--doctor", action="store_true", help="의존성·SDK·디바이스·모델 확인 (추론 없음)")
    p.add_argument("--image", "-i", help="질의할 이미지 경로 (없으면 텍스트 전용)")
    p.add_argument(
        "--prompt",
        "-p",
        default="이 이미지를 한국어로 자세히 설명해줘.",
        help="사용자 프롬프트",
    )
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--top-p", type=float, default=None)
    p.add_argument("--top-k", type=int, default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--system",
        default=None,
        help="시스템 프롬프트 오버라이드",
    )
    p.add_argument(
        "--no-stream",
        action="store_true",
        help="스트리밍 비활성화 (모든 토큰을 다 받은 뒤 한꺼번에 출력)",
    )
    p.add_argument(
        "--chat",
        action="store_true",
        help="대화 모드: 첫 턴에 이미지를 받고 이후 텍스트로 반복 질의 (Ctrl-D 종료)",
    )
    return p


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.list_models:
        for alias, spec in MODELS.items():
            print(f"{alias}: {spec.name} — HailoRT {', '.join(spec.builds)}")
        return 0
    if args.doctor:
        return _doctor(args)

    try:
        runtime = runtime_version()
        spec = MODELS[args.model]
        spec.check_runtime(runtime)
        hef = Path(args.hef).expanduser() if args.hef else spec.path(runtime)
        if not hef.is_file():
            print(f"[error] HEF 파일이 없습니다: {hef}", file=sys.stderr)
            print(download_instructions(args.model, runtime, hef), file=sys.stderr)
            return 2
        from .vlm import GenerationConfig, open_vlm
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(f"[error] {error}", file=sys.stderr)
        return 2

    cfg = GenerationConfig(
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        max_generated_tokens=args.max_tokens,
        seed=args.seed,
    )

    kwargs = {"hef_path": hef, "model": args.model}
    if args.system is not None:
        kwargs["system_prompt"] = args.system

    print(f"[1/3] Hailo-10H 디바이스 초기화 중…", flush=True)
    t0 = time.perf_counter()
    with open_vlm(**kwargs) as session:
        t_init = time.perf_counter() - t0
        h, w, c = session.input_shape
        print(
            f"      ✓ 초기화 완료 ({t_init:.2f}s) — 입력 shape=({h}x{w}x{c}) dtype={session.input_dtype}",
            flush=True,
        )

        if args.chat:
            _chat_loop(session, args, cfg)
            return 0

        print(f"[2/3] 프롬프트: {args.prompt!r}")
        if args.image:
            print(f"      이미지: {args.image}")
        print(f"[3/3] 추론 시작 (NPU)…\n")
        t0 = time.perf_counter()
        if args.no_stream:
            answer = session.ask(args.prompt, image_path=args.image, config=cfg)
            print(answer)
        else:
            for tok in session.stream(args.prompt, image_path=args.image, config=cfg):
                print(tok, end="", flush=True)
            print()
        t_gen = time.perf_counter() - t0
        print(f"\n[done] {t_gen:.2f}s ({cfg.max_generated_tokens} max tokens)")
    return 0


def _doctor(args) -> int:
    """모델을 로드하지 않고 현재 호스트의 실행 준비 상태를 확인."""
    ok = True
    print(f"Python: {sys.executable}")
    for name in ("numpy", "cv2"):
        try:
            module = importlib.import_module(name)
            print(f"[ok] {name}: {module.__version__}")
        except (ImportError, OSError) as error:
            print(f"[error] {name}: {error}")
            ok = False
    devices = sorted(Path("/dev").glob("h1x-[0-9]*"))
    print(f"[{'ok' if devices else 'error'}] Hailo device: {', '.join(map(str, devices)) or '없음'}")
    ok = ok and bool(devices)
    try:
        runtime = runtime_version()
        print(f"[ok] HailoRT Python SDK: {runtime}")
        spec = MODELS[args.model]
        spec.check_runtime(runtime)
        hef = Path(args.hef).expanduser() if args.hef else spec.path(runtime)
        print(f"Model: {spec.name}")
        print(f"[{'ok' if hef.is_file() else 'error'}] HEF: {hef}")
        if not hef.is_file():
            print(download_instructions(args.model, runtime, hef))
            ok = False
    except (RuntimeError, ValueError) as error:
        print(f"[error] {error}")
        ok = False
    print("장치 펌웨어 확인: hailortcli fw-control identify")
    return 0 if ok else 2


def _chat_loop(session, args, cfg: GenerationConfig) -> None:
    image_path = args.image
    if image_path:
        print(f"[chat] 첫 턴에 이미지를 사용합니다: {image_path}")
    print("[chat] 메시지를 입력하세요 (Ctrl-D 또는 빈 줄이면 종료)")
    first = True
    try:
        while True:
            try:
                line = input("\n나> ")
            except EOFError:
                break
            line = line.strip()
            if not line:
                break
            print("AI> ", end="", flush=True)
            t0 = time.perf_counter()
            img = image_path if first else None
            for tok in session.stream(line, image_path=img, config=cfg):
                print(tok, end="", flush=True)
            dt = time.perf_counter() - t0
            print(f"\n   [{dt:.2f}s]")
            first = False
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    sys.exit(run())
