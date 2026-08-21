"""Retain 750 replayed three-axis rows as non-authoritative candidates."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ledger.domain.direct_all_period_historical_carryforward_census import (
    build_historical_carryforward_census,
)
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT
from ledger.domain.direct_all_period_historical_replay import (
    replay_legacy_classification,
)


ARTIFACT_TYPE = "all-period-historical-carryforward-candidates-v3"
RULE_VERSION = "isolated-legacy-replay-three-active-axis-candidate-only-v3"
EXPECTED_REPLAY_SELECTED_COUNT = 750
EXPECTED_CANDIDATE_AXIS_COUNT = 2250


def build_historical_carryforward_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger",
        replay: dict[str, Any] | None = None,
        census: dict[str, Any] | None = None) -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("carryforward_admission_noncanonical_ledger")
    census = census or build_historical_carryforward_census(ledger_dir=ledger_dir)
    replay = replay or replay_legacy_classification(ledger_dir)
    replay_rows = replay["rows"]
    replay_sha = str(replay["sha256"])
    replay_row_count = int(replay["row_count"])
    commands = replay["commands"]
    replay_by_uid = {row["uid"]: row for row in replay_rows}
    candidates = []
    changed = []
    missing = []
    for candidate in census["candidates"]:
        uid = str(candidate["historical_uid"])
        replay_row = replay_by_uid.get(uid)
        if replay_row is None:
            missing.append(uid)
            continue
        axes = {dimension: candidate[field] for dimension, field in (
            ("allocation_target", "bucket"), ("account", "account"),
            ("cost_type", "cost_type"))}
        differences = {dimension: (value, replay_row.get(
            "bucket" if dimension == "allocation_target" else dimension, ""))
            for dimension, value in axes.items()
            if replay_row.get(
                "bucket" if dimension == "allocation_target" else dimension, "") != value}
        if differences:
            changed.append((uid, differences))
            continue
        candidates.append({
            "direct_event_key": candidate["direct_event_key"],
            "historical_uid": uid,
            "current_event_sha256": candidate["current_event_sha256"],
            "current_source_sha256": candidate["current_source_sha256"],
            "axes": axes,
            "legacy_trip_target_hint": candidate["legacy_trip_target_hint"],
            "candidate_status": "withheld_pending_independent_evidence",
            "posting_status": "blocked",
        })
    if (missing or changed or len(candidates) != EXPECTED_REPLAY_SELECTED_COUNT
            or sum(len(row["axes"]) for row in candidates) != EXPECTED_CANDIDATE_AXIS_COUNT
            or sum(bool(row["legacy_trip_target_hint"]) for row in candidates) != 700):
        raise ValueError("carryforward_replay_selected_mismatch")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "candidate_count": len(candidates),
            "candidate_axis_count": EXPECTED_CANDIDATE_AXIS_COUNT,
            "gate5_credit": 0,
            "legacy_trip_hint_count": 700, "legacy_nontrip_hint_count": 50,
            "replay_v14_sha256": replay_sha,
            "replay_v14_row_count": replay_row_count,
            "replay_missing_count": len(missing), "replay_changed_count": len(changed),
            "replay_commands": commands,
            "classification_set_sha256": census["classification_set_sha256"],
            "semantic_set_sha256": census["semantic_set_sha256"],
            "authority_status": "candidate_only",
            "excluded_dimensions": ["vat_tag"],
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "candidates": candidates,
    }
