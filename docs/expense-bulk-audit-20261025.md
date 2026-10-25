# 지출 일괄 재분류 경로 감사

기준: `d4c5934` 작업 트리 소스와 합성 테스트 코드. 운영 DB/API, 실제 금융자료, 배포 동작은 확인하지 않았다.

## 호출 경로와 쓰기 영향

- 일반 화면 `render_expense_cleanup()`은 owner 역할에서만 내용을 렌더링한다. 이전 UI의 전용 스크립트는 클릭 시 CSRF 헤더를 붙여 `POST /api/imports/reclassify-pending`를 호출했다. 이 요청은 화면 조회와 별개인 쓰기 요청이다.
- `dispatch()`의 해당 POST 분기는 owner 및 CSRF 검증 뒤 `reclassify_cleanup(board)`를 직접 호출한다. 인증된 직접 재전송은 계속 가능하며, 현재 요청 ID 기반 멱등성·동시 실행 잠금은 이 경로에서 확인하지 못했다.
- `reclassify_cleanup()`은 `board._lock`으로 프로세스 내 동시 실행을 막지만 전체 요청 재전송을 멱등하게 만들지는 않는다. `app.classify.classify_batch`는 `transactions`, `import_batches`, `change_log`를 `BEGIN IMMEDIATE` 또는 기존 트랜잭션용 `SAVEPOINT`로 갱신한다. `app.ledger.commit`은 `ledger_entries`, `transactions`, `import_batches`, `requests`, `change_log`와 `CardFlow.project`의 `board_rows`, `board_revisions`를 하나의 `BEGIN IMMEDIATE` 안에서 반영한다. `assign_existing_local_expenses()`는 `board.save`를 호출해 `board_rows`, `board_revisions`, `board_requests`를 행 단위로 별도 저장하므로 전체 재처리는 원자적이지 않다. 결과에 일부 성공과 실패가 함께 반환될 수 있다.
- `reclassify_cleanup()`은 OTA `warmup`/`request_check` 경로를 호출할 수 있어 외부 워커 접촉 가능성이 있다. 운영 워커 동작은 확인하지 않았다.
- 규칙 설정 직후의 `reclassify_pending()`은 미래 적용 설정에 따라 미기장 거래를 재분류하는 별도 경로다. 카드 업로드 후 자동 처리는 업로드 처리에서 `_classify()`와 `_auto_record_locked()`를 부르는 별도 흐름이다. 둘 다 일반 화면 조회와 다르며 이번 UI 수정에서 제거하지 않았다.

## 현재 보호와 남은 위험

- 일반 화면과 해당 POST는 owner 역할 및 CSRF 검사를 사용한다. 화면 전용 JS는 중복 클릭 중 버튼을 잠시 비활성화했지만, 서버 요청 ID 멱등성·재시도 안전성은 보장하지 않는다.
- 재분류/기장 경로에는 수동 결정·보류·충돌·파싱 오류·중복·취소/환불 및 기존 기장 보호 분기가 있다. 개별 여행 이동은 요청 기록과 revision을 확인한다. 이는 모든 거래가 불변이라는 보증은 아니다.
- 이번 변경은 일반 화면의 일괄 버튼과 전용 클릭 동작만 제거했다. `POST /api/imports/reclassify-pending`와 서버 처리 함수는 남아 있다. 유효한 owner 세션과 CSRF 토큰을 가진 직접 호출은 여전히 분류, 내부 장부 기록, 기존 장부 여행 귀속을 바꿀 수 있다.
- GET 화면 렌더링은 읽기·집계만 수행하고 해당 일괄 POST를 호출하지 않는다. 배포된 운영 코드와 실제 자료의 동작은 검증하지 않았다.

## 다음 유지보수 작업

별도 `EXPENSE-BULK-MAINT-01`에서 owner 전용 경로와 읽기 전용 사전 미리보기, 미리보기 이후 최신성 확인, 범위 동의, 중복/동시 실행 통제, 비밀정보 없는 감사 기록을 설계해야 한다. 기존 POST를 포함한 모든 쓰기 진입점을 같은 게이트에 묶고 합성 자료로 검증하기 전에는 새 관리 UI를 열지 않는다.

## 표적 검증

실행 명령: `python -m pytest -q webapp/tests/test_cleanup_reclassification.py webapp/tests/test_expense_cleanup.py webapp/tests/test_cleanup_ota_contract.py::test_cleanup_reads_change_no_card_decision_or_ledger_state`.

실제 결과: 29 passed, 1 failed. 기존 실패는 `test_expense_cleanup.py::test_unlinked_booking_explains_missing_connection_without_requesting_card_evidence`이며 기준 커밋 `d4c5934`에서도 같은 실패를 확인했다. 고치지 않았고 재실행하지 않았다. 변경된 지출 정리 UI, 건별 처리, 페이징, 조회 불변성 표적 검사는 통과했다.

전체 회귀, 브라우저 E2E, 운영 API/DB, 배포, 실제 일괄 POST는 실행하지 않았다.
