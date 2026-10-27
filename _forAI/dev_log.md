# Dev Log

## 목차

- [Entries](#entries)
  - [2026-10-26 구버전 정리](#2026-10-26-구버전-정리)
  - [2026-10-13 웹 채팅과 RPC 서비스](#2026-10-13-웹-채팅과-rpc-서비스)
  - [2026-10-12 HailoRT 5.4.0 전환](#2026-10-12-hailort-540-전환)
  - [2026-05-12 초기 구축과 RealSense 조사](#2026-05-12-초기-구축과-realsense-조사)

## Entries

### 2026-10-26 구버전 정리

사용자 요청: 구버전(HailoRT 5.1.1 + Qwen2-VL-2B)은 쓰지 않으니 제거하고 쓰는 것만 정리.

- 코드: 모델 레지스트리에서 `qwen2-vl-2b`와 5.1.1 전용 HEF 경로(`DEFAULT_HEF`)를 지우고 `qwen3-vl-2b` 빌드를 5.4.0으로 한정했다. `--doctor`의 구 드라이버 장치 `/dev/hailo*` 인식, `run.sh`의 시스템 Python 대체(이제 `.venv`가 없으면 코드 2), SDK 오류 안내의 `python3-h10-hailort` 문구를 지웠다.
- 테스트: 구버전 HEF 경로 테스트 1개 삭제, 관련 테스트 6개 수정. 35개 통과.
- 문서: README에서 5.1.1 복구·Qwen2 다운로드·구 수치 정정 내용을 지웠다. `docs/setup-hailort-5.4.0.md`의 "5.1.1로 복구"를 "배포판 5.1.1 패키지 정리"로 바꿨다. 업그레이드 전 5.1.1 조사 기록 `docs/update-2026-10-12.md`는 삭제하고, 모델 선택 근거만 README와 `memo.md`로 옮겼다.
- `_forAI/` 5개 문서를 현재 구성 기준으로 다시 작성했다.
- 임시 파일 정리: 업그레이드 작업 디렉터리 `.piwankanobi-upgrade-5.4.0`(1.2 GB)에서 압축을 푼 런타임 소스·빌드, 드라이버 git 클론, DKMS 소스·펌웨어 사본, 5.1.1 백업, 검토용 소스, 문서 초안·상태 파일·중복 결과·로그를 지웠다. 지우기 전에 압축 파일 4개가 기록된 SHA256과 같고 펌웨어·DKMS 압축 파일 내용이 설치본과 같음을 확인했다. 재설치 자료 4개(39 MB)는 `/opt/hailort/5.4.0/dist/`로 옮기고 `SHA256SUMS`를 만들었다. 설치 검증 원본은 `localfiles/verification/hailort-5.4.0/`로 옮겼다. `PREPARATION.md`의 FLR 전환 근거는 setup 문서로 옮기고 5.1.1 롤백 절은 버렸다. 작업 디렉터리에는 실행 대기 중인 정리 스크립트만 남았다.
- Qwen2 HEF `models/Qwen2-VL-2B-Instruct.hef`(2.2 GB) 삭제. 프로젝트의 `__pycache__`, `piwankanobi.egg-info`(editable 설치는 site-packages의 dist-info·finder 사용), 브라우저 검증용 `node_modules`(14 MB)와 설치 로그, `/home/goback/works/hailort.log`를 지웠다. 서비스가 열고 있는 `piWanKanobi/hailort.log`는 남겼다.
- 시스템: `remove-hailo-5.1.1.sh`를 검토했다. `apt-get -s purge`로 Hailo 패키지 8개 외에 지워지는 패키지가 없음을 확인했다. `h10-hailort-pcie-driver`의 `prerm`(`make uninstall` → 모든 DKMS 버전 삭제, `rm -rf /lib/firmware/hailo/`)과 펌웨어 링크를 따라가는 파일 목록을 스크립트가 피하는 것도 확인했다. 마지막 `autoremove` 대상 135개는 실행 중인 프로세스가 쓰지 않는다. 사용자가 실행을 지시했지만 auto mode 분류기가 sudo 실행을 두 번 막아, 사용자가 직접 실행했다.
- 시스템 정리 실행(사용자): `remove-hailo-5.1.1.sh`가 Hailo 패키지 8개를 purge하고 apt pin `/etc/apt/preferences.d/piwankanobi-hailo.pref`를 만들었다. 이어서 `autoremove --purge`로 134개(예상 135개)를 지웠고, 작업 디렉터리 `.piwankanobi-upgrade-5.4.0`과 남은 `/usr/lib/libhailort.so` 링크도 지웠다. 확인: `dpkg -l | grep -i hailo` 결과 없음, `dkms status`는 `hailo1x_pci/5.4.0`만, 펌웨어 링크 `hailo10h → hailo10h-5.4.0`, `./run.sh --doctor` 정상(`/dev/h1x-0`, SDK 5.4.0), 테스트 35개 통과, `/api/health` ready.

### 2026-10-13 웹 채팅과 RPC 서비스

- 0.3.0: Flask 이미지 채팅과 JSON-RPC 2.0(`system.info`, `vlm.chat`). 모델 상주, 요청마다 컨텍스트 초기화, 한 번에 한 추론.
- systemd `piwankanobi.service`, nginx `/piwankanobi/`, WorkGate `piwankanobi` 등록. 헬스 HTTP 200, 버전 0.3.0 확인.
- 실제 이미지 RPC에서 한국어 사과 답변 확인(6.191초). 브라우저 확인 중 질문 표현을 바꾸자 사과를 오렌지로 오인했다(첫 답변 7.753초, 후속 5.552초).
- 테스트 36개 통과 (웹·RPC 13개 추가).

### 2026-10-12 HailoRT 5.4.0 전환

- 0.2.0 (당시 5.1.1 환경): `--model`·`--list-models`·`--doctor` 추가. 후속 질의가 NPU 컨텍스트를 재사용하도록 바꿔 과거 대화 재전송으로 생기던 `HAILO_INVALID_OPERATION`을 해결했다. 컨텍스트 초기화 실패를 호출자에게 전달하고, 스트리밍의 응답 끝 표식을 처리했다.
- 사용자 승인 후 HailoRT·Python SDK·드라이버·펌웨어를 5.4.0으로 전환했다(소스 빌드, DKMS, 펌웨어 링크, PCI FLR; 호스트 재부팅 없음). 기본 모델을 Qwen3-VL-2B-Instruct로 바꿨다.
- 한국어 CLI 질의에 "이 그림은 빨간색의 사과를 그렸습니다." (로드 25.45초, 생성 6.25초). 상세 기록은 `docs/setup-hailort-5.4.0.md`.

### 2026-05-12 초기 구축과 RealSense 조사

- HailoRT 5.1.1 + Qwen2-VL-2B-Instruct로 CLI와 Python API를 처음 구축했다. 이후 5.4.0 + Qwen3로 대체했고, 2026-10-26 구버전 코드를 지웠다.
- Hailo-10H용 VLM·LoRA·기타 모델의 HEF 가용성을 전수 조사했다 → `memo.md` "Hailo-10H에서 쓸 수 있는 VLM".
- RealSense D435 통합을 조사했다. 소스 빌드만 가능하고 USB2로 연결되어 있었다 → `memo.md` 조사 메모, `plan.md` 2번.
- `forai-scaffold` 스킬로 `_forAI/`를 생성했다.
