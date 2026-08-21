"""Retain six legacy-bound Mutsu rows as booking candidates only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, build_annex


ARTIFACT_TYPE = "all-period-verified-mutsu-lodging-admission-v1"
RULE_VERSION = "verified-agoda-booking-card-exact-lodging-v1"
OTA_LINKS_SHA256 = "2a3bc075b0d7596d5d99bef9dd7b9fda61a88428cf833e48042f55fbe6801b27"
SELECTED_SET_SHA256 = "c9c9c81d3d1c2416cba72477344f0768ec9e8d4350d82df0d8bf876bb0debc9c"
TRIP_TARGET = "0417_아오모리"
EXPECTED = {
    "KBO-2681": ("2000890083", "0417_0418", 21030),
    "KBO-2682": ("1706671692", "0417_0419", 34370),
    "KBO-2689": ("1716795279", "0417_0419", 27152),
    "KBO-2700": ("1718382019", "0418_0419", 6501),
    "KBO-2701": ("1718165811", "0417_0418", 6183),
    "KBO-2702": ("1718165346", "0418_0419", 6773),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_verified_mutsu_lodging_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("verified_mutsu_noncanonical_ledger")
    links_path = ledger_dir / "data/ota_event_links_verified.json"
    raw = links_path.read_bytes()
    if _sha(raw) != OTA_LINKS_SHA256:
        raise ValueError("verified_mutsu_ota_links_drift")
    links = json.loads(raw)
    annex = build_annex(ledger_dir=ledger_dir)
    envelopes = {row.get("historical_uid"): row
                 for row in annex["package"]["envelopes"] if row.get("historical_uid")}
    decisions = []
    for uid, (booking_id, period, foreign_amount) in EXPECTED.items():
        link = links.get(uid)
        envelope = envelopes.get(uid)
        if (not isinstance(link, dict) or link.get("booking_id") != booking_id
                or link.get("category") != "숙박" or link.get("period") != period
                or link.get("hotel") != "Plaza Hotel Mutsu"
                or link.get("card4") != "8835" or link.get("currency") != "JPY"
                or int(link.get("foreign_amount", 0)) != foreign_amount
                or link.get("verification_source") != "agoda_booking_page"):
            raise ValueError("verified_mutsu_booking_contract_drift")
        if not isinstance(envelope, dict):
            raise ValueError("verified_mutsu_legacy_candidate_binding_missing")
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
    if len(decisions) != 6 or len(keys) != 6 or r36._event_set_sha(keys) != SELECTED_SET_SHA256:
        raise ValueError("verified_mutsu_selected_set_drift")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "selected_event_set_sha256": SELECTED_SET_SHA256,
            "selected_count": 6, "candidate_axis_count": 18,
            "gate5_credit": 0, "authority_status": "candidate_only",
            "excluded_dimensions": ["vat_tag"],
            "ota_links_sha256": OTA_LINKS_SHA256,
            "current_event_set_sha256": annex["manifest"]["current_event_set_sha256"],
            "decision_scope_sha256": annex["manifest"]["decision_scope_sha256"],
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "candidates": sorted(decisions, key=lambda row: row["direct_event_key"]),
    }
