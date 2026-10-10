"""Guide-airfare attribution for the OTA snapshot worker.

Runs on the snapshot worker only, never on a request. Passenger names stay in memory while one
evaluation runs; the returned results carry no names, only the verdict, the trip and an evidence digest.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app import flight_evidence, guide_airfare, guide_identity

REGISTRY_ENV = "WEBLEDGER_GUIDE_IDENTITIES"
REGISTRY_FILE = "guide-identities.json"
AIRPORTS_ENV = "WEBLEDGER_GUIDE_AIRPORTS"

PUBLIC_KEYS = ("status", "code", "trip_id", "trip_name", "candidate_trip_ids", "passenger_count",
               "guide_passenger_count", "mixed", "guide_match", "guide_portion_krw",
               "evidence_digest", "engine_version")
_TRIP_DIGEST_KEYS = ("tab_id", "display_key", "destination", "starts_on", "ends_on", "prepared_by_name",
                     "assignee_source", "archived", "deleted", "revision", "source_sha256",
                     "authority_status", "event_year", "valid")


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def registry_path(board) -> Path:
    configured = os.environ.get(REGISTRY_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path(board.path).parent / REGISTRY_FILE


def airport_table() -> dict:
    configured = os.environ.get(AIRPORTS_ENV, "").strip()
    return guide_airfare.load_airport_table(configured or None)


def _load_registry(board):
    """(registry, error code). A broken registry disables aliases, so English names stay unconfirmed."""
    try:
        return guide_identity.load_alias_registry(registry_path(board)), ""
    except (OSError, ValueError) as exc:
        return {}, type(exc).__name__


def trip_inputs(board) -> list[dict]:
    """Every live trip with whether its schedule is currently validated as authoritative."""
    lister = getattr(board, "list_trips", None)
    if not callable(lister):
        return []
    from . import card_flow
    flow = card_flow.CardFlow(board)
    trips = []
    for trip in lister():
        trips.append(dict(trip, valid=bool(flow.trip_valid(trip["tab_id"]))))
    return trips


def _owner_assignee(board) -> str:
    reader = getattr(board, "owner_profile", None)
    if not callable(reader):
        return ""
    return str((reader() or {}).get("assignee_name") or "")


def input_digest(board) -> str:
    """Everything the attribution reads besides mail content (mail content is in the source stamps)."""
    registry, registry_error = _load_registry(board) if hasattr(board, "path") else ({}, "")
    try:
        table_digest = guide_airfare.airport_table_digest(airport_table())
    except (OSError, ValueError) as exc:
        table_digest = "unreadable:" + type(exc).__name__
    return _digest({
        "parser": flight_evidence.PARSER_VERSION, "identity": guide_identity.IDENTITY_VERSION,
        "engine": guide_airfare.ENGINE_VERSION, "airports": table_digest,
        "registry": registry, "registry_error": registry_error,
        "owner": _owner_assignee(board),
        "trips": [{key: trip.get(key) for key in _TRIP_DIGEST_KEYS} for trip in trip_inputs(board)],
    })


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
    registry, _ = _load_registry(board)
    trips = trip_inputs(board)
    identities = guide_identity.guide_identities(trips, _owner_assignee(board), registry)
    trusted = set(guide_identity.TRUSTED_ASSIGNEE_SOURCES)
    assignee_by_key = {identity["normalized"]: identity["assignee_name"] for identity in identities}
    candidates = []
    for trip in trips:
        key = "".join(guide_identity.normalize_name_part(trip.get("prepared_by_name")).split())
        if trip["valid"] and trip.get("assignee_source") in trusted and key in assignee_by_key:
            candidates.append({"trip_id": trip["tab_id"], "display_key": trip["display_key"],
                               "destination": trip["destination"], "starts_on": trip["starts_on"],
                               "ends_on": trip["ends_on"], "assignee_name": assignee_by_key[key]})
    evidence_by_booking = flight_evidence.collect_flight_evidence(mail_directories)
    airports = airport_table()
    cards = {str(row.get("transaction_id")): row for row in transactions}
    verdicts = {}
    for result, event in wanted:
        card = cards.get(str(result.get("transaction_id"))) or {}
        if event.get("event_type") != "charge" or card.get("transaction_direction") != "purchase":
            verdict = _not_applicable("NOT_APPLICABLE_REFUND_EXISTING_PATH")
        else:
            attribution = guide_airfare.attribute(
                evidence=evidence_by_booking.get((str(event.get("provider")), str(event.get("booking_ref")))),
                identities=identities, trips=candidates, airports=airports,
                item="항공료", card_amount_krw=card.get("amount_krw"))
            verdict = {key: attribution.get(key) for key in PUBLIC_KEYS}
        verdict["booking_ref"] = str(event.get("booking_ref") or "")
        verdicts[str(result.get("ota_event_id"))] = verdict
    return verdicts


def _not_applicable(code):
    return {"status": "NOT_APPLICABLE", "code": code, "trip_id": "", "trip_name": "",
            "candidate_trip_ids": [], "passenger_count": 0, "guide_passenger_count": 0, "mixed": False,
            "guide_match": "unknown", "guide_portion_krw": None, "evidence_digest": "",
            "engine_version": guide_airfare.ENGINE_VERSION}


def failed(error) -> dict:
    """Fail closed: an evaluation error never grants an attribution."""
    return dict(_not_applicable("HOLD_GUIDE_AIRFARE_ERROR"), status="HOLD", error=type(error).__name__)
