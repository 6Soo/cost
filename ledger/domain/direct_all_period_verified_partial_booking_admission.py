"""Retain seven mixed-provenance booking rows as candidates only."""
from __future__ import annotations

import hashlib
import warnings
import json
from datetime import date, timedelta
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, build_annex
from ledger.domain.staged_inputs import is_strict_static_pins


ARTIFACT_TYPE = "all-period-verified-partial-booking-admission-v1"
RULE_VERSION = "exact-booking-payment-explicit-axes-only-v1"
OTA_LINKS_SHA256 = "2a3bc075b0d7596d5d99bef9dd7b9fda61a88428cf833e48042f55fbe6801b27"
TRIPS_SHA256 = "0a9fdd6b4835d2cf889391b00e2567977858b77376d3d3071023e81609e51969"
SELECTED_SET_SHA256 = "cfcbbffd02f21ae6bad9ee7fa414ed0130b8bb60f84ab0c772a529168824cc59"
EXPECTED = {
    "HAN-3004": {
        "booking_id": "1400825055983985", "category": "숙박", "period": "1127",
        "paid_amount": 1224285, "verification_source": "trip_hotel_and_manual_ledger",
        "amount_verification": "exact", "trip": "1127_야쿠시마",
        "axes": {"account": "숙박비", "cost_type": "여행원가",
                 "allocation_target": "1127_야쿠시마"},
    },
    "HAN-3011": {
        "booking_id": "1400825121225979", "category": "숙박", "period": "0408",
        "paid_amount": 792768, "verification_source": "trip_hotel_and_manual_ledger",
        "amount_verification": "exact", "trip": "0408_교토",
        "axes": {"account": "숙박비", "cost_type": "여행원가",
                 "allocation_target": "0408_교토"},
    },
    "HAN-3047": {
        "booking_id": "1400825265150133", "category": "숙박", "period": "0424",
        "paid_amount": 762870, "verification_source": "trip_hotel_and_manual_ledger",
        "amount_verification": "exact", "trip": "0424_알펜루트",
        "axes": {"account": "숙박비", "cost_type": "여행원가",
                 "allocation_target": "0424_알펜루트"},
    },
    "KBD-0741": {
        "external_source_id": "retired_staff_ota:2026:45", "category": "항공",
        "period": "1010_1013", "paid_amount": 1248400,
        "verification_source": "retired_staff_ota_trusted_fields",
        "amount_verification": "exact", "trip": "1010_도쿠시마",
        "axes": {"account": "항공료", "cost_type": "여행원가",
                 "allocation_target": "1010_도쿠시마"},
    },
    "KBD-0871": {
        "booking_id": "1400826610904891", "category": "항공", "period": "0801_0805",
        "paid_amount": 1293600, "verification_source": "user_booking_page",
        "amount_verification": "exact", "trip": "0801_노리쿠라",
        "axes": {"account": "항공료", "allocation_target": "0801_노리쿠라"},
    },
    "KBD-0927": {
        "booking_id": "1400826934962683", "category": "항공", "period": "0616_0621",
        "paid_amount": 1081000, "verification_source": "user_booking_page_and_payment_discount",
        "amount_verification": "exact_after_discount", "trip": "0616_레분토&리시리",
        "axes": {"account": "항공료", "allocation_target": "0616_레분토&리시리"},
    },
    "KBD-0958": {
        "booking_id": "1400826306387654", "category": "숙박", "period": "",
        "paid_amount": 750030, "verification_source": "manual_ledger_crosscheck",
        "amount_verification": "exact", "trip": None,
        "axes": {"account": "숙박비"},
    },
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _period_dates(period: str) -> tuple[date, date]:
    start, _, end = period.partition("_")
    if not end:
        end = start
    return (date(2026, int(start[:2]), int(start[2:])),
            date(2026, int(end[:2]), int(end[2:])))


def build_verified_partial_booking_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("verified_partial_noncanonical_ledger")
    links_raw = (ledger_dir / "data/ota_event_links_verified.json").read_bytes()
    trips_raw = (ledger_dir / "data/trips.json").read_bytes()
    if _sha(links_raw) != OTA_LINKS_SHA256 or _sha(trips_raw) != TRIPS_SHA256:
        if is_strict_static_pins():
            raise ValueError("verified_partial_input_drift")
        warnings.warn("verified_partial_input_drift (non-strict)", stacklevel=2)
    links = json.loads(links_raw)
    trips = {row["tab"]: row for row in json.loads(trips_raw)}
    annex = build_annex(ledger_dir=ledger_dir)
    envelopes = {row.get("historical_uid"): row
                 for row in annex["package"]["envelopes"] if row.get("historical_uid")}
    decisions = []
    for uid, expected in EXPECTED.items():
        link = links.get(uid)
        envelope = envelopes.get(uid)
        if not isinstance(link, dict) or not isinstance(envelope, dict):
            raise ValueError("verified_partial_binding_missing")
        for field in ("booking_id", "external_source_id", "category", "period", "paid_amount",
                      "verification_source", "amount_verification"):
            if field in expected and link.get(field) != expected[field]:
                raise ValueError("verified_partial_booking_contract_drift")
        trip_target = expected["trip"]
        if trip_target is not None:
            trip = trips.get(trip_target)
            if not isinstance(trip, dict) or set(trip) != {"tab", "mm", "dd", "region", "window"}:
                raise ValueError("verified_partial_trip_contract_drift")
            start = date(2026, int(trip["mm"]), int(trip["dd"]))
            end = start + timedelta(days=int(trip["window"]) - 1)
            period_start, period_end = _period_dates(str(expected["period"]))
            if not (start <= period_start <= period_end <= end):
                raise ValueError("verified_partial_period_outside_trip")
        decisions.append({
            "direct_event_key": envelope["direct_event_key"],
            "current_event_sha256": envelope["current_event_sha256"],
            "current_source_sha256": envelope["current_source_sha256"],
            "evidence_record_sha256": _sha(json.dumps(
                link, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()),
            "axes": dict(expected["axes"]),
            "candidate_status": "withheld_pending_direct_current_binding_and_trip_evidence",
            "posting_status": "blocked",
        })
    keys = {row["direct_event_key"] for row in decisions}
    axis_count = sum(len(row["axes"]) for row in decisions)
    if (len(decisions) != 7 or len(keys) != 7 or axis_count != 17
            or r36._event_set_sha(keys) != SELECTED_SET_SHA256):
        if is_strict_static_pins():
            raise ValueError("verified_partial_selected_set_drift")
        warnings.warn("verified_partial_selected_set_drift (non-strict)", stacklevel=2)
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "selected_event_set_sha256": SELECTED_SET_SHA256,
            "selected_count": 7, "candidate_axis_count": 17,
            "excluded_dimensions": ["vat_tag"], "gate5_credit": 0,
            "authority_status": "candidate_only",
            "ota_links_sha256": OTA_LINKS_SHA256, "trips_sha256": TRIPS_SHA256,
            "current_event_set_sha256": annex["manifest"]["current_event_set_sha256"],
            "decision_scope_sha256": annex["manifest"]["decision_scope_sha256"],
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "candidates": sorted(decisions, key=lambda row: row["direct_event_key"]),
    }
