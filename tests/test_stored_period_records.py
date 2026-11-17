"""Synthetic source identity and bounded batch reads used by the React DTO."""
import json
import sqlite3

import pytest

from app import core_writer as writer


@pytest.fixture
def record_db(tmp_path, monkeypatch):
    path = tmp_path / 'core.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE decisions(transaction_id TEXT,source_hash TEXT,revision INTEGER,service_period_json TEXT)')
        conn.executemany('INSERT INTO decisions VALUES (?,?,?,?)', [
            ('verified', 'a' * 64, 3, json.dumps({'kind': 'known', 'starts_on': '2026-10-01', 'ends_on': '2026-10-03'})),
            ('bad', 'b' * 64, 4, 'malformed')])
    monkeypatch.setenv(writer.WRITER_ENV, 'rust')
    monkeypatch.setenv(writer.CORE_DB_ENV, str(path))
    monkeypatch.setattr(writer, '_PERIOD_RECORD_CACHE', {})
    monkeypatch.setattr(writer, '_LAST_RECORD_READ', {'path': None, 'records': None})
    monkeypatch.setattr(writer, '_READ_ERROR', {'error': '', 'stale': False})
    monkeypatch.setattr(writer, '_schedule_publish', lambda: None)
    return path


def test_records_include_source_identity_and_normalize_without_writing(record_db):
    before = record_db.read_bytes()
    records = writer.load_stored_period_records()
    assert records['verified'] == {'kind': 'verified', 'starts_on': '2026-10-01', 'ends_on': '2026-10-03',
                                   'source_hash': 'a' * 64, 'revision': 3}
    assert records['bad'] == {'kind': 'unknown', 'source_hash': 'b' * 64, 'revision': 4}
    records['verified']['kind'] = 'corrupted_by_caller'
    assert writer.load_stored_period_records()['verified']['kind'] == 'verified'
    assert record_db.read_bytes() == before


def test_busy_reuses_only_same_core_path(record_db, monkeypatch, tmp_path):
    expected = writer.load_stored_period_records()
    monkeypatch.setattr(writer, '_core_signature', lambda: None)
    def unavailable(*args, **kwargs):
        assert kwargs['timeout'] <= 1
        raise sqlite3.OperationalError('synthetic confidential text')
    monkeypatch.setattr(writer.sqlite3, 'connect', unavailable)
    assert writer.load_stored_period_records() == expected
    assert writer._READ_ERROR == {'error': 'OperationalError', 'stale': True}
    monkeypatch.setenv(writer.CORE_DB_ENV, str(tmp_path / 'different.sqlite'))
    assert writer.load_stored_period_records() == {}
    assert writer._READ_ERROR == {'error': 'OperationalError', 'stale': False}


def test_python_does_not_open_core(record_db, monkeypatch):
    monkeypatch.setenv(writer.WRITER_ENV, 'python')
    monkeypatch.setattr(writer.sqlite3, 'connect', lambda *a, **k: pytest.fail('unexpected core read'))
    assert writer.load_stored_period_records() is None
