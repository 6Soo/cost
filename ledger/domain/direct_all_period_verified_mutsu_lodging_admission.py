"""Admit six Plaza Hotel Mutsu payments from individually verified Agoda bookings."""
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
        proposal = envelope.get("proposal") if isinstance(envelope, dict) else None
        if (not isinstance(proposal, dict)
                or (proposal.get("bucket"), proposal.get("account"),
                    proposal.get("cost_type"), proposal.get("vat_tag"),
                    proposal.get("confidence"), proposal.get("tax_conf"))
                != (TRIP_TARGET, "숙박비", "여행원가", "불공제_해외", "상", "상")):
            raise ValueError("verified_mutsu_lineage_contract_drift")
        decisions.append({
            "direct_event_key": envelope["direct_event_key"],
            "current_event_sha256": envelope["current_event_sha256"],
            "current_source_sha256": envelope["current_source_sha256"],
            "booking_id": booking_id,
            "booking_record_sha256": _sha(json.dumps(
                link, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()),
            "account": "숙박비", "cost_type": "여행원가",
            "vat_tag": "불공제_해외", "trip_target": TRIP_TARGET,
            "decision_status": "confirmed", "posting_status": "blocked",
        })
    keys = {row["direct_event_key"] for row in decisions}
    if len(decisions) != 6 or len(keys) != 6 or r36._event_set_sha(keys) != SELECTED_SET_SHA256:
        raise ValueError("verified_mutsu_selected_set_drift")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "selected_event_set_sha256": SELECTED_SET_SHA256,
            "selected_count": 6, "axis_decision_count": 24,
            "ota_links_sha256": OTA_LINKS_SHA256,
            "current_event_set_sha256": annex["manifest"]["current_event_set_sha256"],
            "decision_scope_sha256": annex["manifest"]["decision_scope_sha256"],
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "decisions": sorted(decisions, key=lambda row: row["direct_event_key"]),
    }
