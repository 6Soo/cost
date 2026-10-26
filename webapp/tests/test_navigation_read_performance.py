"""Synthetic read performance contracts also preserve financial guard results."""
import json
import threading
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD


def test_catalog_during_central_refresh_never_runs_legacy_reconciliation(monkeypatch):
    from webapp import ota_catalog, ota_payment_review
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    for current in (None, {'data': {'events': [], 'transactions': []}}):
        flow = SimpleNamespace(board=object(), _ota_report=lambda: (_ for _ in ()).throw(
            AssertionError('page GET must not recompute reconciliation')))
        monkeypatch.setattr(ota_payment_review, 'snapshot_service', lambda _: SimpleNamespace(held=lambda: (current, False)))
        assert ota_catalog._card_matches(flow) == ({}, {}, True)


def test_catalog_page_without_saved_index_returns_loading_without_rebuilding_inline(tmp_path, monkeypatch):
    from webapp import ota_catalog
    board = SimpleNamespace(path=tmp_path / 'board.sqlite')
    monkeypatch.setattr(ota_catalog, '_INDEX', {'key': None, 'value': None})
    monkeypatch.setattr(ota_catalog, '_signature', lambda *_: 'new-key')
    monkeypatch.setattr(ota_catalog, '_saved_value_for_stale', lambda _: None)
    monkeypatch.setattr(ota_catalog, '_load_saved_index', lambda *_: None)
    monkeypatch.setattr(ota_catalog, '_build_index', lambda *_: (_ for _ in ()).throw(
        AssertionError('page must not build the index inline')))
    requests = []
    monkeypatch.setattr(ota_catalog, '_start_rebuild', lambda *args: requests.append(args))
    data = ota_catalog.catalog(board, {}, sources={}, allow_stale=True)
    html = ota_catalog.render_html(data, {})
    assert requests and data['refresh_state'] != 'ready'
    assert '불러오는 중' in html and '조회된 OTA 예약이 없습니다' not in html


@pytest.mark.parametrize('phase', ['build', 'save'])
def test_catalog_display_does_not_wait_for_startup_prewarm_cache_lock(tmp_path, monkeypatch, phase):
    from webapp import ota_catalog
    board = SimpleNamespace(path=tmp_path / 'board.sqlite')
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(ota_catalog, '_INDEX', {'key': None, 'value': None})
    monkeypatch.setattr(ota_catalog, '_signature', lambda *_: 'key')
    monkeypatch.setattr(ota_catalog, '_load_saved_index', lambda *_: None)
    monkeypatch.setattr(ota_catalog, '_saved_value_for_stale', lambda _: None)
    monkeypatch.setattr(ota_catalog, '_save_index', lambda *_: True)
    monkeypatch.setattr(ota_catalog, '_start_rebuild', lambda *_: None)
    def block():
        entered.set()
        release.wait(5)
    def build(*_):
        if phase == 'build':
            block()
        return {'entries': [], 'warnings': [], 'trips': [], 'months': [], 'providers': []}
    def save(*_):
        if phase == 'save':
            block()
        return True
    monkeypatch.setattr(ota_catalog, '_build_index', build)
    monkeypatch.setattr(ota_catalog, '_save_index', save)
    prewarm = threading.Thread(target=lambda: ota_catalog._index(board, {}, rebuild=True))
    display = threading.Thread(target=lambda: (ota_catalog._index(board, {}, allow_stale=True), returned.set()))
    prewarm.start()
    try:
        assert entered.wait(2)
        display.start()
        assert returned.wait(2), f'read-only display queued behind startup index {phase}'
    finally:
        release.set()
        prewarm.join(5)
        if display.ident is not None:
            display.join(5)


def test_automatic_holds_reads_projection_once_and_next_call_observes_new_ledger(tmp_path):
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive(CARD + CARD.splitlines(keepends=True)[1].replace(b'A123', b'A124') +
                                      CARD.splitlines(keepends=True)[1].replace(b'A123', b'A125'), 'synthetic.csv')['batch_id']
        rows = flow.pipeline.get_batch(batch)['rows']
        first = rows[0]['transaction_id']
        source = board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        queries = []
        board.conn.set_trace_callback(queries.append)
        with patch.object(flow, 'ota_group_holds', return_value={}):
            before = flow.automatic_holds(batch)
            assert all(h['kind'] != 'existing_ledger' for h in before.values())
            payload = json.dumps({'source_event_id': first})
            board.conn.execute("INSERT INTO board_rows VALUES ('synthetic-projected','expense','',1,?)", (payload,))
            changes = board.conn.total_changes
            after = flow.automatic_holds(batch)
        board.conn.set_trace_callback(None)
        assert after[first]['kind'] == 'existing_ledger'
        assert all(h['kind'] != 'existing_ledger' for tid, h in after.items() if tid != first)
        assert board.conn.total_changes == changes
        assert board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == source
        scans = [q for q in queries if 'SUM(revision)' in q and 'FROM board_rows' in q]
        assert len(scans) == 2  # One snapshot per call, with fresh next-call state.
    finally:
        board.close()


def test_cleanup_shares_unlinked_refund_count_check_for_the_display(tmp_path, monkeypatch):
    from app import partial_refund
    from webapp import card_flow, ledger_board
    board = LedgerStore(tmp_path / 'refund-display.sqlite', seed_demo=False)
    old_store = ledger_board._STORE
    ledger_board.bind_store(board)
    try:
        flow = CardFlow(board)
        flow.pipeline.receive(CARD + CARD.splitlines(keepends=True)[1].replace(b'A123', b'A124'), 'refunds.csv')
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-37000")
        monkeypatch.setattr(card_flow, '_ota_entries_by_card', lambda _: {})
        monkeypatch.setattr(CardFlow, 'ota_group_holds', lambda _: {})
        checks = []
        original = partial_refund.count_held_cancellations
        monkeypatch.setattr(partial_refund, 'count_held_cancellations', lambda conn: (checks.append(1), original(conn))[1])
        before = board.conn.total_changes
        markup = card_flow.render_expense_cleanup(board, 'synthetic')
        assert markup.count('확정 원결제 자료 미확인') == 2
        assert board.conn.total_changes == before
        assert len(checks) == 2  # One batch guard and one shared display check.
    finally:
        ledger_board.bind_store(old_store)
        board.close()
