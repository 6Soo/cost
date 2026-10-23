# 웹 장부

> **현재 코드의 웹 실행기 설명**. V3 OTA 매칭/여행 AI 신규 목표와 현재 구현은 [단일 개발 진입점](../docs/COST_V3_START_HERE.md)에서 구분한다. 이 문서의 운영 경로·웹 동작은 실제 배포 SHA로 확인한다.


## 현재 OTA 자료 연결

메일·포털·과거 조사 자료는 운영 `ota-sources.json`에 등록해 함께 조회한다. 자료 내용 변경을 감지하고 미연결 사유를 구분하는 수정까지 적용했다. OTA 매칭의 새로운 목표 계약은 [COST V3 진입점](../docs/COST_V3_START_HERE.md)과 [OTA A 정책](../docs/ota-card-reconciliation-policy-a-v3.md)을 따른다. 과거 OTA 조사·실측 수치는 [운영 기록](../docs/operations.md)에서 해당 시점별로 확인한다.

현재 웹 장부는 운영 SQLite, 실제 카드 파일 처리, Google 로그인과 권한 검사, 장부 편집·입금 배분·XLSX 출력을 연결한다. 과거 합성 데모만 존재한다는 설명은 현재 코드에 맞지 않는다. 운영 상태는 [운영 문서](../docs/operations.md), 처리 구조는 [구조 문서](../docs/architecture.md)를 따른다.

## 개발 서버

저장소 루트에서 운영과 다른 데이터 폴더를 지정한다.

```powershell
$env:WEBLEDGER_CARD_FLOW='1'
$env:WEBLEDGER_UNIFIED_DB='1'
python run_candidate.py --data-root C:\AX\cost-dev-data --port 8765 --environment local-synthetic --synthetic-sessions
```

`run_candidate.py`는 `--data-root` 또는 `WEBLEDGER_DATA_ROOT`로 지속 데이터 경로를 받는다. 직접 `ledger_board.serve()`를 호출하는 호환 경로는 명시 `db_path`나 `WEBLEDGER_DB`가 없으면 현재 작업 폴더의 `webledger.work.sqlite`를 사용한다. 테스트에서는 임시 DB를 명시한다. 기본 바인딩은 `127.0.0.1`이다.

## 운영과 인증

운영 정본은 `D:/WebLedgerHost/data/board.sqlite`이고 별도 실행기는 `D:/WebLedgerHost/bin/launch_web_ledger.py`다. 설정과 비밀값은 저장소 밖에 둔다. Google 로그인과 소유자·조회 권한, CSRF 및 revision 검사를 유지한다. 비로그인 카드 검토와 API 요청은 401로 거절한다. 합성 세션을 운영 인증으로 사용하지 않는다.

## 예약 참가자 후보 연결 (선택 기능)

기능은 기본 비활성 상태다. 합성 환경에서 연결을 시험할 때만 아래 변수를 설정한다. 예시 파일은 `webapp/reservation-passenger.env.example`이며, 실제 값과 토큰 파일은 저장소 밖에 둔다.

- `WEBLEDGER_FLIGHT_PASSENGER_MATCHING=1`은 owner 화면과 API를 켠다.
- `WEBLEDGER_FLIGHT_PASSENGER_DB`는 COST가 사용자 확인 연결을 보관할 별도 SQLite 파일 경로다.
- `RESERVATION_INTERNAL_BASE_URL`은 예약 서비스 주소이며 생략하면 `https://reserve.foresttour.kr`을 사용한다.
- `RESERVATION_INTERNAL_API_TOKEN_FILE`은 예약 서비스의 내부 읽기 전용 API 토큰 파일 경로다. 또는 보호된 서비스 환경변수 `RESERVATION_INTERNAL_API_TOKEN`을 사용할 수 있다.

예약 서비스의 `INTERNAL_API_TOKEN`과 COST의 토큰은 권한 있는 운영자가 승인된 비밀 관리 경로에서 같은 값으로 설정해야 한다. 이 저장소는 토큰을 만들거나 포함하지 않는다. 로컬 실행에서는 `.env` 내용을 Git에 넣지 말고, 비밀 파일은 COST 실행 계정만 읽도록 제한한다. 토큰이나 예약 원문은 로그·화면 오류·AI 요청에 넣지 않는다. 예약 자료 조회가 실패하면 참가자 연결만 사용할 수 없으며 카드 대사·지출 검토는 계속 동작한다. 후보 선택은 COST 내부 연결만 확정하고 실제 탑승이나 예약 원본은 바꾸지 않는다.

## 자료와 출력

최신 main의 카드 파서(`app/import_card.py`)는 CSV·XLSX·바이너리 XLS 형식을 지원하며 바이너리 XLS에는 `xlrd` 모듈이 필요하다. 웹 업로드 UI에도 `.xls` 확장자가 허용된다. 다만 운영 서버의 의존성·배포 상태는 실제 환경에서 확인해야 한다. 보존 OTA 메일과 Agoda 포털 근거는 읽기 전용으로 대조한다. 웹 요청에서 메일을 보내거나 예약을 만들지 않는다. 카드사 직접 API와 무인 인증서 로그인 성공은 확인되지 않았다.

XLSX 생성은 현재 장부 행을 읽는다. 출력 화면과 출력 작업 조회는 기존 카드 importer를 생성하거나 스키마를 쓰지 않는다. Google 로그인 범위와 메일·Drive·Sheets 권한은 별개이며, 로그인만으로 외부 문서 쓰기가 승인되지는 않는다.

## 검증

변경과 관련된 테스트를 먼저 실행한다. 기존 DB를 삭제해 테스트를 통과시키지 않는다. 최신 명령·결과·브라우저 확인 범위는 [운영 문서](../docs/operations.md)에 기록한다. 전체 회귀를 개별 수정마다 반복하지 않는다.
