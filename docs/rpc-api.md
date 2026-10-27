# 웹 채팅과 JSON-RPC API

버전 0.3.0 · 문서 갱신 2026-10-26

PiWanKanobi는 한 개의 Qwen3-VL-2B 모델을 Hailo-10H에 로드해 웹 채팅과 HTTP API에서 함께 사용합니다. 이미지와 대화 기록은 호출자가 보내며, 각 추론 전후에 모델 컨텍스트를 초기화합니다.

## 접속 주소

| 용도 | LAN 주소 |
|---|---|
| 이미지 채팅 | <http://192.168.0.213/piwankanobi/> |
| RPC | `POST http://192.168.0.213/piwankanobi/rpc` |
| 브라우저용 API 안내 | <http://192.168.0.213/piwankanobi/api/help> |
| 헬스 | <http://192.168.0.213/piwankanobi/api/health> |
| 버전 | <http://192.168.0.213/piwankanobi/api/version> |

같은 호스트에서는 `http://127.0.0.1:3010/`으로 직접 접근합니다. 직결 경로에는 `/piwankanobi` 접두사가 없습니다. 위 LAN 주소는 이 호스트의 nginx 배포 설정 기준입니다.

데모 API는 인증 토큰 없이 호출합니다. WorkGate 관리 토큰은 데모 호출에 사용하지 않습니다. 다른 앱의 서버·스크립트에서 HTTP로 사용할 수 있으며, 별도 origin의 브라우저 JavaScript를 위한 CORS는 설정하지 않았습니다.

## JSON-RPC 계약

