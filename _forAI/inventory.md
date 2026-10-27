# Inventory

## 목차

- [Repository](#repository)
- [Top-level structure](#top-level-structure)
- [Entrypoints and key modules](#entrypoints-and-key-modules)
- [Build and validation commands](#build-and-validation-commands)
- [Tests](#tests)
- [Notes](#notes)

## Repository

- Name: `piWanKanobi`
- Path: `/home/goback/works/piWanKanobi`
- Summary: Raspberry Pi 5 + Hailo-10H NPU에서 Qwen3-VL-2B-Instruct를 실행하는 VLM 챗봇. 웹 이미지 채팅과 JSON-RPC API, CLI, Python API를 제공한다.

## Top-level structure

```
piWanKanobi/
├── piwankanobi/
│   ├── __init__.py        # __version__ (0.3.0)
│   ├── models.py          # 모델 레지스트리(qwen3-vl-2b, HailoRT 5.4.0), HEF 경로·URL, SDK 버전 확인
│   ├── vlm.py             # hailo_platform.genai.VLM 래퍼: open_vlm / VLMSession / GenerationConfig
│   ├── cli.py             # argparse CLI (--image / --prompt / --chat / --doctor / --list-models)
│   ├── web.py             # Flask 앱: 이미지 채팅 UI, JSON-RPC 2.0, /api/health·version·help
│   └── static/            # index.html, app.js, app.css (채팅 UI)
├── models/5.4.0/Qwen3-VL-2B-Instruct.hef   # 3.19 GB, gitignore
├── samples/               # apple / shapes / gradient / signs .png 테스트 이미지
├── tests/                 # test_cli_models.py, test_vlm.py, test_web.py (NPU 미사용)
├── docs/
│   ├── rpc-api.md         # RPC 계약, 오류 코드, 배포·확인 절차
│   └── setup-hailort-5.4.0.md  # 5.4.0 소스 설치·검증 기록, 배포판 5.1.1 패키지 정리 절차
├── deploy/                # piwankanobi.service, nginx-piwankanobi.conf, workgate.json
├── localfiles/            # 검증 산출물 (웹·브라우저 확인, verification/hailort-5.4.0 설치 기록), gitignore
├── _forAI/                # 본 문서 세트
├── main.py                # CLI 진입점 — piwankanobi.cli.run
├── run.sh                 # CLI 런처 (.venv/bin/python 필수)
├── run-web.sh             # 웹 런처 (gunicorn, 127.0.0.1:3010)
├── pyproject.toml         # dependencies = [], extra [web] = Flask, gunicorn
└── README.md              # 사용자용 가이드 (한글)
```

프로젝트 밖 관련 경로:

- `/opt/hailort/5.4.0` — 소스 빌드한 HailoRT 런타임과 `hailortcli` (`/usr/local/bin/hailortcli`가 가리킴). `dist/`에 재설치 자료(소스·DKMS·펌웨어 압축 파일, SDK wheel, `SHA256SUMS`)
- `/usr/src/hailo1x_pci-5.4.0` — DKMS 드라이버 소스
- `/lib/firmware/hailo/hailo10h` → `hailo10h-5.4.0` — 활성 펌웨어 링크
- `/etc/udev/rules.d/52-piwankanobi-hailo1x.rules` — `/dev/h1x-*` 접근 권한
- `/etc/systemd/system/piwankanobi.service` — 운영 서비스
- `/etc/apt/preferences.d/piwankanobi-hailo.pref` — 배포판 Hailo-10 패키지 재설치를 막는 apt pin (2026-10-26 `remove-hailo-5.1.1.sh`가 만듦). 배포판 패키지로 전환할 때만 지운다

## Entrypoints and key modules

- **웹·RPC 서비스**: `./run-web.sh` → `.venv/bin/gunicorn 'piwankanobi.web:create_app()'` (워커 1, 스레드 4, `127.0.0.1:3010`). systemd `piwankanobi.service`가 실행하고, nginx가 `/piwankanobi/`로 LAN에 연결한다. WorkGate에 `piwankanobi`로 등록되어 있다.
  - `POST /rpc` — JSON-RPC 2.0 `system.info`, `vlm.chat`
  - `GET /api/health`, `/api/version`, `/api/help`
- **CLI**: `./run.sh [options]` → `.venv/bin/python main.py` → `piwankanobi.cli:run`
- **Python API**:
  - `piwankanobi.vlm.open_vlm(hef_path=None, *, model="qwen3-vl-2b", ...)` — VDevice + VLM 자원을 정리하는 context manager
  - `piwankanobi.vlm.VLMSession` — `ask()` / `stream()` / `reset()`, `input_shape` / `input_dtype`
  - `piwankanobi.vlm.GenerationConfig` — 샘플링 파라미터. `safe_temperature()`가 0.05 미만을 클램프
- **모델 레지스트리**: `piwankanobi.models.MODELS` — `qwen3-vl-2b` 하나, 빌드 `5.4.0`. HEF 경로는 `models/<런타임 버전>/<모델명>.hef`

## Build and validation commands

```bash
# 웹 의존성 (Hailo SDK는 docs/setup-hailort-5.4.0.md대로 별도 설치)
.venv/bin/python -m pip install -e '.[web]'

# 환경 점검 (추론 없음)
./run.sh --list-models
./run.sh --doctor

# 자동 테스트 (NPU 미사용)
.venv/bin/python -m unittest discover -s tests -v

# 서비스 상태
systemctl status piwankanobi.service --no-pager
curl -sS http://127.0.0.1:3010/api/health
```

실제 추론은 운영 서비스가 NPU를 점유하므로 서비스를 멈춘 뒤 실행한다.

```bash
sudo systemctl stop piwankanobi.service
./run.sh --image samples/apple.png --prompt "이 그림의 과일과 색을 짧게 알려줘."
./run.sh --chat --image samples/apple.png
sudo systemctl start piwankanobi.service
```

## Tests

- 35개 (2026-10-26): `test_cli_models.py` 7, `test_vlm.py` 15, `test_web.py` 13.
- 세션·이미지 테스트는 SDK·OpenCV·NumPy를 쓰지만 NPU를 열지 않는다. 웹 테스트는 가짜 추론 엔진으로 요청 검증, 후속 대화, 요청 간 격리, 동시 요청 거절, 시간 초과 후 정리를 확인한다.
- 실제 NPU 추론과 응답 품질은 자동 테스트 범위 밖이다. 실측 기록은 README `검증` 절과 `docs/setup-hailort-5.4.0.md`에 있다.

## Notes

- `pyproject.toml`의 `dependencies = []`. Hailo SDK(`hailort` 5.4.0 wheel)와 gunicorn은 `.venv`에 있고, OpenCV·NumPy·Pillow·Flask는 시스템 apt 패키지를 `--system-site-packages`로 쓴다.
- `run.sh`는 `.venv/bin/python`이 없으면 안내를 출력하고 코드 2로 끝난다.
- `.python-version`(3.11)은 초기 `uv init`의 흔적이며 실행에 쓰이지 않는다.
- 카메라 입력은 미연결. RealSense 통합은 `plan.md` 참조.
