"""All migration rehearsal tests use synthetic, disposable SQLite files."""

import hashlib
import sqlite3

import pytest

from app import db
from tools.rehearse_cost_schema import RehearsalError, main, rehearse


def synthetic_source(path):
    from webapp.ledger_store import LedgerStore
    board = LedgerStore(path, seed_demo=False)
    board.close()
    with sqlite3.connect(path) as conn:
        conn.execute('INSERT INTO board_rows VALUES (?, ?, ?, ?, ?)',
                     ('synthetic', 'card_expense', 'synthetic-trip', 1, b'\x00original'))
    conn.close()
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rehearsal_adds_schema_only_on_temporary_clone(tmp_path):
    source = synthetic_source(tmp_path / 'offline-copy.sqlite')
    before = digest(source)
    result = rehearse(source, before)
    assert result['status'] == 'PASS'
    assert result['source_sha256_unchanged'] is True
    assert 'transaction_company_exclusions' in result['added_tables']
    assert digest(source) == before
    with sqlite3.connect(source) as conn:
        assert conn.execute('SELECT payload_json FROM board_rows').fetchone() == (b'\x00original',)
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='transaction_company_exclusions'").fetchone() is None


def test_rehearsal_rejects_checksum_mismatch_without_changes(tmp_path):
    source = synthetic_source(tmp_path / 'copy.sqlite')
    before = digest(source)
    with pytest.raises(RehearsalError, match='BACKUP_CHECKSUM_MISMATCH'):
        rehearse(source, '0' * 64)
    assert digest(source) == before


def test_rehearsal_rejects_database_with_wal_sidecar(tmp_path):
    source = synthetic_source(tmp_path / 'copy.sqlite')
    wal = tmp_path / 'copy.sqlite-wal'
    wal.write_bytes(b'synthetic')
    with pytest.raises(RehearsalError, match='UNQUIESCENT_SOURCE_REFUSED'):
        rehearse(source)


def test_rehearsal_rejects_failed_migration_and_preserves_source(tmp_path, monkeypatch):
    source = synthetic_source(tmp_path / 'copy.sqlite')
    before = digest(source)
    monkeypatch.setattr(db, 'SCHEMA_SQL', db.SCHEMA_SQL + '\nCREATE TABLE invalid(;')
    with pytest.raises(sqlite3.Error):
        rehearse(source)
    assert digest(source) == before


def test_cli_requires_explicit_offline_confirmation(tmp_path):
    source = synthetic_source(tmp_path / 'copy.sqlite')
    with pytest.raises(SystemExit) as exit_info:
        main(['--source-copy', str(source)])
    assert exit_info.value.code == 2


def test_rehearsal_rejects_empty_sqlite_database(tmp_path):
    source = tmp_path / 'empty.sqlite'
    with sqlite3.connect(source):
        pass
    with pytest.raises(RehearsalError, match='INVALID_SQLITE_BACKUP'):
        rehearse(source)


def test_rehearsal_rejects_unrelated_database(tmp_path):
    source = tmp_path / 'unrelated.sqlite'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE something_else(x INTEGER)')
    with pytest.raises(RehearsalError, match='NOT_A_BOARD_DATABASE'):
        rehearse(source)


def test_rehearsal_rejects_lookalike_table_names(tmp_path):
    source = tmp_path / 'lookalike.sqlite'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE board_rows(id TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE board_requests(id TEXT PRIMARY KEY)')
    with pytest.raises(RehearsalError, match='NOT_A_BOARD_DATABASE'):
        rehearse(source)


def test_rehearsal_refuses_source_that_becomes_live_during_copy(tmp_path, monkeypatch):
    from tools import rehearse_cost_schema as tool
    source = synthetic_source(tmp_path / 'copy.sqlite')
    copy = tool.shutil.copyfile

    def raced_copy(src, dest):
        result = copy(src, dest)
        tmp_path.joinpath('copy.sqlite-wal').write_bytes(b'new writer')
        return result

    monkeypatch.setattr(tool.shutil, 'copyfile', raced_copy)
    with pytest.raises(RehearsalError, match='UNQUIESCENT_SOURCE_REFUSED'):
        rehearse(source)
