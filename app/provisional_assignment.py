"""Pure, read-only trip attribution decisions for card and OTA evidence."""
from __future__ import annotations

from datetime import date

POLICY_VERSION = "provisional-trip-v1"


def rank_trip_candidates(candidates, *, trips=(), manual_trip_id=None,
                         financial_hold=False, confidence_gap=1):
    """Rank candidate records against authoritative trips without mutating input.

    Candidate records accept ``trip_id``, ``score``, ``basis`` and optional
    ``service_period``. Trip records require ``trip_id``, ``starts_on`` and
    ``ends_on`` (empty end date means open through the day before next trip).
    """
    if manual_trip_id:
        return _decision("USER_CONFIRMED", manual_trip_id, "사용자 여행 결정 보호", ())
    by_id = {str(t.get("trip_id")): t for t in trips if t.get("trip_id")}
    valid = []
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
        valid.append({"trip_id": trip_id, "score": score,
                      "basis": str(candidate.get("basis") or "근거 부족"),
                      "service_period": candidate.get("service_period")})
    if not valid:
        return _decision("FINANCIAL_HOLD" if financial_hold else "UNASSIGNED_NO_VALID_TRIP", "",
                         "금융 보류" if financial_hold else "유효한 여행 후보 없음", ())
    valid.sort(key=lambda c: (-c["score"], c["trip_id"]))
    top = valid[0]
    alternatives = tuple(valid[:3])
    if financial_hold:
        return _decision("FINANCIAL_HOLD", "", "금융 보류: 여행 후보는 참고 정보", alternatives)
    if len(valid) > 1 and top["score"] - valid[1]["score"] < confidence_gap:
        return _decision("CONFLICT_REVIEW", "", "최상위 여행 후보가 충분히 구분되지 않음", alternatives)
    return _decision("AUTO_PROVISIONAL", top["trip_id"], top["basis"], alternatives,
                     confidence="낮음" if top["score"] < 50 else "중간")


def ota_service_period_candidate(event, trips, *, score=60):
    """Return one candidate per authoritative trip overlapping OTA service dates."""
    period = event.get("service_period") or {}
    start, end = period.get("starts_on"), period.get("ends_on")
    try:
        service_start, service_end = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        return []
    if service_end < service_start or event.get("service_period_conflict"):
        return []
    result = []
    for trip in trips:
        try:
            trip_start = date.fromisoformat(trip["starts_on"])
            trip_end = date.fromisoformat(trip["ends_on"]) if trip.get("ends_on") else None
        except (KeyError, TypeError, ValueError):
            continue
        if trip_start <= service_end and (trip_end is None or service_start <= trip_end):
            result.append({"trip_id": str(trip.get("trip_id") or ""), "score": score,
                           "basis": "OTA 확인 이용기간과 여행 기간 일치",
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
