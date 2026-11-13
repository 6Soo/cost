# 자동 기록 원자성·금액 묶음 정렬 확인 (2026-11-13)

승인 범위는 헤드의 운영 결함 2건 지시다. 시작 `96fb90e8`, 브랜치 `fix/amount-group-and-revision-20261113`. 운영 DB·포트·고객 자료를 사용하지 않았다. 병합·배포는 하지 않았으며 서버 변경이므로 배포가 필요하다.

## 1. 투영 실패 뒤 revision 증가 — 수정

`auto_record`의 사전 `_classify`가 자체 트랜잭션을 끝내고, 이후 장부·화면 투영만 별도 트랜잭션에서 롤백됐다. 자동 기록 요청의 분류·revision·장부·화면 투영·감사·멱등 요청 기록을 외부 트랜잭션으로 묶었다. `ledger.commit`과 `quarter_tab.confirm_tab`은 외부 트랜잭션이 있으면 savepoint로 참여하고, 단독 호출은 기존 BEGIN IMMEDIATE 경계를 유지한다. 원문·금액·연결·기록 자격·환불 및 수동 보호 판정은 변경하지 않았다.

- 기존 `test_projection_failure_rolls_back_the_entire_automatic_write`: 수정 전 revision 1→2 잔존으로 실패, 수정 후 통과.
- 신규 합성 5건: 첫/두 번째 투영을 실제로 쓴 뒤 실패시키고 transactions·ledger_entries·board_rows·board_revisions·change_log·requests 전체가 이전과 일치함을 검증했다. 호출자의 외부 트랜잭션 유무, 그 이전 쓰기 보존, 재시도 2건 기록·재실행 0건, 성공 후 호출자 rollback도 검증했다.
- 기존 자동 기록 파일(별도 작업자 소관인 `real_blocking` 제외): 9 passed, 1 deselected. 제외는 성공으로 계산하지 않는다.
- 신규 5건 + 기존 부분 환불 검사 31건: 36 passed.

## 2. 금액 묶음 정렬 회귀 의심 — 운영 수정 없음

지정 board/http 파일과 기존 투영 실패 재현을 함께 실행: **6 failed / 2 passed**. 실패는 revision 1, board 4, HTTP 1이다. board 4 중 순서 관련은 3건이며 나머지 1건은 그룹 details 펼침 계약, HTTP는 로더 호출 횟수 기대다. 화면 계약 판정과 검사 정리는 병행 담당 소관이다.

정렬 함수 `sort_for_display` 자체의 exact/partial/unmatched·Google 행 순서·부분집합·입력 불변 단언은 통과하고, 첫 정렬 테스트는 마지막 renderer 순서 단언에서만 실패했다. `8cd0e58bb366ba4017eb299b0f1de263d765ea5a` (`feat(ui): rebuild trip ledger workspace`)는 `_group_expenses_for_display(sort_for_display(...))`를 명시적으로 제거하고 날짜 오름차순 및 같은 날짜 항목 순위로 바꿨다. 모바일도 같은 변경이다. 과거 승인 계약 `docs/history/specs-20261110/uiux-full-audit-redesign-20261110.md`의 지출 표 절(현재 359행)은 기본 날짜 오름차순을 규정한다. 이 문서는 새 과제 지시가 아닌 현재 코드 변경의 근거로만 확인했다.

따라서 Google 순서/숙박 이용일 그룹 순서가 기본 렌더러를 지배한다는 검사는 이전 계약이다. 금액 오름차순을 검증하는 테스트도 아니다. 정렬 회귀로 되돌리지 않고, 해당 5개 실패의 검사·화면 계약 정리는 병행 G4/G5 담당에게 남겼다. 이 PR은 해당 테스트 기대값과 `ledger_design.py`, `card_catalog.py`, `card_transactions.py`를 수정하지 않았다.

## 영향 검사·인계

`python tools/run_quality_checks.py --base origin/main --run`: **PASSED**, base `96fb90e8096bc42a205515e9bc470b5ce9ca3fe4`, 코드 HEAD `fde5af7b94e48a616fe93cade9af8017e548e5aa`. 575 passed·30 subtests passed·skip 0·browser 16건 실행/누락 0·compile PASS, 712.92초. 근거는 이 worktree의 `quality-artifacts/run-summary.json`, `junit.xml`, `pytest.log`에 보존했다(미추적, 커밋하지 않음). 원자성 신규 파일을 기존 card-flow 영향 그룹에 추가했다.

PR #846을 생성하고 push했다. 헤드가 전달한 opus 검수는 `77c5561e` 코드 APPROVE다. 이후 변경은 이 문서와 `docs/session_handoff.md` 새 절의 손상된 한글을 UTF-8(BOM 없음)로 복원한 것뿐이다. 코드 변경·테스트 재실행·병합·배포는 하지 않았다. 최종 SHA는 PR HEAD를 따르며, 헤드의 병합과 서버 배포가 남았다.
