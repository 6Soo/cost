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
    labeled_outbound = []
    for leg in booking.get("legs") or []:
        if not isinstance(leg, Mapping):
            continue
        label = "".join(str(leg.get("label") or "").split()).casefold()
        leg_dates = []
        for segment in leg.get("segments") or []:
            if isinstance(segment, Mapping) and _day(segment.get("departure_on")):
                leg_dates.append(str(segment["departure_on"])[:10])
        if _day(leg.get("departure_on")):
            leg_dates.append(str(leg["departure_on"])[:10])
        dates.extend(leg_dates)
        if label.startswith("가는") and leg_dates:
            labeled_outbound.extend(leg_dates)
    if labeled_outbound:
        return min(labeled_outbound)
    return min(dates) if dates else ""


def resolve_assignment(booking: Mapping[str, Any], trips: Sequence[Mapping[str, Any]], *,
                       user_assignment: Mapping[str, Any] | None = None,
                       authority_trip_ids: Sequence[str] = ()) -> dict[str, Any]:
    """Resolve one booking to at most one trip; never override explicit decisions."""
    trips = _valid_trips(trips)
    tab_map = {str(t.get("tab_id")): t for t in trips}
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
    ordered = sorted(((t, _day(t.get("start_on") or t.get("starts_on"))) for t in _valid_trips(trips)),
                     key=lambda pair: pair[1] or date.min)
    candidates = []
    for index, (trip, start) in enumerate(ordered):
        end = _day(trip.get("end_on") or trip.get("ends_on"))
        if end is None:
            next_start = next((later_start for _, later_start in ordered[index + 1:]
                               if later_start and start and later_start > start), None)
            if next_start:
                from app.reconciliation import open_trip_end
                end = _day(open_trip_end(start.isoformat(), next_start.isoformat()))
        if start and start <= day and (end is None or day <= end):
            candidates.append((trip, start))
    if not candidates:
        return _result("", "UNRESOLVED", "NO_TRIP_CONTAINS_OUTBOUND", departure)
    winners = ([candidates[0][0]] if len(candidates) == 1 else
               [trip for trip, start in candidates if start == day])
    if len(winners) != 1:
        return _result("", "CONFLICT", "AMBIGUOUS_OUTBOUND_TRIP", departure)
    return _result(str(winners[0]["tab_id"]), "AUTO_INFERRED", "OUTBOUND_WITHIN_TRIP", departure)


def _valid_trips(trips):
    """Keep canonical, usable travel periods before resolving open boundaries."""
    valid = []
    for trip in trips:
        if (not isinstance(trip, Mapping) or not trip.get("tab_id")
                or trip.get("deleted") or trip.get("archived")
                or trip.get("enabled") is False or trip.get("valid") is False
                or trip.get("conflict") or trip.get("period_conflict")):
            continue
        start = _day(trip.get("start_on") or trip.get("starts_on"))
        raw_end = trip.get("end_on") or trip.get("ends_on")
        end = _day(raw_end)
        if not start or (raw_end and not end) or (end and end < start):
            continue
        valid.append(trip)
    return valid


def _result(tab_id: str, status: str, basis: str, departure: str, **extra: Any) -> dict[str, Any]:
    return {"trip_tab_id": tab_id, "assignment_status": status,
            "assignment_basis": basis, "outbound_departure_on": departure, **extra}
