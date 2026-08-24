"""Retain two legacy-bound Kamenoi rows as booking candidates only."""
from __future__ import annotations

import hashlib
import warnings
import json
from datetime import date, timedelta
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, build_annex
from ledger.domain.staged_inputs import is_strict_static_pins


ARTIFACT_TYPE = "all-period-verified-kamenoi-lodging-admission-v1"
RULE_VERSION = "user-booking-page-exact-kamenoi-lodging-v1"
OTA_LINKS_SHA256 = "2a3bc075b0d7596d5d99bef9dd7b9fda61a88428cf833e48042f55fbe6801b27"
TRIPS_SHA256 = "0a9fdd6b4835d2cf889391b00e2567977858b77376d3d3071023e81609e51969"
SELECTED_SET_SHA256 = "060271be84bbaa74b1ecbe84b35c1e08a9554318a4bdbcdc358c81150e849fee"
TRIP_TARGET = "0704_아키타"
EXPECTED = {
    "KBD-0389": ("1400827051075866", 1307772, 3, 2),
    "KBD-0390": ("1400827051083658", 887640, None, 2),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_verified_kamenoi_lodging_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("verified_kamenoi_noncanonical_ledger")
    links_raw = (ledger_dir / "data/ota_event_links_verified.json").read_bytes()
    trips_raw = (ledger_dir / "data/trips.json").read_bytes()
    if _sha(links_raw) != OTA_LINKS_SHA256 or _sha(trips_raw) != TRIPS_SHA256:
        if is_strict_static_pins():
            raise ValueError("verified_kamenoi_input_drift")
        warnings.warn("verified_kamenoi_input_drift (non-strict)", stacklevel=2)
    links = json.loads(links_raw)
    trips = {row["tab"]: row for row in json.loads(trips_raw)}
    trip = trips.get(TRIP_TARGET)
    if not isinstance(trip, dict) or set(trip) != {"tab", "mm", "dd", "region", "window"}:
        raise ValueError("verified_kamenoi_trip_contract_drift")
    start = date(2026, int(trip["mm"]), int(trip["dd"]))
    end = start + timedelta(days=int(trip["window"]) - 1)
    if not (start <= date(2026, 7, 5) <= date(2026, 7, 7) <= end):
        raise ValueError("verified_kamenoi_stay_outside_trip")
    annex = build_annex(ledger_dir=ledger_dir)
    envelopes = {row.get("historical_uid"): row
                 for row in annex["package"]["envelopes"] if row.get("historical_uid")}
    decisions = []
    for uid, (booking_id, amount, rooms, nights) in EXPECTED.items():
        link = links.get(uid)
        envelope = envelopes.get(uid)
        if (not isinstance(link, dict) or link.get("booking_id") != booking_id
                or link.get("category") != "숙박" or link.get("period") != "0705_0707"
                or link.get("hotel") != "카메노이 호텔 다자와코"
                or int(link.get("paid_amount", 0)) != amount or link.get("currency") != "KRW"
                or link.get("nights") != nights or (rooms is not None and link.get("rooms") != rooms)
                or link.get("verification_source") != "user_booking_page"
                or link.get("amount_verification") != "exact"):
            raise ValueError("verified_kamenoi_booking_contract_drift")
        if not isinstance(envelope, dict):
            raise ValueError("verified_kamenoi_legacy_candidate_binding_missing")
        decisions.append({
            "direct_event_key": envelope["direct_event_key"],
            "current_event_sha256": envelope["current_event_sha256"],
            "current_source_sha256": envelope["current_source_sha256"],
            "booking_id": booking_id,
            "booking_record_sha256": _sha(json.dumps(
                link, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()),
            "account": "숙박비", "cost_type": "여행원가",
            "trip_target": TRIP_TARGET,
            "candidate_status": "withheld_pending_direct_current_binding_and_trip_evidence",
            "posting_status": "blocked",
        })
    keys = {row["direct_event_key"] for row in decisions}
    if len(decisions) != 2 or len(keys) != 2 or r36._event_set_sha(keys) != SELECTED_SET_SHA256:
        if is_strict_static_pins():
            raise ValueError("verified_kamenoi_selected_set_drift")
        warnings.warn("verified_kamenoi_selected_set_drift (non-strict)", stacklevel=2)
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "selected_event_set_sha256": SELECTED_SET_SHA256,
            "selected_count": 2, "candidate_axis_count": 6,
            "gate5_credit": 0, "authority_status": "candidate_only",
            "excluded_dimensions": ["vat_tag"],
            "ota_links_sha256": OTA_LINKS_SHA256, "trips_sha256": TRIPS_SHA256,
            "current_event_set_sha256": annex["manifest"]["current_event_set_sha256"],
            "decision_scope_sha256": annex["manifest"]["decision_scope_sha256"],
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "candidates": sorted(decisions, key=lambda row: row["direct_event_key"]),
    }
