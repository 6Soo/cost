# Provisional trip review integration handoff

Base main: `61211012a0bbd250ab5e5fa6b629e3af9e672324`, merged normally into this feature branch. Core checkpoint c253086 is included. Existing PR297 refund replay and PR299 cleanup filters are preserved. Main merge/deploy/archive remain assigned to supervisor 3cebc37b; no production writes were run here.

## Requirement state

| ID | State | Actual scope / remaining boundary |
|---|---|---|
| PA-01 | PARTIAL | Synthetic baseline tool and current batch read-only projection; real customer baseline/shadow not measured. |
| PA-02 | CODE_WRITTEN / TEST_PASSED | Common authority validator, open periods, semantic grouping and ranker. Card fallback now shares locality/date/net ordering and leaves semantic ties unresolved rather than using ID/start as an arbitrary tiebreak. Archived/deleted/invalid periods excluded. |
| PA-03 | CODE_WRITTEN / TEST_PASSED | Existing classification persists trip_id/display_tab_id; the review reads those real fields and never invents an assignment on GET. OTA worker creates the independent DTO once per generation from verified portal or existing authenticated-mail period evidence. Policy/trip inputs invalidate the key. Manual unassignment and financial/source holds stay protected; payment identity/status are unchanged. |
| PA-04 | CODE_WRITTEN / TEST_PASSED | Owner-only lazy review on /import with 20-row server pagination, generation checks, provisional/unassigned/manual filters, actual evidence/alternatives, explicit confirmed correction using the existing revisioned decision endpoint, and explicit idempotent hold. No bulk reclassification or GET writes. |
| PA-05 | CODE_WRITTEN / TEST_PASSED (transaction-exact scope) | Owner selects 2-20 distinct current manual decisions with identical scope. Pending proposals use the existing append-only change_log, not a new schema/store. Approval receives only the stored proposal ID, enforces owner+CSRF+explicit confirmation, then rechecks current authority, revision, source hash, holds/refunds/duplicates/exclusions. Proposal UI shows source date/merchant/amount plus item/trip scope, disables stale approval. Existing exact-source rules/audit remain atomic and replay-safe; merchant-wide trip assignment remains prohibited. Broader future-pattern generalization is not introduced. Actual owner review/correction counts/rate are measured only from newly observed audit events, with unmeasured rate null. |
| PA-06 | PARTIAL | Targeted regression, synthetic HTTP/browser/responsive/zoom/theme and snapshot checks passed. Production shadow, deployed SHA, protected table/health smoke and real-data acceptance belong to the deploy supervisor and have not run in this checkout. |

## Changed behavior and boundaries

New modules: app/trip_correction_review.py, webapp/provisional_trip_review.py. Existing CardFlow dispatch and fallback are extended. The shared app.review protection helper also protects original purchases with same-issuer/card original-approval-linked refunds; the existing save_decision transaction appends trip_assignment.reviewed evidence only for inferred decisions. A failed measurement audit rolls back the decision and its old audit too. No monetary/source/ID edits or new schema are introduced.

GET review is bounded to 20 rows, does not parse mail or run a financial matcher, and reports missing persisted attribution separately from candidate suggestions. Current manual decisions remain protected. Supplementary trip review leaves the deployed cleanup reason partition/counts intact. All mutations are explicit owner calls; holds do not clear financial holds, rules do not reclassify existing rows, and Google writes remain absent.

## Executed verification

- New controller/storage/HTTP/browser suite: `python -m pytest webapp/tests/test_provisional_trip_review.py -q` -> **11 passed**. Real synthetic HTTP browser covers initial lazy state, 20/3 page movement, selection/proposal without active rules, explicit approval, hold, existing decision POST, owner review audit, 320/375/390/760/1440 widths, both color schemes and 200% zoom. Temporary SQLite and synthetic CSV only.
- Core + financial boundaries: `python -m pytest tests/card_pipeline/test_provisional_assignment.py tests/card_pipeline/test_ota_inference.py tests/card_pipeline/test_history_recovery.py tests/card_pipeline/test_booking_mail.py tests/card_pipeline/test_rule_proposals.py tests/card_pipeline/test_ota_payments.py tests/card_pipeline/test_ota_exact_gate.py tests/card_pipeline/test_ota_reservation_identity.py -q` -> **215 passed**.
- New/core/snapshot combined after authenticated-mail and key wiring -> **90 passed**: new review + provisional_assignment + ota_inference + ota_snapshot_service/display_context/actions.
- Priority/pipeline and existing cleanup browser combined -> **59 passed**; after the extra atomic measurement case, review/priority/pipeline alone -> **59 passed**.
- OTA telemetry/projection/paging/candidate/pages/detail/summary -> **163 passed**.
- Snapshot service/display/action standalone -> **32 passed**.
- CardFlow plus inline refund action/query/UI adjacent suite -> **83 passed, 28 subtests passed, 6 baseline failures**. Each exact failed node below was run from a clean git-archive export of main6121101 and failed identically. These failures are not counted as passes.

Baseline failures in webapp/tests/test_card_flow.py::CardFlowTests:
1. test_canonical_undated_ota_inference_flows_through_classification_and_expense (inferred_link KeyError)
2. test_reconciliation_snapshot_drives_ota_card_status_and_preserves_trip_expense (ota-synthetic missing)
3. test_review_mail_evidence_reuses_in_memory_cache (provider versus no_core_event)
4. test_same_approval_purchase_and_cancellation_both_reach_the_board (applied0 versus2)
5. test_same_card_and_approval_from_another_issuer_is_a_separate_transaction (applied0 versus4)
6. test_worker_managed_card_page_does_not_parse_all_mail_under_request_lock (OTA label)

Synthetic benchmark current result: 10k candidates0.022637s,100k0.246842s, both CONFLICT_REVIEW; this is not a production SLA or real correction-rate claim.

## Integration

Branch feat/luna-assignment-20261028 includes core implementation and normal merges of mainad117 and main6121101. Integrate the branch with a normal feature PR rather than reapplying participant/OTA commits individually. Main/root shared documents were not edited by this supervisor. The older finance/OTA spec additions from the worker remain in the feature diff for canonical-doc owner review.

Next: supervisor reviews the final exact SHA and runs normal main PR integration, fixed-SHA deployment and minimum operational protected-table/health/API smoke. Do not run real reassignment, bulk processing, insurer registration/transfer, Google writes or migrations under the code-deploy approval. Keep real-data acceptance explicitly unmeasured until separately observed.
