"""Execution wrapper for the owned OTA collection Node fixtures.

Runs the synthetic fixture suite `tests/ota_collection/*.test.mjs` with the
repository Node toolchain and checks its TAP result. Synthetic fixtures only:
no real portal, login session, account or customer data is used, and nothing
is installed or downloaded. A missing Node toolchain fails this check instead
of skipping. The repository-wide impact map (`config/test-impact-map.json`) is
owned and maintained separately, so it is not read or written here.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE_GLOB = 'tests/ota_collection/*.test.mjs'
TIMEOUT_SECONDS = 300

TAP_PLAN = re.compile(r'^1\.\.(\d+)$', re.MULTILINE)
TAP_CASE = re.compile(r'^(ok|not ok) \d+ - ', re.MULTILINE)
TAP_NOT_OK = re.compile(r'^not ok \d+ - ', re.MULTILINE)
TAP_SKIP = re.compile(r'^ok \d+ - .*# SKIP', re.MULTILINE)


def test_ota_collection_node_fixture_suite_passes() -> None:
    suite = sorted(str(path) for path in ROOT.glob(SUITE_GLOB))
    assert suite, f'no owned fixture suite matched {SUITE_GLOB!r}'

    if shutil.which('node') is None:
        raise AssertionError('node executable not found; failing because the toolchain must not be auto-installed')

    try:
        result = subprocess.run(
            ['node', '--test', '--test-reporter=tap', *suite],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        raise AssertionError('node executable not found; failing because the toolchain must not be auto-installed') from None
    except subprocess.TimeoutExpired:
        raise AssertionError(f'ota fixture suite timed out after {TIMEOUT_SECONDS}s') from None

    combined = '\n'.join(part for part in (result.stdout, result.stderr) if part)
    cases = TAP_CASE.findall(result.stdout)
    failures = TAP_NOT_OK.findall(result.stdout)
    skips = TAP_SKIP.findall(result.stdout)
    assert cases, f'tap report executed no top-level cases:\n{combined[-2000:]}'
    assert not failures, f'tap report contains failures:\n{combined[-4000:]}'
    assert not skips, f'tap report contains skips:\n{combined[-2000:]}'
    assert result.returncode == 0, f'node fixture suite exited {result.returncode}:\n{combined[-4000:]}'

    plan = TAP_PLAN.search(result.stdout)
    assert plan is None or int(plan.group(1)) == len(cases), (
        f'tap plan {plan.group(1) if plan else "?"} != executed cases {len(cases)}'
    )

    passed = len(cases) - len(failures)
    print(f'ota_collection_node_fixtures: {passed}/{len(cases)} pass, 0 fail, 0 skip')
