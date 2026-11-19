"""M6 교정 경로가 통합 장부(`ledger`)까지 고치는지 확인한다.

호남 drift의 원인은 화면 행(board_rows)만 고치고 기장 기록(ledger_entries)이
따라가지 않는 경로였다. 이 검사는 교정·되돌리기·멱등·미이관 DB를 모두 덮는다.
"""
import sqlite3

from app.db import LEDGER_SCHEMA_SQL, SCHEMA_SQL
from app.ledger import sync_ledger_row, write_ledger_row


def _conn(*, with_ledger: bool = True):
    conn = sqlite3.connect(':memory:')
    conn.executescript(SCHEMA_SQL)
    if with_ledger:
        conn.executescript(LEDGER_SCHEMA_SQL)
    return conn


def _book(conn, tid='tx1', tab='trip-A', item='숙박비'):
    conn.execute(
        "INSERT INTO ledger_entries(transaction_id,batch_id,item,description,"
        "display_tab_id,trip_id,amount_krw,merchant,occurred_on,"
        "transaction_direction,source_hash,committed_at) "
        "VALUES (?,?,?,?,'trip-A','trip-A',1000,'m','2026-01-01',"
        "'purchase','h','2026-01-01')", (tid, 'b1', item, ''))
    write_ledger_row(conn, tid, {'item': item, 'description': '',
                                 'display_tab_id': tab, 'trip_id': tab,
                                 'amount_krw': 1000, 'merchant': 'm',
                                 'occurred_on': '2026-01-01'},
                     now='2026-01-01', batch='b1')


def test_booking_writes_ledger():
    conn = _conn()
    _book(conn)
    assert conn.execute(
        "SELECT item,display_tab_id FROM ledger WHERE transaction_id='tx1'"
    ).fetchone() == ('숙박비', 'trip-A')


def test_correction_updates_ledger_alongside_old_tables():
    conn = _conn()
    _book(conn)
    conn.execute("UPDATE ledger_entries SET item='식비',display_tab_id='trip-B',"
                 "trip_id='trip-B' WHERE transaction_id='tx1'")
    sync_ledger_row(conn, 'tx1', item='식비',
                    display_tab_id='trip-B', trip_id='trip-B')
    ledger = conn.execute(
        "SELECT item,display_tab_id FROM ledger WHERE transaction_id='tx1'").fetchone()
    entry = conn.execute(
        "SELECT item,display_tab_id FROM ledger_entries WHERE transaction_id='tx1'").fetchone()
    assert ledger == entry == ('식비', 'trip-B')


def test_revert_restores_ledger():
    conn = _conn()
    _book(conn)
    sync_ledger_row(conn, 'tx1', item='식비', display_tab_id='trip-B', trip_id='trip-B')
    sync_ledger_row(conn, 'tx1', item='숙박비', display_tab_id='trip-A', trip_id='trip-A')
    assert conn.execute(
        "SELECT item,display_tab_id FROM ledger WHERE transaction_id='tx1'"
    ).fetchone() == ('숙박비', 'trip-A')


def test_duplicate_booking_does_not_add_a_second_row():
    conn = _conn()
    _book(conn)
    write_ledger_row(conn, 'tx1', {'item': 'x', 'amount_krw': 999}, now='2026-01-02')
    assert conn.execute(
        "SELECT COUNT(*) FROM ledger WHERE transaction_id='tx1'").fetchone()[0] == 1


def test_sync_ignores_partial_arguments():
    """넘기지 않은 컬럼은 건드리지 않는다."""
    conn = _conn()
    _book(conn)
    sync_ledger_row(conn, 'tx1', item='식비')
    row = conn.execute(
        "SELECT item,display_tab_id FROM ledger WHERE transaction_id='tx1'").fetchone()
    assert row == ('식비', 'trip-A')


def test_pre_migration_database_skips_dual_write():
    """이관 전 DB에는 통합 장부가 없다. 예외 없이 기존 기장만 남아야 한다."""
    conn = _conn(with_ledger=False)
    _book(conn)
    sync_ledger_row(conn, 'tx1', item='식비')
    assert conn.execute(
        "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id='tx1'").fetchone()[0] == 1
