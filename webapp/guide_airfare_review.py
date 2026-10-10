"""Guide-airfare attribution for the OTA snapshot worker.

The reservation system is the authority for who the guides are and which tours they lead. COST reads it
read-only on the snapshot worker, bridges each reservation tour to an authoritative COST trip by exact
key and dates, and attributes the airfare. Nothing here runs a network call on a request thread.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from app import flight_evidence, guide_airfare, guide_identity, reservation_authority

AIRPORTS_ENV = "WEBLEDGER_GUIDE_AIRPORTS"
TOKEN_FILE_NAME = "reservation-internal-token.txt"
GRACE_SECONDS = 600           # 화면 연속성용: 마지막 정상본을 보여 줄 수 있는 시간
MIN_INTERVAL_SECONDS = 45
WRITE_FRESH_SECONDS = 90      # 장부 기록 근거로 쓸 수 있는 authority 확인 나이. 위 유예와 별개다.

PUBLIC_KEYS = ("status", "code", "trip_id", "trip_name", "candidate_trip_ids", "passenger_count",
               "guide_passenger_count", "mixed", "guide_match", "guide_portion_krw",
               "evidence_digest", "engine_version")
_TRIP_DIGEST_KEYS = ("tab_id", "display_key", "destination", "starts_on", "ends_on", "prepared_by_name",
                     "assignee_source", "archived", "deleted", "revision", "source_sha256",
                     "authority_status", "event_year", "valid")
CONFLICT = "HOLD_GUIDE_ASSIGNMENT_CONFLICT"
MISMATCH = "HOLD_RESERVATION_TRIP_AUTHORITY_MISMATCH"
UNAVAILABLE = "HOLD_GUIDE_AUTHORITY_UNAVAILABLE"


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def airport_table() -> dict:
    configured = os.environ.get(AIRPORTS_ENV, "").strip()
    return guide_airfare.load_airport_table(configured or None)


def _token_file(board) -> Path:
    return Path(board.path).resolve().parent.parent / "secrets" / TOKEN_FILE_NAME


# reservation authority (worker thread only)

def refresh_authority(board, *, fetcher=None, clock=time.monotonic):
    """Read guides and tours from reservation and cache them on the board. Never raises.

    State: fresh (this fetch succeeded), degraded (fetch failed, last good copy kept for display for
    GRACE_SECONDS), unavailable (nothing usable). Only fresh authority may justify a ledger write."""
    previous = getattr(board, "_reservation_authority", None)
    now = clock()
    if previous and now - previous["checked_at"] < MIN_INTERVAL_SECONDS:
        return previous
    code = ""
    authority = None
    try:
        if fetcher is not None:
            authority = fetcher()
        else:
            token = reservation_authority.configured_token(_token_file(board) if hasattr(board, "path") else None)
            authority = reservation_authority.fetch_authority(token=token)
    except reservation_authority.AuthorityUnavailable as exc:
        code = exc.code
    except Exception:
        code = "unavailable"
    if authority is not None:
        state = {"authority": authority, "error": "", "fresh": True, "degraded": False, "checked_at": now,
                 "last_success_at": now, "digest": authority["digest"]}
    elif (previous and previous.get("authority") is not None and previous.get("last_success_at") is not None
          and now - previous["last_success_at"] <= GRACE_SECONDS):
        state = dict(previous, fresh=False, degraded=True, error=code or "unavailable", checked_at=now)
    else:
        state = {"authority": None, "error": code or "unavailable", "fresh": False, "degraded": False,
                 "checked_at": now, "last_success_at": None,
                 "digest": "unavailable:" + (code or "unavailable")}
    board._reservation_authority = state
    return state


def authority_state(board) -> dict:
    return getattr(board, "_reservation_authority", None) or {
        "authority": None, "error": "not_loaded", "fresh": False, "degraded": False, "last_success_at": None,
        "digest": "authority:not_loaded"}


def state_label(state) -> str:
    if state.get("authority") is None:
        return "unavailable"
    return "degraded" if state.get("degraded") else "fresh"


def write_authorization(board, *, clock=time.monotonic):
    """(allowed, code). Pure cache read, never a network call. Display grace is not write authority."""
    state = authority_state(board)
    if state.get("authority") is None:
        return False, "GUIDE_AUTHORITY_UNAVAILABLE"
    if state.get("degraded") or not state.get("fresh"):
        return False, "GUIDE_AUTHORITY_DEGRADED"
    last = state.get("last_success_at")
    if last is None or clock() - last > WRITE_FRESH_SECONDS:
        return False, "GUIDE_AUTHORITY_STALE"
    return True, ""


def authority_summary(board) -> dict:
    """Non-identifying metadata for the snapshot: state, content digest prefix, last error code."""
    state = authority_state(board)
    return {"state": state_label(state), "digest": str(state.get("digest") or "")[:12],
            "error": str(state.get("error") or "")}


# COST trips

def trip_inputs(board) -> list[dict]:
    """Every live trip with whether its schedule is currently validated as authoritative."""
    lister = getattr(board, "list_trips", None)
    if not callable(lister):
        return []
    from . import card_flow
    flow = card_flow.CardFlow(board)
    return [dict(trip, valid=bool(flow.trip_valid(trip["tab_id"]))) for trip in lister()]


def _registrations(board) -> dict:
    """trip id -> reserve cafe fldid for trips registered from the reservation catalog."""
    conn = getattr(board, "conn", None)
    if conn is None:
        return {}
    try:
        rows = conn.execute("SELECT trip_id, source_key FROM reserve_trip_registrations").fetchall()
    except Exception:
        return {}
    registered = {}
    for trip_id, source_key in rows:
        parts = str(source_key).split(":")
        if len(parts) == 3 and parts[0] == "reserve":
            registered[str(trip_id)] = parts[1]
    return registered


def input_digest(board) -> str:
    """Everything the attribution reads besides mail content (mail content is in the source stamps).

    Uses the cached reservation authority; it never fetches."""
    try:
        table_digest = guide_airfare.airport_table_digest(airport_table())
    except (OSError, ValueError) as exc:
        table_digest = "unreadable:" + type(exc).__name__
    return _digest({
        "parser": flight_evidence.PARSER_VERSION, "identity": guide_identity.IDENTITY_VERSION,
        "engine": guide_airfare.ENGINE_VERSION, "airports": table_digest,
        "authority": authority_state(board)["digest"],
        "authority_state": state_label(authority_state(board)),
        "registrations": _registrations(board),
        "trips": [{key: trip.get(key) for key in _TRIP_DIGEST_KEYS} for trip in trip_inputs(board)],
    })


# reservation tour -> COST trip bridge

def _iso(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and value else None
    except ValueError:
        return None


def _name(value) -> str:
    return "".join(guide_identity.normalize_name_part(value).split())


def bridge(authority, trips, registrations):
    """Per guide id: bridged COST trips and problem windows. Exact keys only: the reserve fldid
    registration or the exact trip code, and in every case exactly the same start and end dates."""
    guides = {guide["id"]: guide for guide in authority["guides"]}
    valid = [trip for trip in trips if trip.get("valid") and _iso(trip.get("starts_on")) and _iso(trip.get("ends_on"))]
    usable, problems = {}, {}
    claimed = {}
    for tour in authority["tours"]:
        guide_id = tour.get("leader_guide_id")
        if guide_id is None or guide_id not in guides:
            continue
        start, end = _iso(tour.get("depart_date")), _iso(tour.get("return_date"))
        if start is None or end is None:
            continue
        window = (start, end)
        def key_hit(trip):
            registered = registrations.get(trip["tab_id"])
            by_fldid = registered is not None and registered == tour["fldid"]
            by_code = bool(tour.get("code")) and tour["code"] == trip["display_key"]
            return by_fldid or by_code

        def key_consistent(trip):
            registered = registrations.get(trip["tab_id"])
            if registered is not None and registered != tour["fldid"]:
                return False
            return not tour.get("code") or tour["code"] == trip["display_key"]

        keyed = [trip for trip in valid if key_hit(trip)]
        if (len(keyed) == 1 and key_consistent(keyed[0])
                and keyed[0]["starts_on"] == tour["depart_date"] and keyed[0]["ends_on"] == tour["return_date"]):
            claimed.setdefault(keyed[0]["tab_id"], []).append((guide_id, tour))
            continue
        problems.setdefault(guide_id, []).append((window, MISMATCH))
    for trip_id, owners in claimed.items():
        trip = next(item for item in valid if item["tab_id"] == trip_id)
        for guide_id, tour in owners:
            window = (_iso(tour["depart_date"]), _iso(tour["return_date"]))
            if len(owners) > 1:
                problems.setdefault(guide_id, []).append((window, MISMATCH))
                continue
            guide = guides[guide_id]
            prepared = _name(trip.get("prepared_by_name"))
            if (trip.get("assignee_source") == "manual" and prepared
                    and prepared not in {_name(guide.get("real_name")), _name(guide.get("nickname"))}):
                problems.setdefault(guide_id, []).append((window, CONFLICT))
                continue
            usable.setdefault(guide_id, []).append(trip)
    return usable, problems


def bridge_coverage(authority, trips, registrations) -> dict:
    """Per authoritative COST trip: how (or why not) it bridges to a reservation tour. Measurement only.

    Categories: fldid, code, both (bridged and date-exact), date_mismatch, conflict (two keys disagree or
    several tours claim it), unbridgeable (no stable key)."""
    tours = authority["tours"]
    by_fldid = {tour["fldid"]: tour for tour in tours}
    result = {"fldid": [], "code": [], "both": [], "date_mismatch": [], "conflict": [], "unbridgeable": []}
    for trip in trips:
        if not trip.get("valid"):
            continue
        tab_id = trip["tab_id"]
        fldid = registrations.get(tab_id)
        by_key = by_fldid.get(fldid) if fldid else None
        coded = [tour for tour in tours if tour.get("code") and tour["code"] == trip["display_key"]]
        if by_key is None and not coded:
            result["unbridgeable"].append(tab_id)
            continue
        distinct = {tour["fldid"] for tour in coded} | ({by_key["fldid"]} if by_key else set())
        if len(distinct) > 1:
            result["conflict"].append(tab_id)
            continue
        tour = by_key or coded[0]
        if tour.get("code") and tour["code"] != trip["display_key"]:
            result["conflict"].append(tab_id)
        elif tour.get("depart_date") != trip.get("starts_on") or tour.get("return_date") != trip.get("ends_on"):
            result["date_mismatch"].append(tab_id)
        elif by_key is not None and coded:
            result["both"].append(tab_id)
        else:
            result["fldid" if by_key is not None else "code"].append(tab_id)
    return result


def _window_problem(problems, legs, gap):
    dates = [_iso(leg.get("departure_on")) for leg in legs]
    dates = [item for item in dates if item]
    if not dates:
        return ""
    low, high = min(dates) - timedelta(days=gap), max(dates) + timedelta(days=gap)
    hits = [code for (start, end), code in problems if start - timedelta(days=gap) <= high and end + timedelta(days=gap) >= low]
    if CONFLICT in hits:
        return CONFLICT
    return MISMATCH if hits else ""


def _is_airfare(item) -> bool:
    return str(item or "").strip().casefold() in guide_airfare.AIRFARE_ITEMS


def evaluate(board, mail_directories, events, transactions, results) -> dict:
    """event id -> public attribution verdict for every matched airfare event."""
    event_by_id = {str(event.get("ota_event_id")): event for event in events}
    wanted = [(result, event_by_id[str(result.get("ota_event_id"))]) for result in results
              if str(result.get("ota_event_id")) in event_by_id
              and _is_airfare(event_by_id[str(result.get("ota_event_id"))].get("item"))
              and result.get("status") in ("MATCHED_AUTO", "MATCHED_USER") and result.get("transaction_id")]
    if not wanted:
        return {}
    state = authority_state(board)
    authority = state.get("authority")
    cards = {str(row.get("transaction_id")): row for row in transactions}
    if authority is None:
        return {str(result.get("ota_event_id")): _unavailable(event, state) for result, event in wanted}

    identities = guide_identity.reservation_identities(authority["guides"])
    usable, problems = bridge(authority, trip_inputs(board), _registrations(board))
    candidates = [{"trip_id": trip["tab_id"], "display_key": trip["display_key"],
                   "destination": trip["destination"], "starts_on": trip["starts_on"],
                   "ends_on": trip["ends_on"], "assignee_name": f"guide:{guide_id}"}
                  for guide_id, trips in usable.items() for trip in trips]
    evidence_by_booking = flight_evidence.collect_flight_evidence(mail_directories)
    airports = airport_table()
    gap = airports["max_gap_days"]
    verdicts = {}
    for result, event in wanted:
        card = cards.get(str(result.get("transaction_id"))) or {}
        evidence = evidence_by_booking.get((str(event.get("provider")), str(event.get("booking_ref"))))
        if event.get("event_type") != "charge" or card.get("transaction_direction") != "purchase":
            verdict = _verdict("NOT_APPLICABLE", "NOT_APPLICABLE_REFUND_EXISTING_PATH")
        else:
            attribution = guide_airfare.attribute(
                evidence=evidence, identities=identities, trips=candidates, airports=airports,
                item="항공료", card_amount_krw=card.get("amount_krw"))
            verdict = {key: attribution.get(key) for key in PUBLIC_KEYS}
            matched = sorted({guide_identity.match_passenger(
                {"surname": person.get("surname", ""), "given_name": person.get("given_name", "")},
                identities)["guide"] for person in (evidence or {}).get("passengers", [])} - {""})
            guide_ids = [int(name.split(":")[1]) for name in matched]
            if len(guide_ids) == 1:
                verdict["guide_id"] = guide_ids[0]
            hit = ""
            if guide_ids and evidence:
                hit = _window_problem([item for gid in guide_ids for item in problems.get(gid, [])],
                                      evidence.get("legs") or [], gap)
            if hit and verdict["status"] in ("ATTRIBUTED", "HOLD") and verdict["code"] not in (
                    "HOLD_MIXED_PASSENGERS", "HOLD_GUIDE_PORTION_ONLY"):
                verdict.update(status="HOLD", code=hit, trip_id="", trip_name="")
        verdict["booking_ref"] = str(event.get("booking_ref") or "")
        verdict["authority_digest"] = str(state.get("digest") or "")[:12]
        verdict["authority_state"] = state_label(state)
        verdicts[str(result.get("ota_event_id"))] = verdict
    return verdicts


def _verdict(status, code):
    return {"status": status, "code": code, "trip_id": "", "trip_name": "", "candidate_trip_ids": [],
            "passenger_count": 0, "guide_passenger_count": 0, "mixed": False, "guide_match": "unknown",
            "guide_portion_krw": None, "evidence_digest": "", "engine_version": guide_airfare.ENGINE_VERSION}


def _unavailable(event, state) -> dict:
    verdict = _verdict("HOLD", UNAVAILABLE)
    verdict.update(booking_ref=str(event.get("booking_ref") or ""),
                   authority_digest=str(state.get("digest") or "")[:12], reason=str(state.get("error") or ""))
    return verdict


def failed(error) -> dict:
    """Fail closed: an evaluation error never grants an attribution."""
    return dict(_verdict("HOLD", "HOLD_GUIDE_AIRFARE_ERROR"), error=type(error).__name__)
