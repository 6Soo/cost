"""Route OTA payment events to the mandatory P2 source review of DECISION_POLICY §3.0.

The rule is already canonical on main: an OTA event that is a *verified card
charge* but that P1 did not match to a card row must be handed to P2 for a
mandatory source comparison, even when the expense row's item/trip
classification is already complete. No code performed that routing; P2 target
selection only dumped transactions (`tools/p2_batch/scope.py:select`) and its
own `service_warnings`, and OTA events never entered it.

This module is the routing *decision* only. It is pure: no database, no file
IO, no network, no model call, no write, and no new user-facing state. It never
creates a card relation, a booking reference, a payment date, a ledger entry or
a Google value. It is not wired into any runtime yet; the P2 runner (M5 queue /
M6 event boundary) is a separate change. Callers must keep the returned event
references local and pseudonymize (see `app/reconcile/trace.py:pseudonym`) before
publishing anything.

LINK-044 obligations encoded here (current canonical wording):

* every candidate is classified MATCH / MISMATCH / UNKNOWN, never promoted;
* a missing gateway alias or financial hold is *UNKNOWN*, not a proven
  counterparty conflict (DECISION_POLICY §3.5 item 2/4);
* several accepted candidates are M:N evidence, not a failure;
* "P2 finished and found no relation" and "P2 did not run / failed / has
  incomplete evidence" are different states (PROC-010), and P2 never records a
  verified relation (§3.0).
"""
from __future__ import annotations

from collections import Counter

from app import ota_payments
from app.reconcile import index_results

# Obligation outcomes. Names describe evidence, not workflow states; none of
# them is a screen label and none may be presented as a booking/ledger fact.
EXACT_RELATION = "CARD_RELATION_EXACT"
INFERRED_RELATION = "CARD_RELATION_INFERENCE_ONLY"
INVESTIGATION_REQUIRED = "CARD_RELATION_INVESTIGATION_REQUIRED"
OUT_OF_SCOPE = "OUT_OF_CARD_RELATION_SCOPE"
RESULT_UNAVAILABLE = "ENGINE_RESULT_UNAVAILABLE"

# Sub-state of INVESTIGATION_REQUIRED. P2_RUN_* requires an actual run record.
INVESTIGATION_STATES = (
    "P2_NOT_STARTED",
    "P2_RUN_FAILED",
    "P2_RUN_INVALID",
    "P2_COMPLETED_UNVERIFIED",
)

# LINK-044 detail a P2 record must carry before it counts as an actual review.
REQUIRED_DETAIL = (
    "candidate_outcomes",
    "sources",
    "policy_version",
    "explicit_conflicts",
    "candidate_ranking",
)
ACCEPTED_OUTCOMES = ("no_relation", "relation_unverified")

CANDIDATE_STATES = ("MATCH", "MISMATCH", "UNKNOWN")

# Reason vocabulary of the card-candidate search, mapped to LINK-044 signals.
# Source: app/ota_payments.py:search_card_candidates rejection_counts and
# compare_payment_amount reasons.
_UNKNOWN_REASONS = frozenset((
    "PROVIDER_ALIAS_MISSING",   # an unregistered alias is not a proven conflict
    "CARD_FINANCIAL_HOLD",      # duplicate/parse/conflict protection, not evidence
    "CARD_DUPLICATE",
    "AMOUNT_EVIDENCE_REQUIRED",
    "FX_EVIDENCE_REQUIRED",
))
_MISMATCH_REASONS = frozenset((
    "AMOUNT_MISMATCH",
    "CURRENCY_MISMATCH",
    "CARD_IDENTITY_MISMATCH",
))

