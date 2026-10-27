"""공식 Qwen VLM 빌드와 HailoRT 버전에 맞는 모델 경로."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex


MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
DEFAULT_MODEL = "qwen3-vl-2b"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    builds: tuple[str, ...]

    @property
    def filename(self) -> str:
        return f"{self.name}.hef"

    def check_runtime(self, runtime: str) -> None:
        if runtime not in self.builds:
            raise ValueError(
                f"{self.name}: 등록된 HEF 빌드의 HailoRT 버전은 "
                f"{', '.join(self.builds)}입니다. 현재 Python SDK는 {runtime}입니다. "
                "공식 모델 목록에서 호환 빌드를 확인하세요."
            )

    def path(self, runtime: str) -> Path:
        self.check_runtime(runtime)
        return MODEL_DIR / runtime / self.filename

    def url(self, runtime: str) -> str:
        self.check_runtime(runtime)
        return f"https://dev-public.hailo.ai/v{runtime}/blob/{self.filename}"


# 이 장비에서 사용하는 HailoRT 5.4.0용 공식 GenAI Model Zoo 빌드만 등록.
MODELS = {
    "qwen3-vl-2b": ModelSpec("Qwen3-VL-2B-Instruct", ("5.4.0",)),
}


def runtime_version() -> str:
    """디바이스를 초기화하지 않고 설치된 Python SDK 버전을 읽는다."""
    try:
        import hailo_platform
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "Hailo Python SDK를 불러올 수 없습니다. ./run.sh로 실행하고 "
            "프로젝트 .venv의 SDK와 네이티브 HailoRT 버전이 같은지 확인하세요."
        ) from error
    return str(hailo_platform.__version__)


def download_instructions(model: str, runtime: str, path: Path | None = None) -> str:
    spec = MODELS[model]
    target = path if path is not None else spec.path(runtime)
    return (
        f"mkdir -p {shlex.quote(str(target.parent))}\n"
        f"curl --fail --location --continue-at - --output {shlex.quote(str(target))} "
        f"{shlex.quote(spec.url(runtime))}"
    )
