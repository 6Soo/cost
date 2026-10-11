import sqlite3

import pytest

from app import db


def test_require_refuses_missing_schema_without_touching_pending_data():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE evidence(value BLOB)')
    conn.execute('INSERT INTO evidence VALUES (?)', (b'pending',))
    before = conn.execute('SELECT * FROM sqlite_master').fetchall()
    with pytest.raises(db.StoreError) as error:
        db.Store(conn, schema_policy='require')
    assert error.value.code == 'SCHEMA_MIGRATION_REQUIRED'
    assert conn.in_transaction
    assert conn.execute('SELECT * FROM sqlite_master').fetchall() == before
    assert conn.execute('SELECT * FROM evidence').fetchall() == [(b'pending',)]
    conn.rollback()
    assert conn.execute('SELECT * FROM evidence').fetchall() == []
    conn.close()


def test_require_accepts_prepared_schema_without_ddl(monkeypatch):
    conn = sqlite3.connect(':memory:')
    db.Store(conn)
    statements = []
    conn.set_trace_callback(statements.append)
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'require')
    db.Store(conn)
    assert statements
    assert all(not sql.lstrip().upper().startswith(
        ('CREATE', 'ALTER', 'DROP', 'SAVEPOINT', 'RELEASE')) for sql in statements)
    conn.close()


def test_require_rejects_wrong_index():
    conn = sqlite3.connect(':memory:')
    db.Store(conn)
    conn.execute('DROP INDEX transactions_state')
    conn.execute('CREATE INDEX transactions_state ON transactions(source_hash)')
    with pytest.raises(db.StoreError) as error:
        db.Store(conn, schema_policy='require')
    assert error.value.code == 'SCHEMA_MIGRATION_REQUIRED'
    conn.close()


def test_require_open_does_not_create_missing_file(tmp_path):
    path = tmp_path / 'missing.sqlite'
    with pytest.raises(sqlite3.OperationalError):
        db.Store.open(str(path), schema_policy='require')
    assert not path.exists()


def test_invalid_policy_fails_closed(monkeypatch):
    conn = sqlite3.connect(':memory:')
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'typo')
    with pytest.raises(db.StoreError) as error:
        db.Store(conn)
    assert error.value.code == 'SCHEMA_POLICY_INVALID'
    assert conn.execute('SELECT * FROM sqlite_master').fetchall() == []
    conn.close()


def test_production_preflight_is_read_only_and_overrides_inherited_policy(tmp_path, monkeypatch):
    from tools.launch_web_ledger import _Refused, require_card_schema

    path = tmp_path / 'board.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE evidence(value BLOB)')
    conn.commit()
    conn.close()
    original = path.read_bytes()
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
    with pytest.raises(_Refused, match='CARD_SCHEMA'):
        require_card_schema(path)
    assert path.read_bytes() == original
    assert os_policy() == 'require'
    conn = sqlite3.connect(path)
    db.Store(conn, schema_policy='create')
    conn.close()
    prepared = path.read_bytes()
    require_card_schema(path)
    assert path.read_bytes() == prepared


def os_policy():
    import os
    return os.environ['WEBLEDGER_CARD_SCHEMA_POLICY']


def test_require_rejects_removed_exclusion_constraint():
    conn = sqlite3.connect(':memory:')
    conn.executescript(db.SCHEMA_SQL.replace('CHECK(excluded IN (0,1))', ''))
    assert db.Store.schema_differences(conn) == ['transaction_company_exclusions']
    with pytest.raises(db.StoreError) as error:
        db.Store(conn, schema_policy='require')
    assert error.value.code == 'SCHEMA_MIGRATION_REQUIRED'
    conn.close()


def test_production_entry_refuses_before_readiness_or_server(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    import run_candidate

    path = tmp_path / 'missing.sqlite'
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
    monkeypatch.setattr(run_candidate.ops, 'durable_config_for',
                        lambda *args, **kwargs: SimpleNamespace(db_path=path))
    monkeypatch.setattr(run_candidate, 'gate_on_readiness',
                        lambda *args, **kwargs: pytest.fail('must refuse before readiness'))
    assert run_candidate.main(['--data-root', str(tmp_path),
                               '--environment', 'production']) == 2
    assert 'CARD_SCHEMA' in capsys.readouterr().err
    assert not path.exists()
    assert os_policy() == 'require'


def test_invalid_open_policy_does_not_create_file(tmp_path):
    path = tmp_path / 'missing.sqlite'
    with pytest.raises(db.StoreError) as error:
        db.Store.open(str(path), schema_policy='')
    assert error.value.code == 'SCHEMA_POLICY_INVALID'
    assert not path.exists()
