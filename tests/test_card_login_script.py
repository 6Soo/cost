"""Execution wrapper for the owned card-login Node fixture suites.

Runs every synthetic fixture ``tests/card_login/test_*.mjs`` with the repository's
Node toolchain and checks its result lines. Synthetic fixtures only: no real card
site, login session, account or customer data is used, and nothing is installed or
downloaded. A missing Node toolchain fails this check instead of skipping, and a
suite that reports no executed test, any FAIL, or any skip marker fails too.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE_GLOB = "tests/card_login/test_*.mjs"
TIMEOUT_SECONDS = 300

PASS_LINE = re.compile(r"^PASS\b", re.MULTILINE)
FAIL_LINE = re.compile(r"^FAIL\b", re.MULTILINE)
SKIP_LINE = re.compile(r"^(?:ok\s+\S+\s+-\s+.*# SKIP|SKIP\b.*)$", re.MULTILINE | re.IGNORECASE)


def test_card_login_node_fixture_suites_pass() -> None:
    suite = sorted(str(path) for path in ROOT.glob(SUITE_GLOB))
    assert suite, f"no owned fixture suite matched {SUITE_GLOB!r}"

    if shutil.which("node") is None:
        raise AssertionError("node executable not found; failing because the toolchain must not be auto-installed")

    total_passed = 0
    lines: list[str] = []
    for path in suite:
        try:
            result = subprocess.run(
                ["node", path], cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS, check=False,
            )
        except FileNotFoundError:
            raise AssertionError("node executable not found; toolchain must not be auto-installed") from None
        except subprocess.TimeoutExpired:
            raise AssertionError(f"{path} timed out after {TIMEOUT_SECONDS}s") from None

        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        passed = len(PASS_LINE.findall(combined))
        failures = len(FAIL_LINE.findall(combined))
        skips = len(SKIP_LINE.findall(combined))

        assert passed > 0, f"{path} reported no executed tests:\n{combined[-2000:]}"
        assert not failures, f"{path} reported {failures} failure lines:\n{combined[-4000:]}"
        assert not skips, f"{path} reported skipped tests:\n{combined[-2000:]}"
        assert result.returncode == 0, f"{path} exited {result.returncode}:\n{combined[-4000:]}"

        total_passed += passed
        lines.append(f"{path}: {passed} pass, {failures} fail, {skips} skip")

    for line in lines:
        print(line)
    print(f"card_login_node_fixtures: {total_passed} tests clean, 0 fail, 0 skip")
