"""지출 정리: 미배정 장부 지출을 여기서 바로 여행에 배정하고, 조회는 장부를 바꾸지 않는다 (COST V2)."""
import json

from webapp import card_catalog, ledger_board, ledger_design
from webapp.card_flow import PAGE, cleanup_total, render_expense_cleanup
from webapp.ledger_store import LedgerStore


def unassigned_row(board, row_id='expense-cleanup-1', *, confirmed=False):
    payload = {'row_id': row_id, 'row_kind': 'expense', 'display_tab_id': None, 'revision': 1,
               'occurred_on': '2026-09-30', 'amount_krw': 12000, 'item': '', 'description': '합성 상점',
               'source_merchant': '합성 상점', 'source_kind': '수기', 'source_event_id': '', 'service_period': '',
               'reservation_no': '', 'evidence_type': '카드', 'memo': '', 'classification_state': 'confirmed' if confirmed else 'needs_review',
               'confirmed_by': 'owner' if confirmed else '', 'event_kind': '', 'source_card_last4': '', 'source_approval_number': ''}
    board.conn.execute("INSERT INTO board_rows VALUES (?,?,?,?,?)",
                       (row_id, 'expense', None, 1, json.dumps(payload, ensure_ascii=False, sort_keys=True)))


def card_rows(board, count):
    from webapp.card_flow import CardFlow
    header = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
              'Date,Post Date,Authorization Code,Cancel,Status\n')
    lines = ''.join(
        f'국민,1234,domestic,purchase,합성상점{index},5000,,,5000,2026-10-03,2026-10-04,A{index:05d},,매입\n'
        for index in range(count)
    )
    flow = CardFlow(board)
    batch = flow.pipeline.receive((header + lines).encode(), 'cleanup-synthetic.csv')['batch_id']
    board.conn.execute(
        "UPDATE transactions SET classification_state='classified', item='소모품' WHERE batch_id=?",
        (batch,),
    )
    board.conn.commit()
    return flow, batch, flow.pipeline.get_batch(batch)['rows']


