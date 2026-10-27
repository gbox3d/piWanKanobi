# Plan

## 목차

- [Current goal](#current-goal)
- [Near-term work](#near-term-work)
- [Structure decisions](#structure-decisions)
- [Risks](#risks)

## Current goal

HailoRT 5.4.0 + Qwen3-VL-2B 웹·RPC 서비스(0.3.0)를 유지하면서 모델 품질 평가와 카메라 입력을 진행한다.

## Near-term work

우선순위 순:

1. **Qwen3-VL-2B 품질 평가**
   - `samples/` 4종으로 한국어 답변·색·개수·글자 인식 기준 응답을 기록
   - 질문 표현에 따라 사과를 오렌지로 오인한 사례(2026-10-13) 재현
2. **RealSense D435 입력** (2026-05-12 이후 진행 기록 없음)
   - USB3 링크 확보 → librealsense2 소스 빌드 → `pyrealsense2` import 확인 (`memo.md` 조사 메모)
   - 컬러 프레임을 VLM에 넣는 입력 모드 추가
3. **(후보) Qwen3.5-2B/4B 비교** — 별도 CPU 환경에서 품질·속도

## Structure decisions

이미 정해진 것:

- Python: 프로젝트 `.venv` (`--system-site-packages`). Hailo SDK는 `.venv`, 이미지·웹 라이브러리는 시스템 apt.
- Hailo 스택: HailoRT 5.4.0 소스 빌드(`/opt/hailort/5.4.0`), DKMS 5.4.0, 펌웨어 링크. 배포판 Hailo 패키지는 쓰지 않는다.
- 모델: 레지스트리에 `qwen3-vl-2b` 하나, HEF 경로 `models/<버전>/`.
- 웹: 모델 상주 단일 워커, 요청마다 컨텍스트 초기화(stateless RPC), 한 번에 한 추론.
- 배포: systemd + nginx `/piwankanobi/` + WorkGate.

앞으로 결정 필요한 것:

- 카메라 입력 위치와 인터페이스 — `piwankanobi/` 안 새 모듈. 현재 `ask()`/`stream()`은 이미지 파일 경로만 받으므로 numpy 프레임 입력이 필요하다. RealSense 전용으로 할지 `cv2.VideoCapture` 호환으로 할지.
- 컨텍스트 2048 한도 — 긴 대화에서 기록을 자르는 정책.

## Risks

- 수동 설치한 5.4.0은 apt가 관리하지 않는다. 배포판 Hailo 패키지를 설치하거나 지우면 5.4.0 드라이버·펌웨어가 덮어써지거나 삭제된다 (`memo.md` 반복 금지). 커널 업데이트 뒤에는 `dkms status`로 새 커널용 5.4.0 설치를 확인한다.
- 공개 데모 API에 인증이 없다 (LAN 전용 전제).
- 모델 정확도 한계 — 같은 이미지도 질문 표현에 따라 오인한다.
- 컨텍스트 2048 — 이미지와 긴 대화가 한도를 넘으면 추론이 실패할 수 있다.
- NPU 단일 점유 — 서비스가 모델을 점유하므로 CLI·실험 추론 때마다 서비스를 멈춰야 한다.
