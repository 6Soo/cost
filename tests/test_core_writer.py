import json
import sqlite3
import subprocess

import pytest

from app import automatic_classification as policy
from app import core_writer


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in (core_writer.WRITER_ENV, core_writer.BIN_ENV, core_writer.CORE_DB_ENV):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch, tmp_path


@pytest.mark.parametrize('value', [None, '', 'python', 'PYTHON', 'rusty', 'true'])
def test_python_is_the_default_writer_and_every_other_value_keeps_it(env, value):
    monkeypatch, _ = env
    if value is not None:
        monkeypatch.setenv(core_writer.WRITER_ENV, value)
    assert core_writer.selected() == 'python'


def test_only_rust_selects_the_core_and_unsetting_returns_to_python(env):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.WRITER_ENV, ' Rust ')
    assert core_writer.selected() == 'rust'
    monkeypatch.delenv(core_writer.WRITER_ENV)
    assert core_writer.selected() == 'python'


def test_python_apply_does_not_touch_the_core_writer_by_default(env, monkeypatch):
    monkeypatch.setattr(core_writer, 'apply', lambda *a, **k: pytest.fail('core writer used'))
    conn = sqlite3.connect(':memory:')
    with pytest.raises(sqlite3.OperationalError):  # reaches the Python path (no schema), not the core writer
        policy.apply(conn, {'digest': 'x'}, [])


def test_rust_writer_refuses_without_configuration_or_inside_a_transaction(env, tmp_path):
    monkeypatch, _ = env
    db = tmp_path / 'board.sqlite'
    conn = sqlite3.connect(db)
    with pytest.raises(RuntimeError, match='CORE_WRITER_NOT_CONFIGURED'):
        core_writer.apply(conn, {'digest': 'd'}, [])
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn.execute('CREATE TABLE t(a)')
    conn.execute('INSERT INTO t VALUES (1)')
    with pytest.raises(RuntimeError, match='CORE_WRITER_IN_TRANSACTION'):
        core_writer.apply(conn, {'digest': 'd'}, [])


def _fake_run(monkeypatch, stdout):
    seen = {}

    def run(command, **kwargs):
        seen['command'], seen['input'] = command, json.loads(kwargs['input'])
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr='')
    monkeypatch.setattr(core_writer.subprocess, 'run', run)
    return seen


def test_rust_writer_passes_digest_and_context_and_returns_the_summary(env, tmp_path):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn = sqlite3.connect(tmp_path / 'board.sqlite')
    seen = _fake_run(monkeypatch, json.dumps({'ok': True, 'result': {'to_classify': 2}}) + '\n')
    result = core_writer.apply(conn, {'digest': 'abc'}, [{'trip_id': 'A'}], transaction_ids={'t2', 't1'},
                               reconsider=True, evidence={'t1': {}})
    assert result == {'to_classify': 2}
    assert seen['command'][1] == 'apply' and seen['command'][seen['command'].index('--digest') + 1] == 'abc'
    assert seen['input'] == {'trips': [{'trip_id': 'A'}], 'nets': {}, 'evidence': {'t1': {}},
                             'reconsider': True, 'transaction_ids': ['t1', 't2']}


def test_stale_preview_keeps_the_python_error_and_other_codes_are_runtime_errors(env, tmp_path):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn = sqlite3.connect(tmp_path / 'board.sqlite')
    _fake_run(monkeypatch, json.dumps({'ok': False, 'error': {'code': 'CLASSIFICATION_PREVIEW_STALE'}}) + '\n')
    with pytest.raises(ValueError, match='CLASSIFICATION_PREVIEW_STALE'):
        core_writer.apply(conn, {'digest': 'x'}, [])
    _fake_run(monkeypatch, json.dumps({'ok': False, 'error': {'code': 'STORE_ERROR'}}) + '\n')
    with pytest.raises(RuntimeError, match='STORE_ERROR'):
        core_writer.apply(conn, {'digest': 'x'}, [])


def test_stored_service_period_reads_core_sqlite_read_only(env, tmp_path):
    monkeypatch, _ = env
    core = tmp_path / 'core.sqlite'
    with sqlite3.connect(core) as c:
        c.execute('CREATE TABLE decisions(transaction_id TEXT, service_period_json TEXT)')
        c.execute("INSERT INTO decisions VALUES ('t1', '{\"kind\": \"known\", \"starts_on\": \"2026-10-01\", \"ends_on\": \"2026-10-02\"}')")
    c.close()
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(core))
    assert core_writer.stored_service_period('t1')['starts_on'] == '2026-10-01'
    assert core_writer.stored_service_period('missing') is None
