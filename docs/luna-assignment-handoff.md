# Luna assignment handoff — PA scope

Base implementation: `393b540b6cc5a72fb3f8a11110f92fe7f26bb724`. Latest PA-05 guard implementation: `e9a0f2f44907e629a9afab4bb9df912a511073d9`; protection regression tests: `e1a29aab41838cb8629a6e1a3c729bb85a51a323`.

## Acceptance state

- PA-01: PARTIAL. Synthetic baseline/performance tool exists; no real card/OTA baseline was read because projection sources are Supervisor-owned and real data is prohibited for this worker.
- PA-02: PARTIAL ACCEPTANCE. Common ranker validates canonical trip periods, groups evidence by trip, preserves manual/financial holds, and sends equal top scores to review. No confidence margin was invented.
- PA-03: CODE_WRITTEN / TEST_PASSED. `app.ota_inference.provisional_trip_decisions` calls the common candidate generator/ranker for verified service periods without changing `unique_pairs` or payment solver results. UI consumer wiring remains Supervisor-owned.
- PA-04: DEFERRED to UI owners. Caller passes current authoritative trips and persisted manual state.
- PA-05: TEST_PASSED for exact-source proposal, approval and protected persistence. Approval rechecks latest revision/source hash/manual trip/item and authoritative trip, calls the shared review protection checker for current parse errors, cancellation/refund direction/kind, duplicate/conflict, review holds and company exclusion, and independently rejects duplicate transaction IDs or source hashes in forged proposal contents. Rules and append-only approval audit roll back together on save failure while an outer transaction remains intact. Existing merchant-wide trip-effect ban remains. Pending proposal storage and authenticated owner/CSRF authorization remain caller/API responsibilities; `approved_by` is audit metadata, not an authorization check. No customer ledger, bulk reclassification or operational writes were used.
- PA-06: PARTIAL. Synthetic 10k/100k benchmark and targeted tests only; no runtime/real-data/DB/Google/browser/production validation.

## Verification

`python -m pytest tests/card_pipeline/test_provisional_assignment.py tests/card_pipeline/test_ota_inference.py tests/card_pipeline/test_history_recovery.py tests/card_pipeline/test_booking_mail.py tests/card_pipeline/test_rule_proposals.py -q` at `e1a29aab41838cb8629a6e1a3c729bb85a51a323` — **120 passed**. Added synthetic checks for each persisted hold class, parse error, cancellation/refund direction and kind, company exclusion, stale owner revision, forged duplicate transaction/source references, and second-rule failure with outer-transaction preservation.

Earlier synthetic benchmark: 10k 0.061179s; 100k 0.621966s before OTA decision wiring. This is not a production baseline.

No customer originals, production DB, Google, credentials, or real insurance accessed. No payment solver, financial linkage, operational write, bulk reclassification, push, PR, or deploy performed. UI wiring and merge/deployment acceptance remain outside this worker's scope.
