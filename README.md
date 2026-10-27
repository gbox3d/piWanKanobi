# piWanKanobi

Raspberry Pi 5 + **Hailo-10H**에서 Qwen Vision Language Model을 직접 실행하는 챗봇입니다. 웹 채팅에서 이미지를 넣고 질문하거나, 다른 앱에서 JSON-RPC API로 같은 모델을 사용할 수 있습니다. CLI와 Python API도 제공합니다.

**제작: gbox3d · 버전: 0.3.0 · 문서 갱신: 2026-10-26**

현재 구성은 **HailoRT 5.4.0 + Qwen3-VL-2B-Instruct**입니다. SDK·드라이버·펌웨어 모두 5.4.0이며, 사과 이미지에 한국어로 답하는 것을 실제 NPU에서 확인했습니다. [설치·검증 기록](docs/setup-hailort-5.4.0.md)을 참고하세요.

## 웹 데모와 공용 RPC API

| 용도 | 이 장비의 LAN 주소 |
|---|---|
| 이미지 채팅 | <http://192.168.0.213/piwankanobi/> |
| JSON-RPC 2.0 | `POST http://192.168.0.213/piwankanobi/rpc` |
| API 사용법 | <http://192.168.0.213/piwankanobi/api/help> |
| 서비스 상태 | <http://192.168.0.213/piwankanobi/api/health> |

이미지를 선택·끌어놓기·붙여넣기 한 뒤 질문합니다. 사과 예제 버튼으로도 시작할 수 있습니다. 같은 이미지에 후속 질문을 이어가고, 이미지를 바꾸면 새 대화가 시작됩니다.

WorkGate에 `piwankanobi`로 등록되어 있습니다. 2026-10-13 최초 배포에서는 systemd로 실행했으며, 2026-10-26 PM2 프로세스 `piwankanobi`로 전환했습니다. PM2 재시작 후 모델 준비, 헬스 HTTP 200, 버전 0.3.0과 실제 이미지 RPC 응답을 확인하고 부팅 복원 목록을 저장했습니다. WorkGate 관리 방식도 PM2로 변경했습니다.

웹 화면과 다른 앱이 함께 `vlm.chat` RPC를 사용합니다. 서버는 요청마다 NPU 컨텍스트를 초기화하므로 API 호출자는 **같은 이미지와 전체 대화 기록**을 매번 보냅니다. 모델은 메모리에 유지하며, 한 번에 한 추론을 처리합니다. 토큰 인증 없이 사용하는 공개 데모 API입니다. [RPC 명세·Python 예제·배포 방법](docs/rpc-api.md)

기존 Hailo 5.4.0 가상환경에서 웹 서비스를 PM2로 실행하려면:

```bash
.venv/bin/python -m pip install -e '.[web]'
pm2 start deploy/ecosystem.config.cjs --only piwankanobi
pm2 save
```

