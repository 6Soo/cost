"""``eval_cases --planner rust``: per-case Python/Rust comparison with synthetic data only."""
import json
import os
import sys

import pytest

from tests.test_quarter_review_eval_cases import (  # noqa: F401
    NAME, REVIEW_ID, TRIPS, corrected, host_with_copy, setup)
from tools.quarter_review import eval_cases


def python_as_rust(copy, trips, ids, nets, evidence):
    """A stand-in Rust planner that agrees with Python exactly."""
    return eval_cases._python_plan(copy, trips, ids, nets, evidence)


def empty_rust(copy, trips, ids, nets, evidence):
    """A stand-in Rust planner that judges nothing (every row keeps the import classification)."""
    return {'targets': []}


def test_python_planner_report_is_unchanged(setup):
    c, _ = corrected(setup)
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    assert 'comparison' not in report and 'planner' not in report


def test_agreeing_rust_planner_gives_identical_results_and_zero_differences(setup):
    c, ids = corrected(setup)
    baseline = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID, planner='rust', rust_plan=python_as_rust)
    assert report['planner'] == 'rust'
    assert report['comparison'] == dict(cases=5, same=5, different=0, by_transition={}, by_type=[])
    assert {k: v for k, v in report.items() if k not in ('planner', 'comparison')} == baseline


def test_diverging_rust_planner_is_reported_by_fixed_tokens_only(setup):
    c, ids = corrected(setup)
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID, planner='rust', rust_plan=empty_rust)
    comparison = report['comparison']
    assert comparison['cases'] == 5 and comparison['same'] + comparison['different'] == 5
    assert comparison['different'] >= 1
    assert sum(comparison['by_transition'].values()) == comparison['different']
    for key in comparison['by_transition']:
        for token in key.split('->'):
            eval_cases.validate_token(token)
    for t in comparison['by_type']:
        eval_cases.validate_public([{k: v for k, v in t.items() if k not in ('python', 'rust', 'count')}])
    text = json.dumps(report, ensure_ascii=False)
    assert not any(i in text for i in ids) and NAME not in text


def test_rust_planner_requires_a_plan_function(setup):
    c, _ = corrected(setup)
    with pytest.raises(ValueError, match='RUST_PLANNER_NOT_CONFIGURED'):
        eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID, planner='rust')


def test_validate_token_is_an_allow_list():
    for good in ('MATCH', 'MISMATCH[ITEM_DIFFERS]', 'MISMATCH[ATTRIBUTION_QUARTER_VS_TRIP+ITEM_DIFFERS]',
                 'NOT_REJUDGED[NOT_REJUDGED_SOURCE_PROTECTED]'):
        eval_cases.validate_token(good)
    for bad in (NAME, 'MISMATCH[' + NAME + ']', 'MISMATCH[FREE_TEXT]', 'UNKNOWN', 'MATCH[ITEM_DIFFERS]x'):
        with pytest.raises(ValueError, match='PUBLIC_VALUE_NOT_ALLOWED'):
            eval_cases.validate_token(bad)


def fake_costcore(tmp_path, response):
    """An executable that records its --db argument and prints a fixed response line."""
    script = tmp_path / 'fake_costcore.py'
    record = tmp_path / 'argv.txt'
    script.write_text(
        'import sys\n'
        'sys.stdin.read()\n'
        f'open({str(record)!r}, "w").write(sys.argv[sys.argv.index("--db") + 1])\n'
        f'print({json.dumps(response)!r})\n', encoding='utf-8')
    if os.name == 'nt':
        launcher = tmp_path / 'costcore.cmd'
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding='utf-8')
    else:
        launcher = tmp_path / 'costcore'
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding='utf-8')
        launcher.chmod(0o755)
    return launcher, record


def prepare_main(setup, tmp_path, monkeypatch):
    c, _ = corrected(setup)
    c.commit()
    host = host_with_copy(setup, tmp_path)
    (host / 'data/backups').mkdir(parents=True)
    import tools.complete_card_classification as legacy
    monkeypatch.setattr(legacy, 'load_context', lambda conn, host_root: (TRIPS, {}))
    monkeypatch.setattr(legacy, 'load_review_evidence', lambda *a, **k: ({}, {}))
    return host


def test_main_runs_costcore_on_a_private_copy_and_prints_the_comparison(setup, tmp_path, monkeypatch, capsys):
    host = prepare_main(setup, tmp_path, monkeypatch)
    launcher, record = fake_costcore(tmp_path, {'ok': True, 'result': {'targets': []}})
    assert eval_cases.main(['eval', '--host-root', str(host), '--planner', 'rust', '--no-evidence',
                            '--costcore', str(launcher)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'EVALUATED' and out['planner'] == 'rust'
    assert out['comparison']['cases'] == 5
    copy_path = record.read_text(encoding='utf-8')
    backups = (host / 'data/backups').resolve()
    assert os.path.realpath(copy_path).startswith(str(backups)) and not copy_path.startswith(str(eval_cases.REPO_ROOT))
    assert not os.path.exists(copy_path) and list(backups.glob('eval-rust-*')) == []
    # the comparison failure makes --fail-on-mismatch non-zero as well
    assert eval_cases.main(['eval', '--host-root', str(host), '--planner', 'rust', '--no-evidence',
                            '--costcore', str(launcher), '--fail-on-mismatch']) == 2


def test_main_reports_the_engine_not_available_code(setup, tmp_path, monkeypatch, capsys):
    host = prepare_main(setup, tmp_path, monkeypatch)
    launcher, _ = fake_costcore(tmp_path, {'ok': False, 'error': {'code': 'ENGINE_NOT_AVAILABLE'}})
    assert eval_cases.main(['eval', '--host-root', str(host), '--planner', 'rust', '--no-evidence',
                            '--costcore', str(launcher)]) == 1
    assert json.loads(capsys.readouterr().out) == {'status': 'FAILED', 'code': 'ENGINE_NOT_AVAILABLE'}
    assert list((host / 'data/backups').glob('eval-rust-*')) == []


def test_main_without_a_costcore_binary_fails_with_a_code(setup, tmp_path, monkeypatch, capsys):
    host = prepare_main(setup, tmp_path, monkeypatch)
    monkeypatch.delenv('COSTCORE_BIN', raising=False)
    monkeypatch.setattr(eval_cases.shutil, 'which', lambda name: None)
    assert eval_cases.main(['eval', '--host-root', str(host), '--planner', 'rust', '--no-evidence']) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'COSTCORE_NOT_FOUND'