# Matching-result statuses. MATCHED_* without a transaction id is inconsistent.
_MATCHED_STATUSES = ("MATCHED_AUTO", "MATCHED_USER", "MATCHED_GROUP")
_INVESTIGATION_STATUSES = (
    "HOLD_NO_CARD", "HOLD_AMOUNT_MISMATCH", "HOLD_AMOUNT_UNVERIFIED",
    "HOLD_DATE_UNKNOWN", "HOLD_EVIDENCE_CONFLICT", "HOLD_GROUP_CHANGED",
    "HOLD_PARTIAL_GROUP", "HOLD_AMBIGUOUS",
)
_OUT_OF_SCOPE_STATUSES = ("NOT_CARD_CHARGE", "PENDING_PAYMENT", "RESERVATION_ONLY")


def _status(result):
    return str((result or {}).get("status") or "NO_RESULT")


def candidate_signal(entry):
    """Classify one search candidate or rejected pair as MATCH/MISMATCH/UNKNOWN.

    `entry` is one row of `search_card_candidates` output: either a rejected
    pair (`reason`) or an accepted candidate (`date_status`, `resolution_allowed`).
    """
    if not isinstance(entry, dict):
        return "UNKNOWN"
    reason = entry.get("reason")
    if reason in _MISMATCH_REASONS:
        return "MISMATCH"
    if reason is not None:
        # Any other rejection means the pair was not usable as evidence. It is
        # only a proven mismatch when the reason names an explicit conflict.
        return "UNKNOWN"
    if entry.get("resolution_allowed"):
        return "MATCH"
    if entry.get("date_status") == "MISMATCH":
        return "MISMATCH"
    return "UNKNOWN"


def candidate_summary(search):
    """Return per-candidate MATCH/MISMATCH/UNKNOWN counts and M:N preservation.

    A search that never ran (no `status`) is reported as zero evidence, not as
    "no candidates exist". `SEARCH_LIMIT_EXCEEDED` keeps the truncation flag.
    """
    if not isinstance(search, dict):
        return {"state": "SEARCH_NOT_RUN", "counts": {}, "candidate_count": 0,
                "m_n_preserved": False, "truncated": False}
    counts = Counter()
    accepted = 0
    for entry in search.get("candidates") or ():
        counts[candidate_signal(entry)] += 1
        accepted += int(candidate_signal(entry) == "MATCH")
    for entry in search.get("rejected") or ():
        counts[candidate_signal(entry)] += 1
    return {
        "state": str(search.get("status") or "UNKNOWN"),
        "counts": {key: counts[key] for key in CANDIDATE_STATES if counts[key]},
        "candidate_count": accepted,
        # Two or more accepted edges are evidence of an M:N component, not a
        # failure (LINK-003). One accepted edge is still not an approval.
        "m_n_preserved": accepted > 1,
        "truncated": str(search.get("status") or "") == "SEARCH_LIMIT_EXCEEDED",
    }


def investigation_state(record):
    """Read a P2 run record; never treat absence or failure as a completed review.

    A record that claims a verified relation is rejected: §3.0 keeps financial
    links in the verified P1 path, so P2 can only report an unverified relation.
    """
    if not isinstance(record, dict):
        return "P2_NOT_STARTED", ()
    if record.get("outcome") in ("failed", "error") or record.get("error"):
        return "P2_RUN_FAILED", ()
    if record.get("outcome") == "relation_verified" or record.get("relation_verified"):
        return "P2_RUN_INVALID", ("P2_CANNOT_VERIFY_RELATION",)
    missing = tuple(name for name in REQUIRED_DETAIL if not record.get(name))
    if missing or record.get("outcome") not in ACCEPTED_OUTCOMES:
        return "P2_RUN_INVALID", tuple("MISSING_" + name.upper() for name in missing) or (
            "P2_OUTCOME_NOT_UNVERIFIED",)
    return "P2_COMPLETED_UNVERIFIED", ()


