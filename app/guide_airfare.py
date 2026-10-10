"""Attribute a guide's airfare to one authoritative trip, or hold."""

import hashlib
import json
from datetime import date
from pathlib import Path

ENGINE_VERSION = "guide-airfare-v1"
AIRFARE_ITEMS = ("항공료", "항공", "항공권", "flight", "airfare")

_DEFAULT_TABLE = Path(__file__).resolve().parent.parent / "config" / "guide-airfare-airports.json"


def load_airport_table(path=None):
    table_path = Path(path) if path is not None else _DEFAULT_TABLE
    with table_path.open(encoding="utf-8") as handle:
        table = json.load(handle)
    _check_airport_table(table)
    return table


def _check_airport_table(table):
    if not isinstance(table, dict):
        raise ValueError("airport table must be an object")
    gap = table.get("max_gap_days")
    if not isinstance(gap, int) or isinstance(gap, bool) or gap < 0:
        raise ValueError("max_gap_days must be a non-negative int")
    korea = table.get("korea_airports")
    if not isinstance(korea, list) or not all(isinstance(code, str) for code in korea):
        raise ValueError("korea_airports must be a list of IATA codes")
    airports = table.get("airports")
    if not isinstance(airports, dict):
        raise ValueError("airports must be an object")
    for code, entry in airports.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("country"), str):
            raise ValueError(f"airport {code} lacks a country")
        regions = entry.get("regions")
        if not isinstance(regions, list) or not all(isinstance(name, str) for name in regions):
            raise ValueError(f"airport {code} has malformed regions")


