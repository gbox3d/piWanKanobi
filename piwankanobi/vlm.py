"""Hailo-10H NPU 기반 Qwen VLM 추론 래퍼.

`hailo_platform.genai.VLM` (HailoRT 5.4.0) 위에 얇은 편의 레이어를 둡니다.
이미지는 모델의 shape/dtype에 맞춰 RGB NHWC/RGB888 형식으로 변환됩니다.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

# hailo_platform은 네이티브 HailoRT와 같은 버전의 SDK 환경에서 불러옵니다.
# run.sh는 프로젝트 가상환경을 사용합니다.
from hailo_platform import FormatOrder, VDevice     # type: ignore[import-not-found]
from hailo_platform.genai import VLM as _HailoVLM   # type: ignore[import-not-found]

from .models import DEFAULT_MODEL, MODELS, download_instructions, runtime_version

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that analyzes images and answers questions about them. "
    "Answer concisely in the user's language."
)


# HailoRT 는 temperature == 0.0 을 HAILO_INVALID_ARGUMENT 로 거부합니다.
# 사용자가 결정적 출력을 원할 때 0 을 넘기는 실수를 막기 위해 클램프.
_TEMPERATURE_FLOOR = 0.05
_RESPONSE_END_MARKERS = ("<|im_end|>", ". [{'type'", "<|endoftext|>")


@dataclass
class GenerationConfig:
    """샘플링 파라미터 묶음."""

    temperature: float = 0.2
    top_p: float | None = None
    top_k: int | None = None
    max_generated_tokens: int = 256
    seed: int | None = 42
    do_sample: bool = True
    frequency_penalty: float | None = None

    def safe_temperature(self) -> float:
        return max(float(self.temperature), _TEMPERATURE_FLOOR)


@dataclass
class VLMSession:
    """대화 컨텍스트를 유지하는 단일 VLM 세션."""

    vlm: _HailoVLM
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    @property
    def input_shape(self) -> tuple[int, int, int]:
        """모델이 요구하는 (H, W, C)."""
        h, w, c = self.vlm.input_frame_shape()
        return int(h), int(w), int(c)

    @property
    def input_dtype(self) -> np.dtype:
        return np.dtype(self.vlm.input_frame_format_type())

    def preprocess_image(self, image_path: str | Path) -> np.ndarray:
        """이미지를 모델이 기대하는 shape/dtype/색 순서로 변환."""
        img = cv2.imread(str(image_path))
        if img is None:
            raise FileNotFoundError(f"이미지를 열 수 없습니다: {image_path}")

        h, w, c = self.input_shape
        if c != 3:
            raise ValueError(f"RGB 이미지 입력만 지원합니다: 모델 채널 수={c}")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)
        img = img.astype(self.input_dtype, copy=False)

        order = self.vlm.input_frame_format_order()
        if order not in (FormatOrder.NHWC, FormatOrder.RGB888):
            raise ValueError(f"지원하지 않는 모델 입력 형식입니다: {order}")
        return np.ascontiguousarray(img)

    def _build_prompt(self, user_text: str, with_image: bool) -> list[dict]:
        content: list[dict] = []
        if with_image:
            content.append({"type": "image"})
        content.append({"type": "text", "text": user_text})

        messages: list[dict] = []
        # Hailo VLM이 장치에서 히스토리를 유지하므로 새 메시지만 보냅니다.
        # 시스템 메시지는 빈 컨텍스트에서만 허용됩니다.
        if self.system_prompt and self.vlm.get_context_usage_size() == 0:
            messages.append({
                "role": "system",
                "content": [{"type": "text", "text": self.system_prompt}],
            })
        messages.append({"role": "user", "content": content})
        return messages

    def ask(
        self,
        text: str,
        image_path: str | Path | None = None,
        config: GenerationConfig | None = None,
    ) -> str:
        """1-턴 질의 → 전체 응답 문자열 반환 (블로킹)."""
        cfg = config or GenerationConfig()
        frames: list[np.ndarray] = []
        if image_path is not None:
            frames.append(self.preprocess_image(image_path))

        prompt = self._build_prompt(text, with_image=bool(frames))
        raw = self.vlm.generate_all(
            prompt=prompt,
            frames=frames,
            temperature=cfg.safe_temperature(),
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            frequency_penalty=cfg.frequency_penalty,
            max_generated_tokens=cfg.max_generated_tokens,
            do_sample=cfg.do_sample,
            seed=cfg.seed,
        )
        return _clean_response(raw)

    def stream(
        self,
        text: str,
        image_path: str | Path | None = None,
        config: GenerationConfig | None = None,
    ) -> Iterator[str]:
        """1-턴 질의 → 토큰 스트림 (제너레이터)."""
        cfg = config or GenerationConfig()
        frames: list[np.ndarray] = []
        if image_path is not None:
            frames.append(self.preprocess_image(image_path))

        prompt = self._build_prompt(text, with_image=bool(frames))
        with self.vlm.generate(
            prompt=prompt,
            frames=frames,
            temperature=cfg.safe_temperature(),
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            frequency_penalty=cfg.frequency_penalty,
            max_generated_tokens=cfg.max_generated_tokens,
            do_sample=cfg.do_sample,
            seed=cfg.seed,
        ) as gen:
            pending = ""
            ended = False
            for token in gen:
                if ended:
                    # 출력은 끝났어도 SDK 생성기를 끝까지 소비합니다.
                    continue
                pending += token
                positions = [pending.find(marker) for marker in _RESPONSE_END_MARKERS]
                marker_at = min((pos for pos in positions if pos >= 0), default=-1)
                if marker_at >= 0:
                    ended = True
                    if marker_at:
                        yield pending[:marker_at]
                    pending = ""
                    continue

                # 청크 경계에서 끝 토큰이 잘릴 수 있으므로 일치하는 접미사만 보관합니다.
                keep = 0
                for marker in _RESPONSE_END_MARKERS:
                    for length in range(1, min(len(marker), len(pending) + 1)):
                        if pending.endswith(marker[:length]):
                            keep = max(keep, length)
                ready = len(pending) - keep
                if ready:
                    yield pending[:ready]
                    pending = pending[ready:]
            if pending and not ended:
                yield pending

    def reset(self) -> None:
        """NPU 측 대화 컨텍스트를 비웁니다. 실패하면 예외를 전달합니다."""
        self.vlm.clear_context()


def _clean_response(raw: str) -> str:
    """Hailo VLM 응답에서 채팅 토큰 잔재를 제거."""
    if not raw:
        return ""
    for sep in _RESPONSE_END_MARKERS:
        idx = raw.find(sep)
        if idx != -1:
            raw = raw[:idx]
    return raw.strip()


@contextmanager
def open_vlm(
    hef_path: str | Path | None = None,
    *,
    model: str = DEFAULT_MODEL,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    optimize_memory_on_device: bool = False,
) -> Iterator[VLMSession]:
    """`with open_vlm(...) as session:` 패턴으로 사용.

    기본 HEF는 Python SDK 버전에 맞게 선택합니다.
    VDevice / VLM 자원 정리를 자동으로 처리합니다.
    """
    if model not in MODELS:
        raise ValueError(f"지원하지 않는 모델입니다: {model}. 선택: {', '.join(MODELS)}")
    runtime = runtime_version()
    spec = MODELS[model]
    spec.check_runtime(runtime)
    hef = Path(hef_path).expanduser() if hef_path is not None else spec.path(runtime)
    if not hef.is_file():
        raise FileNotFoundError(
            f"HEF 파일이 없습니다: {hef}\n"
            "다음 명령으로 받으세요:\n" + download_instructions(model, runtime, hef)
        )

    params = VDevice.create_params()
    # Hailo-apps 의 SHARED_VDEVICE_GROUP_ID 값과 동일.
    params.group_id = "SHARED"
    with VDevice(params) as vdevice:
        with _HailoVLM(vdevice, str(hef), optimize_memory_on_device=optimize_memory_on_device) as vlm:
            yield VLMSession(vlm=vlm, system_prompt=system_prompt)


__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "GenerationConfig",
    "VLMSession",
    "open_vlm",
]