def route(event, result, *, p2_record=None, search=None):
    """One event's routing record. Reads inputs only; confirms no relation."""
    event = event if isinstance(event, dict) else {}
    status = _status(result)
    paid = bool(ota_payments._event_is_paid(event))
    transaction_id = str((result or {}).get("transaction_id") or "")
    inferred = (result or {}).get("inferred_link")

    record = {
        "event_ref": str(event.get("ota_event_id") or ""),
        "provider": str(event.get("provider") or "unknown"),
        "engine_status": status,
        "payment_date_verified": bool(
            not inferred and (result or {}).get("payment_date_verified", True)),
        "reason_codes": [],
        "investigation": None,
        "detail_findings": (),
    }

    if status in _MATCHED_STATUSES and transaction_id:
        if inferred:
            # An inference is not a verified 1:1/M:N relation; §3.0 item 2 also
            # sends period-unknown lodging to P2 before any date substitution.
            record["obligation"] = INFERRED_RELATION
            record["reason_codes"] = ["INFERRED_LINK_NOT_VERIFIED"]
            record["investigation"] = investigation_state(p2_record)[0]
            record["detail_findings"] = investigation_state(p2_record)[1]
        else:
            record["obligation"] = EXACT_RELATION
        return record

    if status in _MATCHED_STATUSES:
        # MATCHED without a card row is internally inconsistent. Review it; do
        # not report a relation from a missing identifier.
        record["obligation"] = RESULT_UNAVAILABLE
        record["reason_codes"] = ["MATCHED_WITHOUT_TRANSACTION_ID"]
        return record

    if not paid or status in _OUT_OF_SCOPE_STATUSES:
        # Reservation-only, unverified, not-charged or pending events carry no
        # actual card charge, so no card relation can be demanded (LINK-091).
        record["obligation"] = OUT_OF_SCOPE
        record["reason_codes"] = ["NOT_A_VERIFIED_CARD_CHARGE" if not paid else status]
        return record

    if status == "NO_RESULT" or status == "UNKNOWN":
        record["obligation"] = RESULT_UNAVAILABLE
        record["reason_codes"] = ["ENGINE_RESULT_MISSING"]
        return record

    if status not in _INVESTIGATION_STATUSES:
        record["obligation"] = RESULT_UNAVAILABLE
        record["reason_codes"] = ["ENGINE_STATUS_UNKNOWN"]
        return record

    # A verified charge with a hold: §3.0 makes this a mandatory P2 review.
    state, findings = investigation_state(p2_record)
    record.update(obligation=INVESTIGATION_REQUIRED, investigation=state,
                  detail_findings=findings)
    record["reason_codes"] = [status]
    if (result or {}).get("inferred_link"):
        record["reason_codes"].append("INFERRED_LINK_NOT_VERIFIED")
    if search is not None:
        summary = candidate_summary(search)
        record["candidate_evidence"] = summary
        if summary["truncated"]:
            record["reason_codes"].append("CANDIDATE_SEARCH_TRUNCATED")
        if summary["m_n_preserved"]:
            record["reason_codes"].append("M_N_EDGES_PRESERVED")
    return record


def plan(events, results, *, p2_records=None, searches=None):
    """Aggregate routing for a whole read pass. Returns counts and local routes.

    `p2_records` / `searches` are keyed by `ota_event_id`. Duplicate or malformed
    result rows are invalidated by the shared `index_results` contract, so an
    ambiguous event is reported as unavailable rather than silently resolved.
    """
    events = list(events or ())
    indexed = index_results(results)
    p2_records = p2_records or {}
    searches = searches or {}
    routes = []
    for event in events:
        identity = str((event or {}).get("ota_event_id") or "")
        routes.append(route(event, indexed.get(identity),
                            p2_record=p2_records.get(identity),
                            search=searches.get(identity)))
    obligations = Counter(row["obligation"] for row in routes)
    states = Counter(row["investigation"] for row in routes if row["investigation"])
    reasons = Counter(code for row in routes for code in row["reason_codes"])
    return {
        "event_count": len(events),
        "engine_result_count": len(indexed),
        "obligations": dict(sorted(obligations.items())),
        "investigation_states": dict(sorted(states.items())),
        "reason_counts": dict(sorted(reasons.items())),
        # Aggregates only. Per-event rows stay local; pseudonymize before publishing.
        "routes": routes,
        "run_mode": "READ_ONLY",
        "creates_relation": False,
    }
