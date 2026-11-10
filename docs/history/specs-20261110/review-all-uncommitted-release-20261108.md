# 미커밋·미배포 코드 통합 검토 (2026-11-08)

상태: **COMPLETE** — PR735 병합·운영 `d043892777dc50d1e61d3478440f4148719fd39f` 배포·보호13표 및 영향 경로 최소 수락 완료. 전체 고객 화면의 시각 수락은 별도 미검증.

사용자 승인: “미커밋 변경사항까지 모두 검토해서 배포”. 시작 시 root HEAD `b2763e3f`의 미배포8커밋, tracked25파일/untracked3파일을 SHA256 snapshot으로 보관하고 검토했다. 기존 stash6개는 보존하며 과거 작업을 재실행하지 않는다. 현재 실행 범위는 이 snapshot과 병합된 영수증 복구 PR733이다. 고객 원본은 Git/보고서에 넣지 않는다.

## 반영 범위

- 미배포8커밋: 어드벤처코리아/스카이티켓 항공료 규칙, 여행 관리 단일 집계 조회, 모바일 수입표/보험/합계 배치, 실제 OPEN 사용자 업무만 표시, Google 지출 행 대조와 복사 가능성 안내. 이미 운영 반영된 카드 공백 PR731·후속 문서732를 유지한다.
- 신규 변경: P1/P2 마지막 단계에서 실제 여행 후보가 없는 정상 구매만 원문 결제일(없으면 매입일)의 유효한 분기로 귀속한다. 실제 여행·기존 사용자 결정·3820 예외·원본/중복/환불 보호가 우선이다. 잘못된 날짜를 오늘 날짜로 대체하지 않는다.
- 여행 집계 조회 실패를 0건/0원으로 위장하지 않는다. 실제 삭제 미리보기의 보정/분할 합계와 일치하고, 원행 없는 고아 배분은 집계하지 않는다. Google 합계 수식 경고는 개별 행 금액과 행 합계가 검증될 때만 허용하며 지문·stale·중복·충돌 보호를 유지한다.
- PR733 영수증 복구 코드는 upstream merge `6ddbc7ef9feb796e444704a87ab7733cde8a8e82` 그대로 통합한다. 개별 배포는 하지 않고 이 최종 SHA에 포함한다.
- 운영 DB/기존 거래 재분류·여행 이동·원본/금융/Google 쓰기 및 마이그레이션 없음. 향후 자동 수집도 기존 보호 계약 안에서만 실행한다.

## 파일별 판정

| 파일 | 판정 | 근거 |
| --- | --- | --- |
| `app/__init__.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `app/automatic_classification.py` | REWORKED | Only final no-real-trip normal purchase can use observed valid payment quarter; preserve3820 policy, invalid dates, source and manual guards; never apply production data in this release. |
| `app/classify.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `app/db.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `app/review.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `app/transaction_read_contract.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `tests/card_pipeline/test_card_upload_coverage_review.py` | SUPERSEDED | Already deployed PR731 exact approved code is newer; keep the deployed implementation and stronger tests. |
| `webapp/access_control.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `webapp/autonomous_cleanup_worker.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `webapp/card_actions.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `webapp/card_catalog.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `webapp/card_cleanup_ui.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `webapp/card_flow.py` | PARTIAL | Keep deployed date-gap flow and reviewed local8 open-action suppression; reject root queue removal, false quarter labels, removed unassigned filter and eager trip reload. |
| `webapp/card_upload_coverage.py` | SUPERSEDED | Already deployed PR731 exact approved code is newer; keep the deployed implementation and stronger tests. |
| `webapp/cards_all.py` | PARTIAL | Keep deployed date-gap flow and reviewed local8 open-action suppression; reject root queue removal, false quarter labels, removed unassigned filter and eager trip reload. |
| `webapp/ledger_board.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `webapp/ledger_design.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `webapp/receipt_review.py` | INTEGRATED_PR733 | Receipt owner finished QA307+32 skip0/browser37 and merged6ddbc7ef; include exact upstream files, no duplicate recommit. |
| `webapp/static/js/card_history_workspace.js` | SUPERSEDED | Already deployed PR731 exact approved code is newer; keep the deployed implementation and stronger tests. |
| `webapp/tests/test_card_history_upload_feedback.py` | SUPERSEDED | Already deployed PR731 exact approved code is newer; keep the deployed implementation and stronger tests. |
| `webapp/tests/test_card_upload_coverage_api.py` | SUPERSEDED | Already deployed PR731 exact approved code is newer; keep the deployed implementation and stronger tests. |
| `webapp/tests/test_card_upload_coverage_ui.py` | SUPERSEDED | Already deployed PR731 exact approved code is newer; keep the deployed implementation and stronger tests. |
| `webapp/tests/test_card_upload_management.py` | SUPERSEDED | Already deployed PR731 exact approved code is newer; keep the deployed implementation and stronger tests. |
| `webapp/tests/test_receipt_page_flow.py` | INTEGRATED_PR733 | Receipt owner finished QA307+32 skip0/browser37 and merged6ddbc7ef; include exact upstream files, no duplicate recommit. |
| `webapp/user_action_adapters.py` | REJECTED_ROOT_PATCH | Reject removal of owner/CSRF/user queue/answer/source conflict and refund state protections or misleading blanket complete labels. Corresponding reviewed local8 independent fixes are retained. |
| `_temp_extract_receipt_script.py` | ARCHIVED_DIAGNOSTIC_ONLY | Temporary local script/extracted JS, not a runtime dependency; preserve snapshot and exclude from package. |
| `_temp_receipt_script.js` | ARCHIVED_DIAGNOSTIC_ONLY | Temporary local script/extracted JS, not a runtime dependency; preserve snapshot and exclude from package. |
| `tests/card_pipeline/test_card_destination_contract.py` | REWORKED | Test actual final P1/P2 stage, real-trip precedence, source/invalid-date protection and atomic idempotent synthetic apply instead of premature P1 completion. |