def airport_table_digest(table):
    canonical = json.dumps(table, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def attribute(*, evidence, identities, trips, airports, item, card_amount_krw=None):
    digest = str((evidence or {}).get("digest") or "")
    if not _is_airfare(item):
        return _result("NOT_APPLICABLE", "NOT_APPLICABLE_NOT_AIRFARE", digest)

    passengers = (evidence or {}).get("passengers") or []
    if not passengers:
        return _result("HOLD", "HOLD_PASSENGER_EVIDENCE_MISSING", digest)

    from app import guide_identity

    matches = [
        guide_identity.match_passenger(
            {"surname": p.get("surname", ""), "given_name": p.get("given_name", "")}, identities)
        for p in passengers
    ]
    statuses = [m.get("status") for m in matches]
    guide_count = statuses.count("guide")
    summary = {
        "passenger_count": len(passengers),
        "guide_passenger_count": guide_count,
        "mixed": 0 < guide_count < len(passengers),
        "guide_match": "guide" if guide_count else ("unknown" if "unknown" in statuses else "not_guide"),
    }
    if guide_count == 0:
        if "unknown" in statuses:
            return _result("HOLD", "HOLD_GUIDE_IDENTITY_UNCONFIRMED", digest, summary)
        return _result("NOT_APPLICABLE", "NOT_APPLICABLE_NO_GUIDE_PASSENGER", digest, summary)

    legs = evidence.get("legs") or []
    if (evidence.get("conflict") or not legs or not evidence.get("legs_complete")
            or any(_parse_date(leg.get("departure_on")) is None or not leg.get("segments")
                   for leg in legs)):
        return _result("HOLD", "HOLD_FLIGHT_ITINERARY_INCOMPLETE", digest, summary)

    guide_keys = {_normalize(m.get("guide")) for m in matches if m.get("status") == "guide"}
    guide_keys.discard("")
    rows = [_trip_row(t) for t in trips if _valid_trip(t) and _normalize(t.get("assignee_name")) in guide_keys]
    if not rows:
        return _result("HOLD", "HOLD_GUIDE_AIRFARE_NO_TRIP", digest, summary)

    korea = set(airports["korea_airports"])
    gap = airports["max_gap_days"]
    table = airports["airports"]
    relations = []
    leg_survivors = []
    for leg in legs:
        survivors, code = _leg_survivors(leg, rows, korea, gap, table)
        if code is None and len({trip_id for trip_id, _ in survivors}) > 1:
            code = "HOLD_GUIDE_AIRFARE_AMBIGUOUS"
        relations.extend({"leg": leg.get("label"), "kind": kind, "trip_id": trip_id}
                         for trip_id, kind in sorted(survivors))
        if code is not None:
            return _result("HOLD", code, digest, summary, relations=relations)
        leg_survivors.append(survivors)

    trip_ids = {trip_id for survivors in leg_survivors for trip_id, _ in survivors}
    if len(trip_ids) > 1:
        return _result("HOLD", "HOLD_GUIDE_AIRFARE_AMBIGUOUS", digest, summary, relations=relations)
    trip_id = trip_ids.pop()
    trip = next(row for row in rows if row["trip_id"] == trip_id)

    kinds = {kind for survivors in leg_survivors for _, kind in survivors}
    if len(kinds) == 1:
        code = f"guide_airfare_{kinds.pop()}"
    else:
        code = "guide_airfare_round_trip"

    if summary["mixed"]:
        fares = [p.get("fare_krw") for p in passengers]
        if (all(_is_int(fare) and fare > 0 for fare in fares) and _is_int(card_amount_krw)
                and sum(fares) == card_amount_krw):
            portion = sum(p["fare_krw"] for p, m in zip(passengers, matches) if m.get("status") == "guide")
            return _result("HOLD", "HOLD_GUIDE_PORTION_ONLY", digest, {**summary, "guide_portion_krw": portion},
                           trip=trip, relations=relations)
        return _result("HOLD", "HOLD_MIXED_PASSENGERS", digest, summary, relations=relations)

    return _result("ATTRIBUTED", code, digest, summary, trip=trip, relations=relations)


def _leg_survivors(leg, rows, korea, gap, table):
    origin = _airport_code(leg["segments"][0].get("departure_airport"))
    dest = _airport_code(leg["segments"][-1].get("arrival_airport"))
    if not origin or not dest or (origin in korea and dest in korea):
        return set(), "HOLD_FLIGHT_ROUTE_UNVERIFIED"
    if origin in korea:
        direction = "outbound"
    elif dest in korea:
        direction = "inbound"
    else:
        direction = "positioning"

    origin_regions = _regions(table, origin) if direction != "outbound" else set()
    dest_regions = _regions(table, dest) if direction != "inbound" else set()
    if (direction != "outbound" and not origin_regions) or (direction != "inbound" and not dest_regions):
        return set(), "HOLD_FLIGHT_ROUTE_UNVERIFIED"

    d = _parse_date(leg["departure_on"])
    survivors = set()
    for row in rows:
        if direction != "inbound" and row["dest"] in dest_regions and d <= row["end"]:
            if d >= row["start"]:
                kind = "mid_trip_join"
            elif (row["start"] - d).days <= gap:
                kind = "inter_trip" if direction == "positioning" else "pre_departure"
            else:
                kind = None
            if kind and direction == "outbound" and _abroad_on_other_trip(d, row, rows):
                kind = None
            if kind:
                survivors.add((row["trip_id"], kind))

        if direction != "outbound" and row["dest"] in origin_regions and d >= row["start"]:
            if d < row["end"]:
                kind = "early_leave"
            elif (d - row["end"]).days <= gap:
                kind = "inter_trip" if direction == "positioning" else "post_trip_return"
            else:
                kind = None
            if kind and _began_other_between(d, row, rows):
                kind = None
            if kind:
                survivors.add((row["trip_id"], kind))

    if not survivors:
        return set(), "HOLD_FLIGHT_ROUTE_UNRELATED"
    return survivors, None


def _abroad_on_other_trip(d, row, rows):
    return any(other["trip_id"] != row["trip_id"] and other["start"] < d <= other["end"] for other in rows)


def _began_other_between(d, row, rows):
    return any(other["trip_id"] != row["trip_id"] and row["start"] < other["start"] < d for other in rows)


def _result(status, code, digest, fields=None, trip=None, relations=()):
    relations = list(relations)
    result = {
        "status": status,
        "code": code,
        "trip_id": "",
        "trip_name": "",
        "candidate_trip_ids": sorted({rel["trip_id"] for rel in relations}),
        "relations": relations,
        "passenger_count": 0,
        "guide_passenger_count": 0,
        "mixed": False,
        "guide_match": "unknown",
        "guide_portion_krw": None,
        "evidence_digest": digest,
        "engine_version": ENGINE_VERSION,
    }
    result.update(fields or {})
    if trip is not None:
        result["trip_id"] = trip["trip_id"]
        result["trip_name"] = trip["display_key"]
    return result


def _trip_row(trip):
    return {
        "trip_id": trip["trip_id"],
        "display_key": trip.get("display_key", ""),
        "dest": str(trip.get("destination") or "").strip(),
        "start": _parse_date(trip["starts_on"]),
        "end": _parse_date(trip["ends_on"]),
    }


def _valid_trip(trip):
    starts = _parse_date(trip.get("starts_on"))
    ends = _parse_date(trip.get("ends_on"))
    return starts is not None and ends is not None and ends >= starts


def _regions(table, code):
    return set((table.get(code) or {}).get("regions") or [])


def _airport_code(value):
    return str(value or "").strip().upper()


def _normalize(name):
    return "".join(str(name or "").split()).upper()


def _parse_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_airfare(item):
    text = str(item or "").strip().casefold()
    return text in {name.casefold() for name in AIRFARE_ITEMS}
