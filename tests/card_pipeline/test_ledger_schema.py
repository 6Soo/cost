"""M6 unified `ledger` schema and one-time backfill, on synthetic databases only.

Verifies the contract in docs/design/m6-ledger-merge-contract.md:
- `ledger` exists with the contract columns and its two indexes
- `LEDGER_SCHEMA_SQL` stays out of `SCHEMA_SQL`, so an un-migrated production
  database still passes the startup `schema_differences` gate
- the backfill is idempotent, keeps amounts per tab, and leaves `card-*` rows
  pointing at a transaction while manual rows keep a NULL `transaction_id`
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app import db
from tools import migrate_to_ledger

EXPECTED_COLUMNS = {
    'entry_id', 'transaction_id', 'entry_kind', 'item', 'description',
    'amount_krw', 'occurred_on', 'display_tab_id', 'trip_id', 'service_period',
    'reservation_no', 'evidence_type', 'source_kind', 'source_event_id',
    'source_fact_digest', 'source_merchant', 'source_issuer',
    'source_card_last4', 'source_approval_number', 'source_approval_date',
    'source_posting_date', 'source_local_amount', 'source_currency',
    'event_kind', 'classification_state', 'classification_source',
    'classification_basis', 'confirmed_by', 'memo', 'operator_note',
    'revision', 'committed_at', 'batch_id', 'created_at',
}


def board_connection(tmp_path):
    """A board database with three card rows and one hand-entered cash row."""
    conn = sqlite3.connect(tmp_path / 'board.sqlite', isolation_level=None)
    from webapp.ledger_store_schema import SCHEMA_SQL as BOARD_SCHEMA_SQL
    conn.executescript(db.SCHEMA_SQL)          # transactions, ledger_entries
    conn.executescript(BOARD_SCHEMA_SQL)       # board_rows, board_revisions
    rows = [
        ('card-aaa', 'trip-A', 12_000, '숙박비'),
        ('card-bbb', 'trip-A', 45_000, '항공료'),
        ('card-ccc', 'trip-B', 8_000, '식비'),
        ('man-cash-klook-1', 'trip-B', 19_835, '액티비티'),
    ]
    for row_id, tab, amount, item in rows:
        payload = {
            'row_id': row_id, 'row_kind': 'expense', 'display_tab_id': tab,
            'revision': 1, 'item': item, 'description': item,
            'amount_krw': amount, 'occurred_on': '2026-05-01',
            'source_kind': '카드', 'classification_state': 'classified',
        }
        conn.execute(
            'INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)'
            ' VALUES (?,?,?,?,?)', (row_id, 'expense', tab, 1, json.dumps(payload)))
    for transaction_id, batch_id in (('aaa', 'batch-1'), ('bbb', 'batch-1'), ('ccc', 'batch-2')):
        conn.execute(
            'INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,'
            'trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at)'
            " VALUES (?,?,'','','trip-A','',0,'','2026-05-01','purchase','h','2026-10-07T14:48:18+00:00')",
            (transaction_id, batch_id))
    conn.execute(
        'INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,'
        'actor,created_at,client_request_id)'
        " VALUES ('card-aaa',1,'{}','{}','','save','owner','2026-10-07T14:48:18+00:00','r1')")
    return conn


def test_ledger_not_required_by_startup_gate_before_migration(tmp_path):
    """A database with no `ledger` must still satisfy the require-mode gate."""
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(db.SCHEMA_SQL)
        assert 'CREATE TABLE IF NOT EXISTS ledger (' not in db.SCHEMA_SQL
        assert 'CREATE TABLE IF NOT EXISTS ledger (' in db.LEDGER_SCHEMA_SQL
        assert db.Store.schema_differences(conn) == []
        db.Store.require_schema(conn)
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'").fetchone() is None
    finally:
        conn.close()


def test_ledger_exists_with_contract_columns_and_indexes(tmp_path):
    conn = board_connection(tmp_path)
    try:
        migrate_to_ledger.migrate(conn, apply=True)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(ledger)')}
        assert columns == EXPECTED_COLUMNS
        indexes = {row[1] for row in conn.execute('PRAGMA index_list(ledger)')}
        assert {'idx_ledger_transaction', 'idx_ledger_display_tab'} <= indexes
        assert 'ledger' in db.LEDGER_SCHEMA_SQL
    finally:
        conn.close()


def test_uniqueness_of_transaction_id_is_enforced(tmp_path):
    conn = board_connection(tmp_path)
    try:
        migrate_to_ledger.migrate(conn, apply=True)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO ledger(entry_id,transaction_id,entry_kind,created_at)'
                         " VALUES ('card-dup','aaa','expense','2026-11-18')")
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    conn = board_connection(tmp_path)
    try:
        first = migrate_to_ledger.migrate(conn, apply=True)
        assert first['status'] == 'APPLIED'
        assert first['inserted'] == 4
        assert first['problems'] == []
        second = migrate_to_ledger.migrate(conn, apply=True)
        assert second['inserted'] == 0
        assert second['skipped_existing'] == 4
        assert second['problems'] == []
        assert conn.execute('SELECT COUNT(*) FROM ledger').fetchone()[0] == 4
    finally:
        conn.close()


def test_amount_totals_are_preserved_per_tab(tmp_path):
    conn = board_connection(tmp_path)
    try:
        def board_totals():
            out = {}
            for tab, amount in conn.execute(
                    "SELECT display_tab_id, json_extract(payload_json,'$.amount_krw')"
                    ' FROM board_rows'):
                out[tab] = out.get(tab, 0) + (amount or 0)
            return out

        before = board_totals()
        migrate_to_ledger.migrate(conn, apply=True)
        after = {(tab, kind): bucket['amount'] for (tab, kind), bucket
                 in migrate_to_ledger.totals(conn, 'ledger').items()}
        assert {(tab, 'expense'): amount for tab, amount in before.items()} == after
        assert sum(after.values()) == sum(before.values())
    finally:
        conn.close()


def test_manual_rows_migrate_with_null_transaction_id(tmp_path):
    conn = board_connection(tmp_path)
    try:
        migrate_to_ledger.migrate(conn, apply=True)
        card = conn.execute("SELECT transaction_id,trip_id FROM ledger WHERE entry_id='card-aaa'").fetchone()
        assert card == ('aaa', 'trip-A')
        manual = conn.execute(
            "SELECT transaction_id,display_tab_id FROM ledger"
            " WHERE entry_id='man-cash-klook-1'").fetchone()
        assert manual == (None, 'trip-B')
        assert conn.execute(
            'SELECT COUNT(*) FROM ledger WHERE transaction_id IS NULL').fetchone()[0] == 1
    finally:
        conn.close()


def test_committed_fields_are_carried_from_ledger_entries(tmp_path):
    conn = board_connection(tmp_path)
    try:
        migrate_to_ledger.migrate(conn, apply=True)
        row = conn.execute(
            "SELECT committed_at,batch_id FROM ledger WHERE entry_id='card-aaa'").fetchone()
        assert row == ('2026-10-07T14:48:18+00:00', 'batch-1')
        # The manual row has no ledger_entries counterpart, so it stays unbooked.
        manual = conn.execute(
            "SELECT committed_at,batch_id FROM ledger WHERE entry_id='man-cash-klook-1'").fetchone()
        assert manual == ('', '')
    finally:
        conn.close()


def test_dry_run_reverts_and_apply_keeps_ledger(tmp_path):
    conn = board_connection(tmp_path)
    try:
        preview = migrate_to_ledger.migrate(conn, apply=False)
        assert preview['status'] == 'PREVIEW'
        assert preview['inserted'] == 4
        assert preview['problems'] == []
        # Rolled back: the table is not left behind by a dry run.
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'").fetchone() is None
        applied = migrate_to_ledger.migrate(conn, apply=True)
        assert applied['ledger_total_rows'] == 4
    finally:
        conn.close()


def test_duplicate_entry_id_is_reported_not_invented(tmp_path):
    conn = board_connection(tmp_path)
    try:
        # `row_id` is the primary key of board_rows, so a duplicate can only
        # arrive with a schema that lost that constraint. Simulate that table.
        conn.execute('DROP TABLE board_rows')
        conn.execute('CREATE TABLE board_rows(row_id TEXT, row_kind TEXT, display_tab_id TEXT,'
                     ' revision INTEGER, payload_json TEXT)')
        payload = json.dumps({'amount_krw': 1, 'display_tab_id': 'trip-A'})
        for _ in range(2):
            conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
                         ('card-dup', 'expense', 'trip-A', 1, payload))
        with pytest.raises(SystemExit, match='MIGRATION_DUPLICATE_ENTRY_ID'):
            migrate_to_ledger.migrate(conn, apply=True)
    finally:
        conn.close()
