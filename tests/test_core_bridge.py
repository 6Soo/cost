"""Python bridge for the M3 Rust core: protocol, read-only guarantee, golden drift and the allow-list guard."""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tools.core_bridge import commands, golden, golden_guard
from tools.core_bridge.synthetic import scenario_db

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tools' / 'core_bridge' / 'cli.py'
SCENARIO = {'rows': [golden._row('syn-p1', 'gs25')]}


def run_cli(command, *requests):
    proc = subprocess.run([sys.executable, '-I', str(CLI), command], input='\n'.join(requests), text=True,
                          encoding='utf-8', capture_output=True, cwd=ROOT.parent)
    return proc, [json.loads(line) for line in proc.stdout.splitlines()]


def test_cli_runs_isolated_and_wraps_every_response_in_the_envelope():
    request = json.dumps({'scenario': SCENARIO, 'trips': golden.TRIPS})
    proc, (response,) = run_cli('plan', request)
    assert proc.returncode == 0
    assert response['ok'] and response['protocol'] == 'core-bridge/1' and response['command'] == 'plan'
    assert re.fullmatch(r'[0-9a-f]{40}', response['python_sha'])
    assert response['input_digest'] == hashlib.sha256(json.dumps(
        json.loads(request), ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    assert response['result']['summary']['to_classify'] == 1


def test_cli_answers_one_line_per_request_and_reports_failures_without_source_text():
    good = json.dumps({'scenario': SCENARIO, 'trips': golden.TRIPS})
    proc, responses = run_cli('plan', good, 'not json', json.dumps({'trips': []}))
    assert [r['ok'] for r in responses] == [True, False, False]
    assert responses[1]['error']['code'] == 'REQUEST_NOT_JSON'
    assert responses[2]['error']['code'] == 'DB_OR_SCENARIO_REQUIRED'
    assert proc.returncode == 1
    proc, (unknown,) = run_cli('apply', good)
    assert unknown['error']['code'] == 'COMMAND_UNKNOWN' and proc.returncode == 1


def test_database_is_opened_read_only_and_plan_leaves_the_file_untouched():
    with scenario_db(SCENARIO) as path:
        before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with commands.open_ro(path) as conn:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO change_log(at,kind,subject) VALUES ('x','x','x')")
        result = commands.plan({'db': str(path), 'trips': golden.TRIPS})
        snap = commands.snapshot({'db': str(path)})
        assert result['summary']['scanned'] == 1
        assert snap['counts']['transactions'] == 1 and 'read_seconds' not in snap['projection']
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before
    with pytest.raises(commands.BridgeError) as missing:
        commands.snapshot({'db': str(ROOT / 'does-not-exist.sqlite')})
    assert missing.value.code == 'DB_NOT_FOUND'


def test_bridge_has_no_write_path_in_its_sources():
    source = ''.join((ROOT / 'tools' / 'core_bridge' / name).read_text(encoding='utf-8')
                     for name in ('commands.py', 'cli.py'))
    assert not re.search(r"policy\.apply|\.apply\(|\bUPDATE\b|\bDELETE\b|\.commit\(", source)
    assert 'mode=ro' in source


def test_facts_from_a_supplied_report_and_extract_of_a_synthetic_message():
    from tests.card_pipeline.test_booking_mail import message
    row = golden._row('syn-p1', 'AGODA')
    request = {'scenario': {'rows': [row]}, 'trips': golden.TRIPS, 'report': {'matches': []}}
    assert commands.facts(request) == {'evidence': {}, 'summary': {
        'matched_facts': 0, 'service_period_evidence': 0, 'conflicting_periods': 0,
        'source_errors': 0, 'missing_sources': 0}}
    with pytest.raises(commands.BridgeError):
        commands.facts({'scenario': {'rows': [row]}})
    from tests.card_pipeline.test_ota_payments import JP_PAID_BODY, JP_PAID_SUBJECT
    paid = message(JP_PAID_BODY, subject=JP_PAID_SUBJECT, identity='syn-mail-1', sent='2026-09-25')
    plain = message('SYN body without a payment', subject='SYN subject', identity='syn-mail-2')
    facts = commands.extract({'kind': 'message', 'messages': [paid, plain]})['facts']
    assert facts[0]['evidence_status'] == 'paid_verified' and facts[0]['amount'] == '9737' and facts[1] is None
    with pytest.raises(commands.BridgeError):
        commands.extract({'kind': 'nothing'})


# --- golden files ---------------------------------------------------------------------------

def _cases(area):
    return [json.loads(line) for line in (golden.GOLDEN_DIR / f'{area}.jsonl').read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('area', golden.AREAS)
def test_golden_expected_values_still_equal_current_python_output(area):
    from tools.core_bridge.cli import handle
    cases = _cases(area)
    assert cases
    bad = []
    for case in cases:
        response = handle(case['command'], case['input'], sha='')
        if not response['ok'] or response['result'] != case['expected']:
            bad.append(case['case_id'])
    assert not bad, f'Python output moved from the golden for {bad}; regenerate and state the diff types in the PR'


def test_manifest_matches_files_and_lists_every_area():
    manifest = json.loads((golden.GOLDEN_DIR / 'manifest.json').read_text(encoding='utf-8'))
    assert sorted(manifest['files']) == sorted(f'{a}.jsonl' for a in golden.AREAS)
    for name, entry in manifest['files'].items():
        data = (golden.GOLDEN_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
        assert data.count(b'\n') == entry['cases']
    assert {a: manifest['files'][f'{a}.jsonl']['cases'] for a in golden.AREAS} == {
        a: len(_cases(a)) for a in golden.AREAS}


def test_golden_case_ids_are_unique_and_carry_no_python_sha():
    ids = [c['case_id'] for a in golden.AREAS for c in _cases(a)]
    assert len(ids) == len(set(ids))
    for area in golden.AREAS:
        assert 'python_sha' not in (golden.GOLDEN_DIR / f'{area}.jsonl').read_text(encoding='utf-8')


# --- allow-list guard -----------------------------------------------------------------------

@pytest.mark.parametrize('area', golden.AREAS)
def test_committed_golden_passes_the_allow_list(area):
    golden_guard.validate_text(area, (golden.GOLDEN_DIR / f'{area}.jsonl').read_text(encoding='utf-8'))


def _guarded(change):
    case = json.loads(json.dumps(_cases('plan')[0]))
    change(case)
    return case


@pytest.mark.parametrize('name,change', [
    ('real-looking merchant', lambda c: c['input']['scenario']['rows'][0].update(merchant='STARBUCKS GANGNAM')),
    ('non-synthetic id', lambda c: c['input']['scenario']['rows'][0].update(transaction_id='20261013-0042')),
    ('card number', lambda c: c['input']['scenario']['rows'][0].update(card_tail='4512-3456-7890-1234')),
    ('card tail outside the list', lambda c: c['input']['scenario']['rows'][0].update(card_tail='4813')),
    ('unknown key', lambda c: c['input']['scenario']['rows'][0].update(customer_name='SYN')),
    ('real approval number', lambda c: c['input']['scenario']['rows'][0].update(approval_number='30118842')),
    ('free-text description', lambda c: c['input']['scenario']['rows'][0].update(description_raw='dinner with a client')),
    ('mail address in note', lambda c: c.update(note='ask someone@example.com')),
    ('long digit run in expected output', lambda c: c['expected'].update(leak='contact 01012345678')),
    ('mail address in expected output', lambda c: c['expected'].update(leak='a@b.co')),
    ('unknown date year', lambda c: c['input']['scenario']['rows'][0].update(approval_date='2019-01-01')),
    ('envelope key added', lambda c: c.update(extra='x')),
])
def test_guard_rejects_customer_like_values(name, change):
    with pytest.raises(golden_guard.GoldenViolation):
        golden_guard.validate_case(_guarded(change))


def test_guard_accepts_the_unchanged_case_and_every_bridge_input_key_is_listed():
    golden_guard.validate_case(_guarded(lambda c: None))
    keys = set()

    def walk(value):
        if isinstance(value, dict):
            keys.update(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for area in golden.AREAS:
        for case in _cases(area):
            walk(case['input'])
    ids = set(k for k in keys if k.startswith('syn-') or re.fullmatch(r'T-[A-Z0-9]+', k))
    assert keys - ids <= set(golden_guard.KEYS) | golden_guard.CONTAINERS


def test_every_case_reaches_the_branch_it_names_and_the_key_boundaries_are_covered():
    tokens = set()
    for area in golden.AREAS:
        for case in _cases(area):
            text = json.dumps(case['expected'], ensure_ascii=False, sort_keys=True)
            assert all(token in text for token in case['covers']), case['case_id']
            tokens.update(case['covers'])
    for boundary in ('owner_card_residual', 'owner_booking', 'guide_airfare_evidence', '동률 2개 중', '기간 일치',
                     'provisional_assignment', 'rule_conflict', '"links": {}'):
        assert any(boundary in token for token in tokens), boundary
    assert any('user_exception' in token and True for token in tokens)


def test_python_sha_reads_release_marker_then_git_then_fails_closed(tmp_path):
    from tools.core_bridge import cli
    marker = 'ab' * 20
    (tmp_path / 'DEPLOYED_COMMIT').write_text(marker + '\n', encoding='ascii')
    assert cli.python_sha(tmp_path) == marker
    (tmp_path / 'DEPLOYED_COMMIT').write_text('not-a-sha', encoding='ascii')
    assert cli.python_sha(tmp_path) == ''
    (tmp_path / 'DEPLOYED_COMMIT').unlink()
    assert cli.python_sha(tmp_path) == ''
    assert cli.python_sha() == cli.python_sha(ROOT)
    assert re.fullmatch(r'[0-9a-f]{40}', cli.python_sha())


def test_handle_reports_python_sha_unavailable_instead_of_an_empty_sha(monkeypatch):
    from tools.core_bridge import cli
    monkeypatch.setattr(cli, 'python_sha', lambda root=None: '')
    response = cli.handle('plan', {})
    assert not response['ok'] and response['error']['code'] == 'PYTHON_SHA_UNAVAILABLE'
