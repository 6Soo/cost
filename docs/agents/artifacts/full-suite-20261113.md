# 전체 검사 결과 (2026-11-13)

환불 표시 검사 브랜치 `fix/refund-display-checks-20261113`의 기준선·수정 전체 검사 기록이다. 영향 검사가 아니라 `pytest.ini`의 `testpaths`(tests, tools, webapp/tests) 전체를 각 1회 돌렸다. 고객 원문·금액·식별값은 넣지 않는다.

## 실행 개요

| 구분 | 기준 SHA | worktree/명령 | 결과 |
| --- | --- | --- | --- |
| 기준선(main) | `335b9eda56b73fd65e201f39a1ffdefd82c955f3` | detached `.local-archive/main-baseline-335b9eda-20261113/`, `python -m pytest -q -ra -o faulthandler_timeout=240 --junitxml=pytest-full.xml` | **398 failed / 7222 passed / 4 skipped / 1511 subtests passed**, 11472.34s(3:11:12), exit 1 |
| 수정 브랜치 | `4f8e837c30a9590726afad284025b4417564124b` | 메인 worktree, `python -m pytest -q -ra -o faulthandler_timeout=240 --junitxml=.local-archive/refund-display-checks/branch-solo.xml` | **373 failed / 7248 passed / 4 skipped / 1510 subtests passed**, 10285.18s(2:51:25), exit 1 |

JUnit testcase 기준(서브테스트를 별도 testcase로计数): 기준선 9135 중 8733 passed/398 failed/4 skipped/0 errors, 브랜치 9135 중 8758 passed/373 failed/4 skipped/0 errors. skipped 4건은 두 실행 동일하며 브랜치가 추가한 skip/xfail은 없다.

## 차집합 검증 — 브랜치가 고친 것과 신규 회귀

실패 ID 차집합(`.local-archive/compare_suites.py`) 결과:

- **기준선 대비 실패 25건 감소.** 이 25건은 [대조표](refund-display-check-reconciliation-20261113.md)의 (b) 16단위가 덮는 실패와 정확히 일치한다. 분류는 전부 **(b) 승인·배포된 계약으로 대체된 옛 기대값**이며 (a) 운영 코드 결함 수정 0, (c) 검사 수정 0, (d) 검사 수정 0.
- **신규 실제 회귀 0.** 브랜치에만 있는 실패 1건은 아래 간헐이다.
- 간헐 요동 2건은 단독 재실행으로 **(c)** 확정(2 passed/2 subtests, 14.94s):
  - `webapp/tests/test_receipt_page_flow.py::ReceiptPageFlowTests::test_committed_upload_recovers_truncated_or_stalled_response_body` — 브랜치 전체에서 우연 실패, 재실행 통과. #816이 이미 ReceiptPageFlowTests의 route.abort 경합을 (c)로 기록한 계열.
  - `webapp/tests/test_card_catalog_browser.py::CardCatalogBrowserTests::test_menu_search_and_source_review_at_390` — 기준선에서 우연 실패, 브랜치에서 통과. 브랜치가 수정하지 않은 파일.

## 금융 보호 재확인

운영 소스 diff는 없다(테스트·영향 맵·문서만 변경). 환불 짝 `pair_refunds` 연결 1건, 원결제 목적지/항목/`refund_original` 단언, 순액·초과 환불·원본 충돌·수동 교정·다중도 보호 기대값을 삭제·완화하지 않았다. 폐지된 unassigned 조회가 환불을 숨기지 않는 것은 금융 기록 허용 조건 변경이 아니라 폐지 필터의 no-op 계약이다. skip/xfail 추가 없음. 상세는 대조표의 "금융 보호 재확인" 절.

## SRC-045 동일 tick 캐시

