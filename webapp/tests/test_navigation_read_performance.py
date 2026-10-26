"""Synthetic read performance contracts also preserve financial guard results."""
import json
import threading
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD


@pytest.mark.parametrize('fresh', [False, True])
def test_display_state_metadata_never_runs_legacy_during_snapshot_refresh(tmp_path, monkeypatch, fresh):
    from webapp import ota_payment_review
    board = LedgerStore(tmp_path / 'state-read.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
        monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: ({'data': {}}, fresh))
        report = {'matches': [], 'type_only_candidates': []}
        projections = []
        monkeypatch.setattr(flow, '_canonical_snapshot_report', lambda value: (projections.append(value), report)[1])
        legacy = []
        monkeypatch.setattr(flow, '_ota_report', lambda: (legacy.append(1), report)[1])
        row = {'merchant': 'AGODA', 'transaction_direction': 'purchase', 'source_hash': 'synthetic',
               'transaction_id': 'synthetic', 'item': '숙박비'}
        before = list(board.conn.iterdump())
        callback = flow.preview_metadata(display_only=True)
        assert callback(row) == {'booking_ref': '', 'service_period': '', 'ota_evidence': {}}
        callback(row)
        assert not legacy and len(projections) == int(fresh)
        # Real commit/default metadata retains its existing strict validation path.
        flow.preview_metadata()(row)
        assert legacy == [1]
        assert list(board.conn.iterdump()) == before
    finally:
        board.close()


def test_batch_state_selects_display_metadata_without_legacy_fallback(tmp_path, monkeypatch):
    from webapp import ota_payment_review
    board = LedgerStore(tmp_path / 'state-route.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive(CARD.replace('합성상점'.encode(), b'AGODA'), 'synthetic.csv')['batch_id']
        monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
        monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: (None, False))
        monkeypatch.setattr(flow, 'ota_group_holds', lambda: {})
        monkeypatch.setattr(flow, '_compute_ota_report', lambda: (_ for _ in ()).throw(AssertionError('legacy foreground work')))
        before = list(board.conn.iterdump())
        result = flow.state(batch)
        assert result['ota_reconciliation']['status'] == 'loading'
        assert result['rows'] and all(row['ota_link_status'] == 'UNKNOWN' for row in result['rows'])
        assert list(board.conn.iterdump()) == before
    finally:
        board.close()


def test_board_income_and_expense_share_tab_reads_only_within_render(tmp_path, monkeypatch):
    from webapp import ledger_board, read_scope
    store = LedgerStore(tmp_path / 'board-display.sqlite', seed_demo=True)
    previous = ledger_board._STORE
    ledger_board.bind_store(store)
    try:
        tabs = ledger_board._all_tab_ids() + [None]
        expected = ledger_board._with_display_amount([dict(r) for tab in tabs for r in store.list_tab_rows(tab)])
        original = store.list_tab_rows
        calls = []
        monkeypatch.setattr(store, 'list_tab_rows', lambda tab: (calls.append(tab), original(tab))[1])
        before = list(store.conn.iterdump())
        @read_scope.scoped
        def render():
            return ledger_board._income_rows(), ledger_board._expense_rows()
        income, expense = render()
        assert income == [r for r in expected if r['row_kind'] == 'income']
        assert expense == [r for r in expected if r['row_kind'] == 'expense']
        assert calls == tabs
        assert list(store.conn.iterdump()) == before
        row_id = expense[0]['row_id']
        store.conn.execute('UPDATE board_rows SET revision=revision+1 WHERE row_id=?', (row_id,))
        _, fresh = render()
        assert next(r for r in fresh if r['row_id'] == row_id)['revision'] == expense[0]['revision'] + 1
        assert calls == tabs + tabs
    finally:
        ledger_board.bind_store(previous)
        store.close()


def test_cleanup_reuses_trip_validation_and_revalidates_next_render(tmp_path, monkeypatch):
    from webapp import card_flow, ledger_board
    from app import Pipeline
    store = LedgerStore(tmp_path / 'cleanup-validation.sqlite', seed_demo=False)
    previous = ledger_board._STORE
    ledger_board.bind_store(store)
    try:
        flow = CardFlow(store)
        flow.pipeline.receive(CARD, 'synthetic.csv')
        valid = [True]
        checks, observed = [], []
        def trip_valid(self, trip):
            checks.append(trip)
            return valid[0]
        def preview(self, batch_id, **options):
            observed.append([options['trip_validator']('synthetic-trip') for _ in range(8)])
            observed.append([options['tab_validator']('synthetic-trip') for _ in range(8)])
            return {'rows': []}
        monkeypatch.setattr(CardFlow, 'trip_valid', trip_valid)
        monkeypatch.setattr(Pipeline, 'preview', preview)
        monkeypatch.setattr(CardFlow, 'ota_group_holds', lambda _: {})
        monkeypatch.setattr(card_flow, '_ota_entries_by_card', lambda _: {})
        before = list(store.conn.iterdump())
        card_flow.render_expense_cleanup(store, 'synthetic')
        assert observed == [[True] * 8, [True] * 8]
        assert checks == ['synthetic-trip'] * 2
        valid[0] = False
        card_flow.render_expense_cleanup(store, 'synthetic')
        assert observed[2:] == [[False] * 8, [False] * 8]
        assert checks == ['synthetic-trip'] * 4
        assert list(store.conn.iterdump()) == before
    finally:
        ledger_board.bind_store(previous)
        store.close()


