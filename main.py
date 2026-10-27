#!/usr/bin/env python3
"""piWanKanobi 진입점.

현재 5.4.0 SDK가 설치된 프로젝트 가상환경으로 실행합니다:

    .venv/bin/python main.py --image sample.jpg --prompt "이 사진 설명해줘"

또는 셸 래퍼:

    ./run.sh --image sample.jpg --prompt "이 사진 설명해줘"
"""

from piwankanobi.cli import run


if __name__ == "__main__":
    raise SystemExit(run())