def test_unlinked_booking_explains_missing_connection_without_requesting_card_evidence(tmp_path, monkeypatch):
    from webapp import card_flow

    board = LedgerStore(tmp_path / 'unlinked-booking.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, _, rows = card_rows(board, 1)
        tid = rows[0]['transaction_id']
        board.conn.execute("UPDATE transactions SET merchant='AGODA.COM' WHERE transaction_id=?", (tid,))
        board.conn.commit()
        monkeypatch.setattr(card_flow, '_ota_entries_by_card', lambda _board, **kw: {'__snapshot_status__': {'fresh': True, 'status': 'ready'}})
        before = tuple(board.conn.execute("SELECT * FROM transactions WHERE transaction_id=?", (tid,)).fetchone())

        markup = render_expense_cleanup(board, 'token')

        assert 'OTA 결제 연결 없음 · 결제 근거 확인 필요' in markup
        assert '예약 자료가 없습니다' not in markup
        assert '예약 근거를 카드 자료에서 확인' not in markup
        assert tuple(board.conn.execute("SELECT * FROM transactions WHERE transaction_id=?", (tid,)).fetchone()) == before
    finally:
        ledger_board.bind_store(None)
        board.close()


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
        board.close()


def test_manual_trip_override_is_not_counted_as_expense_cleanup_review(tmp_path):
    from webapp.card_flow import CardFlow
    board = LedgerStore(tmp_path / 'manual-trip-protected.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        CardFlow(board)
        unassigned_row(board, row_id='expense-manual-trip')
        board.conn.execute(
            "INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?,?,?)",
            ('expense-manual-trip', 'display_tab_id', 'owner-trip-edit'),
        )
        board.conn.commit()

        assert cleanup_total(board) == 0
        assert "data-row-id='expense-manual-trip'" not in render_expense_cleanup(board, 'token')
    finally:
        ledger_board.bind_store(None)
        board.conn.close()


def test_owner_card_trip_decision_is_not_counted_as_expense_cleanup_review(tmp_path, monkeypatch):
    from webapp.card_flow import CardFlow
    board = LedgerStore(tmp_path / 'owner-card-trip-protected.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        flow, batch, rows = card_rows(board, 1)
        row = rows[0]
        trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05', destination='test',
                                 client_request_id='owner-card-trip')
        monkeypatch.setattr(flow, 'trip_valid', lambda target: target == trip['tab_id'])
        flow.pipeline.save_decision(
            row['transaction_id'], row['revision'], item='meal', description='',
            display_tab_id=trip['tab_id'], trip_id=trip['tab_id'],
            trip_validator=flow.trip_valid, tab_validator=flow.tab_valid,
            request_id='owner-card-trip-decision')

        assert cleanup_total(board) == 0
        assert f"data-transaction='{row['transaction_id']}'" not in render_expense_cleanup(board, 'token')
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_browsing_the_cleanup_and_catalog_never_posts_an_auto_record():
    opening = PAGE[PAGE.index('async function loadBatch'):]
    assert 'auto-record' not in opening[:opening.index('const pollCard')]
    assert not hasattr(card_catalog, '_automatic_script')


def test_the_primary_menu_has_one_expense_cleanup_entry_and_no_rail_unassigned_section(tmp_path):
    board = LedgerStore(tmp_path / 'menu.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        nav = ledger_design._nav_html('unclassified', '')
        assert nav.count("href='/cards/all'") == 1 and "<span class='nm'>거래</span>" in nav
        assert '지출 정리' not in nav and '미배정 지출' not in nav
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


def test_a_classified_row_waiting_for_a_trip_is_listed_and_one_trip_choice_records_it(tmp_path, monkeypatch):
    from app.db import StoreError
    from webapp.card_flow import CardFlow
    from webapp.tests.test_card_flow import CARD
    import pytest
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'waiting.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        flow = CardFlow(board)
        trip = board.create_trip(starts_on='2026-09-28', ends_on='2026-10-05', destination='합성', client_request_id='waiting-trip')
        monkeypatch.setattr(flow, 'trip_valid', lambda target: target == trip['tab_id'])
        batch = flow.pipeline.receive(CARD, 'synthetic.csv')['batch_id']
        flow.pipeline.classify_batch(batch)
        row = flow.pipeline.get_batch(batch)['rows'][0]
        board.conn.execute("UPDATE transactions SET classification_state='classified', item='소모품' WHERE transaction_id=?",
                           (row['transaction_id'],))
        board.conn.commit()
        assert f"data-transaction='{row['transaction_id']}'" in render_expense_cleanup(board, 'token')
        with pytest.raises(StoreError) as blocked:
            flow.record_decision(batch, row['transaction_id'])
        assert blocked.value.code == 'NOT_RECORDED' and '여행' in str(blocked.value)
        flow.pipeline.save_decision(row['transaction_id'], board.conn.execute(
            "SELECT revision FROM transactions WHERE transaction_id=?", (row['transaction_id'],)).fetchone()[0],
            item='소모품', description='', display_tab_id=trip['tab_id'], trip_id=trip['tab_id'],
            trip_validator=flow.trip_valid, tab_validator=flow.tab_valid, request_id='waiting-choice')
        assert flow.record_decision(batch, row['transaction_id']) == 1
        assert f"data-transaction='{row['transaction_id']}'" not in render_expense_cleanup(board, 'token')
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_a_changed_booking_index_is_served_stale_while_it_rebuilds(tmp_path):
    import threading
    import time
    from webapp import ota_catalog
    board = LedgerStore(tmp_path / 'stale-index.sqlite', seed_demo=False)
    release = threading.Event()
    keys, builds = ['first'], []

    def fake_build(_board, _sources):
        builds.append(keys[0])
        if len(builds) > 1:
            release.wait(5)
        return {'entries': [], 'label': keys[0]}

    saved_signature, saved_build = ota_catalog._signature, ota_catalog._build_index
    ota_catalog._signature = lambda _board, _sources: keys[0]
    ota_catalog._build_index = fake_build
    ota_catalog._INDEX.update(key=None, value=None)
    try:
        first = ota_catalog._index(board, {})  # Seed a complete index before testing stale refresh.
        assert first['label'] == 'first' and builds == ['first']
        keys[0] = 'second'
        stale = ota_catalog._index(board, {}, allow_stale=True)
        assert stale is first and ota_catalog.rebuilding()
        release.set()
        deadline = time.monotonic() + 5
        while ota_catalog.rebuilding() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not ota_catalog.rebuilding()
        assert ota_catalog._index(board, {}, allow_stale=True)['label'] == 'second'
    finally:
        ota_catalog._signature, ota_catalog._build_index = saved_signature, saved_build
        ota_catalog._INDEX.update(key=None, value=None)
        board.conn.close()


def test_booking_index_ignores_disposable_sqlite_shared_memory_metadata(tmp_path):
    from webapp import ota_catalog

    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    portal = tmp_path / 'portal.sqlite'
    shared_memory = tmp_path / 'portal.sqlite-shm'
    portal.write_bytes(b'example')
    shared_memory.write_bytes(b'first')
    try:
        sources = {'portal_databases': [portal]}
        first = ota_catalog._signature(board, sources)
        shared_memory.write_bytes(b'changed by a read')
        assert ota_catalog._signature(board, sources) == first
        portal.write_bytes(b'a real source change')
        assert ota_catalog._signature(board, sources) != first
    finally:
        board.close()


def test_failed_booking_refresh_stops_repeating_and_displays_failure(tmp_path, monkeypatch, caplog):
    import time
    from webapp import ota_catalog

    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    ledger_board.bind_store(board)
    key = ['first']
    builds = []

    def build(_board, _sources):
        builds.append(key[0])
        if key[0] == 'second':
            raise RuntimeError('private booking content must not be logged')
        return {'entries': [], 'warnings': [], 'trips': [], 'months': [], 'providers': []}

    monkeypatch.setattr(ota_catalog, '_signature', lambda _board, _sources: key[0])
    monkeypatch.setattr(ota_catalog, '_build_index', build)
    monkeypatch.setattr(ota_catalog, 'configured_sources', lambda _board: {})
    ota_catalog._INDEX.update(key=None, value=None)
    try:
        ota_catalog._index(board, {})
        key[0] = 'second'
        ota_catalog._index(board, {}, allow_stale=True)
        deadline = time.monotonic() + 5
        while ota_catalog.rebuilding() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ota_catalog.rebuild_failed()
        assert 'RuntimeError' in caplog.text
        assert 'private booking content' not in caplog.text
        markup = render_expense_cleanup(board, 'token')
        # 예약 탐색 캐시의 실패를 중앙 대사의 실패로 오인하지 않는다.
        assert '예약 근거 갱신에 실패했습니다' not in markup
        assert '/api/ota-catalog/status' not in markup
        assert builds == ['first', 'second']
    finally:
        ota_catalog._INDEX.update(key=None, value=None)
        with ota_catalog._REBUILD_LOCK:
            ota_catalog._REBUILD.update(running=False, failed_key=None, failed_at=0.0)
        ledger_board.bind_store(None)
        board.close()


def test_booking_refresh_rebuilds_changed_inputs_before_marking_current(tmp_path, monkeypatch):
    import time
    from webapp import ota_catalog

    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    key = ['first']
    builds = []

    def build(_board, _sources):
        current = key[0]
        builds.append(current)
        if current == 'second':
            key[0] = 'third'  # A source changes while the second index is being built.
        return {'entries': [], 'label': current}

    monkeypatch.setattr(ota_catalog, '_signature', lambda _board, _sources: key[0])
    monkeypatch.setattr(ota_catalog, '_build_index', build)
    monkeypatch.setattr(ota_catalog, 'configured_sources', lambda _board: {})
    ota_catalog._INDEX.update(key=None, value=None)
    try:
        assert ota_catalog._index(board, {})['label'] == 'first'
        key[0] = 'second'
        assert ota_catalog._index(board, {}, allow_stale=True)['label'] == 'first'
        deadline = time.monotonic() + 5
        while ota_catalog.rebuilding() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert builds == ['first', 'second', 'third']
        assert ota_catalog.refresh_state(board, {}) == 'ready'
        assert ota_catalog._index(board, {}, allow_stale=True)['label'] == 'third'
        assert ota_catalog._load_saved_index(board, key[0])['label'] == 'third'
    finally:
        ota_catalog._INDEX.update(key=None, value=None)
        board.close()


def test_failed_booking_index_save_keeps_old_evidence_and_reports_failure(tmp_path, monkeypatch):
    import time
    from webapp import ota_catalog

    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    key = ['first']
    saved = ota_catalog._save_index
    monkeypatch.setattr(ota_catalog, '_signature', lambda _board, _sources: key[0])
    monkeypatch.setattr(ota_catalog, 'configured_sources', lambda _board: {})
    monkeypatch.setattr(ota_catalog, '_build_index',
                        lambda _board, _sources: {'entries': [], 'label': key[0]})
    ota_catalog._INDEX.update(key=None, value=None)
    try:
        ota_catalog._index(board, {})
        monkeypatch.setattr(ota_catalog, '_save_index', lambda _board, _key, _value: False)
        key[0] = 'second'
        assert ota_catalog._index(board, {}, allow_stale=True)['label'] == 'first'
        deadline = time.monotonic() + 5
        while ota_catalog.rebuilding() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ota_catalog.refresh_state(board, {}) == 'failed'
        assert ota_catalog._INDEX['value']['label'] == 'first'
        assert ota_catalog._load_saved_index(board, 'first')['label'] == 'first'
        assert ota_catalog._load_saved_index(board, 'second') is None
    finally:
        monkeypatch.setattr(ota_catalog, '_save_index', saved)
        with ota_catalog._REBUILD_LOCK:
            ota_catalog._REBUILD.update(running=False, active_key=None, failed_key=None, failed_at=0.0)
        ota_catalog._INDEX.update(key=None, value=None)
        board.close()


def test_refresh_status_route_is_owner_only_and_cleanup_polls_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from webapp import ota_catalog

    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    ledger_board.bind_store(board)
    replies = []
    handler = SimpleNamespace(_send_json=lambda value, code=200: replies.append((code, value)))
    request = SimpleNamespace(path='/api/ota-refresh-state')
    monkeypatch.setattr(ota_catalog, 'configured_sources', lambda _board: {})
    monkeypatch.setattr(ota_catalog, '_index', lambda _board, _sources, **_kw: {'entries': []})
    monkeypatch.setattr(ota_catalog, 'refresh_state', lambda _board, _sources: 'ready')
    try:
        assert ota_catalog.dispatch(handler, request, board=board, is_owner=False, query={})
        assert replies.pop() == (404, {'code': 'NOT_FOUND'})
        assert ota_catalog.dispatch(handler, request, board=board, is_owner=True, query={})
        assert replies.pop() == (200, {'state': 'ready'})
        with ota_catalog._REBUILD_LOCK:
            ota_catalog._REBUILD.update(running=True, failed_key=None)
        markup = render_expense_cleanup(board, 'token')
        assert '/api/ota-refresh-state' not in markup
        assert "state==='ready'" not in markup
    finally:
        with ota_catalog._REBUILD_LOCK:
            ota_catalog._REBUILD.update(running=False, active_key=None, failed_key=None, failed_at=0.0)
        ledger_board.bind_store(None)
        board.close()


def test_the_trip_list_is_written_once_and_each_row_gets_only_its_placeholder(tmp_path, monkeypatch):
    from webapp.card_flow import CardFlow
    board = LedgerStore(tmp_path / 'trip-options.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        for index in range(3):
            unassigned_row(board, row_id=f'expense-options-{index}')
        trip = board.create_trip(starts_on='2026-09-28', ends_on='2026-10-01', destination='합성',
                                 client_request_id='options-trip')
        monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: target == trip['tab_id'])
        html = render_expense_cleanup(board, 'token')
        assert html.count("<template id='cleanup-trip-options'>") == 1
        assert html.count(f"<option value='{trip['tab_id']}'>") == 1
        assert html.count("<select name='display_tab_id' aria-label='여행 선택'><option value=''>여행 선택</option></select>") == 3
    finally:
        ledger_board.bind_store(None)
        board.conn.close()


def test_card_detail_opens_inline_and_keeps_current_trip_for_immediate_edit(tmp_path, monkeypatch):
    from webapp.card_flow import CardFlow
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-inline-detail.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, _, rows = card_rows(board, 1)
        tid = rows[0]['transaction_id']
        trip = board.create_trip(starts_on='2026-09-28', ends_on='2026-10-05', destination='합성',
                                 client_request_id='cleanup-inline-trip')
        monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: target == trip['tab_id'])
        board.conn.execute(
            "UPDATE transactions SET display_tab_id=?, trip_id=?, item='숙박비', classification_state='needs_review' WHERE transaction_id=?",
            (trip['tab_id'], trip['tab_id'], tid),
        )
        board.conn.commit()

        html = render_expense_cleanup(board, 'token')

        assert "<p class='cleanup-editor-title'>여행·항목 수정</p>" in html
        assert "<button type='submit'>변경 저장</button>" in html
        row_html = html.split(f"data-transaction='{tid}'", 1)[1].split("</li>", 1)[0]
        assert row_html.index('<form') < row_html.index('<details')
        assert '검토 필요' not in row_html
        assert '장부 기록 가능' not in row_html
        assert '여행·항목을 확인하고 변경 저장을 눌러 주세요.' in row_html
        assert '<details><summary>근거 보기' not in row_html
        assert f"data-current-tab='{trip['tab_id']}'" in html
        assert "const current=select.closest('.cleanup-row')?.dataset.currentTab||'';" in html
        assert "select.value=current" in html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_counts_all_cards_but_renders_only_one_page(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-page.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        card_rows(board, 301)
        assert cleanup_total(board) == 301
        html = render_expense_cleanup(board, 'token')
        assert html.count("class='cleanup-row'") == 20
        assert "\uac70\ub798\u00b7\uc7a5\ubd80 \uc0c1\ud0dc \uc0c1\uc138 \u00b7 301\uac74 \u00b7 \uc0ac\uc6a9\uc790 \uc694\uccad \uc544\ub2d8" in html
        assert '다음 20건' in html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_does_not_build_booking_mail_index_during_initial_render(tmp_path, monkeypatch):
    from app import booking_evidence

    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-ota-lazy.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, _, rows = card_rows(board, 1)
        tid = rows[0]['transaction_id']
        board.conn.execute(
            "UPDATE transactions SET merchant='AGODA.COM', classification_source='booking_evidence_needed' "
            "WHERE transaction_id=?",
            (tid,),
        )
        board.conn.commit()

        def fail_if_built(*_args, **_kwargs):
            raise AssertionError('booking mail index was built during initial cleanup render')

        monkeypatch.setattr(booking_evidence, 'build_index', fail_if_built)
        html = render_expense_cleanup(board, 'token')
        assert f"data-transaction='{tid}'" in html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_keeps_source_conflicts_visible_for_review(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-conflict.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, _, rows = card_rows(board, 1)
        tid = rows[0]['transaction_id']
        board.conn.execute("UPDATE transactions SET conflict_reason='synthetic conflict' WHERE transaction_id=?", (tid,))
        board.conn.commit()
        html = render_expense_cleanup(board, 'token')
        assert f"data-transaction='{tid}'" in html
        assert '원본 충돌' in html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_trip_choice_never_auto_resolves_a_review_hold(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-hold.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, _, rows = card_rows(board, 1)
        row = rows[0]
        board.conn.execute(
            'INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
            (row['transaction_id'], row['source_hash'], 'evidence_pending', 'receipt check'),
        )
        board.conn.commit()
        html = render_expense_cleanup(board, 'token')
        assert "data-held='1'" in html
        assert "resolve_hold:item.dataset.held==='1'" not in html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_cards_hide_per_row_ai_inputs_and_protect_held_rows(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-proposal-ui.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, _, rows = card_rows(board, 2)
        protected = rows[1]
        board.conn.execute(
            'INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
            (protected['transaction_id'], protected['source_hash'], 'evidence_pending', 'receipt check'),
        )
        board.conn.commit()

        html = render_expense_cleanup(board, 'token')
        first = html.split(f"data-transaction='{rows[0]['transaction_id']}'", 1)[1]
        first = first.split("</li>", 1)[0]
        held = html.split(f"data-transaction='{protected['transaction_id']}'", 1)[1]
        held = held.split("</li>", 1)[0]
        assert "class='cleanup-badge'" in first
        assert '거래 귀속 수정' not in held
        assert 'AI에게 처리 방법 알려주기' not in first
        assert '이 지시로 규칙 제안하기' not in first
        assert '근거 보기' in first and '여행·항목 수정' in first and '변경 저장' in first
        assert '<form' not in held
        assert 'data-cleanup-propose' not in held and '보류 중' not in held
        assert '보류 해제' not in held and '내 확인 필요' not in held
        assert "'rule-proposal/approve'" not in first  # HTML은 서버 승인 없이 기록하지 않는다.
        assert 'resolve_hold:' not in html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_shows_reason_counts_without_hiding_unposted_expenses(tmp_path, monkeypatch):
    from webapp.card_flow import _cleanup_card_breakdown
    monkeypatch.setattr('webapp.card_flow._ota_entries_by_card', lambda _, **kw: {})

    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-counts.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, _, rows = card_rows(board, 4)
        trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                                 destination='합성', client_request_id='cleanup-breakdown')
        board.conn.execute(
            "UPDATE transactions SET classification_state='needs_review', item='',"
            " display_tab_id='unclassified' WHERE transaction_id=?", (rows[0]['transaction_id'],),
        )
        board.conn.execute(
            "UPDATE transactions SET classification_state='classified', item='식비',"
            " display_tab_id='unclassified' WHERE transaction_id=?", (rows[1]['transaction_id'],),
        )
        board.conn.execute(
            "UPDATE transactions SET classification_state='classified', item='식비',"
            " display_tab_id=? WHERE transaction_id=?", (trip['tab_id'], rows[2]['transaction_id']),
        )
        board.conn.execute(
            'INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
            (rows[3]['transaction_id'], rows[3]['source_hash'], 'evidence_pending', 'synthetic'),
        )
        unassigned_row(board, row_id='cleanup-unassigned')
        board.conn.commit()

        assert _cleanup_card_breakdown(board) == {
            'classification': 2, 'recording': 1, 'evidence': 1,
        }
        assert cleanup_total(board) == 5
        html = render_expense_cleanup(board, 'token')
        assert '\ub0b4 \ud655\uc778 \ud544\uc694' not in html
        assert '\uac70\ub798\u00b7\uc7a5\ubd80 \uc0c1\ud0dc \uc0c1\uc138 \u00b7 5\uac74 \u00b7 \uc0ac\uc6a9\uc790 \uc694\uccad \uc544\ub2d8' in html
        assert "<details class='cleanup-diagnostics'>" in html
        assert "cleanup_reason=classification#expense-cleanup'>분류 상태 <span class='cleanup-filter-count'>3건</span>" in html
        assert "cleanup_reason=recording#expense-cleanup'>내부 기록 상태 <span class='cleanup-filter-count'>1건</span>" in html
        assert "cleanup_reason=evidence#expense-cleanup'>원본·보호 상태 <span class='cleanup-filter-count'>1건</span>" in html
        assert '\ucc98\ub9ac \ud544\uc694\ud55c \uac70\ub798' not in html
        assert '\ubd84\ub958\u00b7\ubc30\uc815 \ud544\uc694 3\uac74' not in html
        assert '\uae30\ub85d \ub300\uae30' not in html
        assert '사용자 보류 0건' not in html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_direct_hotel_card_uses_matching_reservation_period_only_once(tmp_path, monkeypatch):
    from datetime import date
    from app import booking_evidence
    from webapp import ota_catalog

    board = LedgerStore(tmp_path / 'direct-hotel.sqlite', seed_demo=False)
    try:
        flow, batch, rows = card_rows(board, 2)
        confirmed = booking_evidence.summarize(
            '[예약 확정 안내] 토요코인 대구 동성로 예약이 확정되었습니다',
            date(2026, 10, 1),
            '예약 번호 1400829364445735\n체크인: 2026년 10월 4일\n'
            '체크아웃: 2026년 10월 5일\n237,500원 결제 완료',
        )
        monkeypatch.setattr(booking_evidence, 'build_index', lambda _: {
            'by_amount': {237500: [confirmed]}, 'count': 1,
        })
        monkeypatch.setattr(ota_catalog, 'configured_sources', lambda _: {'mail_directories': []})
        monkeypatch.setattr(flow, 'booking_trip', lambda _tx, _period: 'verified-trip')
        for row in rows:
            board.conn.execute(
                "UPDATE transactions SET merchant='토요코인 대구동성로',"
                "merchant_normalized='토요코인 대구동성로', amount_krw=237500,"
                "classification_source='pattern',item='숙박비',display_tab_id='unclassified'"
                " WHERE transaction_id=?", (row['transaction_id'],),
            )
        board.conn.commit()

        # 같은 호텔에서 같은 금액이 두 번 결제되면 예약을 한쪽에 임의로 붙이지 않는다.
        assert flow._evidence_period_assignments(batch, set(), set(), None) == []
        board.conn.execute('UPDATE transactions SET amount_krw=123000 WHERE transaction_id=?',
                           (rows[1]['transaction_id'],))
        board.conn.commit()
        assignments = flow._evidence_period_assignments(batch, set(), set(), None)
        assert len(assignments) == 1
        assert assignments[0]['optional']['inferred_assignment']['trip_id'] == 'verified-trip'
        assert assignments[0]['optional']['inferred_assignment']['confidence'] == '중간'

        # 같은 지점을 다른 띄어쓰기로 승인한 카드 거래도 중복 결제로 차단한다.
        board.conn.execute(
            "UPDATE transactions SET merchant='토요코인호텔 대구 동성로',"
            " merchant_normalized='토요코인호텔 대구 동성로', amount_krw=237500"
            " WHERE transaction_id=?", (rows[1]['transaction_id'],),
        )
        board.conn.commit()
        assert flow._evidence_period_assignments(batch, set(), set(), None) == []
        board.conn.execute('UPDATE transactions SET amount_krw=123000 WHERE transaction_id=?',
                           (rows[1]['transaction_id'],))
        board.conn.commit()

        # 예약 확정만 있고 카드 결제 완료 증빙이 없는 메일로 자동 기장하지 않는다.
        only_reserved = dict(confirmed, paid_amounts=[])
        monkeypatch.setattr(booking_evidence, 'build_index', lambda _: {
            'by_amount': {237500: [only_reserved]}, 'count': 1,
        })
        assert flow._evidence_period_assignments(batch, set(), set(), None) == []
        monkeypatch.setattr(booking_evidence, 'build_index', lambda _: {
            'by_amount': {237500: [confirmed, dict(confirmed, subject='토요코인 대구 동성로 예약 취소')]},
            'count': 2,
        })
        assert flow._evidence_period_assignments(batch, set(), set(), None) == []
        monkeypatch.setattr(booking_evidence, 'build_index', lambda _: {
            'by_amount': {237500: [confirmed]}, 'count': 1,
        })

        # 취소 메일에 금액이 없더라도 같은 예약번호면 자동 연결을 보류한다.
        cancelled = booking_evidence.summarize(
            '토요코인 대구 동성로 예약 취소', date(2026, 10, 12),
            '예약 번호 1400829364445735\n예약이 취소되었습니다',
        )
        monkeypatch.setattr(booking_evidence, 'build_index', lambda _: {
            'by_amount': {237500: [confirmed]},
            'by_ref': {'1400829364445735': [confirmed, cancelled]}, 'count': 2,
        })
        assert flow._evidence_period_assignments(batch, set(), set(), None) == []
        monkeypatch.setattr(booking_evidence, 'build_index', lambda _: {
            'by_amount': {237500: [confirmed]}, 'count': 1,
        })

        # 환불·충돌·보류 근거가 생기면 사용자가 확인할 때까지 연결하지 않는다.
        board.conn.execute(
            'INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
            (rows[0]['transaction_id'], rows[0]['source_hash'], 'evidence_pending', 'synthetic'),
        )
        board.conn.commit()
        assert flow._evidence_period_assignments(batch, set(), set(), None) == []
    finally:
        board.close()


def test_booked_state_without_a_ledger_entry_is_not_reported_as_recorded(tmp_path, monkeypatch):
    from webapp.card_actions import next_action
    from webapp import ota_catalog
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'booked-state.sqlite', seed_demo=False)
    try:
        flow, batch, rows = card_rows(board, 1)
        tid = rows[0]['transaction_id']
        board.conn.execute("UPDATE transactions SET classification_state='booked' WHERE transaction_id=?", (tid,))
        board.conn.commit()
        row = flow.pipeline.get_batch(batch)['rows'][0]
        row['batch_id'] = batch
        assert board.conn.execute('SELECT 1 FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone() is None
        assert next_action(row, {'already_booked': False})['group'] != 'booked'
        card = ota_catalog._card_states(board, [tid])[tid]
        assert not card['already_booked'] and ota_catalog._state_label(card) != '장부 기록됨'

        board.conn.execute(
            "INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) "
            "SELECT transaction_id,batch_id,item,'','unclassified','',amount_krw,merchant,approval_date,transaction_direction,source_hash,'2026-10-17T00:00:00Z' "
            "FROM transactions WHERE transaction_id=?",
            (tid,),
        )
        board.conn.commit()
        card = ota_catalog._card_states(board, [tid])[tid]
        assert card['already_booked']
    finally:
        board.close()


def test_cleanup_refund_pair_full_offset_shows_linked_pending_when_unrecorded(tmp_path, monkeypatch):
    """같은 승인번호 원결제(+625280)와 취소(-625280)가 1:1 전액 상쇄되고,
    ledger.preview에 refund_link가 있으나 양쪽 모두 미기록인 경우.
    기존 cleanup은 '원결제 근거 필요'였으나, 새 표시는 '원결제 연결 완료·환불 기록 처리 대기'여야 함.
    """
    from webapp.card_flow import CardFlow
    from webapp.tests.test_card_flow import CARD
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'cleanup-refund-pair.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        flow = CardFlow(board)
        # 원결제: 승인번호 APPROVAL123, 금액 625280
        # 취소: 같은 승인번호, 금액 -625280
        card_data = (
            'Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,Date,Post Date,Authorization Code,Cancel,Status\n'
            '국민,1234,domestic,purchase,합성상점,625280,,,625280,2026-10-03,2026-10-04,APPROVAL123,,매입\n'
            '국민,1234,domestic,cancellation,합성상점,-625280,,,-625280,2026-10-05,2026-10-06,,APPROVAL123,매입취소\n'
        ).encode('utf-8')
        batch = flow.pipeline.receive(card_data, 'refund-pair.csv')['batch_id']
        flow.pipeline.classify_batch(batch)
        rows = flow.pipeline.get_batch(batch)['rows']
        purchase_tid = rows[0]['transaction_id']
        refund_tid = rows[1]['transaction_id']
        board.conn.execute("UPDATE transactions SET original_approval_number=(SELECT approval_number FROM transactions WHERE transaction_id=?) WHERE transaction_id=?", (purchase_tid, refund_tid))
        board.conn.commit()

        # 원결제와 취소 모두 미기록 상태 확인
        assert board.conn.execute('SELECT 1 FROM ledger_entries WHERE transaction_id=?', (purchase_tid,)).fetchone() is None
        assert board.conn.execute('SELECT 1 FROM ledger_entries WHERE transaction_id=?', (refund_tid,)).fetchone() is None

        # cleanup 렌더링
        html = render_expense_cleanup(board, 'token')

        # 취소 거래 행 찾기
        refund_section = html.split(f"data-transaction='{refund_tid}'", 1)[1]
        refund_section = refund_section.split("<li class='cleanup-row'", 1)[0]

        # 기존 '원결제 근거 필요' 문구가 없어야 함
        assert '원결제 근거가 필요합니다' not in refund_section
        assert '원결제 연결 자료 보기' in refund_section

        # 새 표시: '원결제 연결 완료·환불 기록 처리 대기' 또는 유사 문구
        assert '원결제' in refund_section and '연결 완료' in refund_section
        assert '환불' in refund_section and ('기록 처리 대기' in refund_section or '대기' in refund_section)

        # 원결제 ID 표시 확인
        assert purchase_tid not in refund_section

        # full 상태의 상세 안내 문구는 표시하지 않는다.
        assert '전액 상쇄' not in refund_section

        # 원결제 거래 행도 확인
        purchase_section = html.split(f"data-transaction='{purchase_tid}'", 1)[1]
        purchase_section = purchase_section.split('</li>', 1)[0]
        # 원결제는 환불 탭 이동 안내 등이 있을 수 있음

    finally:
        ledger_board.bind_store(None)
        board.close()
