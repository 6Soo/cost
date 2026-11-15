import json
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import automatic_classification as policy
from app import core_switch_config, core_writer
from tools import core_rejudge
from tools import complete_card_classification as complete_tool
from webapp import card_classification_completion as completion


@pytest.fixture
def host(tmp_path, monkeypatch):
    for name in core_switch_config.ENV_NAMES:
        monkeypatch.setenv(name, 'x')  # restored on teardown; core_switch_config.apply rewrites them
    (tmp_path / 'config').mkdir()
    data = tmp_path / 'data'
    (data / 'backups/b1').mkdir(parents=True)
    (data / 'core.sqlite').write_bytes(b'')
    (tmp_path / 'costcore.exe').write_bytes(b'')
    with sqlite3.connect(data / 'board.sqlite') as conn:
        conn.execute('CREATE TABLE t(a)')
        conn.execute('INSERT INTO t VALUES (1)')
    set_options(tmp_path)
    return tmp_path


def set_options(host, **overrides):
    options = {'classification_writer': 'rust', 'costcore_bin': str(host / 'costcore.exe'),
               'core_db': str(host / 'data/core.sqlite'), **overrides}
    (host / 'config/card-flow.json').write_text(json.dumps(options), encoding='utf-8')


def write_backup(host, **overrides):
    evidence = {'live_state_unchanged': True, 'restored_review_binding_equal': True,
                'backup_scope_kind': 'scoped', 'out_of_scope_unchanged': True,
                'backup_scope': ['board.sqlite', 'core.sqlite'],
                'recorded_at': datetime.now(timezone.utc).isoformat(),
                'backup_directory': str(host / 'data/backups/b1'), **overrides}
    path = host / 'data/backups/evidence.json'
    path.write_text(json.dumps(evidence), encoding='utf-8')
    return path


@pytest.fixture
def wired(host, monkeypatch):
    """Fake flow and plan; the real policy.apply -> core_writer.apply path runs against a fake costcore."""
    calls = {'run': [], 'periods_built': 0}

    def read_flow(conn, root):
        return SimpleNamespace(board=SimpleNamespace(conn=conn, _lock=threading.RLock()))

    def built(conn, lock=None):
        calls['periods_built'] += 1
        return {'t1': [{'basis': 'x'}]}, 'key'

    monkeypatch.setattr(complete_tool, 'read_flow', read_flow)
    monkeypatch.setattr(completion, 'context', lambda flow: ([], {}))
    monkeypatch.setattr(completion, 'classification_evidence', lambda *a, **k: {})
    monkeypatch.setattr(policy, 'plan', lambda *a, **k: {
        'digest': 'dg', 'targets': [], 'summary': {'scanned': 5, 'to_classify': 2, 'protected': 1}})
    monkeypatch.setattr(core_writer, 'periods_with_key', built)
    monkeypatch.setattr(core_writer, 'periods_key', lambda conn, lock=None: 'key')

    def respond(*replies):
        queue = list(replies)

        def run(command, **kwargs):
            calls['run'].append((command, json.loads(kwargs['input'])))
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(reply) + '\n', stderr='')
        monkeypatch.setattr(core_writer.subprocess, 'run', run)
    calls['respond'] = respond
    return calls


OK = {'ok': True, 'result': {'to_classify': 2}, 'written': 2, 'skipped_unjudged': 0, 'skipped_mismatch': 0,
      'backfilled': 0, 'transaction_id': 'SECRET-TID'}
STALE = {'ok': False, 'error': {'code': 'CLASSIFICATION_PREVIEW_STALE'}}


def test_refuses_unless_the_writer_is_rust(host, wired, capsys):
    set_options(host, classification_writer='python')
    assert core_rejudge.main(['--host-root', str(host), '--dry-run']) == 2
    assert 'CORE_REJUDGE_WRITER_NOT_RUST' in capsys.readouterr().out
    (host / 'config/card-flow.json').unlink()
    assert core_rejudge.main(['--host-root', str(host), '--dry-run']) == 2
    assert wired['run'] == []


