# HailoRT 5.4.0 / Qwen3-VL-2B 설치 및 검증 기록

2026-10-12, Raspberry Pi 5 8GB · Hailo-10H · Debian 13 · Python 3.13.5.
**설치 및 실행 검증 완료:** 런타임·Python SDK·드라이버·펌웨어 5.4.0으로 Qwen3-VL-2B 추론을 확인했다. 호스트 재부팅 없이 PCI FLR과 모듈 재로드로 전환했다.

구성은 `/opt/hailort/5.4.0`, 프로젝트 `.venv`, `models/5.4.0/Qwen3-VL-2B-Instruct.hef`를 사용한다. 배포판 5.1.1 패키지는 5.4.0 드라이버와 함께 쓸 수 없으며 [아래 절차](#배포판-511-패키지-정리)로 정리한다. 사용 중인 커널은 `6.12.75+rpt-rpi-2712`이다. 다시 설치할 때 쓰는 압축 파일과 SDK wheel은 `/opt/hailort/5.4.0/dist/`(SHA256은 같은 위치의 `SHA256SUMS`), 설치 검증 원본은 프로젝트 `localfiles/verification/hailort-5.4.0/`에 둔다.

## 소스 빌드와 Python 환경

공식 소스: [HailoRT v5.4.0](https://github.com/hailo-ai/hailort/tree/v5.4.0), [드라이버 v5.4.0](https://github.com/hailo-ai/hailort-drivers/tree/v5.4.0). 아래는 설치 구성을 재현하는 명령이다. 설치된 시스템에서 다시 실행할 필요는 없다. 소스 압축 파일은 `/opt/hailort/5.4.0/dist/hailort-v5.4.0.tar.gz`이며, 빌드는 임시 디렉터리에서 한다.

```bash
PIWAN_DIST=/opt/hailort/5.4.0/dist
PIWAN_PROJECT=/home/goback/works/piWanKanobi
PIWAN_PREFIX=/opt/hailort/5.4.0
PIWAN_BUILD="$(mktemp -d)"
tar -xzf "$PIWAN_DIST/hailort-v5.4.0.tar.gz" -C "$PIWAN_BUILD"
PIWAN_SOURCE="$PIWAN_BUILD/hailort-5.4.0"
cmake -S "$PIWAN_SOURCE" -B "$PIWAN_SOURCE/build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PIWAN_PREFIX" \
  -DCMAKE_INSTALL_LIBDIR=lib -DHAILO_BUILD_GSTREAMER=OFF \
  -DHAILO_BUILD_EXAMPLES=OFF -DHAILO_SUPPORT_PACKAGING=OFF \
  -DHAILO_BUILD_HAILORT_SERVER=OFF -DHAILO_BUILD_GENAI_SERVER=OFF \
  -DHAILO_BUILD_CLIENT_TOKENIZER=OFF
cmake --build "$PIWAN_SOURCE/build" --parallel 3
sudo cmake --install "$PIWAN_SOURCE/build"
/usr/bin/python3 -m venv --system-site-packages "$PIWAN_PROJECT/.venv"
CMAKE_ARGS="-DHailoRT_DIR=$PIWAN_PREFIX/lib/cmake/HailoRT -DCMAKE_INSTALL_RPATH=$PIWAN_PREFIX/lib" \
  "$PIWAN_PROJECT/.venv/bin/python" -m pip wheel --no-deps \
  "$PIWAN_SOURCE/hailort/libhailort/bindings/python/platform" \
  --wheel-dir "$PIWAN_BUILD/wheels"
"$PIWAN_PROJECT/.venv/bin/python" -m pip install --no-deps \
  "$PIWAN_BUILD/wheels/hailort-5.4.0-cp313-cp313-linux_aarch64.whl"
```

위 이름의 cp313/aarch64 wheel을 설치했다. 빌드 의존성은 scikit-build-core와 `pybind11>=2.13.6,<3`이며, 시스템 NumPy 2.2.4/OpenCV를 재사용한다. 최초 CMake 설정에서도 protobuf를 빌드하므로 시간이 걸린다. 설치 파일은 모두 `/opt/hailort/5.4.0`(bin·include·lib) 안에 있으므로, 런타임을 지울 때는 이 디렉터리와 `/usr/local/bin/hailortcli` 링크를 지운다. 이때 `dist/`의 설치 자료도 함께 지워진다.
SDK만 다시 설치할 때(새 `.venv` 등)는 빌드 없이 보관한 wheel을 쓴다.

```bash
"$PIWAN_PROJECT/.venv/bin/python" -m pip install --no-deps \
  /opt/hailort/5.4.0/dist/hailort-5.4.0-cp313-cp313-linux_aarch64.whl
```

`run.sh`는 `.venv/bin/python`과 `/opt/hailort/5.4.0/lib`를 사용하도록 설정했다. `/usr/local/bin/hailortcli`는 `/opt/hailort/5.4.0/bin/hailortcli`를 가리킨다. wheel의 RPATH와 `ldd`가 `/opt/hailort/5.4.0/lib/libhailort.so.5.4.0`를 선택함을 확인했다.
공개 소스에는 DEB 패키징 디렉터리가 없으므로 `HAILO_SUPPORT_PACKAGING=OFF`로 빌드한다. `optimize_memory_on_device=True`는 별도 Rust/tokenizer 빌드가 필요하며 현재 구성은 기본값 `False`를 사용한다.

## 드라이버와 펌웨어 전환

드라이버는 공식 태그 커밋 `b6dd17c609504e648eb516ff4a867167edf56f3c`의 소스로 DKMS 소스를 만들고, 펌웨어는 공식 `download_firmware_hailo10h.sh`에 적힌 URL에서 받았다. 두 압축 파일은 `/opt/hailort/5.4.0/dist/`의 `hailo1x_pci-5.4.0-dkms-source.tar.gz`(풀면 `hailo1x_pci-5.4.0/`)와 `hailo10h_fw.tar.gz`(파일이 최상위에 바로 있음)이며, SHA256은 같은 위치의 `SHA256SUMS`에 있다.
upstream `make install_dkms`·`make uninstall`은 쓰지 않는다. 모든 `hailo1x_pci` DKMS 버전과 커널 모듈 사본, `/usr/src/hailo1x_pci-*` 소스를 지우기 때문이다. DKMS 명령에 버전을 지정해 설치했다.

```bash
sudo tar -xzf /opt/hailort/5.4.0/dist/hailo1x_pci-5.4.0-dkms-source.tar.gz -C /usr/src
sudo dkms add -m hailo1x_pci -v 5.4.0
sudo dkms build -m hailo1x_pci -v 5.4.0 -k 6.12.75+rpt-rpi-2712
sudo dkms install -m hailo1x_pci -v 5.4.0 -k 6.12.75+rpt-rpi-2712 --force
sudo apt-mark hold h10-hailort-pcie-driver
sudo udevadm control --reload-rules
```

펌웨어는 `/lib/firmware/hailo/hailo10h-5.4.0`에 압축 파일 그대로 풀고, 활성 경로 `hailo10h`를 이 디렉터리의 심볼릭 링크로 연결했다. 압축 파일 안의 `u-boot-default.dtb.signed -> u-boot-0.dtb.signed` 링크를 유지한다. 드라이버가 SKU ID로 `u-boot-{SKU}.dtb.signed`를 고르므로 보드별 링크를 따로 만들지 않는다.

```bash
sudo mkdir -p /lib/firmware/hailo/hailo10h-5.4.0
sudo tar -xzf /opt/hailort/5.4.0/dist/hailo10h_fw.tar.gz -C /lib/firmware/hailo/hailo10h-5.4.0
sudo ln -sfn hailo10h-5.4.0 /lib/firmware/hailo/hailo10h
```

새 규칙 `/etc/udev/rules.d/52-piwankanobi-hailo1x.rules`의 내용은 `SUBSYSTEM=="hailo1x", KERNEL=="h1x-*", MODE="0666"`이다. 기존 장치 접근 정책을 유지하며 새 노드 `/dev/h1x-0`를 인식한다.
드라이버 패키지 hold는 배포판 5.1.1 패키지 갱신이 수동 설치한 5.4.0을 덮어쓰지 않게 하려는 것이다. [5.1.1 패키지 정리](#배포판-511-패키지-정리) 뒤에는 apt pin이 이 역할을 맡는다.
장치를 사용하는 프로세스가 없는 상태에서 다음 순서로 전환했다. 단순 모듈 재로드로는 이미 실행 중인 펌웨어가 바뀌지 않는다(`load_soc_firmware()`는 펌웨어가 올라와 있으면 바로 반환한다). 새 모듈은 구 펌웨어와 버전이 달라도 probe를 마치므로, PCI FLR로 디스크의 새 펌웨어를 올린다. FLR 뒤에는 호환 플래그가 되돌아오지 않아 모듈을 한 번 더 다시 로드한다.

```bash
sudo modprobe -r hailo1x_pci
sudo modprobe hailo1x_pci
printf '1\n' | sudo tee /sys/bus/pci/devices/0001:01:00.0/reset >/dev/null
sudo modprobe -r hailo1x_pci
sudo modprobe hailo1x_pci
```

PCI FLR 후 커널에 `SOC Firmware Batch loaded successfully`와 로드 시간 1,176ms가 기록됐다. 이어 모듈을 다시 로드했고 실제 로드된 드라이버와 `hailortcli fw-control identify`의 펌웨어가 모두 5.4.0임을 확인했다. 커널 로그 `dmesg-after-reset.txt`와 펌웨어 확인 출력 `fw-identify-5.4.0.txt`는 프로젝트 `localfiles/verification/hailort-5.4.0/`에 있다.
호스트는 재부팅하지 않았다. 기존 initramfs 이미지 4개에서 Hailo 파일이 없음을 확인했으며 initramfs를 변경하지 않았다.

## 모델과 실행 확인

모델은 [Hailo 공식 5.4.0 HEF](https://dev-public.hailo.ai/v5.4.0/blob/Qwen3-VL-2B-Instruct.hef)를 사용한다. 다운로드 크기는 3,185,773,502바이트이며, 다운로드 파일의 SHA256은 다음과 같다. 공급자가 별도로 공표한 체크섬을 대조한 값은 아니다.

```text
3e302b1d0bdc4beaf4ff982cb34f18bc957d3acd1e20e275eb0dd3536b3043a7
```

```bash
"$PIWAN_PROJECT/.venv/bin/python" -c 'import hailo_platform; print(hailo_platform.__version__, hailo_platform.__file__)'
/opt/hailort/5.4.0/bin/hailortcli fw-control identify
cd "$PIWAN_PROJECT"
./run.sh --model qwen3-vl-2b --doctor
./run.sh --model qwen3-vl-2b --image samples/apple.png \
  --prompt '이 그림의 과일과 색을 짧게 알려줘.' --max-tokens 64
./run.sh --model qwen3-vl-2b --chat --image samples/apple.png --max-tokens 64
```

실제 검증 결과(`max_tokens=64`, `seed=42`, `temperature=0.2`):

| 항목 | 결과 |
|---|---|
| 한국어 CLI 이미지 질의 | 로드 25.45초, 생성 6.25초. “이 그림은 **빨간색**의 **사과**를 그렸습니다.” |
| 별도 세션의 이미지 스트리밍 | 로드 14.25초, 생성 6.39초. 같은 한국어 답변 수신 |
| 이미지를 다시 보내지 않은 후속 질문 | 1.71초, “The apple is red.”. 영어 한 단어 요청은 따르지 못함 |
| `reset()` 및 새 이미지 질의 | 컨텍스트 사용량 0 확인. 새 gradient 이미지에 응답했지만 64토큰 한도로 중단 |
| 프로젝트 자동 테스트 | `.venv`에서 23개 통과 |

이는 실행·스트리밍·대화 문맥·초기화 검증이며, 전반적인 시각 정확도나 한국어 품질 향상을 입증하는 평가가 아니다. 원본 측정 `qwen3-session-results.json`과 CLI 출력 `qwen3-korean-demo.txt`는 `localfiles/verification/hailort-5.4.0/`에 있다.

## 배포판 5.1.1 패키지 정리

배포판 Hailo-10 패키지(5.1.1)는 5.4.0 드라이버와 함께 쓸 수 없고 프로젝트에서 사용하지 않는다. **apt로 바로 지우면 5.4.0도 함께 지워진다.**

- `h10-hailort-pcie-driver`의 `prerm`은 `make uninstall`로 모든 `hailo1x_pci` DKMS 버전을 지우고 `/lib/firmware/hailo/`를 통째로 삭제한다.
- 같은 패키지의 파일 목록에 있는 `/lib/firmware/hailo/hailo10h/*`는 심볼릭 링크를 따라가 `hailo10h-5.4.0`의 같은 이름 파일을 가리킨다.

정리 스크립트 `remove-hailo-5.1.1.sh`는 두 경로를 피해서 정리한다. 한 번만 쓰는 스크립트라 2026-10-26 실행 후 작업 디렉터리와 함께 지웠다.

1. 5.4.0 펌웨어·DKMS 소스·커널 모듈·런타임의 SHA256을 기록한다.
2. `.venv`가 쓰는 `python3-opencv`, `python3-numpy`, `python3-pil`, `python3-flask`를 수동 설치로 표시한다. `prerm`을 비활성화하고 펌웨어 링크를 잠시 치운 뒤 Hailo 패키지 8개(`hailo-h10-all`, `h10-hailort`, `h10-hailort-pcie-driver`, `python3-h10-hailort`, `hailo-tappas-core`, `python3-hailo-tappas`, `hailo-models`, `rpicam-apps-hailo-postprocess`)를 purge하고 링크를 되돌린다.
3. DKMS 5.1.1, 펌웨어 백업 `hailo10h-5.1.1-piwankanobi-backup`, `/usr/src`의 5.1.1 드라이버 소스를 지운다. apt pin `/etc/apt/preferences.d/piwankanobi-hailo.pref`로 배포판 Hailo-10 패키지가 다시 설치되지 않게 한다.
4. 5.4.0 SHA256이 그대로인지 확인한다.
5. 작업 디렉터리의 중간 파일, 5.1.1 백업, Qwen2 HEF를 지운다. 2026-10-26에 이 항목들은 먼저 정리했고, 작업 디렉터리에는 이 스크립트만 남았다.

2026-10-26 사용자가 아래 명령을 직접 실행했다. 스크립트가 성공해 작업 디렉터리도 지워졌다.

```bash
sudo bash /home/goback/works/.piwankanobi-upgrade-5.4.0/remove-hailo-5.1.1.sh \
  && rm -rf /home/goback/works/.piwankanobi-upgrade-5.4.0
```

2026-10-26 `apt-get -s purge` 결과 위 8개 외에 함께 지워지는 패키지는 없었다. 마지막 `apt-get autoremove --purge`는 선택 항목이다. 수동 설치로 표시한 4개 패키지의 의존성을 빼면 135개(대부분 `-dev` 헤더와 GStreamer·GObject 개발 파일)가 지워지며, 2026-10-26 확인에서 실행 중인 프로세스가 쓰는 라이브러리나 프로젝트가 import하는 모듈은 없었다. `h10-hailort`의 `postinst`가 만든 `/usr/lib/libhailort.so` 링크는 패키지 파일 목록에 없어 제거 후에도 남는다. 5.4.0은 `/opt/hailort/5.4.0/lib`를 쓰므로 지워도 된다.

2026-10-26 실행에서는 `autoremove`로 134개가 지워졌고, `/usr/lib/libhailort.so` 링크도 지웠다. 정리 후 `dpkg -l | grep -i hailo` 결과가 없고 `dkms status`에는 `hailo1x_pci/5.4.0`만 남았다. 펌웨어 링크 `hailo10h → hailo10h-5.4.0`과 apt pin이 있으며, `./run.sh --doctor`(장치 `/dev/h1x-0`, SDK 5.4.0)와 `/api/health`가 정상이다.
