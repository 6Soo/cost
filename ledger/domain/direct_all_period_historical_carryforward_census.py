"""Dry-run census for the large historical high/high carry-forward decision."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, build_annex


ARTIFACT_TYPE = "all-period-historical-carryforward-census-v1"
RULE_VERSION = "exact-lineage-posted-merchant-high-high-dry-run-v1"
TRIPS_SHA256 = "0a9fdd6b4835d2cf889391b00e2567977858b77376d3d3071023e81609e51969"
CLASSIFICATION_SET_SHA256 = "71ebfa85e2dbf97d778da60767072bc2300a87411442490ab0bdbb44ba671438"
GATE5_ELIGIBLE_SET_SHA256 = "9b5f2286fa608f4407f287d0c486ef232362e96a928cb8c01826a43ae6950a52"
SEMANTIC_SET_SHA256 = "c44ce5848421667e92df3438eab0b79130108f41c90476e51869de1080e37d2e"
ALREADY_PROJECTED_UIDS = {
    "KBO-2681", "KBO-2682", "KBO-2689", "KBO-2700", "KBO-2701", "KBO-2702",
    "KBD-0389", "KBD-0390", "HAN-3004", "HAN-3011", "HAN-3047", "KBD-0741",
    "KBD-0871", "KBD-0927", "KBD-0958",
}
EXPECTED_ACCOUNTS = {
    "교통비": 40, "렌터카": 23, "소모품비": 4, "수수료": 1, "숙박비": 130,
    "식비": 346, "이용료": 3, "입장료": 14, "주유비": 25, "주차비": 6, "통신비": 1,
    "통행료": 15, "항공료": 3,
}
EXPECTED_SOURCES = {"HAN": 343, "KBD": 31, "KBO": 237}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_historical_carryforward_census(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("carryforward_census_noncanonical_ledger")
    trips_raw = (ledger_dir / "data/trips.json").read_bytes()
    if _sha(trips_raw) != TRIPS_SHA256:
        raise ValueError("carryforward_census_trips_drift")
    trip_codes = {row["tab"] for row in json.loads(trips_raw)}
    annex = build_annex(ledger_dir=ledger_dir)
    selected = []
    strict_before_policy = 0
    for row in annex["package"]["envelopes"]:
        proposal = row.get("proposal") or {}
        strict = (row.get("disposition") == "historical_high_complete_proposal"
                  and row.get("posted_date_exact") is True
                  and row.get("merchant_exact") is True
                  and row.get("historical_uid") not in ALREADY_PROJECTED_UIDS)
        if not strict:
            continue
        strict_before_policy += 1
        if ((proposal.get("cost_type"), proposal.get("vat_tag"))
                != ("여행원가", "불공제_해외")
                or proposal.get("bucket") in {None, "", "확인"}
                or proposal.get("account") in {None, "", "확인"}):
            continue
        selected.append({
            "direct_event_key": row["direct_event_key"],
            "historical_uid": row["historical_uid"],
            "current_event_sha256": row["current_event_sha256"],
            "current_source_sha256": row["current_source_sha256"],
            "bucket": proposal["bucket"], "account": proposal["account"],
            "cost_type": proposal["cost_type"], "vat_tag": proposal["vat_tag"],
            "gate5_trip_eligible": proposal["bucket"] in trip_codes,
        })
    keys = {row["direct_event_key"] for row in selected}
    eligible = {row["direct_event_key"] for row in selected if row["gate5_trip_eligible"]}
    semantic = [{"event": row["direct_event_key"], "bucket": row["bucket"],
                 "account": row["account"], "cost_type": row["cost_type"],
                 "vat_tag": row["vat_tag"]} for row in selected]
    semantic_sha = _sha((json.dumps(
        sorted(semantic, key=lambda row: row["event"]), ensure_ascii=False,
        sort_keys=True, separators=(",", ":")) + "\n").encode())
    accounts = dict(sorted(Counter(row["account"] for row in selected).items()))
    sources = dict(sorted(Counter(
        str(row["historical_uid"]).split("-", 1)[0] for row in selected).items()))
    lifecycle = [row for row in selected if not row["gate5_trip_eligible"]]
    if (strict_before_policy != 764 or len(selected) != 611 or len(eligible) != 608
            or r36._event_set_sha(keys) != CLASSIFICATION_SET_SHA256
            or r36._event_set_sha(eligible) != GATE5_ELIGIBLE_SET_SHA256
            or semantic_sha != SEMANTIC_SET_SHA256
            or accounts != EXPECTED_ACCOUNTS or sources != EXPECTED_SOURCES
            or len(lifecycle) != 3
            or {row["historical_uid"] for row in lifecycle}
            != {"KBD-0779", "KBD-0781", "KBD-0783"}
            or {row["bucket"] for row in lifecycle} != {"취소환불"}):
        raise ValueError("carryforward_census_drift")
    return {
        "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
        "strict_before_policy_count": strict_before_policy,
        "classification_candidate_count": len(selected),
        "gate5_trip_eligible_count": len(eligible),
        "lifecycle_nontrip_count": len(lifecycle),
        "classification_set_sha256": CLASSIFICATION_SET_SHA256,
        "gate5_eligible_set_sha256": GATE5_ELIGIBLE_SET_SHA256,
        "semantic_set_sha256": SEMANTIC_SET_SHA256,
        "account_counts": accounts, "source_counts": sources,
        "lifecycle_uids": sorted(row["historical_uid"] for row in lifecycle),
        "current_event_set_sha256": annex["manifest"]["current_event_set_sha256"],
        "decision_scope_sha256": annex["manifest"]["decision_scope_sha256"],
        "authority_status": "awaiting_user_policy_decision",
        "database_applied": False, "posting_status": "blocked",
        "all_source_events_retained": True,
    }
