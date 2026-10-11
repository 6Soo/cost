import sqlite3

import pytest

from app import db


def legacy_connection(path):
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute('CREATE TABLE legacy_evidence(id TEXT PRIMARY KEY, original BLOB)')
    conn.execute('INSERT INTO legacy_evidence VALUES (?, ?)', ('synthetic', b'original'))
    return conn


def tables(conn):
    return conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()


def test_additive_migration_is_idempotent_and_preserves_legacy_data(tmp_path):
    conn = legacy_connection(tmp_path / 'legacy.sqlite')
    try:
        before = conn.execute('SELECT * FROM legacy_evidence').fetchall()
        store = db.Store(conn)
        schema = tables(conn)
        assert 'transaction_company_exclusions' in {row[0] for row in schema}
        store.ensure_schema()
        assert tables(conn) == schema
        assert conn.execute('SELECT * FROM legacy_evidence').fetchall() == before
        assert not conn.in_transaction
    finally:
        conn.close()


def test_failed_migration_rolls_back_every_new_table(tmp_path, monkeypatch):
    conn = legacy_connection(tmp_path / 'failed.sqlite')
    before = tables(conn)
    monkeypatch.setattr(db, 'SCHEMA_SQL', db.SCHEMA_SQL + '\nCREATE TABLE broken(;')
    try:
        with pytest.raises(sqlite3.Error):
            db.Store(conn)
        assert tables(conn) == before
        assert conn.execute('SELECT * FROM legacy_evidence').fetchall() == [('synthetic', b'original')]
        assert not conn.in_transaction
    finally:
        conn.close()


def test_schema_creation_does_not_commit_callers_transaction(tmp_path):
    conn = legacy_connection(tmp_path / 'outer.sqlite')
    before = tables(conn)
    try:
        conn.execute('BEGIN')
        conn.execute('INSERT INTO legacy_evidence VALUES (?, ?)', ('pending', b'pending'))
        db.Store(conn)
        assert conn.in_transaction
        conn.rollback()
        assert tables(conn) == before
        assert conn.execute('SELECT * FROM legacy_evidence').fetchall() == [('synthetic', b'original')]
    finally:
        conn.close()


def test_first_card_flow_constructs_schema_on_selected_database(tmp_path, monkeypatch):
    from webapp.card_flow import CardFlow
    from webapp.ledger_store import LedgerStore

    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    try:
        assert 'transaction_company_exclusions' not in {row[0] for row in tables(board.conn)}
        before = board.conn.execute('SELECT * FROM board_rows').fetchall()
        flow = CardFlow(board)
        assert flow.pipeline.store.conn is board.conn
        assert 'transaction_company_exclusions' in {row[0] for row in tables(board.conn)}
        assert board.conn.execute('SELECT * FROM board_rows').fetchall() == before
        assert CardFlow(board).pipeline is flow.pipeline
    finally:
        board.close()
