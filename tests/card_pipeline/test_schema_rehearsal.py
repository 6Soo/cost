"""All migration rehearsal tests use synthetic, disposable SQLite files."""

import hashlib
import sqlite3

import pytest

from app import db
from tools.rehearse_cost_schema import RehearsalError, main, rehearse


def synthetic_source(path):
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE protected_rows(id TEXT PRIMARY KEY, value BLOB)')
        conn.execute('INSERT INTO protected_rows VALUES (?, ?)', ('synthetic', b'\x00original'))
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
        assert conn.execute('SELECT value FROM protected_rows').fetchone() == (b'\x00original',)
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