## 검증·종료 조건

- `python tools/run_quality_checks.py --base origin/main --run`의 실제 대상·정확 SHA·skip0/필수 브라우저 및 금융/권한/원본/Google 경계를 확인한다. unknown impact를 무시하지 않는다.
- 변경 화면은 실제 better-interface/layout/ui/typography/colors/accessibility/writing·interface-review 절차로 합성 PC/모바일 전후 및 예외 상태를 검증한다. 기존 메뉴·권한과 사용자 답변을 유지한다.
- 호스팅 CI가 결제/사용 한도로 시작 전에 차단된 경우에만 사용자 승인 Sol medium 이상 정확 SHA 검수 예외를 적용한다. 실제 실패는 수정 후 재검증한다.
- PR 정상 병합 후 검증된 병합 SHA를 고정하고 공식 보호13표·파일 blob·단일 lease·PREVIEW/APPLY로 한 번 배포한다. health/ready·보호API·task/process SHA·영향 읽기 smoke 후 결과를 운영 기록에 남긴다.
- 원본 root 및 진행 중 작성자를 덮지 않는다. 검토에서 제외한 snapshot·임시 진단·기존 stash는 복구 가능하게 보존한다.

## 최종 수락·운영 근거

- 검수 HEAD `1ee5c6983f11e59bb1a2b52f3df90f1eab487165`, 운영 `d043892777dc50d1e61d3478440f4148719fd39f`. Windows 영향 1166 passed +133 subtests, skip0, browser72/72, compile PASS.
- Sol medium 독립 최종 승인 및 interface-review Approve. P3 조회 오류/빈 상태, 실제 큐0일 때 P1/P2 업무 숨김, 메일 캐시와 모바일 행 겹침을 수정·재검증했다. 짧은 보험 문구의 Range 텍스트 경계와 큰 금액/긴 이름을 검증했다.
- 최종 CI는 결제 차단 steps0이며 사용자 승인 예외를 적용했다. CI 녹색 아님. merged tree는 검수 HEAD와 동일, tracked blobs mismatch0·runtime SHA일치·health/ready200·보호API401·보호13표 불변.
- 인증 GET 수락: 카드·여행·영수증 영향 화면 main/heading 및 coverage API200 확인. 고객 원본 파일 확인 POST는 실행하지 않았다.
- 원래8커밋/28파일·기존stash6개는 보존하고 root main을 정상 fast-forward했다. 기존 고객 파일 실제 복구·운영 재분류/재처리·Google 쓰기는 하지 않았다.
- 상세 [운영 기록](../../operations.md)·[현재 상태](../../session_handoff.md). 비공개 final-qa/와 deploy-evidence.json, root-reconciliation.json 및 독립 final-review.json에 정확SHA 근거를 보존했다. 문서 후속으로 재배포하지 않는다.
