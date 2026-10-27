#!/usr/bin/env bash
# piWanKanobi 런처 — HailoRT 5.4.0 SDK가 설치된 프로젝트 가상환경으로 실행.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$HERE/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "프로젝트 가상환경이 없습니다: $PYTHON (docs/setup-hailort-5.4.0.md 참고)" >&2
    exit 2
fi
exec "$PYTHON" "$HERE/main.py" "$@"
