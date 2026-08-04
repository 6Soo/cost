"""Admit the 611 historical decisions only after isolated code replay reproduces them."""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ledger.domain.direct_all_period_historical_carryforward_census import (
    build_historical_carryforward_census,
)
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT


ARTIFACT_TYPE = "all-period-historical-carryforward-admission-v1"
RULE_VERSION = "isolated-legacy-code-replay-exact-axes-v1"
EXPECTED_REPLAY_V14_SHA256 = "93ad47c4ef78301d1934411e53bc48e560cba2bce1fe7f926af32a2b384a5fc1"
EXPECTED_REPLAY_ROW_COUNT = 1684
EXPECTED_REPLAY_SELECTED_COUNT = 611
EXPECTED_AXIS_DECISION_COUNT = 2444
REPLAY_COMMANDS = (
    ("python3", "build_v13_trip.py"),
    ("python3", "fix_v14.py"),
    ("python3", "patch_v14.py"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replay_legacy(ledger_dir: Path) -> tuple[list[dict[str, str]], str, list[dict[str, object]]]:
    with tempfile.TemporaryDirectory(prefix="historical-carryforward-replay-") as directory:
        replay_ledger = Path(directory) / "ledger"
        shutil.copytree(ledger_dir, replay_ledger, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(REPOSITORY_ROOT))
        commands = []
        for command in REPLAY_COMMANDS:
            process = subprocess.run(
                command, cwd=replay_ledger, env=environment,
                capture_output=True, text=True, check=False,
            )
            commands.append({"command": list(command), "returncode": process.returncode,
                             "stdout_sha256": _sha(process.stdout.encode()),
                             "stderr_sha256": _sha(process.stderr.encode())})
            if process.returncode != 0:
                raise ValueError(f"carryforward_replay_failed:{command[1]}")
        output = replay_ledger / "data/classified_v14.csv"
        raw = output.read_bytes()
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        if _sha(raw) != EXPECTED_REPLAY_V14_SHA256 or len(rows) != EXPECTED_REPLAY_ROW_COUNT:
            raise ValueError("carryforward_replay_output_drift")
        return rows, _sha(raw), commands


def build_historical_carryforward_admission(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("carryforward_admission_noncanonical_ledger")
    census = build_historical_carryforward_census(ledger_dir=ledger_dir)
    replay_rows, replay_sha, commands = _replay_legacy(ledger_dir)
    replay_by_uid = {row["uid"]: row for row in replay_rows}
    decisions = []
    changed = []
    missing = []
    for candidate in census["candidates"]:
        uid = str(candidate["historical_uid"])
        replay = replay_by_uid.get(uid)
        if replay is None:
            missing.append(uid)
            continue
        axes = {dimension: candidate[field] for dimension, field in (
            ("allocation_target", "bucket"), ("account", "account"),
            ("cost_type", "cost_type"), ("vat_tag", "vat_tag"))}
        differences = {dimension: (value, replay.get(
            "bucket" if dimension == "allocation_target" else dimension, ""))
            for dimension, value in axes.items()
            if replay.get("bucket" if dimension == "allocation_target" else dimension, "") != value}
        if differences:
            changed.append((uid, differences))
            continue
        decisions.append({
            "direct_event_key": candidate["direct_event_key"],
            "historical_uid": uid,
            "current_event_sha256": candidate["current_event_sha256"],
            "current_source_sha256": candidate["current_source_sha256"],
            "axes": axes,
            "gate5_trip_eligible": candidate["gate5_trip_eligible"],
            "decision_status": "confirmed", "posting_status": "blocked",
        })
    if (missing or changed or len(decisions) != EXPECTED_REPLAY_SELECTED_COUNT
            or sum(len(row["axes"]) for row in decisions) != EXPECTED_AXIS_DECISION_COUNT
            or sum(bool(row["gate5_trip_eligible"]) for row in decisions) != 608):
        raise ValueError("carryforward_replay_selected_mismatch")
    return {
        "manifest": {
            "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "selected_count": len(decisions),
            "axis_decision_count": EXPECTED_AXIS_DECISION_COUNT,
            "gate5_trip_eligible_count": 608, "lifecycle_nontrip_count": 3,
            "replay_v14_sha256": replay_sha,
            "replay_v14_row_count": len(replay_rows),
            "replay_missing_count": len(missing), "replay_changed_count": len(changed),
            "replay_commands": commands,
            "classification_set_sha256": census["classification_set_sha256"],
            "semantic_set_sha256": census["semantic_set_sha256"],
            "authority_status": "confirmed_by_reproducible_code_replay",
            "posting_status": "blocked", "database_applied": False,
            "all_source_events_retained": True,
        },
        "decisions": decisions,
    }