def test_catalog_during_central_refresh_never_runs_legacy_reconciliation(monkeypatch):
    from webapp import ota_catalog, ota_payment_review
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    for current in (None, {'data': {'events': [], 'transactions': []}}):
        flow = SimpleNamespace(board=object(), _ota_report=lambda: (_ for _ in ()).throw(
            AssertionError('page GET must not recompute reconciliation')))
        monkeypatch.setattr(ota_payment_review, 'snapshot_service', lambda _: SimpleNamespace(held=lambda: (current, False)))
        assert ota_catalog._card_matches(flow) == ({}, {}, True)


def test_runtime_catalog_build_isolates_source_parsing(monkeypatch):
    from webapp import ota_catalog
    board = SimpleNamespace(_catalog_source_process=True)
    monkeypatch.setattr(ota_catalog, '_rows_from_sources', lambda *_: (_ for _ in ()).throw(
        AssertionError('runtime must not parse mail in the HTTP process')))
    monkeypatch.setattr(ota_catalog, '_source_rows_in_child', lambda *_: (_ for _ in ()).throw(
        RuntimeError('isolated-source-worker')), raising=False)
    with pytest.raises(RuntimeError, match='isolated-source-worker'):
        ota_catalog._build_index(board, {})


@pytest.mark.parametrize('central', [True, False])
def test_central_mode_does_not_prewarm_unused_legacy_mail_index(monkeypatch, central):
    from app import booking_evidence
    from webapp import card_flow, ota_catalog, ota_payment_review
    calls = []
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: central)
    monkeypatch.setattr(ota_catalog, 'configured_sources', lambda _: {'mail_directories': []})
    monkeypatch.setattr(booking_evidence, 'build_index', lambda _: calls.append(1))
    card_flow.prewarm_booking_evidence(object())
    assert calls == ([] if central else [1])


def test_catalog_source_child_matches_direct_read_and_preserves_databases(tmp_path):
    import sqlite3
    from webapp import ota_catalog
    store = LedgerStore(tmp_path / 'board.sqlite', seed_demo=True)
    portal = sqlite3.connect(tmp_path / 'portal.sqlite')
    try:
        portal.execute('CREATE TABLE bookings(id,provider,booking_number,product_type,label,service_start_on,service_end_on,status)')
        portal.execute("INSERT INTO bookings VALUES (1,'trip','SYNTHETIC-BOOKING','lodging','synthetic','2026-10-01','2026-10-03','confirmed')")
        portal.commit()
        sources = {'portal_databases': [str(tmp_path / 'portal.sqlite')], 'mail_directories': []}
        expected_warnings, actual_warnings = [], []
        expected = ota_catalog._rows_from_sources(store, sources, expected_warnings)
        before_board, before_portal = list(store.conn.iterdump()), list(portal.iterdump())
        actual = ota_catalog._source_rows_in_child(store, sources, actual_warnings)
        assert actual == expected and actual
        assert actual_warnings == expected_warnings
        assert list(store.conn.iterdump()) == before_board
        assert list(portal.iterdump()) == before_portal
        assert list(tmp_path.glob('ota-catalog-worker-*')) == []
    finally:
        portal.close()
        store.close()


def test_catalog_source_timeout_stops_its_child_and_cleans_exchange(tmp_path, monkeypatch):
    import subprocess
    from webapp import ota_catalog, ota_payment_review
    stopped = []
    def communicate(**_):
        raise subprocess.TimeoutExpired('synthetic-child', 900)
    process = SimpleNamespace(pid=123456, communicate=communicate, wait=lambda: stopped.append('wait'))
    monkeypatch.setattr(subprocess, 'Popen', lambda *_, **__: process)
    monkeypatch.setattr(ota_payment_review, '_stop_process_tree', lambda pid: stopped.append(pid))
    with pytest.raises(RuntimeError, match='OTA_CATALOG_SOURCE_TIMEOUT'):
        ota_catalog._source_rows_in_child(SimpleNamespace(path=tmp_path / 'board.sqlite'), {}, [])
    assert stopped == [123456, 'wait']
    assert list(tmp_path.glob('ota-catalog-worker-*')) == []


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
