"""Pure, read-only OTA/card coverage trace helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
from collections import Counter, defaultdict

from app import ota_payments

PROVIDERS = frozenset(('agoda', 'trip', 'booking', 'klook', 'toyoko', 'unknown'))
EVIDENCE_STATUSES = frozenset(('paid_verified', 'refund_verified', 'scheduled',
    'reservation_only', 'unverified', 'observed', 'conflict', 'evidence_conflict', 'refund_conflict', 'unknown'))
ENGINE_STATUSES = frozenset(('MATCHED_AUTO', 'MATCHED_USER', 'HOLD_AMBIGUOUS',
    'HOLD_AMOUNT_MISMATCH', 'HOLD_AMOUNT_UNVERIFIED', 'HOLD_DATE_UNKNOWN',
    'HOLD_EVIDENCE_CONFLICT', 'HOLD_GROUP_CHANGED', 'HOLD_NO_CARD', 'HOLD_PARTIAL_GROUP',
    'NOT_CARD_CHARGE', 'PENDING_PAYMENT', 'RESERVATION_ONLY', 'NO_RESULT', 'UNKNOWN'))
OBSERVATION_REASONS = frozenset(('SOURCE_UNREADABLE', 'SOURCE_MISSING', 'NO_PAYMENT_EVENT',
    'SOURCE_CONFLICT', 'RAW_PAYLOAD_MISSING', 'PAYMENT_COMPONENT_MISSING_OR_UNVERIFIED',
    'SOURCE_ID_COLLISION', 'POSSIBLE_SOURCE_COPY', 'PAYMENT_EVENT_CREATED',
    'EVIDENCE_ROLE_MISSING', 'SOURCE_EVIDENCE_CONFLICT', 'BOOKING_IDENTITY_MISMATCH',
    'BOOKING_AMOUNT_INVALID', 'PAID_TODAY_COMPONENT_MISSING', 'REFUND_STATUS_UNRESOLVED',
    'CARD_HINT_MISSING_OR_INVALID', 'SERVICE_PERIOD_INVALID', 'PAYMENT_COMPONENT_AMOUNT_INVALID',
    'PAYMENT_NOT_VERIFIED_UNKNOWN', 'PAYMENT_NOT_VERIFIED_UNVERIFIED',
    'PAYMENT_NOT_VERIFIED_SCHEDULED', 'PAYMENT_NOT_VERIFIED_PROPERTY_COLLECT',
    'PAYMENT_NOT_VERIFIED_CANCELLED', 'PAYMENT_NOT_VERIFIED_CONFLICT'))
ERROR_TYPES = frozenset(('ValueError', 'TypeError', 'KeyError', 'OSError', 'FileNotFoundError',
    'PermissionError', 'JSONDecodeError', 'UnicodeDecodeError', 'OperationalError',
    'DatabaseError', 'IntegrityError', 'OtaSourcesError', 'SOURCE_READ_ERROR'))
SOURCE_KINDS = ('mail_directory', 'portal_database', 'reference_document', 'unified_database')


def finite(value, allowed):
    """Never echo arbitrary source text, including malformed non-string values."""
    return value if isinstance(value, str) and value in allowed else 'UNKNOWN'


def safe_error_type(value):
    return finite(value, ERROR_TYPES)


def _count(value):
    return value if type(value) is int and value >= 0 else 'UNKNOWN'


def _reason_counts(values):
    result = {}
    for key, value in (values.items() if isinstance(values, dict) else ()):
        key = finite(key, OBSERVATION_REASONS)
        count = _count(value)
        previous = result.get(key, 0)
        result[key] = previous + count if type(previous) is int and type(count) is int else 'UNKNOWN'
    return result


def _diagnostic(value):
    allowed = {'SOURCE_UNREADABLE', 'SOURCE_DIAGNOSTIC'} | set(ERROR_TYPES)
    allowed.update('SOURCE_MISSING:' + kind for kind in SOURCE_KINDS)
    for prefix in ('REVIEW_SOURCE_', 'LEGACY_MATCHER_', 'RECONCILIATION_ENGINE_'):
        allowed.update(prefix + error for error in ERROR_TYPES)
    return finite(value, allowed)


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
    """Explain shared candidate-search results without treating them as confirmed links."""
    result = ota_payments.search_card_candidates(event, [card], rules=rules, max_comparisons=1)
    candidates = result.get("candidates", ())
    if candidates:
        return {"UNKNOWN": "DATE_UNKNOWN_CANDIDATE", "MISMATCH": "DATE_MISMATCH_CANDIDATE",
                "MATCH": "EXACT_DATE_CANDIDATE"}.get(candidates[0].get("date_status"),
                                                       "EXACT_DATE_CANDIDATE")
    reasons = result.get("rejection_counts", {})
    for code in ("AMOUNT_MISMATCH", "CURRENCY_MISMATCH", "CARD_IDENTITY_MISMATCH",
                 "CARD_FINANCIAL_HOLD", "PROVIDER_ALIAS_MISSING"):
        if reasons.get(code):
            return code
    return "NO_CARD_CANDIDATE"


def build_coverage_report(*, events, cards, legacy_links=None, user_links=None,
                          frozen_groups=None, source_diagnostics=None,
                          observation_report=None, run_secret=None,
                          reconciliation_results=None):
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
            elif reason in ("AMOUNT_MISMATCH", "CURRENCY_MISMATCH", "CARD_IDENTITY_MISMATCH",
                            "CARD_FINANCIAL_HOLD", "PROVIDER_ALIAS_MISSING"):
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
            "provider": finite(event.get("provider") or "unknown", PROVIDERS),
            "evidence_status": finite(event.get("evidence_status") or "unknown", EVIDENCE_STATUSES),
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
    providers = Counter(finite(event.get("provider") or "unknown", PROVIDERS) for event in events)
    result_by_event = {str(row.get("ota_event_id")): row
                       for row in (reconciliation_results or ())
                       if row.get("ota_event_id") is not None}
    result_statuses = Counter(finite(row.get("status") or "UNKNOWN", ENGINE_STATUSES)
                              for row in result_by_event.values())
    reconciliation_divergences = []
    for event in events:
        event_id = _event_id(event)
        result = result_by_event.get(event_id)
        legacy = legacy_links.get(event_id)
        legacy_card = (str(legacy.get("transaction_id") or "")
                       if isinstance(legacy, dict) else str(legacy or ""))
        result_card = str((result or {}).get("transaction_id") or "")
        if result is None or result_card != legacy_card:
            reconciliation_divergences.append({
                "id": pseudonym(secret, "ota", event_id),
                "legacy_link_present": bool(legacy_card),
                "engine_link_present": bool(result_card),
                "engine_status": finite((result or {}).get("status") or "NO_RESULT", ENGINE_STATUSES),
                "user_pinned": event_id in user_links,
            })
    collisions = defaultdict(set)
    for event in events:
        for source in event.get("source_ids", ()):
            collisions[str(source)].add(_event_id(event))
    observations = observation_report or {}
    safe_observations = {key: _count(observations[key]) for key in (
        'raw_mail_observations', 'raw_portal_observations', 'raw_observations',
        'skipped_observation_count', 'portal_local_id_reuse_count', 'possible_source_copy_count')
        if key in observations}
    if 'skipped_reason_counts' in observations:
        safe_observations['skipped_reason_counts'] = _reason_counts(observations['skipped_reason_counts'])
    safe_observations["skipped"] = [
        {"id": pseudonym(secret, "observation", item.get("source", "")),
         "reason": ([finite(reason, OBSERVATION_REASONS) for reason in item['reason']]
                    if isinstance(item.get('reason'), list) else finite(item.get('reason'), OBSERVATION_REASONS)),
         "error_type": safe_error_type(item['error_type']) if item.get('error_type') is not None else None}
        for item in observations.get("skipped", ()) if isinstance(item, dict)
    ]
    summary = {
        "status": "INCOMPLETE_SOURCE_SET" if source_diagnostics else "COMPLETE_INPUTS",
        "source_diagnostics": [_diagnostic(value) for value in source_diagnostics or ()],
        "observation_counts": safe_observations,
        "denominators": {"card_rows": len(cards), "ota_observations": _count(observations.get("raw_observations", 0)),
                         "verified_payment_events": sum(e.get("evidence_status") in ("paid_verified", "refund_verified") for e in events)},
        "ota_event_count": len(events),
        "provider_event_counts": dict(sorted(providers.items())),
        "candidate_recall_proxy": sum(bool(not legacy_links.get(_event_id(e)) and
                                            event_candidates.get(_event_id(e))) for e in events),
        "legacy_divergence": sum(bool(legacy_links.get(_event_id(e)) and not any(
            cid == (legacy_links[_event_id(e)].get("transaction_id") if isinstance(legacy_links[_event_id(e)], dict)
                   else legacy_links[_event_id(e)]) for cid, _ in event_candidates.get(_event_id(e), [])))
            for e in events),
        "reconciliation_engine_status_counts": dict(sorted(result_statuses.items())),
        "legacy_engine_divergence_count": len(reconciliation_divergences),
        "user_link_count": len(user_links), "frozen_group_count": len(frozen_groups),
        "source_id_collision_count": sum(len(ids) > 1 for ids in collisions.values()),
        "case_count": len(cases), "reason_counts": dict(sorted(reason_counts.items())),
        "automatic_link_approvals": 0, "duplicate_expense_delta": 0,
        "existing_owner_decisions_changed": 0,
    }
    summary["reconciliation_divergences"] = reconciliation_divergences
    return summary, cases
