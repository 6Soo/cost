# webapp

저장소 루트에서 `python run_candidate.py --port 8765`로 실행할 수 있다.
이 실행기는 DB와 출력을 Git 제외 경로인 `runtime/`에 둔다.
아래 직접 모듈 실행법과 기본 DB 설명은 그대로 유효하다.
현재 상태는 [2026-09-27 인계](../docs/handoff/2026-09-27/README.md)를 우선한다.

합성 데이터로 동작하는 웹 장부 확인용 앱이다. 실제 운영 데이터·운영 DB와 연결되어 있지 않으며, 외부 서비스 연결은 구현돼 있지 않다.

## 합성 DB

- 기본 DB 파일명: `webledger.work.sqlite`
- 저장 위치: 실행한 작업 경로의 현재 디렉터리
- 경로 지정: 환경변수 `WEBLEDGER_DB`가 우선한다. 지정이 없으면 기본 파일명을 쓴다.
- 서버 기동 시 DB 파일이 없으면 새로 만든다. 기존 파일이 있으면 그대로 연다.

## 실행 명령

합성 보드 서버(카드 처리 worker 포함, 기본값 `with_worker=True`):

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:WEBLEDGER_DB = (Join-Path $env:TEMP "webledger-demo.sqlite")
python -m webapp.ledger_board --port 8751
```

- 주소: `http://127.0.0.1:8751/board`
- 기본 포트 8751. 종료는 `Ctrl+C`.
- DB를 후보 폴더나 저장소에 남기지 않으려면 `WEBLEDGER_DB`를 임시 경로로 지정한다.

봉인 스냅샷 재생 서버(읽기 전용 대조 경로):

```powershell
python -m webapp.cli serve --snapshot <descriptor 경로> [--ledger <경로>] [--port 8765] [--phase0]
```

- 봉인된 스냅샷 descriptor가 필수다. 검증에 실패하면 시작하지 않는다.
- `--phase0`는 쓰기 route를 전부 끈다.

검사:

```powershell
python -m pytest webapp/tests -q -p no:cacheprovider
```

의존성은 `webapp/requirements.txt`에 선언돼 있다. 이 선언만으로 설치하지 않으며, 현재 환경은 Python 3.12.10 / openpyxl 3.1.5로 확인됐다.

## 미구현 외부 연결

아래는 모두 이 앱에 연결되어 있지 않다. 구현되지 않았고 이 데모 범위 밖이다.

- Google Sheets / Google Drive 업로드와 공유. XLSX는 로컬 파일로만 만든다.
- Apps Script 카드 RAW 수집과 `clasp` 배포 경로.
- 은행 계좌·카드사 직접 API 연결. 카드 데이터는 파일 업로드로만 넣는다.
- Agoda 예약 수집, Gmail 수신, 메일 파싱.
- 로그인, OAuth, 사용자 인증, 권한 관리.
- 외부.origin 허용. 서버는 `127.0.0.1` loopback에만 바인딩한다.
- 실제 운영 DB, 실제 원본 자료, 배포 환경 연결.
