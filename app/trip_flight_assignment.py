"""Pure assignment policy for verified flight bookings and COST trip tabs."""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def outbound_departure(booking: Mapping[str, Any]) -> str:
    """Return earliest actual segment departure, independent of leg ordering."""
    dates = []
    for leg in booking.get("legs") or []:
        if not isinstance(leg, Mapping):
            continue
        for segment in leg.get("segments") or []:
            if isinstance(segment, Mapping) and _day(segment.get("departure_on")):
                dates.append(str(segment["departure_on"])[:10])
        if _day(leg.get("departure_on")):
            dates.append(str(leg["departure_on"])[:10])
    return min(dates) if dates else ""


def resolve_assignment(booking: Mapping[str, Any], trips: Sequence[Mapping[str, Any]], *,
                       user_assignment: Mapping[str, Any] | None = None,
                       authority_trip_ids: Sequence[str] = ()) -> dict[str, Any]:
    """Resolve one booking to at most one trip; never override explicit decisions."""
    tab_map = {str(t.get("tab_id")): t for t in trips if t.get("tab_id")}
    departure = outbound_departure(booking)
    user_trip = str((user_assignment or {}).get("trip_tab_id") or "")
    if user_trip:
        if user_trip not in tab_map:
            return _result("", "CONFLICT", "CONFIRMED_TRIP_MISSING", departure)
        inferred = _infer(departure, trips)
        conflict = bool(inferred["trip_tab_id"] and inferred["trip_tab_id"] != user_trip)
        return _result(user_trip, "USER_CONFIRMED", "USER_CONFIRMED", departure,
                       conflict=conflict, inferred_trip_tab_id=inferred["trip_tab_id"])

    authority = set(map(str, authority_trip_ids))
    if len(authority) > 1:
        return _result("", "CONFLICT", "MULTIPLE_AUTHORITY_TRIPS", departure)
    if authority:
        trip_id = next(iter(authority))
        if trip_id not in tab_map:
            return _result("", "CONFLICT", "AUTHORITY_TRIP_MISSING", departure)
        return _result(trip_id, "AUTHORITY_VERIFIED", "VERIFIED_BOOKING_AUTHORITY", departure)
    return _infer(departure, trips)


def _infer(departure: str, trips: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    day = _day(departure)
    if day is None:
        return _result("", "UNRESOLVED", "OUTBOUND_DATE_MISSING", departure)
    ordered = sorted(((t, _day(t.get("start_on") or t.get("starts_on"))) for t in trips),
                     key=lambda pair: pair[1] or date.min)
    candidates = []
    for index, (trip, start) in enumerate(ordered):
        end = _day(trip.get("end_on") or trip.get("ends_on"))
        if end is None:
            next_start = next((later_start for _, later_start in ordered[index + 1:] if later_start), None)
            if next_start:
                from datetime import timedelta
                end = next_start - timedelta(days=1)
        if start and start <= day and (end is None or day <= end):
            candidates.append((trip, start))
    if not candidates:
        return _result("", "UNRESOLVED", "NO_TRIP_CONTAINS_OUTBOUND", departure)
    latest = max(start for _, start in candidates)
    winners = [trip for trip, start in candidates if start == latest]
    if len(winners) != 1:
        return _result("", "CONFLICT", "AMBIGUOUS_OUTBOUND_TRIP", departure)
    return _result(str(winners[0]["tab_id"]), "AUTO_INFERRED", "OUTBOUND_WITHIN_TRIP", departure)


def _result(tab_id: str, status: str, basis: str, departure: str, **extra: Any) -> dict[str, Any]:
    return {"trip_tab_id": tab_id, "assignment_status": status,
            "assignment_basis": basis, "outbound_departure_on": departure, **extra}
