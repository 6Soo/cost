"""Run the pinned legacy classification lineage once for carry-forward admissions."""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT


EXPECTED_REPLAY_V14_SHA256 = "93ad47c4ef78301d1934411e53bc48e560cba2bce1fe7f926af32a2b384a5fc1"
EXPECTED_REPLAY_ROW_COUNT = 1684
REPLAY_COMMANDS = (
    ("python3", "build_v13_trip.py"),
    ("python3", "fix_v14.py"),
    ("python3", "patch_v14.py"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replay_legacy_classification(ledger_dir: Path) -> dict[str, object]:
    """Return the pinned replay rows and provenance from an isolated ledger copy."""
    with tempfile.TemporaryDirectory(prefix="historical-carryforward-replay-") as directory:
        replay_ledger = Path(directory) / "ledger"
        shutil.copytree(
            ledger_dir, replay_ledger,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(REPOSITORY_ROOT))
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        commands = []
        for command in REPLAY_COMMANDS:
            process = subprocess.run(
                command, cwd=replay_ledger, env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            if process.returncode != 0 and command[0] == "python3":
                fallback = (sys.executable, command[1])
                process = subprocess.run(
                    fallback, cwd=replay_ledger, env=environment,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                )
                command = fallback
            commands.append({
                "command": list(command), "returncode": process.returncode,
                "stdout_sha256": _sha(process.stdout.encode()),
                "stderr_sha256": _sha(process.stderr.encode()),
            })
            if process.returncode != 0:
                raise ValueError(f"carryforward_replay_failed:{command[1]}")
        output = replay_ledger / "data/classified_v14.csv"
        raw = output.read_bytes()
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        if (_sha(raw) != EXPECTED_REPLAY_V14_SHA256
                or len(rows) != EXPECTED_REPLAY_ROW_COUNT):
            raise ValueError("carryforward_replay_output_drift")
        return {
            "rows": rows,
            "sha256": _sha(raw),
            "row_count": len(rows),
            "commands": commands,
        }
