"""Pure, read-only trip attribution decisions for card and OTA evidence."""
from __future__ import annotations

from datetime import date

POLICY_VERSION = "provisional-trip-v1"
MANUAL_STATES = {"USER_CONFIRMED", "MANUAL_UNASSIGNED", "MANUAL_HOLD", "MANUAL_EXCLUDED"}


def canonical_trip_periods(trips):
    """Apply the shared open-end rule and discard invalid/non-authoritative trips."""
    rows = []
    for raw in trips:
        trip = dict(raw)
        period_flags = set(trip.get("flags") or trip.get("period_flags") or ())
        if (not trip.get("trip_id") or trip.get("enabled") is False
                or trip.get("valid") is False or trip.get("conflict")
                or trip.get("period_conflict")
                or period_flags & {"PERIOD_START_MISSING", "PERIOD_START_MISMATCH",
                                   "PERIOD_DATE_INVALID", "PERIOD_ORDER"}):
            continue
        try:
            start = date.fromisoformat(trip["starts_on"])
            end = date.fromisoformat(trip["ends_on"]) if trip.get("ends_on") else None
            if end and end < start:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((start, trip))
    rows.sort(key=lambda pair: pair[0])
    from .reconciliation import open_trip_end
    for index, (start, trip) in enumerate(rows):
        if trip.get("ends_on"):
            continue
        following = next((other_start.isoformat() for other_start, _ in rows[index + 1:]
                          if other_start > start), None)
        trip["ends_on"] = open_trip_end(trip.get("starts_on"), following)
    return {str(trip["trip_id"]): trip for _, trip in rows}


def provisional_trip_decision(trip_id, *, basis, confidence="낮음"):
    """Build the shared decision DTO after an existing authority resolver validates the trip."""
    candidate = {"trip_id": str(trip_id), "basis": str(basis), "confidence": confidence}
    return _decision("AUTO_PROVISIONAL", str(trip_id), candidate["basis"], [candidate], confidence)


def propose_correction_pattern(corrections):
    """Create an inactive existing-rule-core DTO from distinct owner correction rows."""
    rows = [dict(row) for row in corrections if row.get("owner_approved") is True
            and row.get("merchant_normalized") and row.get("trip_id")
            and row.get("service_start") and row.get("service_end")
            and row.get("transaction_id") and row.get("revision") is not None
            and not row.get("duplicate_of") and not row.get("conflict_reason")]
    unique = {(r["transaction_id"], str(r["revision"])): r for r in rows}
    rows = list(unique.values())
    signatures = {(r["merchant_normalized"], r["trip_id"], r["service_start"], r["service_end"])
                  for r in rows}
    if len(rows) < 2 or len(signatures) != 1:
        return {"status": "NO_PROPOSAL", "active": False, "corrections": len(rows)}
    merchant, trip_id, start, end = next(iter(signatures))
    return {"status": "PENDING_OWNER_APPROVAL", "active": False, "scope": {
        "merchant_normalized": merchant, "trip_id": trip_id,
        "service_start": start, "service_end": end}, "corrections": len(rows)}


def approve_correction_pattern(proposal, *, approved_by, trips=()):
    """Validate owner approval and return a non-executable suggestion for manual review."""
    if (not approved_by or not isinstance(proposal, dict)
            or proposal.get("status") != "PENDING_OWNER_APPROVAL"
            or proposal.get("active") is not False):
        raise ValueError("OWNER_APPROVAL_REQUIRED")
    scope = proposal.get("scope") or {}
    if set(scope) != {"merchant_normalized", "trip_id", "service_start", "service_end"}:
        raise ValueError("INVALID_CORRECTION_SCOPE")
    try:
        start, end = date.fromisoformat(scope["service_start"]), date.fromisoformat(scope["service_end"])
    except (TypeError, ValueError):
        raise ValueError("INVALID_CORRECTION_SCOPE") from None
    if end < start:
        raise ValueError("INVALID_CORRECTION_SCOPE")
    trip = canonical_trip_periods(trips).get(scope["trip_id"])
    if not trip or not _valid_period(trip, {"starts_on": scope["service_start"],
                                             "ends_on": scope["service_end"]}):
        raise ValueError("TRIP_NOT_AUTHORITATIVE")
    # Existing app.rules deliberately rejects merchant rules that assign a trip.
    # Preserve that boundary; the owner-approved suggestion is not executable.
    return {"status": "OWNER_APPROVED_SUGGESTION", "active": False,
            "approved_by": str(approved_by), "scope": dict(scope),
            "requires_transaction_level_decision": True, "policy_version": POLICY_VERSION}


