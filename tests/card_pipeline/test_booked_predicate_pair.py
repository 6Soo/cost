"""기장 판정 짝(pair) 회귀 — 네 가지 저장소 상태에서 '기장됨' 판정이 뒤집히지 않는지.

`ledger`(새 정본) · `ledger_entries`(기장 영수증) · `board_rows`(화면 행)는 같은
사실을 세 곳에 적는다. 판정 함수가 셋 중 하나만 읽으면 `ledger`에만 행이 있는
상태에서 기장된 거래가 '미기장'으로 뒤집히고, 완료기간 보호가 풀려 재분류된다.

네 케이스:
1. 정상 이중 쓰기 — 셋이 모두 있다(보완 전후 판정이 같아야 한다)
2. `ledger_entries`만 — 이관 전 상태(보완 전후 판정이 같아야 한다)
3. `ledger`만 — **결함 상태** (보완 없으면 실패해야 한다)
4. `ledger` 테이블 없음 — main 모양(오류 없이 기존 동작)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from app import closed_period
from app.db import SCHEMA_SQL, LEDGER_SCHEMA_SQL


# 완료 여행(보호 대상)과 진행 중 여행(재배정 목적지)을 함께 둔다.
COMPLETED_TRIP = dict(trip_id='0118_호남', starts_on='2026-01-18', ends_on='2026-02-20')
OPEN_TRIP = dict(trip_id='0701_오사카', starts_on='2026-07-01', ends_on='2026-07-31')
TRIPS = [COMPLETED_TRIP, OPEN_TRIP]


def _ledger_sql(entry_id: str, txid: str, *, tab: str, amount: int, item: str) -> tuple:
    """`ledger` 한 행. 계약 규칙 1: `entry_id`는 기존 row_id 규칙(`card-<txid>`)."""
    return (entry_id, txid, 'expense', item, '', amount, '2025-03-14', tab,
            tab, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '',
            '', '', '', '', '', 1, '2025-04-01T00:00:00Z', 'batch-1',
            '2025-04-01T00:00:00Z')


def _insert_ledger(conn, entry_id, txid, *, tab, amount, item):
    conn.execute(
        'INSERT INTO ledger(entry_id,transaction_id,entry_kind,item,description,amount_krw,'
        'occurred_on,display_tab_id,trip_id,service_period,reservation_no,evidence_type,'
        'source_kind,source_event_id,source_fact_digest,source_merchant,source_issuer,'
        'source_card_last4,source_approval_number,source_approval_date,source_posting_date,'
        'source_local_amount,source_currency,event_kind,classification_state,'
        'classification_source,classification_basis,confirmed_by,memo,operator_note,revision,'
        'committed_at,batch_id,created_at)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        _ledger_sql(entry_id, txid, tab=tab, amount=amount, item=item))


def _put_transaction(conn, txid: str, *, item: str, amount: int, day: str, row_index: int):
    conn.execute(
        'INSERT INTO transactions(transaction_id,source_hash,batch_id,issuer,card_tail,'
        'card_kind,transaction_direction,transaction_kind,approval_number,'
        'original_approval_number,approval_date,posting_date,merchant,merchant_normalized,'
        'amount_krw,foreign_amount,foreign_currency,description_raw,row_index,raw_row_json,'
        'duplicate_of,conflict_reason,parse_error,classification_state,classification_source,'
        'classification_basis,item,description,display_tab_id,trip_id,revision,decided_at,'
        'created_at)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (txid, 'hash-' + txid, 'batch-1', 'SYN', '3821', 'credit', 'purchase', '승인',
         'AP-' + txid, '', day, day, 'SYNTHETIC HOTEL', 'synthetic hotel', amount, '', '',
         '', row_index, '{}', None, '', '', 'classified', 'inference', '합성 기준선',
         item, '', '0118_호남', '0118_호남', 1, None, day + 'T00:00:00Z'))


def _base_db(tmp_path, *, with_ledger_table: bool = True):
    """거래 1건을 만들고, 저장소 세 곳은 테스트가 직접 채우게 비워 둔다."""
    conn = sqlite3.connect(tmp_path / 'judge.sqlite', isolation_level=None)
    from webapp.ledger_store_schema import SCHEMA_SQL as BOARD_SCHEMA_SQL
    conn.executescript(SCHEMA_SQL)             # transactions, ledger_entries
    conn.executescript(BOARD_SCHEMA_SQL)       # board_rows, board_revisions
    if with_ledger_table:
        conn.executescript(LEDGER_SCHEMA_SQL)
    _put_transaction(conn, 't1', item='숙박비', amount=25000, day='2025-03-14', row_index=1)
    return conn


def _put_board(conn, txid='t1'):
    payload = {'row_id': 'card-' + txid, 'row_kind': 'expense', 'display_tab_id': '0118_호남',
               'revision': 1, 'item': '숙박비', 'description': '', 'amount_krw': 25000,
               'occurred_on': '2025-03-14', 'trip_id': '0118_호남',
               'classification_state': 'classified', 'classification_source': 'inference',
               'confirmed_by': 'automatic'}
    conn.execute('INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)'
                 ' VALUES (?,?,?,?,?)',
                 ('card-' + txid, 'expense', '0118_호남', 1,
                  json.dumps(payload, ensure_ascii=False)))


def _put_entries(conn, txid='t1'):
    conn.execute(
        'INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,'
        'trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at)'
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (txid, 'batch-1', '숙박비', '', '0118_호남', '0118_호남', 25000,
         'SYNTHETIC HOTEL', '2025-03-14', 'purchase', 'hash-' + txid,
         '2025-04-01T00:00:00Z'))


def _recorded(conn, txid='t1') -> bool:
    """`plan`이 쓰는 기장 술어와 같은 식으로 판정한다."""
    from app.automatic_classification import _context
    rows, decisions, holds, excluded, overrides, ledger, boards = _context(conn)
    row = next(r for r in rows if r['transaction_id'] == txid)
    return txid in ledger or 'card-' + txid in boards


def _protected(conn, txid='t1') -> bool:
    """plan()의 첫 보호 분기를 그대로 계산한다."""
    from app.automatic_classification import _context
    rows, decisions, holds, excluded, overrides, ledger, boards = _context(conn)
    row = next(r for r in rows if r['transaction_id'] == txid)
    recorded = txid in ledger or 'card-' + txid in boards
    completed = closed_period.excluded(row, TRIPS, manual=txid in decisions)
    recoverable = closed_period.recoverable_unrecorded_booking(
        row, TRIPS, recorded=recorded, manual=txid in decisions)
    return bool(completed and not recoverable)


# ---- 케이스 1: 정상 이중 쓰기 (ledger + ledger_entries + board_rows)
def test_dual_write_is_recorded_and_protected(tmp_path):
    conn = _base_db(tmp_path)
    try:
        _put_board(conn)
        _put_entries(conn)
        _insert_ledger(conn, 'card-t1', 't1', tab='0118_호남', amount=25000, item='숙박비')
        assert _recorded(conn) is True
        assert _protected(conn) is True
    finally:
        conn.close()


# ---- 케이스 2: ledger_entries만 (이관 전 상태)
def test_entries_only_is_recorded_and_protected(tmp_path):
    conn = _base_db(tmp_path)
    try:
        _put_entries(conn)
        assert _recorded(conn) is True
        assert _protected(conn) is True
    finally:
        conn.close()


# ---- 케이스 3: ledger만 (보완이 없으면 실패한다)
def test_ledger_only_is_recorded_and_protected(tmp_path):
    conn = _base_db(tmp_path)
    try:
        _insert_ledger(conn, 'card-t1', 't1', tab='0118_호남', amount=25000, item='숙박비')
        assert _recorded(conn) is True, 'ledger에만 있는 기장 거래를 미기장으로 판정했다'
        assert _protected(conn) is True, '완료기간 보호가 풀렸다'
    finally:
        conn.close()


def test_ledger_only_is_not_a_reclassification_target(tmp_path):
    """`plan`의 재분류 대상에 그 거래가 들어가지 않아야 한다."""
    from app.automatic_classification import plan
    conn = _base_db(tmp_path)
    try:
        _insert_ledger(conn, 'card-t1', 't1', tab='0118_호남', amount=25000, item='숙박비')
        result = plan(conn, TRIPS)
        assert 't1' not in [t['id'] for t in result['targets']]
        assert result['summary']['protected'] == 1
    finally:
        conn.close()


# ---- 케이스 4: ledger 테이블 없음 (main 모양)
def test_without_ledger_table_keeps_existing_behaviour(tmp_path):
    conn = _base_db(tmp_path, with_ledger_table=False)
    try:
        _put_entries(conn)
        # `ledger_records`는 테이블이 없으면 빈 집합이다(오류 아님).
        assert closed_period.ledger_records(conn) == set()
        assert _recorded(conn) is True
        assert _protected(conn) is True
        from app.automatic_classification import plan
        assert plan(conn, TRIPS)['summary']['to_classify'] == 0
    finally:
        conn.close()


def test_without_ledger_table_and_without_any_store_is_unrecorded(tmp_path):
    """세 저장소가 모두 없으면 미기장이 맞다 — 빈 값을 '기장됨'으로 읽지 않는다."""
    conn = _base_db(tmp_path, with_ledger_table=False)
    try:
        assert closed_period.ledger_records(conn) == set()
        assert _recorded(conn) is False
    finally:
        conn.close()


# ---- 이관: ledger_entries 전용 행이 ledger로 넘어가고 손실이 보고된다
def test_migration_carries_entries_without_board_rows(tmp_path):
    conn = _base_db(tmp_path, with_ledger_table=False)
    try:
        _put_entries(conn, 't1')
        _put_transaction(conn, 't2', item='교통비', amount=7000, day='2025-03-15', row_index=2)
        _put_entries(conn, 't2')
        before_entries = conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
        from tools import migrate_to_ledger as mig
        result = mig.migrate(conn, apply=True)
        assert result['problems'] == [], result['problems']
        assert result['entries_without_board_row'] == 2
        # 옛 두 저장소의 기장 거래가 전부 ledger에 있다.
        in_ledger = {r[0] for r in conn.execute(
            'SELECT transaction_id FROM ledger WHERE transaction_id IS NOT NULL')}
        assert {'t1', 't2'} <= in_ledger
        assert before_entries == 2
        # 옛 테이블은 그대로다.
        assert conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 0
    finally:
        conn.close()


def test_compare_sources_reports_a_lost_entry_row(tmp_path):
    """`ledger`에서 한 행을 지우면 `compare_sources`가 그 손실을 보고해야 한다."""
    conn = _base_db(tmp_path, with_ledger_table=False)
    try:
        _put_entries(conn)
        from tools import migrate_to_ledger as mig
        mig.migrate(conn, apply=True)
        assert mig.compare_sources(conn) == []
        conn.execute("DELETE FROM ledger WHERE transaction_id='t1'")
        problems = mig.compare_sources(conn)
        assert problems and problems[0].startswith('SOURCE_ROWS_NOT_IN_LEDGER')
    finally:
        conn.close()
