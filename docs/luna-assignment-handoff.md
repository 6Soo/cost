# Luna assignment handoff — 2026-10-28 final scope

## Implementation and acceptance

- PA-01: PARTIAL. Synthetic baseline/performance utility exists; no real card/OTA baseline was read because projection sources are Supervisor-owned and real data is prohibited for this worker.
- PA-02: PARTIAL ACCEPTANCE. Common ranker validates canonical trip periods, aggregates evidence by trip, preserves manual/financial holds, and sends equal top scores to review. Thresholds were not invented.
- PA-03: CODE_WRITTEN / TEST_PASSED for the independent OTA projection API. `app.ota_inference.provisional_trip_decisions` calls the common candidate generator/ranker for verified service periods while leaving `unique_pairs` and payment solver outcomes untouched. UI consumption remains Supervisor-owned.
- PA-04: DEFERRED to UI owners. The caller must pass current canonical trips and persisted manual state.
- PA-05: DEFERRED. Existing `app.rule_proposals` and `app.rules` cover classification rules, not trip reassignment; `app.rules.normalize_rule` deliberately rejects merchant-wide trip assignment. No parallel persistence/proposal store was added and no rule boundary was widened. Current owner correction must continue through transaction-level audit path.
- PA-06: PARTIAL. Synthetic 10k/100k benchmark and targeted tests only; no real data, runtime, DB, Google, browser or production validation.

## Verification

At preceding commit `1d98f3748e3a1c7370651c075e171c419a044f5d`, open-period validation, invalid trip filtering, and correction-helper removal were covered. Current targeted command:

`python -m pytest tests/card_pipeline/test_provisional_assignment.py tests/card_pipeline/test_ota_inference.py tests/card_pipeline/test_history_recovery.py tests/card_pipeline/test_booking_mail.py -q`

Result: **88 passed**.

The earlier synthetic benchmark (before OTA ranker wiring): 10k 0.061179s; 100k 0.621966s. It is not a production baseline.

No customer originals, production DB, Google, credentials, or real insurance accessed. No external execution/write permission is implied. No payment solver, financial linkage, or operational write was changed.
