# 지출 일괄 재분류 경로 감사

기준: `d4c5934` 작업 트리 소스와 합성 테스트 코드. 운영 DB/API, 실제 금융자료, 배포 동작은 확인하지 않았다.

## 호출 경로와 쓰기 영향

- 일반 화면 `render_expense_cleanup()`은 owner 역할에서만 내용을 렌더링한다. 이전 UI의 전용 스크립트는 클릭 시 CSRF 헤더를 붙여 `POST /api/imports/reclassify-pending`를 호출했다. 이 요청은 화면 조회와 별개인 쓰기 요청이다.
- `dispatch()`의 해당 POST 분기는 owner 및 CSRF 검증 뒤 `reclassify_cleanup(board)`를 직접 호출한다. 이 일괄 요청 전체에는 재전송 키, 미리보기 버전, 다중 프로세스 실행 게이트가 없다. 인증된 직접 재전송은 계속 가능하다.
- `reclassify_cleanup()`의 `board._lock`은 전체 요청이 아니라 쓰기 구간을 프로세스 안에서 직렬화한다. OTA `warmup`/`request_check` 호출은 이 잠금 밖에서 일어나며 외부 워커에 접촉할 수 있다. 운영 워커 동작은 확인하지 않았다.
- `app.classify.classify_batch`는 `transactions`, `import_batches`, `change_log`를 `BEGIN IMMEDIATE` 또는 기존 트랜잭션용 `SAVEPOINT`로 갱신한다. `app.ledger.commit`은 `ledger_entries`, `transactions`, `import_batches`, `requests`, `change_log`와 `CardFlow.project`의 `board_rows`, `board_revisions`를 하나의 `BEGIN IMMEDIATE` 안에서 반영한다. `assign_existing_local_expenses()`는 `board.save`를 호출해 `board_rows`, `board_revisions`, `board_requests`를 행 단위로 별도 저장하므로 전체 재처리는 원자적이지 않다. 결과에 일부 성공과 실패가 함께 반환될 수 있다.
- 규칙 설정 직후의 `reclassify_pending()`은 미래 적용 설정에 따라 미기장 거래를 재분류하는 별도 경로다. 카드 업로드 후 자동 처리는 업로드 처리에서 `_classify()`와 `_auto_record_locked()`를 부르는 별도 흐름이다. 둘 다 일반 화면 조회와 다르며 이번 UI 수정에서 제거하지 않았다.

## 현재 보호와 남은 위험

- 일반 화면과 해당 POST는 owner 역할 및 CSRF 검사를 사용한다. 화면 전용 JS는 중복 클릭 중 버튼을 잠시 비활성화했지만, 서버는 일괄 요청 전체에 재전송 키나 다중 프로세스 게이트를 적용하지 않는다.
- 재분류/기장 경로에는 수동 결정·보류·충돌·파싱 오류·중복·취소/환불 및 기존 기장 보호 분기가 있다. 개별 여행 이동은 요청 기록과 revision을 확인한다. 이는 모든 거래가 불변이라는 보증은 아니다.
- 이번 변경은 일반 화면의 일괄 버튼과 전용 클릭 동작만 제거했다. `POST /api/imports/reclassify-pending`와 서버 처리 함수는 남아 있다. 유효한 owner 세션과 CSRF 토큰을 가진 직접 호출은 여전히 분류, 내부 장부 기록, 기존 장부 여행 귀속을 바꿀 수 있다.
- GET 화면 렌더링은 읽기·집계만 수행하고 해당 일괄 POST를 호출하지 않는다. 배포된 운영 코드와 실제 자료의 동작은 검증하지 않았다.

## 다음 유지보수 작업

별도 `EXPENSE-BULK-MAINT-01`에서 owner 전용 경로와 읽기 전용 사전 미리보기, 미리보기 이후 최신성 확인, 범위 동의, 중복/동시 실행 통제, 비밀정보 없는 감사 기록을 설계해야 한다. 기존 POST를 포함한 모든 쓰기 진입점을 같은 게이트에 묶고 합성 자료로 검증하기 전에는 새 관리 UI를 열지 않는다.

## 표적 검증

실행 명령: `python -m pytest -q webapp/tests/test_cleanup_reclassification.py webapp/tests/test_expense_cleanup.py webapp/tests/test_cleanup_ota_contract.py::test_cleanup_reads_change_no_card_decision_or_ledger_state`.

실제 결과 출처: 감독 실행과 Luna 터미널 관측 모두 29 passed, 1 failed(3.85초)였다. 실패는 `test_expense_cleanup.py::test_unlinked_booking_explains_missing_connection_without_requesting_card_evidence`이며, 감독이 기준 커밋 `d4c5934`의 `webapp/card_flow.py`를 메모리에 읽어 별도 프로세스에서 해당 테스트 하나를 실행해 기준 실패를 재현했다(0.45초). 기준 검증에서 작업 파일을 복원하거나 초기화하지 않았다. 기존 실패를 수정하지 않았으며, 그 뒤 반복 검사는 생략했다. 변경된 지출 정리 UI, 건별 처리, 페이징, 조회 불변성 표적 검사는 통과했다.

전체 회귀, 브라우저 E2E, 운영 API/DB, 배포, 실제 일괄 POST는 실행하지 않았다.

## 인계

AUDIT-01 및 UI-01 개발과 합성 검토를 완료했다. 작업 브랜치는 `feat/expense-bulk-ui-safety-20261025`, 구현 커밋은 `1d585cb`다. MAINT는 별도 PR 및 위험 검토 전까지 시작하지 않았다. push, PR 생성, 병합, 배포는 하지 않았다. 다음 검토는 이 브랜치에서 `git show --stat 1d585cb`로 시작하고, 운영 POST는 실행하지 않는다. 기존 `C:\AX\cost` 작업공간과 stash는 보존했다.
