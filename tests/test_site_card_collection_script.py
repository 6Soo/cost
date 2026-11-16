"""Run the synthetic Hana/IBK collection contract through Node and the real parser."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "site_card_collection" / "test_site_card_collection.mjs"
TIMEOUT_SECONDS = 180


def test_site_card_collection_node_end_to_end() -> None:
    if shutil.which("node") is None:
        raise AssertionError("node executable not found; refusing to skip the synthetic E2E")
    result = subprocess.run(
        ["node", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    passed = len(re.findall(r"^PASS\b", combined, re.MULTILINE))
    failures = len(re.findall(r"^FAIL\b", combined, re.MULTILINE))
    skipped = len(re.findall(r"^(?:SKIP\b|ok\s+\S+\s+-\s+.*# SKIP)", combined, re.MULTILINE | re.IGNORECASE))
    assert passed == 15, f"expected 15 executed cases, found {passed}:\n{combined[-4000:]}"
    assert failures == 0, f"Node suite reported failures:\n{combined[-4000:]}"
    assert skipped == 0, f"Node suite reported skipped cases:\n{combined[-2000:]}"
    assert result.returncode == 0, f"Node suite exited {result.returncode}:\n{combined[-4000:]}"
    print("site_card_collection_node_e2e: 15 passed, 0 failed, 0 skipped")
