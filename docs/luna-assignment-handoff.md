# Luna assignment handoff — PA scope

Base implementation: `393b540b6cc5a72fb3f8a11110f92fe7f26bb724`.

## Acceptance state

- PA-01: PARTIAL. Synthetic baseline/performance tool exists; no real card/OTA baseline was read because projection sources are Supervisor-owned and real data is prohibited for this worker.
- PA-02: PARTIAL ACCEPTANCE. Common ranker validates canonical trip periods, groups evidence by trip, preserves manual/financial holds, and sends equal top scores to review. No confidence margin was invented.
- PA-03: CODE_WRITTEN / TEST_PASSED. `app.ota_inference.provisional_trip_decisions` calls the common candidate generator/ranker for verified service periods without changing `unique_pairs` or payment solver results. UI consumer wiring remains Supervisor-owned.
- PA-04: DEFERRED to UI owners. Caller passes current authoritative trips and persisted manual state.
- PA-05: CODE_WRITTEN / TEST_PASSED for exact-source proposal and persistence. Distinct owner corrections produce a deterministic pending DTO. Approval revalidates latest transaction revision, source hash, manual trip/item, conflict/duplicate status and current trip authority, then saves one `inferred_assignment` rule per source hash through existing `app.rules.save_rule` and writes approval to existing append-only `change_log` in one savepoint. Replays are idempotent. Rules preserve the existing ban on merchant-wide trip effects. Pending proposal storage and authenticated owner authorization remain caller/API responsibilities; the helper's `approved_by` field is audit metadata, not an authorization check.
- PA-06: PARTIAL. Synthetic 10k/100k benchmark and targeted tests only; no runtime/real-data/DB/Google/browser/production validation.

## Verification

`python -m pytest tests/card_pipeline/test_provisional_assignment.py tests/card_pipeline/test_ota_inference.py tests/card_pipeline/test_history_recovery.py tests/card_pipeline/test_booking_mail.py tests/card_pipeline/test_rule_proposals.py -q` — **110 passed**.

Earlier synthetic benchmark: 10k 0.061179s; 100k 0.621966s before OTA decision wiring. This is not a production baseline.

No customer originals, production DB, Google, credentials, or real insurance accessed. No payment solver, financial linkage, operational write, bulk reclassification, push, PR, or deploy performed. UI wiring and merge/deployment acceptance remain outside this worker's scope.
