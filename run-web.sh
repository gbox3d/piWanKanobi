#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$HERE/.venv/bin/gunicorn" ]]; then
    echo "웹 의존성을 설치하세요: .venv/bin/python -m pip install -e '.[web]'" >&2
    exit 2
fi
# NPU 모델은 단일 worker에 상주하며 요청을 한 번에 하나씩 처리합니다.
exec "$HERE/.venv/bin/gunicorn" \
    --chdir "$HERE" \
    --bind "127.0.0.1:${PIWANKANOBI_PORT:-3010}" \
    --workers 1 --threads 4 --timeout 240 --graceful-timeout 30 \
    --access-logfile - --error-logfile - \
    'piwankanobi.web:create_app()'