`POST /rpc`에 `Content-Type: application/json`으로 [JSON-RPC 2.0](https://www.jsonrpc.org/specification) 요청을 보냅니다. `params`는 이름이 있는 JSON 객체이며, 배열형 위치 인자는 지원하지 않습니다. 응답은 생성이 끝난 뒤 한 번에 반환합니다.

### `system.info`

모델 상태, 서비스 버전과 입력 제한을 조회합니다. `params`는 생략하거나 `{}`를 보냅니다.

```bash
curl -sS http://192.168.0.213/piwankanobi/rpc \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"system.info"}'
```

상태는 `loading`, `ready`, `busy`, `error`, `stopped` 중 하나입니다. `ready`일 때 새 추론을 받을 수 있습니다. `/api/health`는 `ready`와 `busy`에서 HTTP 200, 나머지 상태에서 HTTP 503을 반환합니다.

### `vlm.chat`

```json
{
  "jsonrpc": "2.0",
  "id": "question-1",
  "method": "vlm.chat",
  "params": {
    "messages": [{"role": "user", "content": "이 그림에 무엇이 보이나요?"}],
    "image": "data:image/png;base64,...",
    "max_tokens": 128,
    "temperature": 0.2
  }
}
```

`image`의 `...`는 실제 파일의 base64 데이터로 교체합니다.

| 인자 | 기본값 | 조건 |
|---|---|---|
| `messages` | 필수 | 1~16개의 `{role, content}` 객체. `role`은 `user` 또는 `assistant`, `content`는 비어 있지 않은 문자열 |
| `image` | 없음 | PNG/JPEG/WebP 파일의 base64 data URI, 원본 최대 8 MiB·16,000,000픽셀 |
| `max_tokens` | 128 | 정수 1~256 |
| `temperature` | 0.2 | 숫자 0.05~1.0 |

첫 메시지와 마지막 메시지는 `user`여야 하며, 전체 `content` 길이는 6,000자 이하여야 합니다. 시스템 프롬프트는 서버가 설정합니다. 정의되지 않은 인자나 메시지 필드는 거절합니다.

이미지는 첫 번째 `user` 메시지에 연결합니다. JPEG의 MIME 표기는 `image/jpeg`입니다. 로컬 파일 경로나 원격 이미지 URL을 넘기는 방식은 지원하지 않습니다. `image`를 생략하거나 `null`로 보내면 텍스트만 처리합니다.

응답 형식 예시:

```json
{
  "jsonrpc": "2.0",
  "id": "question-1",
  "result": {
    "message": {"role": "assistant", "content": "빨간 사과가 보입니다."},
    "model": "qwen3-vl-2b",
    "elapsed_seconds": 2.3
  }
}
```

위 문장과 시간은 형식을 설명하기 위한 예시입니다. `elapsed_seconds`는 해당 요청의 서버 처리 시간이며 토큰 수나 TPS는 제공하지 않습니다.

## Python: 이미지 질문과 후속 대화

외부 패키지 없이 Python 표준 라이브러리로 호출할 수 있습니다. 프로젝트 루트에서 `samples/apple.png`를 사용하는 예제입니다.

```python
import base64
import json
from pathlib import Path
from urllib.request import Request, urlopen

RPC_URL = "http://192.168.0.213/piwankanobi/rpc"
image_uri = "data:image/png;base64," + base64.b64encode(
    Path("samples/apple.png").read_bytes()
).decode("ascii")
history = []


def ask(text, request_id):
    conversation = history + [{"role": "user", "content": text}]
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "vlm.chat",
        "params": {
            "messages": conversation,
            "image": image_uri,
            "max_tokens": 128,
        },
    }
    request = Request(
        RPC_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=210) as response:
        reply = json.load(response)
    if "error" in reply:
        error = reply["error"]
        raise RuntimeError(f'{error["code"]}: {error["message"]}')
    answer = reply["result"]["message"]
    history[:] = conversation + [answer]
    return answer["content"]


print(ask("이 그림의 과일과 색을 알려주세요.", 1))
print(ask("그 과일은 어떤 모양인가요?", 2))
```

후속 요청도 같은 이미지와 `user → assistant → user` 기록을 모두 보냅니다. 응답에 성공한 뒤에만 클라이언트 기록을 갱신합니다. 새 이미지로 전환할 때는 `history.clear()`로 새 대화를 시작하세요. 서버의 대화 ID나 세션 쿠키는 필요하지 않습니다.

## 오류와 처리 제한

RPC 오류 응답에는 `result` 대신 `error: {code, message, data?}`가 있습니다. 일반 RPC 오류는 HTTP 200이므로 HTTP 상태뿐 아니라 `error`를 확인해야 합니다.

| 코드 | 의미 | 대응 |
|---|---|---|
| `-32700` | JSON 파싱 오류 | 요청 JSON과 숫자 표현 확인 |
| `-32600` | 잘못된 RPC 요청·ID·batch | `jsonrpc`, `method`, `id`와 요청 구조 확인 |
| `-32601` | 없는 메서드 | `system.info`, `vlm.chat` 사용 |
| `-32602` | 잘못된 인자·이미지 | 메시지·이미지 형식과 제한 확인 |
| `-32603` | 내부 처리 오류 | 서비스 로그 확인 |
| `-32001` | 모델 로딩 중·다른 요청 처리 중·사용 불가 | `error.data.state` 또는 헬스 조회 후 `ready`에서 재시도 |
| `-32002` | 추론 또는 컨텍스트 초기화 실패 | 대화를 줄여 재시도. 상태가 `error`이면 서비스 점검·재시작 |
| `-32003` | 추론 응답 대기 시간 초과 | 모델이 `ready`로 돌아온 뒤 재시도 |

요청 본문은 최대 12 MiB입니다. 초과하면 HTTP 413, JSON 콘텐츠 타입이 아니면 HTTP 415를 반환합니다. nginx가 먼저 본문 크기를 거절하면 응답이 JSON이 아닐 수 있으므로 HTTP 오류도 처리해야 합니다.

모델에는 **한 번에 한 추론**만 전달합니다. 다른 요청을 무제한 대기열에 쌓지 않고 `-32001`로 반환합니다. 추론 응답 대기 한도는 180초이며, 시간 초과 뒤에도 기존 작업의 정리가 끝나기 전까지 다음 추론을 받지 않습니다. 컨텍스트 초기화가 실패하면 워커를 사용할 수 없는 상태로 전환합니다.

메시지·문자 수 제한과 별개로 Hailo HEF의 모델 컨텍스트는 2048입니다. 이미지와 대화가 이 한도를 넘으면 추론이 실패할 수 있으므로 짧은 대화를 사용합니다. 요청 사이에는 NPU 대화 컨텍스트를 유지하지 않으며, 업로드 이미지를 처리하는 임시 파일은 전처리 후 삭제합니다.

batch는 최대 8개 요청을 순서대로 처리합니다. `id`가 없는 유효한 notification은 실행 후 응답 본문 없이 HTTP 204를 반환하며, batch 응답에서는 제외합니다. 긴 추론을 여러 개 묶으면 전체 응답 시간이 길어지므로 이미지 질문은 개별 호출하는 편이 좋습니다.

## 실행과 배포

먼저 [HailoRT 5.4.0 설치 기록](setup-hailort-5.4.0.md)에 맞춰 `.venv`, 네이티브 런타임·드라이버·펌웨어와 Qwen3 HEF를 준비합니다. 웹 의존성 설치는 Hailo SDK를 설치하거나 업그레이드하지 않습니다.

```bash
cd /home/goback/works/piWanKanobi
.venv/bin/python -m pip install -e '.[web]'
pm2 start deploy/ecosystem.config.cjs --only piwankanobi
pm2 save
```

[`run-web.sh`](../run-web.sh)는 `127.0.0.1:3010`에서 Gunicorn 워커 1개·스레드 4개로 실행합니다. SDK를 소유하는 스레드는 워커 시작 후 생성되므로 `--preload`를 추가하지 않습니다. 포트를 바꾸려면 `PIWANKANOBI_PORT`를 지정하고 nginx·WorkGate manifest도 같은 값으로 맞춥니다.

[`deploy/ecosystem.config.cjs`](../deploy/ecosystem.config.cjs)는 `run-web.sh`를 `/bin/bash`로 실행하는 PM2 프로세스 `piwankanobi`를 정의합니다. 작업 디렉터리는 설정 파일 위치를 기준으로 프로젝트 루트를 사용하며, fork 모드의 단일 인스턴스로 실행합니다. PM2 명령은 `goback` 사용자로 실행합니다.

이 호스트의 부팅 자동 실행은 기존 `pm2-goback.service`가 담당합니다. `pm2 save`로 저장한 프로세스 목록을 부팅 때 복원합니다. 운영 명령은 다음과 같습니다.

```bash
pm2 status piwankanobi
pm2 logs piwankanobi --lines 50 --nostream
pm2 restart piwankanobi
```

수동으로 전경 실행할 때는 `pm2 stop piwankanobi` 후 `./run-web.sh`를 사용합니다. 전경 프로세스를 종료한 뒤 `pm2 start piwankanobi`로 운영 서비스를 복원합니다.

[`deploy/nginx-piwankanobi.conf`](../deploy/nginx-piwankanobi.conf)의 `location` 설정을 기존 gateway `server` 블록 안에 포함합니다. 이 파일은 독립적인 `server` 설정 파일이 아닙니다. nginx 설정 검사 후 다시 불러옵니다.

```bash
sudo nginx -t
sudo systemctl reload nginx
```

WorkGate 등록은 서비스 실행과 nginx 경로 준비 후 진행합니다. [`deploy/workgate.json`](../deploy/workgate.json)은 PM2 프로세스 `piwankanobi`, 포트 3010, 공개 경로 `/piwankanobi/`, 헬스·버전 API와 채팅·API 도움말 링크를 선언합니다. 같은 호스트의 WorkGate CLI를 사용할 수 있습니다.

```bash
node /home/goback/works/WorkGate/scripts/py.cjs registry put \
  ./deploy/workgate.json --by codex/piwankanobi-demo
node /home/goback/works/WorkGate/scripts/py.cjs registry list --json
node /home/goback/works/WorkGate/scripts/py.cjs ps --json
```

WorkGate 등록은 서비스를 시작하거나 nginx 설정을 바꾸지 않습니다. 다른 호스트에 옮기면 manifest의 사용자 경로·포트·감독자 이름을 해당 호스트의 실제 값으로 수정합니다.

### 2026-10-26 PM2 전환

기존 `piwankanobi.service`로 실행하던 호스트에서는 전용 systemd 서비스를 먼저 중지·비활성화한 뒤 PM2를 시작합니다. 두 감독자가 같은 포트와 NPU 모델을 동시에 실행하지 않도록 합니다.

```bash
sudo systemctl disable --now piwankanobi.service
pm2 start deploy/ecosystem.config.cjs --only piwankanobi
pm2 save
```

헬스가 `ready`로 돌아온 뒤 WorkGate 항목의 감독자를 `pm2: piwankanobi`로 갱신합니다. 2026-10-26 실제 전환 후 PM2 `online`, 기존 `piwankanobi.service`의 `inactive/disabled`, 헬스 HTTP 200과 버전 0.3.0을 확인했습니다. PM2 재시작 후에도 모델이 정상 로드됐고, 이미지 RPC는 6.404초에 빨간 사과라는 답변을 반환했습니다. `pm2 save`로 부팅 복원 목록도 저장했습니다. [`deploy/piwankanobi.service`](../deploy/piwankanobi.service)는 이전 방식으로 복구할 때 참고할 템플릿으로 보관하며, PM2 운영 중에는 활성화하지 않습니다.

## 배포 후 확인

2026-10-13 최초 배포에서 직결 이미지 RPC의 한국어 사과 답변(처리 6.191초), nginx의 localhost·LAN 경로 HTTP 200을 확인했습니다. 당시 WorkGate의 `piwankanobi` 항목은 소유자 `codex/piwankanobi-demo`였으며, 서비스 스냅샷에서 systemd `active/enabled`, 헬스 HTTP 200, HTTP·checkout 버전 0.3.0을 확인했습니다.

실제 브라우저에서 이미지 업로드, 같은 이미지와 전체 기록을 보내는 후속 질문, 새 대화 초기화, 모바일 화면을 확인했습니다. 첫 답변은 7.753초, 후속 답변은 5.552초였습니다. 이때 다른 표현으로 질문하자 사과를 오렌지로 오인했습니다. API 동작 검증과 모델 정확도 평가는 별개이며, 이미지 인식 결과를 항상 정확한 것으로 취급하지 않습니다. WorkGate 카드의 채팅·API 도움말 링크도 브라우저에서 HTTP 200으로 열렸습니다.

```bash
pm2 status piwankanobi
curl -sS http://127.0.0.1:3010/api/health
curl -sS http://192.168.0.213/piwankanobi/api/version
curl -sS http://192.168.0.213/piwankanobi/rpc \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"system.info"}'
pm2 logs piwankanobi --lines 50 --nostream
```

상태가 `ready`가 되면 브라우저 사과 예제 또는 위 Python 코드로 이미지 답변과 후속 질문을 확인합니다. 실제 웹 추론은 NPU를 사용합니다. 아래 자동 테스트는 가짜 엔진으로 HTTP 계약과 격리를 확인하며 NPU를 열지 않습니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

운영 웹 서비스가 NPU 모델을 점유하므로 CLI나 별도 Python 추론을 실행할 때는 먼저 `pm2 stop piwankanobi`로 서비스를 중지합니다. 작업을 마친 뒤 `pm2 start piwankanobi`로 다시 시작합니다.
