from unittest.mock import patch
from urllib.parse import urlencode

from webapp import ledger_board as board, ledger_design, reserve_link_ui, site_shell, trip_management_ui
from webapp.ledger_store import LedgerStore


def test_trip_controls_preserve_concurrency_assignee_and_return_context(tmp_path):
    store = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=True)
    try:
        trip = store.get_trip('trip-demo-a')
        with patch.object(board, '_STORE', store), patch.object(board, 'current_role', return_value='owner'):
            html = trip_management_ui.controls(board, trip)
            nav = ledger_design.nav_region(trip['tab_id'], '')
        assert "name='expected_revision'" in html
        assert "name='assignee_form' value='1'" in html
        assert "name='expected_closed' value='0'" in html
        assert "name='return_to' value='/board?tab=trip-demo-a'" in html
        assert "href='/reserve-links'" not in nav
        assert '예약 명단·여행 연결' not in nav
        with patch.object(board, 'current_role', return_value='viewer'):
            assert trip_management_ui.controls(board, trip) == ''
            assert trip_management_ui.reservations(board, trip) == ''
    finally:
        store.close()


def test_close_returns_to_same_trip_and_preserves_ledger(tmp_path):
    store = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=True)
    try:
        tid = 'trip-demo-a'
        rows = store.list_tab_rows(tid)
        before = store.get_trip(tid)
        handler = object.__new__(board.Handler)
        locations = []
        handler.send_response = lambda code: None
        handler.send_header = lambda key, value: locations.append((key, value))
        handler.end_headers = lambda: None
        for expected, closed, back, destination in [
            ('0', '1', '/board?' + urlencode({'tab': tid}), '/board?tab=trip-demo-a'),
            ('1', '0', 'https://invalid.test/', '/trips'),
        ]:
            payload = dict(visual_closed=closed, expected_closed=expected,
                           client_request_id='close-' + closed, return_to=back)
            with patch.object(board, '_STORE', store):
                handler._handle_trip_meta(tid, lambda: payload, lambda value: None, 'application/x-www-form-urlencoded')
            assert locations[-1] == ('Location', destination)
        assert store.get_trip(tid) == before
        assert store.list_tab_rows(tid) == rows
    finally:
        store.close()


def test_embedded_editor_has_one_navigation_and_explicit_global_apply():
    document = reserve_link_ui.render_reserve_link_ui('synthetic', trip_id='trip-synthetic', embedded=True)
    assert 'var currentTrip = "trip-synthetic";' in document
    assert '전체 명단 작업' in document
    assert '전체 연결 명단 적용' in document
    assert '이 여행에 연결됨' in document
    assert site_shell.wrap_document(document, '/reserve-links?trip=trip-synthetic&embedded=1') == document
    assert 'site-topbar' not in document
    # IDs are script data, never executable script fragments supplied by a URL.
    escaped = reserve_link_ui.render_reserve_link_ui(trip_id='</script><script>alert(1)</script>')
    assert 'var currentTrip = "</script>' not in escaped
