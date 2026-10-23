"""Pure, read-only OTA/card coverage trace helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
from collections import Counter, defaultdict

from app import ota_payments


def pseudonym(secret: bytes, namespace: str, value) -> str:
    """Create a report-local pseudonym; callers must not persist the secret."""
    message = (str(namespace) + "\0" + str(value)).encode("utf-8", "replace")
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()[:24]
    return f"{namespace}_{digest}"


def _row_id(row):
    return str(row.get("transaction_id") or "")


def _event_id(event):
    return str(event.get("ota_event_id") or "")


def _candidate_reasons(event, card, rules):
    """Explain pair checks without allowing unknown dates to suppress candidates."""
    reason = ota_payments.pair_check(event, card, rules)
    if not reason:
        return "EXACT_DATE_CANDIDATE"
    if reason == "payment_date_unknown":
        dated = dict(event, paid_on=card.get("approval_date"))
        if not dated.get("paid_on"):
            return "PAID_DATE_MISSING"
        return ota_payments.pair_check(dated, card, rules) or "DATE_UNKNOWN_CANDIDATE"
    if reason == "date":
        dated = dict(event, paid_on=card.get("approval_date"))
        return ota_payments.pair_check(dated, card, rules) or "DATE_MISMATCH_CANDIDATE"
    return {
        "amount": "AMOUNT_MISMATCH",
        "card_identity": "CARD_IDENTITY_MISMATCH",
        "direction": "DIRECTION_MISMATCH",
        "row_flagged": "CARD_FINANCIAL_HOLD",
    }.get(reason, f"PAIR_REJECTED_{str(reason).upper()}")


def build_coverage_report(*, events, cards, legacy_links=None, user_links=None,
                          frozen_groups=None, source_diagnostics=None,
                          observation_report=None, run_secret=None):
    """Build redacted case rows and counts; never mutates inputs or approves links."""
    secret = run_secret or __import__("secrets").token_bytes(32)
    events, cards = list(events or ()), list(cards or ())
    legacy_links, user_links = legacy_links or {}, user_links or {}
    frozen_groups = list(frozen_groups or ())
    rules = []
    occupied = defaultdict(list)
    for event_id, link in user_links.items():
        card_id = str(link.get("transaction_id") or "") if isinstance(link, dict) else str(link)
        if card_id:
            occupied[card_id].append((str(event_id), "USER_PIN"))
    for group in frozen_groups:
        event_ids = [str(value) for value in group.get("event_ids", ())]
        card_ids = [str(value) for value in group.get("card_ids", ())]
        for card_id in card_ids:
            occupied[card_id].append(("|".join(event_ids), "FROZEN_GROUP"))

    event_candidates, card_candidates = defaultdict(list), defaultdict(list)
    event_rejections, card_rejections = defaultdict(list), defaultdict(list)
    for event in events:
        eid = _event_id(event)
        for card in cards:
            cid = _row_id(card)
            if not eid or not cid:
                continue
            reason = _candidate_reasons(event, card, rules)
            if reason in ("EXACT_DATE_CANDIDATE", "DATE_UNKNOWN_CANDIDATE",
                          "DATE_MISMATCH_CANDIDATE", "PAID_DATE_MISSING"):
                event_candidates[eid].append((cid, reason))
                card_candidates[cid].append((eid, reason))
            else:
                event_rejections[eid].append((cid, reason))
                card_rejections[cid].append((eid, reason))

    cases = []
    for event in events:
        eid = _event_id(event)
        user_link = user_links.get(eid)
        legacy = legacy_links.get(eid)
        legacy_card = str(legacy.get("transaction_id") or "") if isinstance(legacy, dict) else str(legacy or "")
        candidates = event_candidates.get(eid, [])
        reasons = []
        if event.get("evidence_status") not in ("paid_verified", "refund_verified"):
            reasons.append("PAYMENT_STATE_UNVERIFIED")
        if not event.get("paid_on"):
            reasons.append("PAID_DATE_MISSING")
        if not event.get("card_last4"):
            reasons.append("CARD_HINT_MISSING")
        if not candidates:
            reasons.append("NO_CARD_CANDIDATE")
        reasons.extend(reason for _card, reason in event_rejections.get(eid, ()))
        if legacy_card and not any(card == legacy_card for card, _ in candidates):
            reasons.append("LEGACY_NEW_CORE_DISAGREEMENT")
        if len(candidates) and any(card in occupied for card, _ in candidates):
            reasons.append("CANDIDATE_OCCUPIED")
        if len(candidates) > 1:
            reasons.append("CANDIDATE_AMBIGUOUS")
        cases.append({
            "direction": "OTA_TO_CARD", "id": pseudonym(secret, "ota", eid),
            "provider": str(event.get("provider") or "unknown"),
            "evidence_status": str(event.get("evidence_status") or "unknown"),
            "candidate_count": len(candidates),
            "candidates": ([{"id": pseudonym(secret, "card", cid), "basis": basis,
                             "occupied": bool(occupied.get(cid))}
                            for cid, basis in candidates] +
                           [{"id": pseudonym(secret, "card", cid), "basis": basis,
                             "rejected": True, "occupied": bool(occupied.get(cid))}
                            for cid, basis in event_rejections.get(eid, ())]),
            "rejected_pair_count": len(event_rejections.get(eid, ())),
            "legacy_candidate_present": bool(legacy_card),
            "user_pinned": bool(user_link), "reasons": sorted(set(reasons)),
        })
    for card in cards:
        cid = _row_id(card)
        matches = card_candidates.get(cid, [])
        rejected = card_rejections.get(cid, [])
        reasons = ["CARD_DUPLICATE"] if card.get("duplicate_of") else []
        if card.get("parse_error") or card.get("conflict_reason"):
            reasons.append("CARD_FINANCIAL_HOLD")
        if matches:
            reasons.append("CANDIDATE_FOUND")
        reasons.extend(reason for _event, reason in rejected)
        if not matches and not reasons:
            reasons.append("NO_OTA_CANDIDATE")
        cases.append({"direction": "CARD_TO_OTA", "id": pseudonym(secret, "card", cid),
                      "candidate_count": len(matches), "rejected_pair_count": len(rejected),
                      "candidates": ([{"id": pseudonym(secret, "ota", eid), "basis": basis,
                                      "occupied": any(cid in occupied and reason == "USER_PIN"
                                                      for _owner, reason in occupied[cid])}
                                     for eid, basis in matches] +
                                     [{"id": pseudonym(secret, "ota", eid), "basis": basis,
                                       "rejected": True}
                                      for eid, basis in rejected]),
                      "reasons": reasons,
                      "user_pinned": cid in {str(v.get("transaction_id") or "")
                                               for v in user_links.values() if isinstance(v, dict)}})

    reason_counts = Counter(reason for case in cases for reason in case["reasons"])
    providers = Counter(str(event.get("provider") or "unknown") for event in events)
    collisions = defaultdict(set)
    for event in events:
        for source in event.get("source_ids", ()):
            collisions[str(source)].add(_event_id(event))
    safe_observations = dict(observation_report or {})
    safe_observations["skipped"] = [
        {"id": pseudonym(secret, "observation", item.get("source", "")),
         "reason": item.get("reason"), "error_type": item.get("error_type")}
        for item in (observation_report or {}).get("skipped", ())
    ]
    summary = {
        "status": "INCOMPLETE_SOURCE_SET" if source_diagnostics else "COMPLETE_INPUTS",
        "source_diagnostics": list(source_diagnostics or ()),
        "observation_counts": safe_observations,
        "denominators": {"card_rows": len(cards), "ota_observations": (observation_report or {}).get("raw_observations", 0),
                         "verified_payment_events": sum(e.get("evidence_status") in ("paid_verified", "refund_verified") for e in events)},
        "ota_event_count": len(events),
        "provider_event_counts": dict(sorted(providers.items())),
        "candidate_recall_proxy": sum(bool(not legacy_links.get(_event_id(e)) and
                                            event_candidates.get(_event_id(e))) for e in events),
        "legacy_divergence": sum(bool(legacy_links.get(_event_id(e)) and not any(
            cid == (legacy_links[_event_id(e)].get("transaction_id") if isinstance(legacy_links[_event_id(e)], dict)
                   else legacy_links[_event_id(e)]) for cid, _ in event_candidates.get(_event_id(e), [])))
            for e in events),
        "user_link_count": len(user_links), "frozen_group_count": len(frozen_groups),
        "source_id_collision_count": sum(len(ids) > 1 for ids in collisions.values()),
        "case_count": len(cases), "reason_counts": dict(sorted(reason_counts.items())),
        "automatic_link_approvals": 0, "duplicate_expense_delta": 0,
        "existing_owner_decisions_changed": 0,
    }
    return summary, cases
