"""Read-only checks for the P2 policy packet measurement tool.

No policy file is modified: the fallback case is forced by monkeypatching the
approved fingerprint list, and the CLI runs in isolated Python (-I).
"""
import json
import re
import subprocess
import sys

import pytest

from app import p2_case, p2_policy_pack
from tools import p2_policy_packet_measure as measure

COMBINATIONS = [(), ('link',), ('refund',), ('link', 'refund')]
RULE_HEAD = re.compile(r'(?m)^### ([A-Z]{3,6}-\d{3}) · ')


@pytest.mark.parametrize('areas', COMBINATIONS)
def test_compact_smaller_in_expected_band_and_reproducible(areas):
    first = measure.measure_combination(areas)
    second = measure.measure_combination(areas)
    assert first == second
    assert first['compact_is_fallback'] is False
    assert first['full_bytes'] > first['compact_bytes']
    assert 40.0 <= first['reduction_pct'] <= 50.0
    assert first['areas'] == sorted(areas)


def test_unapproved_catalog_fingerprint_falls_back_to_full(monkeypatch):
    monkeypatch.setattr(p2_policy_pack, 'CATALOG_FINGERPRINTS',
                        {area: frozenset() for area in p2_policy_pack.PINNED})
    assert p2_policy_pack.compact_policy_context(p2_case.ROOT, ('link',)) is None
    row = measure.measure_combination(('link',))
    assert row['compact_is_fallback'] is True
    assert row['compact_bytes'] == row['full_bytes']
    assert row['reduction_pct'] == 0.0
    assert row['compact_sha256'] == row['full_sha256']
    assert row['rule_ids']['only_in_compact'] == []
    assert row['rule_ids']['only_in_full'] == []


@pytest.mark.parametrize('areas', COMBINATIONS)
def test_rule_id_diff_keeps_pinned_protection_clauses(areas):
    row = measure.measure_combination(areas)
    # PROC-010/011 are 보호 clauses the legacy full loader filters out; the
    # compact packet pins them on purpose, so only_in_compact is expected.
    assert {'PROC-010', 'PROC-011'} <= set(row['rule_ids']['only_in_compact'])
    assert row['rule_ids']['common_count'] > 0
    assert row['rule_ids']['only_in_full']


def test_rule_id_diff_matches_direct_packet_comparison():
    areas = ('link', 'refund')
    full = p2_case.policy_context(areas, compact=False)
    compact = p2_policy_pack.compact_policy_context(p2_case.ROOT, areas)
    assert compact is not None
    full_ids = {identity for area, text in full.items() if area != 'CORE'
                for identity in RULE_HEAD.findall(text)}
    compact_ids = {identity for area, text in compact.items() if area != 'CORE'
                   for identity in RULE_HEAD.findall(text)}
    assert measure.measure_combination(areas)['rule_ids'] == {
        'only_in_compact': sorted(compact_ids - full_ids),
        'only_in_full': sorted(full_ids - compact_ids),
        'common_count': len(compact_ids & full_ids),
    }


def test_cli_json_is_deterministic_under_isolated_python():
    script = p2_case.ROOT / 'tools' / 'p2_policy_packet_measure.py'
    runs = [subprocess.run([sys.executable, '-I', str(script), '--json'],
                           capture_output=True, text=True, encoding='utf-8',
                           cwd=str(p2_case.ROOT), timeout=120)
            for _ in range(2)]
    for run in runs:
        assert run.returncode == 0, run.stderr
    assert runs[0].stdout == runs[1].stdout
    report = json.loads(runs[0].stdout)
    assert [row['areas'] for row in report] == [[], ['link'], ['refund'], ['link', 'refund']]
    for row in report:
        assert {'areas', 'compact_bytes', 'full_bytes', 'reduction_pct',
                'compact_is_fallback', 'rule_ids'} <= set(row)
