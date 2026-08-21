"""Retain concrete replay axes for 153 rows as candidate metadata only."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_all_period_historical_carryforward_census import (
    ALREADY_PROJECTED_UIDS,
    build_historical_carryforward_census,
)
from ledger.domain.direct_all_period_historical_replay import replay_legacy_classification
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, build_annex


ARTIFACT_TYPE = "all-period-historical-partial-carryforward-candidates-v2"
RULE_VERSION = "isolated-legacy-replay-active-axis-candidate-only-v2"
EXPECTED_PAYMENT_COUNT = 14
EXPECTED_CANDIDATE_AXIS_COUNT = 28
EXPECTED_EVENT_SET_SHA256 = "88be50debfd09d2a48d927a9c6a2dbf93f53b14289176e19ea8172ba6f6299da"
EXPECTED_SEMANTIC_SET_SHA256 = "627c640d833809fd30c05a97fbddafc181ed8b568e74eb0f5867c6187ec59c37"
EXPECTED_AXIS_COUNTS = {
    "account": 14, "allocation_target": 14,
}
PLACEHOLDERS = {None, "", "확인"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_residual_candidates(
        ledger_dir: Path,
        *,
        annex: dict[str, object] | None = None) -> list[dict[str, object]]:
    selected = []
    annex = annex or build_annex(ledger_dir=ledger_dir)
    for row in annex["package"]["envelopes"]:
        proposal = row.get("proposal") or {}
        strict = (
            row.get("disposition") == "historical_high_complete_proposal"
            and row.get("posted_date_exact") is True
            and row.get("merchant_exact") is True
            and row.get("historical_uid") not in ALREADY_PROJECTED_UIDS
        )
        full_carryforward = all(
            proposal.get(field) not in PLACEHOLDERS
            for field in ("bucket", "account", "cost_type")
        )
        if not strict or full_carryforward:
            continue
        axes = {}
        if proposal.get("bucket") not in PLACEHOLDERS:
            axes["allocation_target"] = proposal["bucket"]
        if proposal.get("account") not in PLACEHOLDERS:
            axes["account"] = proposal["account"]
        if proposal.get("cost_type") not in PLACEHOLDERS:
            axes["cost_type"] = proposal["cost_type"]
        selected.append({
            "direct_event_key": row["direct_event_key"],
            "historical_uid": row["historical_uid"],
            "current_event_sha256": row["current_event_sha256"],
            "current_source_sha256": row["current_source_sha256"],
            "axes": axes,
        })
    return sorted(selected, key=lambda row: str(row["direct_event_key"]))


def build_historical_partial_carryforward_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger",
        replay: dict[str, Any] | None = None,
        census: dict[str, Any] | None = None,
        annex: dict[str, object] | None = None) -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("partial_carryforward_admission_noncanonical_ledger")
    annex = annex or build_annex(ledger_dir=ledger_dir)
    census = census or build_historical_carryforward_census(
        ledger_dir=ledger_dir, annex=annex)
    candidates = _strict_residual_candidates(ledger_dir, annex=annex)
    replay = replay or replay_legacy_classification(ledger_dir)
    replay_by_uid = {row["uid"]: row for row in replay["rows"]}
    decisions = []
    for candidate in candidates:
        uid = str(candidate["historical_uid"])
        replay_row = replay_by_uid.get(uid)
        if replay_row is None:
            raise ValueError("partial_carryforward_replay_missing")
        axes = dict(candidate["axes"])
        for dimension, value in axes.items():
            replay_field = "bucket" if dimension == "allocation_target" else dimension
            if replay_row.get(replay_field, "") != value:
                raise ValueError("partial_carryforward_replay_axis_mismatch")
        decisions.append({**candidate,
                          "candidate_status": "withheld_pending_independent_evidence",
                          "posting_status": "blocked"})
    event_keys = {str(row["direct_event_key"]) for row in decisions}
    semantic = [{"event": row["direct_event_key"], "uid": row["historical_uid"],
                 "axes": row["axes"]} for row in decisions]
    semantic_sha = _sha((json.dumps(
        semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode())
    axis_counts = dict(sorted(Counter(
        dimension for row in decisions for dimension in row["axes"]
    ).items()))
    full_keys = {row["direct_event_key"] for row in
                 census["candidates"]}
    if (len(decisions) != EXPECTED_PAYMENT_COUNT
            or sum(len(row["axes"]) for row in decisions) != EXPECTED_CANDIDATE_AXIS_COUNT
            or r36._event_set_sha(event_keys) != EXPECTED_EVENT_SET_SHA256
            or semantic_sha != EXPECTED_SEMANTIC_SET_SHA256
            or axis_counts != EXPECTED_AXIS_COUNTS
            or event_keys & full_keys
            or Counter(len(row["axes"]) for row in decisions) != {2: 14}):
        raise ValueError("partial_carryforward_admission_drift")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "candidate_count": len(decisions),
            "legacy_candidate_axis_count": EXPECTED_CANDIDATE_AXIS_COUNT,
            "axis_counts": axis_counts, "fully_concrete_payment_count": 0,
            "trip_allocation_eligible_count": 0, "nontrip_full_axis_count": 0,
            "event_set_sha256": EXPECTED_EVENT_SET_SHA256,
            "semantic_set_sha256": EXPECTED_SEMANTIC_SET_SHA256,
            "replay_v14_sha256": replay["sha256"],
            "replay_v14_row_count": replay["row_count"],
            "full_carryforward_overlap_count": len(event_keys & full_keys),
            "authority_status": "candidate_only", "gate5_credit": 0,
            "active_dimensions": ["account", "cost_type", "allocation_target"],
            "excluded_dimensions": ["vat_tag"],
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "candidates": decisions,
    }
