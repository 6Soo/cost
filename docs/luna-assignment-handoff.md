# Luna assignment handoff — 2026-10-28 follow-up

Base implementation commit: `393b540b6cc5a72fb3f8a11110f92fe7f26bb724`

## Review fixes

- Canonical open trip ends use `app.reconciliation.open_trip_end`; missing end closes the day before the next trip. Invalid, disabled, and conflicted periods are filtered.
- Candidates aggregate evidence by trip before ranking. Exact top score ties go to review; no new confidence margin or score threshold is invented. Existing source confidence is carried through.
- Manual confirmed, manual unassigned, hold, and excluded decisions are protected. Classifier uses the shared provisional DTO constructor after its existing authority resolver confirms the selected trip.
- Correction pattern proposal requires repeated owner-approved, identical merchant/trip/date scope and remains inactive until explicit approval. It emits an exact-scope approval result; persistent feedback/UI application remains outside this helper contract.
- Added synthetic-only 10k/100k benchmark: 10k 0.061179s, 100k 0.621966s in this run; 3 top alternatives returned. Naive count shown for comparison is intentionally simple and is not a production baseline.

## Requirements

- PA-01: PARTIAL — synthetic baseline/scale tool available; no real projection baseline because Supervisor-owned UI files remain out of scope.
- PA-02: CODE_WRITTEN / TEST_PASSED — canonical period, grouping, ties, invalid periods and manual/financial protection covered.
- PA-03: PARTIAL — classifier DTO wiring and OTA period candidate helper; owned UI projections still need to consume it.
- PA-04: DEFERRED to Supervisor UI owner. Pass authoritative trips, candidate evidence and manual state into common helper; preserve owner audit path.
- PA-05: PARTIAL — narrow inactive proposal and explicit approval helper; durable correction feedback storage/UI integration remains pending.
- PA-06: PARTIAL — synthetic 10k/100k performance probe and targeted tests. No live runtime, DB, Google, browser, or production validation.

## Verification

`python -m pytest tests/card_pipeline/test_provisional_assignment.py tests/card_pipeline/test_ota_inference.py tests/card_pipeline/test_history_recovery.py tests/card_pipeline/test_booking_mail.py -q` — **86 passed**.

`python tools/benchmark_provisional_assignment.py` — **10k: 0.061179s; 100k: 0.621966s**, synthetic only.

No customer originals, production DB, Google, credentials, or real insurance accessed. No payment solver, financial linkage, or operational writes changed. No push/PR/deploy performed.
## Follow-up verification — 2026-10-28

Commit: pending. The latest correction filters malformed/disabled/conflicted trips before choosing the next trip boundary, so invalid starts cannot truncate a valid open period or raise in `open_trip_end`. Canonical period date flags are honored. Correction evidence must have distinct transaction_id + revision pairs and pass duplicate/conflict exclusions. Approval requires current authoritative trips and returns only an inactive, transaction-level suggestion: the existing `app.rules` intentionally forbids merchant-wide trip assignment. These helpers do not authenticate external authority or grant execution/write permission.

Targeted command: `python -m pytest tests/card_pipeline/test_provisional_assignment.py tests/card_pipeline/test_ota_inference.py -q` — 35 passed before final period-flag addition; rerun required.
