# Luna cleanup handoff

- Main baseline: `496cbbe9778e002bc4265f28b50da704d28f042c`
- Work branch: `feat/luna-cleanup`
- Scope: `webapp/card_flow.py`, new `webapp/card_cleanup_queries.py`, independent cleanup tests, and this handoff. No PR297 merge/cherry-pick, push, PR, deployment, customer or operations data access.

## Requirement status

| ID | Status | Implementation and evidence |
| --- | --- | --- |
| ECF-01 | CODE_WRITTEN / TEST_PASSED | Canonical exclusive card reason SQL (`protected`, `no_item`, `no_trip`, `other_review`), distinct transaction aggregation, card/ledger disjoint totals, server-side reason filtering and 20-row paging. `python -m pytest webapp/tests/test_card_cleanup_queries.py -q` passed in the combined run. |
| ECF-02 | CODE_WRITTEN / TEST_PASSED | GET enum allowlist, malformed/multi-valued reason returns 400, safe page parsing, anchor links, single-select `aria-current`, keyboard focus and minimum 44px targets, selected reason/page links. Cleanup UI contract test passed in combined run. |
| ECF-03 | CODE_WRITTEN / TEST_PASSED | Successful existing POST reloads current URL and fragment, recomputing authoritative counts and current page. Synthetic empty/filter tests passed. Existing CSRF/revision/write APIs unchanged. |
| ECF-04 | PARTIAL | Exact status labels corrected; other-review is not reported as protected. Synthetic 20-row pagination and mixed card/ledger count exercised. No real operating DB, browser viewport, query-plan, or p50/p95 measurement performed. |
| RF103 cleanup status contract | CODE_WRITTEN / TEST_PASSED | The same canonical classifier supplies count/list filtering; all eligible existing cards remain in `all`, and categories are exclusive. Updated legacy count expectation. |

## Verification

Command: `python -m pytest webapp/tests/test_card_cleanup_queries.py webapp/tests/test_expense_cleanup.py webapp/tests/test_card_cleanup_ui.py -q`

Result: 34 passed, 2 failed. A focused rerun of `python -m pytest webapp/tests/test_card_cleanup_queries.py webapp/tests/test_card_cleanup_ui.py -q` passed (11 passed). The two remaining failures are display assertions in `test_unlinked_booking_explains_missing_connection_without_requesting_card_evidence` and `test_cleanup_cards_hide_per_row_ai_inputs_and_protect_held_rows`; observed output contains the booking-period hold copy and `여행 배정 필요` label respectively. They do not involve reason-filter totals/URLs. Baseline equivalence was not checked, so treat them as unresolved pending the integrating owner’s baseline comparison. No failure was treated as a pass.

## Supervisor wiring / remaining

1. Integrate this branch's `card_flow.py` edits serially with PR297; do not take PR297 wholesale into this branch.
2. Confirm `/import` dispatch sends 400 for invalid `cleanup_reason`, and the normal owner-only route still renders every allowed enum.
3. Resolve the two remaining stale/current-copy assertions after comparing against the approved integrated baseline.
4. Run protection-boundary tests for card decision CSRF/revision, duplicate IDs, partial refunds, and ledger save after integration.
5. Record any browser/SQL performance verification separately; none was run here.

No `docs/session_handoff.md`, `docs/operations.md`, finance/OTA specifications, shared config, Google, or operating records were changed.
