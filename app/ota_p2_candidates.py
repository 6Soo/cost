"""P2 entry adapter over `app.ota_p2_routing` — which OTA events P2 must review.

`app/ota_p2_routing` (PR #1034) states, per verified OTA charge, whether the
card relation is exact, inference-only, required to investigate, out of scope,
or unavailable. The autonomous P2 worker selects targets from card *transaction*
rows only, so an OTA event that P1 could not match never reaches P2 selection.

This adapter closes exactly that gap and nothing more: it takes the same inputs
`ota_p2_routing.plan()` already consumes and returns the local set of OTA events
whose obligation is `CARD_RELATION_INVESTIGATION_REQUIRED` or
`CARD_RELATION_INFERENCE_ONLY` — i.e. the events P2 must carry into its review.

Guarantees (unchanged from the router):
* It never creates a card relation, booking reference, payment date or ledger
  value, and it never touches a DB, file, network or model.
* It never re-opens a verified relation: `CARD_RELATION_EXACT` events are not
  targets, and a manual/confirmed link is `EXACT` there, so it is preserved.
* It returns local `event_ref` identifiers only; no `transaction_id` or
  booking reference leaves this function.
"""
from __future__ import annotations

from app import ota_p2_routing

# Obligations that must reach P2 review. A verified relation (EXACT) and the
# no-charge / unavailable cases are deliberately excluded.
_REVIEW_OBLIGATIONS = (
    ota_p2_routing.INVESTIGATION_REQUIRED,
    ota_p2_routing.INFERRED_RELATION,
)


def investigation_targets(events, results, *, p2_records=None, searches=None):
    """Return the OTA events P2 must review, as a read-only plan.

    `events`, `results`, `p2_records`, `searches` are exactly what
    `ota_p2_routing.plan()` accepts. The result carries the target event refs,
    the per-obligation counts it saw, and hardcoded non-write flags. It is pure:
    the inputs are not mutated and no relation is created.
    """
    report = ota_p2_routing.plan(events, results,
                                 p2_records=p2_records, searches=searches)
    routes = report.get("routes") or ()
    targets = []
    for row in routes:
        if row.get("obligation") in _REVIEW_OBLIGATIONS:
            ref = str(row.get("event_ref") or "")
            if ref:
                targets.append(ref)
    return {
        "targets": targets,
        "target_count": len(targets),
        "obligations": report.get("obligations") or {},
        "run_mode": "READ_ONLY",
        "creates_relation": False,
    }
