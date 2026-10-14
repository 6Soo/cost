"""지출 정리: 미배정 장부 지출을 여기서 바로 여행에 배정하고, 조회는 장부를 바꾸지 않는다 (COST V2)."""
import json

from webapp import card_catalog, ledger_board, ledger_design
from webapp.card_flow import PAGE, render_expense_cleanup
from webapp.ledger_store import LedgerStore


def unassigned_row(board, row_id='expense-cleanup-1'):
    payload = {'row_id': row_id, 'row_kind': 'expense', 'display_tab_id': None, 'revision': 1,
               'occurred_on': '2026-09-30', 'amount_krw': 12000, 'item': '', 'description': '합성 상점',
               'source_merchant': '합성 상점', 'source_kind': '수기', 'source_event_id': '', 'service_period': '',
               'reservation_no': '', 'evidence_type': '카드', 'memo': '', 'classification_state': 'confirmed',
               'confirmed_by': 'owner', 'event_kind': '', 'source_card_last4': '', 'source_approval_number': ''}
    board.conn.execute("INSERT INTO board_rows VALUES (?,?,?,?,?)",
                       (row_id, 'expense', None, 1, json.dumps(payload, ensure_ascii=False, sort_keys=True)))


def test_unassigned_expense_is_listed_and_leaves_the_list_once_assigned(tmp_path):
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        unassigned_row(board)
        trip = board.create_trip(starts_on='2026-09-28', ends_on='2026-10-01', destination='합성',
                                 client_request_id='cleanup-trip')
        html = render_expense_cleanup(board, 'token')
        assert "data-row-id='expense-cleanup-1'" in html and '합성 상점' in html
        board.save(row_id='expense-cleanup-1', expected_revision=1, client_request_id='cleanup-save',
                   change_mode='exception', changes={'display_tab_id': trip['tab_id']}, actor='owner')
        assert "data-row-id='expense-cleanup-1'" not in render_expense_cleanup(board, 'token')
    finally:
        ledger_board.bind_store(None)
        board.conn.close()


def test_browsing_the_cleanup_and_catalog_never_posts_an_auto_record():
    opening = PAGE[PAGE.index('async function loadBatch'):]
    assert 'auto-record' not in opening[:opening.index('const pollCard')]
    assert not hasattr(card_catalog, '_automatic_script')


def test_the_primary_menu_has_one_expense_cleanup_entry_and_no_rail_unassigned_section(tmp_path):
    board = LedgerStore(tmp_path / 'menu.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        nav = ledger_design._nav_html('unclassified', '')
        assert '지출 정리' in nav and '카드 검토' not in nav and '미배정 지출' not in nav
    finally:
        ledger_board.bind_store(None)
        board.conn.close()


def test_a_decision_books_only_the_decided_card_row(tmp_path, monkeypatch):
    from webapp.card_flow import CardFlow
    from webapp.tests.test_card_flow import CARD
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'decide.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        trip = board.create_trip(starts_on='2026-09-28', ends_on='2026-10-05', destination='합성', client_request_id='decide-trip')
        monkeypatch.setattr(flow, 'trip_valid', lambda target: target == trip['tab_id'])
        two_rows = CARD + '국민,1234,domestic,purchase,합성상점2,5000,,,5000,2026-10-03,2026-10-04,A124,,매입\n'.encode()
        batch = flow.pipeline.receive(two_rows, 'synthetic.csv')['batch_id']
        flow.pipeline.classify_batch(batch)
        first = flow.pipeline.get_batch(batch)['rows'][0]
        flow.pipeline.save_decision(first['transaction_id'], first['revision'], item='소모품', description='사무실 소모품',
                                    display_tab_id=trip['tab_id'], trip_id=trip['tab_id'], trip_validator=flow.trip_valid, tab_validator=flow.tab_valid, request_id='answer')
        assert flow.record_decision(batch, first['transaction_id']) == 1
        assert board.conn.execute("SELECT COUNT(*) FROM board_rows WHERE row_kind='expense'").fetchone()[0] == 1
    finally:
        board.close()
