# Luna assignment handoff — 2026-10-28

Base SHA: `496cbbe9778e002bc4265f28b50da704d28f042c` (HEAD == origin/main at start)

## Scope and status

- PA-01: PARTIAL / CODE_WRITTEN. Read-only candidate decision API added; actual baseline extraction from card/OTA projections remains blocked by UI ownership (`webapp/card_flow.py`, `ledger_design.py`, `ota_snapshot.py`, `ota_payment_review.py`).
- PA-02: CODE_WRITTEN. `app/provisional_assignment.py` validates authoritative trips, ranks candidates, protects manual choice and financial hold, and sends tied leaders to review.
- PA-03: PARTIAL / CODE_WRITTEN. `app/classify.py` attaches a provisional decision to `automatic-trip-priority`; OTA confirmed service-period candidate helper added. Existing payment solver remains unchanged. Wiring into UI/ledger projection is owned elsewhere.
- PA-04: DEFERRED (owned UI files); exact wiring contract: UI/card projection passes authoritative trip records and candidate evidence to `rank_trip_candidates`; stores/display `status`, `trip_id`, `reason`, `confidence`, `candidates`, `policy_version` as a read-only projection. Manual selection/hold remains on existing owner audit path.
- PA-05: DEFERRED (feedback storage/approval not in owned scope).
- PA-06: PARTIAL. Synthetic isolated unit tests only; no runtime/real-data/Google/DB validation.

## Protection and limits

No customer originals, production database, Google, credentials, or real insurance accessed. No operational classification/write performed. OTA payment identity, refund and settlement solver was not modified. Old unresolved items are not archived or hidden. `ota_service_period_candidate` returns candidates only; caller must invoke common ranker to resolve overlap.

## Validation

Run: `python -m pytest tests/card_pipeline/test_provisional_assignment.py tests/card_pipeline/test_ota_inference.py -q`

Result: PASS — 82 passed (`test_provisional_assignment`, `test_ota_inference`, `test_history_recovery`, `test_booking_mail`).

## Remaining ownership/wiring

Supervisor-owned UI projection should call the helper with current authoritative trip IDs/date periods and evidence candidates; do not infer ledger or payment status from `AUTO_PROVISIONAL`. UI must retain old unresolved OTA queue visibility and show this as a separate trip-attribution axis. Need validate cross-module contract after integration.
