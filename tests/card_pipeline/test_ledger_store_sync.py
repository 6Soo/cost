"""M6: LedgerStore의 화면 행 쓰기가 통합 장부(`ledger`)까지 채우는지 확인한다."""
import sqlite3

from webapp import ledger_store_schema
from webapp.ledger_store import LedgerStore


def _store(tmp_path):
    store = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    ledger_store_schema.ensure_ledger_schema(store.conn)
    return store


def _trip(store):
    return store.create_trip(starts_on='2026-06-01', destination='test-A',
                             ends_on='2026-06-05', display_key='test-A',
                             client_request_id='trip-1')['tab_id']


def _manual(store, tab, request_id='test-1'):
    return store.create_manual_expense(
        fields={'display_tab_id': tab, 'item': '식비', 'description': 't',
                'amount_krw': 5000, 'occurred_on': '2026-06-02',
                'evidence_type': '수기', 'trip_id': tab},
        client_request_id=request_id)


def test_manual_expense_writes_ledger(tmp_path):
    store = _store(tmp_path)
    try:
        tab = _trip(store)
        result = _manual(store, tab)
        row = store.conn.execute(
            'SELECT entry_id, item, display_tab_id, amount_krw FROM ledger').fetchone()
        assert row == (result['row_id'], '식비', tab, 5000)
        assert store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 1
    finally:
        store.close()


def test_ledger_holds_the_same_destination_as_the_screen_row(tmp_path):
    """payload에 trip_id 키가 없으면 display_tab_id로 채운다(계약 규칙 3)."""
    store = _store(tmp_path)
    try:
        tab = _trip(store)
        _manual(store, tab)
        import json
        payload = json.loads(store.conn.execute(
            'SELECT payload_json FROM board_rows').fetchone()[0])
        trip_id = store.conn.execute('SELECT trip_id FROM ledger').fetchone()[0]
        assert payload.get('display_tab_id') == tab
        assert trip_id == tab
    finally:
        store.close()


def test_saving_a_row_keeps_ledger_in_step(tmp_path):
    """save()로 값을 고치면 통합 장부도 같은 값을 본다."""
    store = _store(tmp_path)
    try:
        tab = _trip(store)
        result = _manual(store, tab)
        row_id = result['row_id']
        store.save(row_id=row_id, changes={'item': '교통비'},
                   expected_revision=1, change_mode='exception',
                   client_request_id='save-1')
        ledger_item = store.conn.execute(
            'SELECT item FROM ledger WHERE entry_id=?', (row_id,)).fetchone()[0]
        assert ledger_item == '교통비'
    finally:
        store.close()


def test_two_rows_write_two_ledger_rows(tmp_path):
    store = _store(tmp_path)
    try:
        tab = _trip(store)
        _manual(store, tab, 'r1')
        _manual(store, tab, 'r2')
        assert store.conn.execute('SELECT COUNT(*) FROM ledger').fetchone()[0] == 2
        assert store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 2
    finally:
        store.close()
