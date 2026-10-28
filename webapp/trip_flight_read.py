"""Read-only projection and API contract for trip flight bookings."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping, Sequence

from app.trip_flight_assignment import resolve_assignment

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _booking_key(provider: str, booking_ref: str, digests: Sequence[str]) -> str:
    lineage = hashlib.sha256("|".join(sorted(map(str, digests))).encode()).hexdigest()[:16]
    return f"{provider}:{booking_ref.strip().upper()}:{lineage}"


def project_trip_bookings(index: Mapping[str, Any], trips: Sequence[Mapping[str, Any]], *,
                          source_generation: str, user_assignments: Mapping[str, Mapping[str, Any]] | None = None,
                          authority_trip_ids: Mapping[str, Sequence[str]] | None = None,
                          evidence_status: str = "FRESH") -> dict[str, Any]:
    """Group verified passengers into one booking and assign it to one trip."""
    assignments, authorities = user_assignments or {}, authority_trip_ids or {}
    bookings = []
    seen = set()
    for ref, evidence in (index or {}).items():
        if not isinstance(evidence, Mapping) or not evidence.get("source_digests"):
            continue
        provider = str(evidence.get("provider") or "trip").lower()
        key = _booking_key(provider, str(ref), evidence["source_digests"])
        if key in seen:
            continue
        seen.add(key)
        legs = []
        for leg in evidence.get("legs") or []:
            if not isinstance(leg, Mapping):
                continue
            legs.append({"label": leg.get("label"), "departure_on": leg.get("departure_on"),
                         "segments": [{k: seg.get(k) for k in (
                             "departure_on", "departure_airport", "arrival_airport",
                             "flight_number", "departure_time", "arrival_time")}
                             for seg in leg.get("segments") or [] if isinstance(seg, Mapping)]})
        # The verified parser has already merged repeated observations. Count its
        # passenger records; equal names may represent distinct travelers.
        passenger_count = sum(isinstance(p, Mapping) for p in evidence.get("passengers") or [])
        facts = {"provider": provider, "booking_ref": str(ref), "legs": legs}
        assigned = resolve_assignment(facts, trips, user_assignment=assignments.get(key),
                                      authority_trip_ids=authorities.get(key, ()))
        departure = assigned["outbound_departure_on"]
        bookings.append({"provider": provider, "booking_key": key, "booking_ref": str(ref),
                         "passenger_count": passenger_count,
                         "legs": legs, "outbound_departure_on": departure,
                         "assigned_trip_tab_id": assigned["trip_tab_id"],
                         "assignment_status": assigned["assignment_status"],
                         "assignment_basis": assigned["assignment_basis"],
                         "assignment_conflict": assigned.get("conflict", False),
                         "inferred_trip_tab_id": assigned.get("inferred_trip_tab_id", ""),
                         "source_generation": source_generation,
                         "evidence_status": "CONFLICT" if evidence.get("conflict") else evidence_status,
                         "booking_status": ("CONFLICT" if evidence.get("cancellation_status") == "CONFLICT"
                                            or evidence.get("conflict") else
                                            "CANCELLED" if evidence.get("cancellation_status") not in (None, "NONE")
                                            else "ACTIVE"),
                         "reserved_on": evidence.get("reserved_on", ""),
                         "booking_date_status": evidence.get("booking_date_status", "UNKNOWN")})
    bookings.sort(key=lambda b: (b["outbound_departure_on"] or "9999-99-99", b["booking_key"]))
    return {"source_generation": source_generation, "evidence_status": evidence_status,
            "bookings": bookings}


def page_for_trip(projection: Mapping[str, Any], trip_tab_id: str, *, limit: int = DEFAULT_LIMIT,
                  cursor: str = "", status: str = "active") -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError("INVALID_LIMIT")
    generation = str(projection.get("source_generation") or "")
    offset = 0
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("INVALID_CURSOR") from None
        if not isinstance(data, dict) or data.get("generation") != generation:
            raise LookupError("SOURCE_CHANGED")
        if data.get("trip") != trip_tab_id or data.get("status") != status or type(data.get("offset")) is not int or data["offset"] < 0:
            raise ValueError("INVALID_CURSOR")
        offset = data["offset"]
    all_items = [b for b in projection.get("bookings", []) if b.get("assigned_trip_tab_id") == trip_tab_id]
    if status == "active":
        all_items = [b for b in all_items if b["booking_status"] == "ACTIVE"]
    elif status != "all":
        raise ValueError("INVALID_STATUS")
    items = all_items[offset:offset + limit]
    more = offset + len(items) < len(all_items)
    next_cursor = None
    if more:
        raw = json.dumps({"generation": generation, "trip": trip_tab_id, "status": status,
                          "offset": offset + len(items)}, separators=(",", ":")).encode()
        next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return {"trip_tab_id": trip_tab_id, "source_generation": generation,
            "evidence_status": projection.get("evidence_status", "UNAVAILABLE"),
            "total_bookings": len(all_items),
            "verified_passenger_count": sum(b["passenger_count"] for b in all_items),
            "items": items, "next_cursor": next_cursor, "has_conflicts": any(
                b["assignment_status"] in ("CONFLICT", "UNRESOLVED") or b["assignment_conflict"]
                or b["evidence_status"] == "CONFLICT" for b in all_items)}


def trip_read_allowed(*, is_owner: bool, trip: Mapping[str, Any] | None,
                      allowed_trip_ids: Sequence[str] = ()) -> bool:
    """Owner or explicitly authorized trip reader; archived/deleted trips are refused."""
    if not trip or trip.get("deleted") or trip.get("archived"):
        return False
    return bool(is_owner or str(trip.get("tab_id") or "") in set(map(str, allowed_trip_ids)))


def handle_get(handler: Any, *, board: Any, trip_tab_id: str, query: Mapping[str, Sequence[str]],
               is_owner: bool, allowed_trip_ids: Sequence[str] = (), trip: Mapping[str, Any] | None = None,
               trips: Sequence[Mapping[str, Any]] | None = None,
               index: Mapping[str, Any] | None = None, source_generation: str = "",
               evidence_status: str = "UNAVAILABLE", user_assignments: Mapping[str, Mapping[str, Any]] | None = None,
               authority_trip_ids: Mapping[str, Sequence[str]] | None = None) -> dict[str, Any]:
    """Build GET response from caller-held worker snapshot; performs no collection/reconciliation."""
    if trip is None and board is not None:
        trip = next((t for t in board.live_trips(include_archived=True)
                     if str(t.get("tab_id")) == str(trip_tab_id)), None)
    if not trip_read_allowed(is_owner=is_owner, trip=trip, allowed_trip_ids=allowed_trip_ids):
        return {"code": "TRIP_NOT_FOUND"}
    if index is None:
        return {"code": "FLIGHT_SOURCE_UNAVAILABLE"}
    try:
        limit = int((query.get("limit") or [str(DEFAULT_LIMIT)])[0])
        cursor = str((query.get("cursor") or [""])[0])
        status = str((query.get("status") or ["active"])[0])
        trip_list = list(trips if trips is not None else (
            board.live_trips(include_archived=True) if board is not None else []))
        projection = project_trip_bookings(index, trip_list, source_generation=source_generation,
            user_assignments=user_assignments, authority_trip_ids=authority_trip_ids,
            evidence_status=evidence_status)
        return page_for_trip(projection, trip_tab_id, limit=limit, cursor=cursor, status=status)
    except LookupError:
        return {"code": "SOURCE_CHANGED"}
    except (ValueError, TypeError, IndexError):
        return {"code": "INVALID_QUERY"}


def dispatch(handler: Any, parsed: Any, *, board: Any, is_owner: bool,
             allowed_trip_ids: Sequence[str] = (), raw: bytes | None = None,
             query: Mapping[str, Sequence[str]] | None = None,
             snapshot: Mapping[str, Any] | None = None) -> bool:
    """GET-only API route helper; caller passes an already-held worker snapshot."""
    import re
    from urllib.parse import parse_qs
    match = re.fullmatch(r"/api/trips/([^/]+)/flight-bookings", str(getattr(parsed, "path", "")))
    if not match:
        return False
    if raw is not None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    trip_id = match.group(1)
    trips = board.live_trips(include_archived=True) if board else []
    trip = next((t for t in trips if str(t.get("tab_id")) == trip_id), None)
    if not trip_read_allowed(is_owner=is_owner, trip=trip, allowed_trip_ids=allowed_trip_ids):
        handler._send_json({"code": "TRIP_NOT_FOUND"}, 404)
        return True
    snap = snapshot or {}
    data = snap.get("data") or {}
    result = handle_get(handler, board=board, trip_tab_id=trip_id,
        query=query or parse_qs(getattr(parsed, "query", "")), is_owner=is_owner,
        allowed_trip_ids=allowed_trip_ids, trip=trip, trips=trips,
        index=data.get("passengers") if snap.get("fresh") else None,
        source_generation=str(snap.get("generation") or ""),
        evidence_status="FRESH" if snap.get("fresh") else "UNAVAILABLE")
    code = result.get("code")
    handler._send_json(result, 409 if code == "SOURCE_CHANGED" else 503 if code == "FLIGHT_SOURCE_UNAVAILABLE" else 422 if code == "INVALID_QUERY" else 200)
    return True
