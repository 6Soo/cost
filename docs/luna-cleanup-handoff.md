# Luna cleanup handoff

- Main baseline: `496cbbe9778e002bc4265f28b50da704d28f042c`
- Work branch: `feat/luna-cleanup-20261028`
- Scope: cleanup query/UI wiring, synthetic cleanup tests and this handoff. No PR297 integration, push, PR, deployment, operating DB, Google or customer data access.

## Requirement status

| ID | Status | Evidence |
| --- | --- | --- |
| ECF-01 | CODE_WRITTEN / TEST_PASSED | Canonical exclusive reason SQL; DISTINCT card counts; card/ledger aggregate and server filtering; exact 20-row paging. Synthetic mixed rows exercised. |
| ECF-02 | CODE_WRITTEN / TEST_PASSED | GET enum allowlist rejects invalid and repeated values with 400; filter links, selection state, pagination URLs, keyboard focus and 44px targets covered by HTTP/Playwright. |
| ECF-03 | CODE_WRITTEN / TEST_PASSED | Save success reloads the same filter URL; stale revision is rejected, then refreshed revision saves and counts refresh. No cleanup POST/API contracts changed. |
| ECF-04 | CODE_WRITTEN / TEST_PASSED | Synthetic browser coverage passed for four nonempty reasons, zero-result state, 21-row pagination, stale/save/reload, and 320/375/390px, light/dark, 200% zoom and keyboard. No operating data used. |
| RF103 cleanup state contract | CODE_WRITTEN / TEST_PASSED | Canonical reason feeds counts and selection; `other_review` is not labeled protected; all eligible cards remain in all-results. |

## Baseline comparison for the two legacy failures

Detached clean worktree at `496cbbe9778e002bc4265f28b50da704d28f042c`; command run in both current and baseline trees:

`python -m pytest webapp/tests/test_expense_cleanup.py::test_unlinked_booking_explains_missing_connection_without_requesting_card_evidence webapp/tests/test_expense_cleanup.py::test_cleanup_cards_hide_per_row_ai_inputs_and_protect_held_rows -q`

Both failures reproduce at baseline: `2 failed in 20.15s` on baseline, and `2 failed in 2.72s` on the current tree. Failure 1 expects the older unlinked-booking copy; current and baseline rendering show the booking-period hold copy. Failure 2 expects the older `거래 검토` label; baseline and current row shows `여행 배정 필요`. These are confirmed baseline failures, not regressions from this work. The clean detached worktree was removed after comparison.

## Current verification

- `python -m pytest webapp/tests/test_card_cleanup_queries.py webapp/tests/test_card_cleanup_ui.py webapp/tests/test_expense_cleanup.py webapp/tests/test_card_flow_browser.py::CardFlowBrowserTests::test_cleanup_filters_save_stale_empty_and_responsive_browser_contract -q`: **35 passed, 2 baseline failures**.
- Focused browser rerun after adding invalid/repeated query rejection checks: **1 passed**.
- `git diff --check`: run before the follow-up commit (rerun for final HEAD).

The browser test exposed and fixed two issues: save success needed a guaranteed document reload when the URL is unchanged, and card-only filters were incorrectly filling remaining page slots with unassigned ledger rows.

## Supervisor wiring / remaining

1. Integrate `webapp/card_flow.py` serially with PR297; do not merge PR297 wholesale into this branch.
2. Re-run the two baseline nodes after integration only if surrounding code changes their rendering path; expected baseline failures are documented above.
3. Operating browser, SQL query-plan and p50/p95 checks were not run; synthetic browser acceptance was completed with temporary data only.

No `docs/session_handoff.md`, `docs/operations.md`, finance/OTA specifications, shared config, Google or operating records were changed.