직결 주소는 `http://127.0.0.1:3010/`이며, nginx의 `/piwankanobi/` 경로로 LAN에 연결합니다. [PM2 설정](deploy/ecosystem.config.cjs), [nginx 설정 조각](deploy/nginx-piwankanobi.conf), [WorkGate 등록 manifest](deploy/workgate.json)를 제공합니다. 이 호스트의 기존 `pm2-goback.service`가 저장된 PM2 프로세스를 부팅 때 복원합니다. 이전 전용 systemd 서비스는 중복 실행을 막기 위해 중지·비활성화했으며, [설정 파일](deploy/piwankanobi.service)은 복구 참고용으로 보관합니다. [PM2 전환 절차](docs/rpc-api.md#2026-10-26-pm2-전환)를 참고하세요.

상태는 `pm2 status piwankanobi`, 로그는 `pm2 logs piwankanobi`, 재시작은 `pm2 restart piwankanobi`로 확인·관리합니다. 같은 NPU를 사용하는 CLI·Python 추론을 실행하려면 먼저 `pm2 stop piwankanobi`로 웹 서비스를 멈추고, 작업 후 `pm2 start piwankanobi`로 다시 시작하세요.

## 현재 장비와 지원 범위

| 항목 | 현재 장비에서 확인한 값 |
|---|---|
| 호스트 | Raspberry Pi 5, RAM 8 GiB, aarch64 |
| 가속기 | Hailo-10H, AI HAT+ 2 계열 |
| OS | Debian 13 (trixie), kernel 6.12.75+rpt-rpi-2712 |
| Python | Python 3.13, 프로젝트 `.venv` (`--system-site-packages`) |
| HailoRT / 드라이버 / 펌웨어 | 5.4.0 |
| 런타임 / Python SDK | `/opt/hailort/5.4.0` / `.venv`의 `hailort` 5.4.0 |
| 기본 모델 | Qwen3-VL-2B-Instruct, A16W4, 컨텍스트 2048 |
| Qwen3 HEF | 3,185,773,502 bytes, 약 3.19 GB / 2.97 GiB |
| 장치 노드 | `/dev/h1x-0` |

Raspberry Pi 공식 Trixie arm64 저장소의 Hailo-10 패키지는 **5.1.1**이므로(2026-10-12 확인), 공식 5.4.0 소스를 빌드해 설치했습니다. 프로젝트는 `.venv`의 SDK만 사용합니다. 배포판 Hailo-10 패키지는 설치·제거 스크립트가 `/lib/firmware/hailo/`와 `hailo1x_pci` DKMS를 직접 바꾸므로, apt로 설치하거나 지우면 5.4.0 드라이버·펌웨어가 덮어써지거나 삭제됩니다. 5.1.1 패키지 정리는 [별도 절차](docs/setup-hailort-5.4.0.md#배포판-511-패키지-정리)를 따릅니다.

모델은 `--model qwen3-vl-2b`(기본값, **Qwen3-VL-2B-Instruct**) 하나만 등록되어 있습니다. Qwen2.5-VL과 Qwen3.5 이후 모델은 공식 Hailo HEF가 없으며(2026-10-12 확인), 원본 모델이 공개되어 있어도 HEF가 없으면 이 NPU에서 실행할 수 없습니다. Qwen3.5-2B/4B는 별도 CPU 환경에서 품질·속도를 비교할 후보입니다. 한국어 사과 질문에는 맞게 답했지만 전반적인 정확도는 별도 평가가 필요합니다.

## 먼저 상태 확인

```bash
./run.sh --list-models
./run.sh --doctor
```

`--list-models`는 Hailo SDK 없이도 지원 모델을 보여줍니다. `--doctor`는 추론 없이 Python 의존성, 런타임, 장치와 모델 경로를 점검합니다. 실제 모델 로드·응답 품질을 검증하는 명령은 아닙니다.

직접 장치와 API를 확인하려면:

```bash
hailortcli fw-control identify
.venv/bin/python -c "from hailo_platform.genai import VLM; print(VLM)"
```

## 새 장비 설치

Raspberry Pi 5 + **64비트 Raspberry Pi OS Trixie** 기준입니다. 배포판 Hailo-10 패키지(`hailo-h10-all`, 5.1.1)는 설치하지 않고, HailoRT·드라이버·펌웨어 5.4.0을 [소스 설치 기록](docs/setup-hailort-5.4.0.md)대로 설치합니다. 프로젝트가 쓰는 시스템 패키지는 다음과 같습니다.

```bash
sudo apt update
sudo apt install dkms python3-opencv python3-numpy python3-pil
```

런타임·Python SDK·드라이버·펌웨어·HEF는 모두 같은 HailoRT 버전이어야 합니다. 설치 후 `hailortcli fw-control identify`로 펌웨어 5.4.0을 확인합니다. [Raspberry Pi 공식 설치 문서](https://www.raspberrypi.com/documentation/computers/ai.html)

## 모델 파일

기본 경로는 `models/<런타임 버전>/<공식 모델명>.hef`입니다. Qwen3 파일을 준비하는 명령이며, 이 장비에는 이미 다운로드되어 있습니다.

```bash
mkdir -p models/5.4.0
curl --fail -L -C - --progress-bar -o models/5.4.0/Qwen3-VL-2B-Instruct.hef \
  https://dev-public.hailo.ai/v5.4.0/blob/Qwen3-VL-2B-Instruct.hef
./run.sh --doctor
```

HEF는 같은 HailoRT 버전용 빌드만 동작합니다. 모델이 없으면 CLI가 설치된 런타임에 맞는 다운로드 명령을 안내합니다. 공식 빌드는 [버전별 Hailo 모델 목록](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.4.0/docs/MODELS.rst)에서 확인합니다. `--hef`를 지정하면 해당 파일을 사용하며, 설치된 런타임과 맞는 빌드인지 사용자가 확인해야 합니다.

## 실행

샘플 이미지를 분석:

```bash
./run.sh --image samples/apple.png --prompt "이 그림에 뭐가 보이고 어떤 글자가 적혀있어?"
```

대화 모드에서는 첫 질문에 이미지를 사용하고, 다음 질문부터 텍스트로 이어갑니다. 질문은 실행 후 `나>`에 입력합니다.

```bash
./run.sh --chat --image samples/apple.png
```

이미지 없이 텍스트 질문:

```bash
./run.sh --prompt "라즈베리파이 5와 Hailo-10H의 차이를 한 줄로 요약해줘."
```

주요 옵션:

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--model` | `qwen3-vl-2b` | 지원 모델 선택 |
| `--list-models` | off | 지원 모델과 필요 런타임 표시 |
| `--doctor` | off | 추론 없이 환경 점검 |
| `--hef` | 런타임과 모델에 따라 결정 | 직접 사용할 HEF 경로 |
| `--image / -i` | 없음 | 이미지 경로; 생략하면 텍스트 전용 |
| `--prompt / -p` | `이 이미지를 한국어로 자세히 설명해줘.` | 단일 질의 프롬프트 |
| `--chat` | off | 대화 모드; Ctrl-D 또는 빈 입력으로 종료 |
| `--max-tokens` | 256 | 최대 생성 토큰 수 |
| `--temperature` | 0.2 | 샘플링 온도 |
| `--top-p`, `--top-k` | 모델 기본값 | 샘플링 컷오프 |
| `--seed` | 42 | 샘플링 시드 |
| `--system` | 기본 시스템 프롬프트 | 시스템 메시지 지정 |
| `--no-stream` | off | 단일 질의에서 답변을 한 번에 출력 |

## Python API

```python
from piwankanobi.vlm import GenerationConfig, open_vlm

with open_vlm() as session:
    print(session.input_shape, session.input_dtype)
    answer = session.ask(
        "이 사진에서 사람은 몇 명 있어?",
        image_path="some.jpg",
        config=GenerationConfig(temperature=0.1, max_generated_tokens=128),
    )
    print(answer)
    print(session.ask("그 중 어른은 몇 명이야?"))
```

NPU가 같은 세션의 대화 문맥을 유지합니다. 후속 질의에서는 새 메시지만 보내고, 새 대화를 시작할 때 `session.reset()`으로 초기화합니다.

스트리밍:

```python
with open_vlm() as session:
    for token in session.stream("뭐가 보여?", image_path="foo.jpg"):
        print(token, end="", flush=True)
```

`open_vlm(hef_path="...")`로 HEF 파일을 직접 지정할 수 있습니다.

## 성능과 제한

Qwen3-VL-2B의 5.4.0 공식 수치는 로드 7.02초, TTFT 1.47초, **4.74 tok/s**입니다(A16W4). 제조사 자료이며 이 Pi에서 측정한 값이 아닙니다. Hailo 빌드의 컨텍스트는 2048이며, 이 CLI는 단일 이미지 입력을 제공합니다. [5.4.0 공식 성능 표](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.4.0/docs/MODELS.rst)

## 자주 묻는 것

**어떤 Python으로 실행하나요?**  
`run.sh`는 프로젝트 `.venv/bin/python`으로 실행합니다. 이 환경에는 5.4.0 SDK를 설치했고, `--system-site-packages`로 시스템 패키지(OpenCV, NumPy, Pillow, Flask)를 함께 사용합니다. `.venv`가 없으면 실행하지 않고 안내를 출력합니다. Python API 예제도 `.venv/bin/python`으로 실행하세요.

**Hailo-Ollama로 이미지 질문을 할 수 있나요?**  
아니요. 5.4.0 공식 사용 설명은 Hailo-Ollama REST API를 LLM 전용으로 제한하고 VLM은 지원하지 않는다고 명시합니다. 이 프로젝트의 웹·RPC 서비스는 직접 `hailo_platform.genai.VLM`을 호출해 이미지 질문을 처리합니다. [공식 API 제한](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.4.0/docs/USAGE.rst)

## 검증

2026-10-12 Qwen3에 `samples/apple.png`와 `이 그림의 과일과 색을 짧게 알려줘.`를 입력해 **“이 그림은 빨간색의 사과를 그렸습니다.”**라는 답변을 확인했습니다. 첫 로드 25.45초, 생성 6.25초였으며 짧은 샘플의 실측값입니다. 후속 대화와 초기화 검증은 [설치 검증 기록](docs/setup-hailort-5.4.0.md#모델과-실행-확인)을 참고하세요.

2026-10-13 웹 서비스의 실제 이미지 RPC에서도 한국어로 빨간 사과를 설명하는 답변을 확인했으며, 해당 요청의 처리 시간은 6.191초였습니다. 모델은 서비스에서 계속 로드한 상태로 사용합니다.

실제 브라우저에서도 이미지 업로드와 후속 질문을 확인했습니다. 다만 질문 표현을 바꾸자 같은 사과 그림을 오렌지로 오인한 답변이 나왔습니다(첫 답변 7.753초, 후속 답변 5.552초). 연결·대화 기능은 동작하지만 모델의 이미지 인식과 지시 준수에는 한계가 있습니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

자동 테스트는 35개입니다(CLI·세션 22개, 웹·RPC 13개). 세션·이미지 테스트는 SDK와 OpenCV/NumPy를 사용하지만 NPU를 열지 않습니다. 웹 테스트는 가짜 추론 엔진으로 이미지·요청 검증, 후속 대화, 요청 간 격리, 동시 요청 거절, 시간 초과 후 정리를 확인합니다. 장치 진단은 5.4 드라이버의 `/dev/h1x-0`를 확인합니다. 배포 후 HTTP 확인 명령은 [RPC 문서](docs/rpc-api.md#배포-후-확인)에 있습니다.

## 참고 자료

- [웹 채팅과 JSON-RPC API](docs/rpc-api.md)
- [HailoRT 5.4.0 설치·검증 기록](docs/setup-hailort-5.4.0.md)
- [Raspberry Pi AI HAT 사양](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html)
- [Raspberry Pi AI 소프트웨어 설치](https://www.raspberrypi.com/documentation/computers/ai.html)
- [HailoRT 5.4.0 공개판](https://github.com/hailo-ai/hailort/releases/tag/v5.4.0)
- [Hailo Model Zoo GenAI 5.4.0](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.4.0/docs/MODELS.rst)
