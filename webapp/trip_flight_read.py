"""Read-only projection and API contract for trip flight bookings."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence

from app.trip_flight_assignment import resolve_assignment

DEFAULT_LIMIT = 20
MAX_LIMIT = 20


def _booking_key(provider: str, booking_ref: str) -> str:
    normalized_ref = re.sub(r"[^A-Z0-9]", "", booking_ref.upper())
    return f"{provider.lower()}:{normalized_ref}"


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
        key = _booking_key(provider, str(ref))
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
        passenger_names = [" ".join(str(p.get(k) or "").strip() for k in ("surname", "given_name")).strip()
                           for p in evidence.get("passengers") or [] if isinstance(p, Mapping)]
        facts = {"provider": provider, "booking_ref": str(ref), "legs": legs}
        assigned = resolve_assignment(facts, trips, user_assignment=assignments.get(key),
                                      authority_trip_ids=authorities.get(key, ()))
        departure = assigned["outbound_departure_on"]
        route = _route_summary(legs)
        bookings.append({"provider": provider, "booking_key": key, "booking_ref": str(ref),
                         "passenger_count": passenger_count,
                         "passengers": passenger_names,
                         "route_summary": route,
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
                         "booking_date_status": evidence.get("booking_date_status", "UNKNOWN"),
                         "booking_date_label": ("최초 메일 수신일 기준 " if evidence.get("booking_date_status") == "FIRST_RECEIVED" else
                                                "예약일 " if evidence.get("booking_date_status") == "EXPLICIT_LABEL" else "") +
                                                str(evidence.get("reserved_on") or "")})
    bookings.sort(key=lambda b: (b["outbound_departure_on"] or "9999-99-99", b["booking_key"]))
    return {"source_generation": source_generation, "evidence_status": evidence_status,
            "bookings": bookings}


def _route_summary(legs: Sequence[Mapping[str, Any]]) -> str:
    outbound = [leg for leg in legs if "".join(str(leg.get("label") or "").split()).startswith("가는")]
    selected = outbound or sorted(legs, key=lambda leg: str(leg.get("departure_on") or "9999-99-99"))[:1]
    segments = [segment for leg in selected for segment in leg.get("segments", [])]
    if not segments:
        return ""
    first = segments[0].get("departure_airport") or "?"
    last = segments[-1].get("arrival_airport") or "?"
    return f"{first} → {last}"


def build_authority_maps(index: Mapping[str, Any], trips: Sequence[Mapping[str, Any]], *,
                         booking_trip_rules: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
                         confirmed_card_links: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                         expense_rows: Sequence[Mapping[str, Any]] = ()) -> tuple[dict, dict, str]:
    """Adapt only explicit booking rules and validated user-confirmed booking/card links."""
    trip_ids = {str(t.get("tab_id")) for t in trips if t.get("tab_id") and not t.get("deleted")}
    user_assignments: dict[str, dict[str, Any]] = {}
    authorities: dict[str, set[str]] = {}
    revisions: list[Any] = []
    rules = booking_trip_rules or {}
    normalized_rules = {_booking_key(str(provider).lower(), str(ref)): rule
                        for (provider, ref), rule in rules.items()}
    for ref, evidence in (index or {}).items():
        if not isinstance(evidence, Mapping):
            continue
        provider = str(evidence.get("provider") or "trip").lower()
        key = _booking_key(provider, str(ref))
        rule = normalized_rules.get(key)
        if rule:
            revisions.append((key, rule.get("revision"), rule.get("status"), rule.get("trip_tab_id")))
            if rule.get("status", "active") == "active":
                user_assignments[key] = {"trip_tab_id": str(rule.get("trip_tab_id") or "")}

    card_to_trips: dict[str, set[str]] = {}
    for row in expense_rows:
        if not isinstance(row, Mapping) or row.get("source_kind") != "카드":
            continue
        transaction_id = str(row.get("source_event_id") or "")
        tab_id = str(row.get("display_tab_id") or "")
        if transaction_id and tab_id in trip_ids:
            card_to_trips.setdefault(transaction_id, set()).add(tab_id)
    for ref, links in (confirmed_card_links or {}).items():
        evidence = (index or {}).get(ref)
        if not isinstance(evidence, Mapping) or not evidence.get("source_digests"):
            continue
        provider = str(evidence.get("provider") or "trip").lower()
        key = _booking_key(provider, str(ref))
        trip_ids_for_booking: set[str] = set()
        for link in links or ():
            if not isinstance(link, Mapping) or link.get("link_source") != "USER_CONFIRMED":
                continue
            transaction_id = str(link.get("transaction_id") or "")
            trip_ids_for_booking.update(card_to_trips.get(transaction_id, set()))
        if trip_ids_for_booking:
            authorities[key] = trip_ids_for_booking
    normalized = {key: sorted(value) for key, value in authorities.items()}
    digest_input = json.dumps({"rules": sorted(revisions), "authority": normalized,
                               "trips": sorted((str(t.get("tab_id")), t.get("revision"),
                                                t.get("starts_on"), t.get("ends_on")) for t in trips)},
                              sort_keys=True, default=str, separators=(",", ":"))
    revision = hashlib.sha256(digest_input.encode()).hexdigest()
    return user_assignments, normalized, revision


def read_booking_trip_rules() -> dict:
    """Read configured explicit booking trip rules through the isolated read-only store."""
    from . import ota_payment_review
    configured = ota_payment_review.review_db_path()
    if not configured:
        return {}
    path = Path(configured).expanduser().resolve(strict=False)
    if not path.is_file():
        raise ValueError("FLIGHT_AUTHORITY_UNAVAILABLE")
    conn = None
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if any(not name.startswith("ota_review_") for name in names):
            raise ValueError("FLIGHT_AUTHORITY_UNAVAILABLE")
        if "ota_review_booking_trips" not in names:
            raise ValueError("FLIGHT_AUTHORITY_UNAVAILABLE")
        rows = conn.execute(
            "SELECT provider,booking_ref,trip_tab_id,trip_code,basis,revision,status,user,changed_at "
            "FROM ota_review_booking_trips ORDER BY provider,booking_ref")
        return {(row[0], row[1]): dict(provider=row[0], booking_ref=row[1], trip_tab_id=row[2],
                trip_code=row[3], basis=row[4], revision=int(row[5]), status=row[6],
                user=row[7], changed_at=row[8]) for row in rows}
    except (OSError, ValueError, TypeError, sqlite3.Error):
        raise ValueError("FLIGHT_AUTHORITY_UNAVAILABLE") from None
    finally:
        if conn is not None:
            conn.close()


def confirmed_booking_card_links(board: Any, index: Mapping[str, Any]) -> dict:
    """Reuse the existing strict owner-confirmed OTA/card evidence adapter."""
    try:
        from .flight_passenger_page import _confirmed_card_index
        return _confirmed_card_index(board, index)
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def confirmed_card_trip_rows(board: Any, links: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, str]]:
    """Join verified card IDs to their ledger trip in bounded, read-only SQL batches."""
    conn = getattr(board, "conn", None)
    if conn is None:
        return []
    transaction_ids = sorted({str(link.get("transaction_id") or "")
        for group in (links or {}).values() for link in (group or ())
        if isinstance(link, Mapping) and link.get("link_source") == "USER_CONFIRMED"
        and link.get("transaction_id")})
    rows = []
    for offset in range(0, len(transaction_ids), 400):
        row_ids = ["card-" + value for value in transaction_ids[offset:offset + 400]]
        if not row_ids:
            continue
        marks = ",".join("?" for _ in row_ids)
        try:
            records = conn.execute(
                f"SELECT row_kind,display_tab_id,payload_json FROM board_rows WHERE row_id IN ({marks})",
                row_ids).fetchall()
        except sqlite3.Error:
            return []
        for row_kind, tab_id, payload_json in records:
            if row_kind != "expense" or not tab_id:
                continue
            try:
                payload = json.loads(payload_json)
            except (TypeError, ValueError):
                continue
            if payload.get("source_kind") == "카드" and payload.get("source_event_id"):
                rows.append({"source_kind": "카드", "source_event_id": str(payload["source_event_id"]),
                             "display_tab_id": str(tab_id)})
    return rows


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
    items = [{k: b.get(k) for k in ("provider", "booking_key", "booking_ref",
              "outbound_departure_on", "route_summary", "passenger_count",
              "assignment_status", "assignment_basis", "assignment_conflict",
              "inferred_trip_tab_id", "booking_status", "evidence_status")}
             for b in all_items[offset:offset + limit]]
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


def detail_for_trip(projection: Mapping[str, Any], trip_tab_id: str, booking_key: str) -> dict[str, Any]:
    item = next((b for b in projection.get("bookings", [])
                 if b.get("booking_key") == booking_key
                 and b.get("assigned_trip_tab_id") == trip_tab_id), None)
    if item is None:
        raise LookupError("BOOKING_NOT_FOUND")
    return {"trip_tab_id": trip_tab_id, "source_generation": projection.get("source_generation"),
            "evidence_status": projection.get("evidence_status", "UNAVAILABLE"),
            "item": {k: item.get(k) for k in ("provider", "booking_key", "booking_ref", "passengers",
                "legs", "outbound_departure_on", "assigned_trip_tab_id", "assignment_status",
                "assignment_basis", "assignment_conflict", "inferred_trip_tab_id", "booking_status",
                "evidence_status", "reserved_on", "booking_date_status", "booking_date_label")}}


def trip_read_allowed(*, is_owner: bool, trip: Mapping[str, Any] | None,
                      allowed_trip_ids: Sequence[str] = ()) -> bool:
    """Owner or explicitly authorized trip reader; archived/deleted trips are refused."""
    if not trip or trip.get("deleted") or trip.get("archived"):
        return False
    return bool(is_owner or str(trip.get("tab_id") or "") in set(map(str, allowed_trip_ids)))


def _board_trips(board: Any) -> list[dict[str, Any]]:
    if board is None:
        return []
    getter = getattr(board, "live_trips", None) or getattr(board, "list_trips", None)
    return list(getter(include_archived=True)) if callable(getter) else []


def handle_get(handler: Any, *, board: Any, trip_tab_id: str, query: Mapping[str, Sequence[str]],
               is_owner: bool, allowed_trip_ids: Sequence[str] = (), trip: Mapping[str, Any] | None = None,
               trips: Sequence[Mapping[str, Any]] | None = None,
               index: Mapping[str, Any] | None = None, source_generation: str = "",
               evidence_status: str = "UNAVAILABLE", user_assignments: Mapping[str, Mapping[str, Any]] | None = None,
               authority_trip_ids: Mapping[str, Sequence[str]] | None = None,
               booking_key: str = "", expected_generation: str = "") -> dict[str, Any]:
    """Build GET response from caller-held worker snapshot; performs no collection/reconciliation."""
    if trip is None and board is not None:
        trip = next((t for t in _board_trips(board)
                     if str(t.get("tab_id")) == str(trip_tab_id)), None)
    if not trip_read_allowed(is_owner=is_owner, trip=trip, allowed_trip_ids=allowed_trip_ids):
        return {"code": "TRIP_NOT_FOUND"}
    if index is None:
        return {"code": "FLIGHT_SOURCE_UNAVAILABLE"}
    try:
        try:
            limit = int((query.get("limit") or [str(DEFAULT_LIMIT)])[0])
        except (TypeError, ValueError):
            raise ValueError("INVALID_LIMIT") from None
        cursor = str((query.get("cursor") or [""])[0])
        status = str((query.get("status") or ["active"])[0])
        trip_list = list(trips if trips is not None else (
            _board_trips(board)))
        projection = project_trip_bookings(index, trip_list, source_generation=source_generation,
            user_assignments=user_assignments, authority_trip_ids=authority_trip_ids,
            evidence_status=evidence_status)
        if expected_generation and expected_generation != projection["source_generation"]:
            return {"code": "SOURCE_CHANGED"}
        if booking_key:
            return detail_for_trip(projection, trip_tab_id, booking_key)
        return page_for_trip(projection, trip_tab_id, limit=limit, cursor=cursor, status=status)
    except LookupError as exc:
        return {"code": "BOOKING_NOT_FOUND" if str(exc) == "BOOKING_NOT_FOUND" else "SOURCE_CHANGED"}
    except (ValueError, TypeError, IndexError) as exc:
        code = str(exc)
        return {"code": code if code.startswith("INVALID_") else "INVALID_QUERY"}


def owns_route(path: str) -> bool:
    import re
    return bool(re.fullmatch(r"/api/trips/[^/]+/flight-bookings", str(path)))


def dispatch(handler: Any, parsed: Any, *, board: Any, is_owner: bool,
             allowed_trip_ids: Sequence[str] = (), raw: bytes | None = None,
             query: Mapping[str, Sequence[str]] | None = None,
             snapshot: Mapping[str, Any] | Any | None = None,
             expense_rows: Sequence[Mapping[str, Any]] | Any = (),
             booking_trip_rules: Mapping[tuple[str, str], Mapping[str, Any]] | None = None) -> bool:
    """GET-only API route helper; caller passes an already-held worker snapshot."""
    from urllib.parse import parse_qs
    from urllib.parse import unquote
    import re
    match = re.fullmatch(r"/api/trips/([^/]+)/flight-bookings", str(getattr(parsed, "path", "")))
    if not match:
        return False
    if raw is not None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    try:
        trip_id = unquote(match.group(1), errors="strict")
    except UnicodeDecodeError:
        handler._send_json({"code": "INVALID_TRIP"}, 400)
        return True
    trips = _board_trips(board)
    trip = next((t for t in trips if str(t.get("tab_id")) == trip_id), None)
    if not trip_read_allowed(is_owner=is_owner, trip=trip, allowed_trip_ids=allowed_trip_ids):
        handler._send_json({"code": "TRIP_NOT_FOUND"}, 404)
        return True
    snap = (snapshot() if callable(snapshot) else snapshot) or {}
    data = snap.get("data") or {}
    index = data.get("passengers") if snap.get("fresh") else None
    if index is not None:
        try:
            rules = read_booking_trip_rules() if booking_trip_rules is None else booking_trip_rules
        except ValueError:
            handler._send_json({"code": "FLIGHT_AUTHORITY_UNAVAILABLE"}, 503)
            return True
        links = confirmed_booking_card_links(board, index)
        rows = (expense_rows() if callable(expense_rows) else expense_rows
                if expense_rows else confirmed_card_trip_rows(board, links))
        user_assignments, authorities, authority_revision = build_authority_maps(
            index, trips, booking_trip_rules=rules, confirmed_card_links=links,
            expense_rows=rows)
    else:
        user_assignments, authorities, authority_revision = {}, {}, ""
    generation = hashlib.sha256((str(snap.get("generation") or "") + authority_revision).encode()).hexdigest()
    requested_key = (query or parse_qs(getattr(parsed, "query", ""))).get("booking_key", [""])[0]
    decoded_key = str(requested_key)
    expected_generation = str((query or parse_qs(getattr(parsed, "query", ""))).get("generation", [""])[0])
    result = handle_get(handler, board=board, trip_tab_id=trip_id,
        query=query or parse_qs(getattr(parsed, "query", "")), is_owner=is_owner,
        allowed_trip_ids=allowed_trip_ids, trip=trip, trips=trips,
        index=index, source_generation=generation,
        evidence_status="FRESH" if snap.get("fresh") else "UNAVAILABLE",
        user_assignments=user_assignments, authority_trip_ids=authorities,
        booking_key=decoded_key, expected_generation=expected_generation)
    code = result.get("code")
    handler._send_json(result, 409 if code == "SOURCE_CHANGED" else 404 if code in ("TRIP_NOT_FOUND", "BOOKING_NOT_FOUND") else 503 if code == "FLIGHT_SOURCE_UNAVAILABLE" else 400 if code and code.startswith("INVALID_") else 200)
    return True