@pytest.mark.parametrize('case', ['missing', 'unverified', 'not_covering', 'stale', 'outside'])
def test_refuses_without_valid_backup_evidence(host, wired, capsys, case):
    wired['respond'](OK)
    argv = ['--host-root', str(host)]
    if case != 'missing':
        overrides = {'unverified': {'live_state_unchanged': False},
                     'not_covering': {'backup_scope': ['board.sqlite']},
                     'stale': {'recorded_at': '2020-01-01T00:00:00+00:00'},
                     'outside': {'backup_directory': str(host)}}.get(case, {})
        argv += ['--backup-evidence', str(write_backup(host, **overrides))]
    assert core_rejudge.main(argv) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'FAILED'
    assert wired['run'] == []


def test_dry_run_writes_nothing_and_reports_counts_and_timing(host, wired, capsys):
    wired['respond'](OK)
    before = (host / 'data/board.sqlite').read_bytes()
    assert core_rejudge.main(['--host-root', str(host), '--dry-run']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'DRY_RUN' and report['writes'] == 0
    assert (report['scanned'], report['to_classify'], report['protected']) == (5, 2, 1)
    assert 'evidence_seconds' in report and wired['periods_built'] == 1
    assert wired['run'] == []  # costcore never called
    assert (host / 'data/board.sqlite').read_bytes() == before
    assert not (host / 'data/core-apply-runs').exists()


def test_apply_goes_through_core_writer_with_periods_and_prints_the_run_summary(host, wired, capsys):
    wired['respond'](OK)
    argv = ['--host-root', str(host), '--backup-evidence', str(write_backup(host))]
    assert core_rejudge.main(argv) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert (report['status'], report['written'], report['skipped_mismatch'], report['backfilled']) == ('APPLIED', 2, 0, 0)
    assert 'seconds' in report and 'SECRET-TID' not in out
    assert datetime.fromisoformat(report['backup_recorded_at']).tzinfo is not None
    (command, request), = wired['run']
    assert command[1] == 'apply' and '--backfill-decisions' not in command
    assert request['periods'] == {'t1': [{'basis': 'x'}]}  # evidence from core_writer, not empty
    assert wired['periods_built'] == 1
    latest = json.loads((host / 'data/core-apply-runs/latest.json').read_text(encoding='utf-8'))
    assert latest['latest']['written'] == 2


def test_backfill_flag_reaches_costcore(host, wired):
    wired['respond'](OK)
    argv = ['--host-root', str(host), '--backup-evidence', str(write_backup(host)), '--backfill-decisions']
    assert core_rejudge.main(argv) == 0
    assert '--backfill-decisions' in wired['run'][0][0]


def test_python_writer_apply_rejects_backfill():
    with pytest.raises(ValueError, match='BACKFILL_NEEDS_RUST_WRITER'):
        policy.apply(sqlite3.connect(':memory:'), {'digest': 'x'}, [], backfill=True)


def test_concurrent_board_write_is_retried_once(host, wired, capsys):
    wired['respond'](STALE, OK)
    argv = ['--host-root', str(host), '--backup-evidence', str(write_backup(host))]
    assert core_rejudge.main(argv) == 0
    assert len(wired['run']) == 2 and wired['periods_built'] == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'APPLIED'


def test_persistent_stale_ends_with_a_clear_code_after_one_retry(host, wired, capsys):
    wired['respond'](STALE)
    argv = ['--host-root', str(host), '--backup-evidence', str(write_backup(host))]
    assert core_rejudge.main(argv) == 2
    assert len(wired['run']) == 2
    assert json.loads(capsys.readouterr().out) == {'status': 'FAILED', 'code': 'CORE_REJUDGE_PREVIEW_STALE'}
