# 웹 장부

## 현재 OTA 자료 연결

메일·포털·과거 조사 자료는 운영 `ota-sources.json`에 등록해 함께 조회한다. 자료 내용 변경을 감지하고 미연결 사유를 구분하는 수정까지 적용했다. 현재 연결 수와 남은 항목, 실제 검증 범위는 [OTA 문서](../docs/ota_mail.md)의 최신 항목을 따른다.

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

## 자료와 출력

카드 업로드는 현재 CSV와 XLSX를 지원한다. 국민 바이너리 XLS 원본은 읽기 전용 분석 도구에서 검사하지만 웹 업로드에는 직접 넣을 수 없다. 보존 OTA 메일과 Agoda 포털 근거는 읽기 전용으로 대조한다. 웹 요청에서 메일을 보내거나 예약을 만들지 않는다. 카드사 직접 API와 무인 인증서 로그인 성공은 확인되지 않았다.

XLSX 생성은 현재 장부 행을 읽는다. 출력 화면과 출력 작업 조회는 기존 카드 importer를 생성하거나 스키마를 쓰지 않는다. Google 로그인 범위와 메일·Drive·Sheets 권한은 별개이며, 로그인만으로 외부 문서 쓰기가 승인되지는 않는다.

## 검증

변경과 관련된 테스트를 먼저 실행한다. 기존 DB를 삭제해 테스트를 통과시키지 않는다. 최신 명령·결과·브라우저 확인 범위는 [운영 문서](../docs/operations.md)에 기록한다. 전체 회귀를 개별 수정마다 반복하지 않는다.