미해결. 이번 재개 세션 합성 300회 중 1회 동일 stamp 재현(이전 #815의 300회 중 70회와 별개). 캐시·해싱·읽기 예산 변경 없음. (c) 관측 1건이며 검사 수정 건수와 구분한다. 상세는 대조표의 SRC-045 절과 `docs/policy/CODE_GAPS.md`.

## 이 브랜치가 처리하지 않은 기준선 실패 — 분류만·나열

기준선 398건 중 브랜치가 고친 25건을 제외한 **373건**은 이 브랜치 소관이 아니다. 전체 실행 로그·JUnit에 이름이 보존돼 있다. 대표 실패 트레이스백을 확인한 그룹 분류이며, 전수를 개별 재현한 것은 아니다.

- **(b) 옛 계약 — 다수.** P3(PROC-003·004)가 폐지한 질문/확인 대기 UI(`#questions` 등)를 기다리거나, W3(#799)·CLOSED(#815/PROC-072)로 바뀐 내비게이션·렌더링 계약을 단언하는 브라우저/UI 검사. Playwright `Timeout 30000ms`(폐지된 로케이터 대기) 또는 변경된 문구/구조 단언 실패. 예: `test_real_review_browser`, `test_live_sync_browser`, `test_card_google_copy`, `test_review_ui`, `test_ledger_redesign_*`, `test_global_and_filter_totals`, `test_cleanup_refactor`, `test_review_initial_term_browser` 등.
- **(b) 옛 계약 — 환불 확인 문구/액션.** `webapp/tests/test_refund_inference_runtime.py`의 `test_render_keeps_sources…`, `test_inferred_action_does_not_use_a_trip_label_as_refund_confirmation` — P3가 폐지한 환불 확인 문구·필수 액션을 기대.
- **(d) 판정 보류 — 수동 보류 표시.** `test_refund_inference_runtime.py::test_manual_hold_is_preserved_and_visible_on_either_row[*-original]` — 수동 보류가 데이터(preview)에는 보존되나 expense-cleanup HTML 인라인에 표시되지 않음. 표시 계약 변경인지 결함인지 추가 확인 필요. 보호 기대값을 낮추지 않았으며 이 브랜치가 수정하지 않음.
- **(c) 간헐.** `test_receipt_page_flow…test_committed_upload_recovers_truncated_or_stalled_response_body`(재실행 통과 확인).
- **다른 PR 소관(나열만) — prep-cost/지출 귀속 계열.** `webapp/tests/test_existing_expense_assignment.py`(4), `webapp/tests/test_ota_booking_trip.py::test_preparation_and_ties_are_automatically_inferred_without_financial_writes`, `tests/card_pipeline/test_trip_airfare_descriptor.py`, `tests/card_pipeline/test_trip_currency_comparison.py`, `tests/card_pipeline/test_reserve_trips.py`. 귀속 자동 판정 개선은 별도 과제이며 이 브랜치에서 고치지 않는다.

전체 실패 이름은 `.local-archive/baseline-analysis.txt`(기준선)와 `.local-archive/branch-analysis.txt`(브랜치)에 있다. 원본 로그는 각 worktree의 `pytest-full.log`/`branch-solo.log`.

## origin/main 이동 기록

작업 중 main이 `335b9eda`→`abaa5ba3`(PR #825 카드사 로그인 자동화, 2026-11-13 03:29 병합)로 진행했다. 기준선·수정 전체는 태스크 시작 시점인 `335b9eda`/`4f8e837c` 기준이다. PR 생성 전 `abaa5ba3`를 브랜치에 통합하며, `config/test-impact-map.json`은 자동 병합, `docs/session_handoff.md`는 양쪽 절을 보존해 수동 해결한다. #825가 추가한 카드 로그인 검사는 이 브랜치의 환불 표시 수정과 무관하다.

## 실행 환경 메모

~27% 지점의 `tests/test_cuv_api_persistence.py::test_dispatch_api_10k_rows_and_same_file_retry_metrics`가 첫 업로드 O(n²) 투영 캐시 재구축으로 단독 ~60-70분 걸리는 병목이다. 두 전체 스위트의 10k 구간이 겹치면 서로 정체하므로, 기준선이 10k 구간을 통과한 뒤 브랜치 전체를 시작하는 방식으로 순차화했다. faulthandler 덤프는 테스트당 1회뿐이라 장시간 실행을 멈춤으로 오인하지 않는다.