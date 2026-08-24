"""Candidate census learned from the historical high/high validation process.

The old labels are not evidence.  This module only records which current card
events survived the old identity/cardinality checks and which three cost axes
were concrete.  VAT no longer participates in selection or output.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from collections import Counter
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, build_annex
from ledger.domain.staged_inputs import is_strict_static_pins


ARTIFACT_TYPE = "all-period-historical-carryforward-census-v2"
RULE_VERSION = "legacy-process-audit-three-active-axis-candidate-only-v2"
TRIPS_SHA256 = "0a9fdd6b4835d2cf889391b00e2567977858b77376d3d3071023e81609e51969"
CLASSIFICATION_SET_SHA256 = "7f0c81f10e42da1b7a373283834c9c81081c7eb4197c37b628e27d17262e79f7"
TRIP_HINT_SET_SHA256 = "a5df09ad078cf0a778b4307dea7c05c28b1cd21a8cadad141367891b4c3e771b"
SEMANTIC_SET_SHA256 = "eebe4188f007ba5968e61377d188fa2ca93f5738590e15871e5e2979ffbb821a"
ALREADY_PROJECTED_UIDS = {
    "KBO-2681", "KBO-2682", "KBO-2689", "KBO-2700", "KBO-2701", "KBO-2702",
    "KBD-0389", "KBD-0390", "HAN-3004", "HAN-3011", "HAN-3047", "KBD-0741",
    "KBD-0871", "KBD-0927", "KBD-0958",
}
EXPECTED_ACCOUNTS = {
    "교통비": 54, "렌터카": 26, "복리후생비": 24, "세금과공과": 1,
    "소모품비": 10, "수수료": 1, "숙박비": 168, "식비": 370,
    "이용료": 3, "입장료": 15, "주유비": 26, "주차비": 10,
    "지급수수료": 3, "통신비": 4, "통행료": 16, "항공료": 16,
    "회의비": 3,
}
EXPECTED_COST_TYPES = {"여행원가": 707, "판관비": 43}
EXPECTED_SOURCES = {"HAN": 364, "KBD": 146, "KBO": 240}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_historical_carryforward_census(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger",
        annex: dict[str, object] | None = None) -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("carryforward_census_noncanonical_ledger")
    trips_raw = (ledger_dir / "data/trips.json").read_bytes()
    if _sha(trips_raw) != TRIPS_SHA256:
        if is_strict_static_pins():
            raise ValueError("carryforward_census_trips_drift")
        warnings.warn("carryforward_census_trips_drift (non-strict)", stacklevel=2)
    trip_codes = {row["tab"] for row in json.loads(trips_raw)}
    annex = annex or build_annex(ledger_dir=ledger_dir)
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
        if (proposal.get("bucket") in {None, "", "확인"}
                or proposal.get("account") in {None, "", "확인"}
                or proposal.get("cost_type") in {None, "", "확인"}):
            continue
        selected.append({
            "direct_event_key": row["direct_event_key"],
            "historical_uid": row["historical_uid"],
            "current_event_sha256": row["current_event_sha256"],
            "current_source_sha256": row["current_source_sha256"],
            "bucket": proposal["bucket"], "account": proposal["account"],
            "cost_type": proposal["cost_type"],
            "legacy_trip_target_hint": proposal["bucket"] in trip_codes,
        })
    keys = {row["direct_event_key"] for row in selected}
    trip_hints = {
        row["direct_event_key"] for row in selected
        if row["legacy_trip_target_hint"]
    }
    semantic = [{"event": row["direct_event_key"], "bucket": row["bucket"],
                 "account": row["account"], "cost_type": row["cost_type"],
                 } for row in selected]
    semantic_sha = _sha((json.dumps(
        sorted(semantic, key=lambda row: row["event"]), ensure_ascii=False,
        sort_keys=True, separators=(",", ":")) + "\n").encode())
    accounts = dict(sorted(Counter(row["account"] for row in selected).items()))
    cost_types = dict(sorted(Counter(
        row["cost_type"] for row in selected
    ).items()))
    sources = dict(sorted(Counter(
        str(row["historical_uid"]).split("-", 1)[0] for row in selected).items()))
    nontrip_hints = [row for row in selected if not row["legacy_trip_target_hint"]]
    if (strict_before_policy != 764 or len(selected) != 750 or len(trip_hints) != 700
            or r36._event_set_sha(keys) != CLASSIFICATION_SET_SHA256
            or r36._event_set_sha(trip_hints) != TRIP_HINT_SET_SHA256
            or semantic_sha != SEMANTIC_SET_SHA256
            or accounts != EXPECTED_ACCOUNTS
            or cost_types != EXPECTED_COST_TYPES
            or sources != EXPECTED_SOURCES
            or len(nontrip_hints) != 50
            or Counter(row["bucket"] for row in nontrip_hints)
            != {"기타비용": 43, "취소환불": 7}):
        if is_strict_static_pins():
            raise ValueError("carryforward_census_drift")
        warnings.warn("carryforward_census_drift (non-strict)", stacklevel=2)
    return {
        "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
        "strict_before_policy_count": strict_before_policy,
        "classification_candidate_count": len(selected),
        "trip_target_hint_count": len(trip_hints),
        "nontrip_target_hint_count": len(nontrip_hints),
        "classification_set_sha256": CLASSIFICATION_SET_SHA256,
        "trip_hint_set_sha256": TRIP_HINT_SET_SHA256,
        "semantic_set_sha256": SEMANTIC_SET_SHA256,
        "account_counts": accounts, "cost_type_counts": cost_types,
        "source_counts": sources,
        "nontrip_target_counts": dict(sorted(Counter(
            row["bucket"] for row in nontrip_hints
        ).items())),
        "current_event_set_sha256": annex["manifest"]["current_event_set_sha256"],
        "decision_scope_sha256": annex["manifest"]["decision_scope_sha256"],
        "authority_status": "candidate_only", "gate5_credit": 0,
        "active_dimensions": ["account", "cost_type", "allocation_target"],
        "excluded_dimensions": ["vat_tag"],
        "trips_json_is_evidence": False,
        "legacy_partition_only": True,
        "database_applied": False, "posting_status": "blocked",
        "all_source_events_retained": True,
        "candidates": sorted(selected, key=lambda row: row["direct_event_key"]),
    }