def rank_trip_candidates(candidates, *, trips=(), manual_trip_id=None, manual_status=None,
                         financial_hold=False):
    """Validate, deduplicate by trip, then rank candidates without mutating input."""
    if manual_status in MANUAL_STATES:
        return _decision(manual_status, manual_trip_id or "", "사용자 결정 보호", ())
    if manual_trip_id is not None:
        return _decision("USER_CONFIRMED", str(manual_trip_id or ""), "사용자 여행 결정 보호", ())
    by_id = canonical_trip_periods(trips)
    grouped = {}
    for raw in candidates:
        candidate = dict(raw)
        trip_id = str(candidate.get("trip_id") or "")
        trip = by_id.get(trip_id)
        if not trip or not _valid_period(trip, candidate.get("service_period")):
            continue
        try:
            score = int(candidate.get("score", 0))
        except (TypeError, ValueError):
            continue
        group = grouped.setdefault(trip_id, {"trip_id": trip_id, "score": score,
            "basis": set(), "confidence": candidate.get("confidence", "낮음"),
            "service_period": candidate.get("service_period")})
        group["score"] = max(group["score"], score)
        basis = str(candidate.get("basis") or "근거 부족")
        group["basis"].add(basis)
    valid = [{**group, "evidence_count": len(group["basis"]),
              "basis": " · ".join(sorted(group["basis"])[:3])} for group in grouped.values()]
    if not valid:
        status = "FINANCIAL_HOLD" if financial_hold else "UNASSIGNED_NO_VALID_TRIP"
        return _decision(status, "", "금융 보류" if financial_hold else "유효한 여행 후보 없음", ())
    valid.sort(key=lambda c: (-c["score"], c["trip_id"]))
    alternatives = valid[:3]
    if financial_hold:
        return _decision("FINANCIAL_HOLD", "", "금융 보류: 여행 후보는 참고 정보", alternatives)
    if len(valid) > 1 and valid[0]["score"] == valid[1]["score"]:
        return _decision("CONFLICT_REVIEW", "", "최상위 여행 후보 동률", alternatives)
    top = valid[0]
    return _decision("AUTO_PROVISIONAL", top["trip_id"], top["basis"], alternatives,
                     confidence=top["confidence"])


def ota_service_period_candidate(event, trips, *, score=0):
    """Return candidates where verified OTA service dates overlap canonical trip periods."""
    period = event.get("service_period") or {}
    try:
        start, end = date.fromisoformat(period["starts_on"]), date.fromisoformat(period["ends_on"])
    except (KeyError, TypeError, ValueError):
        return []
    if end < start or event.get("service_period_conflict") or event.get("period_conflict"):
        return []
    result = []
    for trip in canonical_trip_periods(trips).values():
        try:
            trip_start = date.fromisoformat(trip["starts_on"])
            trip_end = date.fromisoformat(trip["ends_on"]) if trip.get("ends_on") else None
        except (KeyError, TypeError, ValueError):
            continue
        if trip_start <= end and (trip_end is None or start <= trip_end):
            result.append({"trip_id": str(trip["trip_id"]), "score": score,
                           "confidence": "낮음", "basis": "OTA 확인 이용기간과 여행 기간 일치",
                           "service_period": dict(period)})
    return result


def _valid_period(trip, service_period):
    try:
        starts = date.fromisoformat(trip["starts_on"])
        ends = date.fromisoformat(trip["ends_on"]) if trip.get("ends_on") else None
        if ends and ends < starts:
            return False
        if service_period:
            service_start = date.fromisoformat(service_period["starts_on"])
            service_end = date.fromisoformat(service_period["ends_on"])
            return service_end >= service_start and starts <= service_end and (ends is None or service_start <= ends)
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _decision(status, trip_id, reason, candidates, confidence="낮음"):
    return {"status": status, "trip_id": trip_id, "reason": reason,
            "confidence": confidence, "candidates": list(candidates),
            "policy_version": POLICY_VERSION}
