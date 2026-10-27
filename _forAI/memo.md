# Memo

## 목차

- [제품 기준선](#제품-기준선)
- [기본 설정값](#기본-설정값)
- [런타임 구조 메모](#런타임-구조-메모)
- [동작 규칙](#동작-규칙)
- [반복 금지](#반복-금지)
- [Hailo-10H에서 쓸 수 있는 VLM](#hailo-10h에서-쓸-수-있는-vlm)
- [RealSense (D435) 조사 메모](#realsense-d435-조사-메모)
- [외부 참조](#외부-참조)

## 제품 기준선

- 보드: Raspberry Pi 5 Model B Rev 1.0 (BCM2712, Cortex-A76 ×4 @ 2.4 GHz), RAM 8 GiB (zram 2 GiB swap)
- OS: Debian 13 (trixie), kernel `6.12.75+rpt-rpi-2712` aarch64
- NPU: Hailo-10H AI HAT+ 2 (PCIe `0001:01:00.0`, 드라이버 `hailo1x`, 장치 노드 `/dev/h1x-0`)
- HailoRT 5.4.0 — 런타임 `/opt/hailort/5.4.0` (소스 빌드), Python SDK는 `.venv`의 `hailort` 5.4.0 cp313 wheel, DKMS `hailo1x_pci` 5.4.0 (`AUTOINSTALL=yes`), 펌웨어 `/lib/firmware/hailo/hailo10h` → `hailo10h-5.4.0`
- 재설치 자료: `/opt/hailort/5.4.0/dist/` (소스·DKMS·펌웨어 압축 파일, SDK wheel, `SHA256SUMS`; 복구 명령은 `docs/setup-hailort-5.4.0.md`). 새 venv에는 이 wheel을 `pip install --no-deps`로 넣는다.
- Python: 3.13.5, 프로젝트 `.venv` (`--system-site-packages`; 시스템 NumPy 2.2.4, OpenCV 4.10.0, Pillow 11.1.0, Flask 3.1.1)
- 모델: Qwen3-VL-2B-Instruct, A16W4 group-wise, 컨텍스트 2048

## 기본 설정값

- HEF 경로: `models/5.4.0/Qwen3-VL-2B-Instruct.hef` (3,185,773,502 bytes)
- HEF URL: `https://dev-public.hailo.ai/v5.4.0/blob/Qwen3-VL-2B-Instruct.hef`
- HEF SHA-256: `3e302b1d0bdc4beaf4ff982cb34f18bc957d3acd1e20e275eb0dd3536b3043a7` (다운로드 파일 기준, 공급자 공표값과 대조하지 않음)
- 비전 인코더 입력: 288×512×3 UINT8 NHWC (`hailortcli parse-hef` 결과). 코드는 `input_frame_shape()`로 런타임에 조회한다.
- CLI 생성 기본값: `temperature=0.2`, `max_generated_tokens=256`, `seed=42`
- RPC `vlm.chat`: `max_tokens` 1–256 (기본 128), `temperature` 0.05–1.0 (기본 0.2), 메시지 1–16개·총 6,000자, 이미지 PNG/JPEG/WebP data URI ≤ 8 MiB·16 MP, 요청 본문 ≤ 12 MiB, batch ≤ 8, 추론 대기 한도 180초
- 웹: gunicorn 워커 1·스레드 4, `127.0.0.1:${PIWANKANOBI_PORT:-3010}`, nginx `/piwankanobi/`
- VDevice `group_id = "SHARED"`

## 런타임 구조 메모

- `VLMSession`은 대화 기록을 Python 쪽에 두지 않는다. NPU가 컨텍스트를 유지하므로 후속 질의는 새 메시지만 보내고, 시스템 프롬프트는 컨텍스트가 비어 있을 때만 붙인다. `reset()`은 `clear_context()`를 호출하고 실패하면 예외를 전달한다.
- 웹 서버는 모델을 한 번 로드해 상주시키고 요청마다 컨텍스트를 초기화한다. 그래서 RPC 호출자는 같은 이미지와 전체 대화 기록을 매번 보낸다. 한 번에 한 추론만 처리하고, 처리 중에 온 요청은 `-32001`로 돌려보낸다.
- 컨텍스트 초기화가 실패하면 워커를 사용 불가 상태로 바꾼다 (`state=error`, 헬스 503).
- 운영 서비스가 NPU 모델을 점유한다. CLI·Python 추론 전에는 서비스를 멈춘다.

## 동작 규칙

- HailoRT는 `temperature <= 0`을 `HAILO_INVALID_ARGUMENT`로 거부한다 (5.4.0 `vlm.cpp`의 `0 < temperature` 검사). `GenerationConfig.safe_temperature()`가 0.05로 클램프하고, RPC는 0.05 미만을 거절한다.
- 이미지는 HEF가 보고하는 shape·dtype으로 변환한다. OpenCV BGR → RGB 변환 필수, 크기·타입 하드코딩 금지.
- 응답 끝 표식 `<|im_end|>`, `". [{'type'"`, `<|endoftext|>`를 잘라낸다. 스트리밍에서는 청크 경계에 걸친 표식도 처리하고, 출력이 끝나도 SDK 생성기는 끝까지 소비한다.
- HEF는 빌드한 HailoRT 버전에서만 동작한다. 경로를 `models/<버전>/`으로 나눠 다른 버전 파일이 섞이지 않게 한다.

## 반복 금지

- 배포판 Hailo-10 패키지(`hailo-h10-all`, `h10-hailort`, `h10-hailort-pcie-driver`, `python3-h10-hailort` 등)를 apt로 설치하거나 지우지 말 것. 설치하면 5.1.1 드라이버·펌웨어가 5.4.0 위에 덮어써지고, 지우면 `h10-hailort-pcie-driver`의 `prerm`이 모든 `hailo1x_pci` DKMS 버전과 `/lib/firmware/hailo/`를 삭제한다. 2026-10-26 `docs/setup-hailort-5.4.0.md`의 `remove-hailo-5.1.1.sh` 절차로 모두 지웠고, apt pin `/etc/apt/preferences.d/piwankanobi-hailo.pref`가 재설치를 막는다.
- upstream 드라이버의 `make install_dkms`·`make uninstall`을 쓰지 말 것. 모든 `hailo1x_pci` DKMS 버전과 모듈 사본, `/usr/src/hailo1x_pci-*`를 지운다. DKMS 명령에 버전을 지정한다.
- 시스템 `/usr/bin/python3`으로 실행하지 말 것. 5.4.0 SDK는 `.venv`에만 있다.
- `--temperature 0`을 넘기지 말 것.
- HEF를 다른 HailoRT 버전과 섞지 말 것.
- Hailo-Ollama로 VLM을 쓰려 하지 말 것. 5.4.0에서도 LLM 전용이다.

## Hailo-10H에서 쓸 수 있는 VLM

- 2026-10-12 Hailo GenAI 5.4.0 공식 목록에서 HEF가 있는 완성형 Qwen VLM은 Qwen2-VL-2B와 Qwen3-VL-2B뿐이다. 이 프로젝트는 Qwen3-VL-2B만 쓴다.
- Qwen2.5-VL, Qwen3.5·3.6·3.8은 공식 HEF가 없다. 원본 Hugging Face 모델이나 GGUF는 HEF 대신 쓸 수 없다.
- 2026-05 전수 조사 기준 Gemma, PaliGemma, Phi-3/3.5, Mistral, InternVL, SmolVLM, MoonDream, Florence-2, SAM 계열, DepthAnything-V2도 HEF가 없다. 7B 이상 풀 VLM도 없다.
- 사용자 LoRA를 HEF에 얹는 공식 경로는 없다.
- Qwen3.5-2B/4B는 별도 CPU 환경에서 품질·속도를 비교할 후보다.
- 상황이 바뀌면 `dev_log.md`에 날짜와 함께 기록한다.

## RealSense (D435) 조사 메모

2026-05-12 조사, 빌드는 미실행.

- apt·PyPI·piwheels·Intel PPA 모두 aarch64/cp313용 `pyrealsense2`가 없다. librealsense2 소스 빌드가 유일한 경로다.
- cmake 옵션: `-DBUILD_PYTHON_BINDINGS=true -DPYTHON_EXECUTABLE=/usr/bin/python3 -DFORCE_RSUSB_BACKEND=true -DBUILD_EXAMPLES=false -DBUILD_GRAPHICAL_EXAMPLES=false -DCMAKE_BUILD_TYPE=Release`. `FORCE_RSUSB_BACKEND`는 커널 UVC 패치 없이 libusb 백엔드를 쓴다.
- 빌드 의존성 `libusb-1.0-0-dev`, `libssl-dev`는 당시 미설치였다.
- 산출물 `pyrealsense2*.so`를 시스템 `dist-packages`에 두면 `.venv`(`--system-site-packages`)에서도 import된다.
- D435가 USB 2.0(480 Mb/s)으로 연결되어 있었다. USB3 케이블과 Pi 5의 파란 USB3 포트로 바꾼 뒤 `cat /sys/bus/usb/devices/3-1/speed`가 5000인지 확인한다. USB2에서는 RGB+depth 고해상도 동시 스트림이 안 된다.
- D435 1대에 `/dev/video0..4`가 생긴다. `cv2.VideoCapture(0)` 대신 `pyrealsense2` pipeline으로 스트림을 지정한다. `dmesg`의 `Unknown video format` 경고는 무시해도 된다.
- VLM에는 컬러 프레임만 RGB888 `numpy.uint8 H×W×3`으로 넣는다.

## 외부 참조

- HailoRT 5.4.0: <https://github.com/hailo-ai/hailort/tree/v5.4.0>
- HailoRT 드라이버 5.4.0: <https://github.com/hailo-ai/hailort-drivers/tree/v5.4.0>
- Hailo Model Zoo GenAI 5.4.0 모델 목록: <https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.4.0/docs/MODELS.rst>
- Hailo-Ollama 사용 제한: <https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.4.0/docs/USAGE.rst>
- HailoRT 5.4 VLM 튜토리얼: <https://github.com/hailo-ai/hailort/blob/v5.4.0/hailort/libhailort/bindings/python/platform/hailo_tutorials/notebooks/HRT_4_VLM_Tutorial.ipynb>
- Qwen3-VL-2B 제품 페이지: <https://hailo.ai/products/hailo-software/model-explorer/generative-ai/qwen3-vl-2b-instruct/>
- Raspberry Pi AI 소프트웨어 설치: <https://www.raspberrypi.com/documentation/computers/ai.html>
- IntelRealSense/librealsense: <https://github.com/IntelRealSense/librealsense>
