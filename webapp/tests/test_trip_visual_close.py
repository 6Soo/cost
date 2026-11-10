from unittest.mock import patch

import pytest

from webapp import ledger_board, ledger_design, ui_icons
from webapp.ledger_store import LedgerStore, SaveError


def test_close_is_durable_reversible_and_does_not_change_ledger(tmp_path):
    path = tmp_path / 'board.sqlite'
    store = LedgerStore(path, seed_demo=True)
    try:
        before = store.get_trip('trip-demo-a')
        rows = store.list_tab_rows('trip-demo-a')
        events = len(store.ledger.all_events())
        args = dict(tab_id='trip-demo-a', expected_closed=False, closed=True,
                    client_request_id='visual-close-1')
        store.save_trip_visual_close(**args)
        store.save_trip_visual_close(**args)
        assert store.get_trip('trip-demo-a') == before
        assert store.list_tab_rows('trip-demo-a') == rows
        assert len(store.ledger.all_events()) == events
        assert next(t for t in store.list_trips() if t['tab_id'] == 'trip-demo-a')['visual_closed']
        with pytest.raises(SaveError, match='마감 표시가 변경'):
            store.save_trip_visual_close(**{**args, 'client_request_id': 'stale'})
        with pytest.raises(SaveError):
            store.save_trip_visual_close(**{**args, 'closed': False})
        assert store.conn.execute("SELECT count(*) FROM trip_tab_history WHERE change_kind='visual_close'").fetchone()[0] == 1
    finally:
        store.close()
    store = LedgerStore(path, seed_demo=True)
    try:
        assert store.trip_visual_close_states()['trip-demo-a']
        store.save_trip_visual_close(tab_id='trip-demo-a', expected_closed=True, closed=False,
                                     client_request_id='visual-close-2')
        assert not store.trip_visual_close_states()['trip-demo-a']
        assert store.get_trip('trip-demo-a') == before
    finally:
        store.close()


def test_sidebar_marks_closed_trip_without_visible_label():
    trip = dict(tab_id='example', display_key='Example', destination='Synthetic',
                starts_on='2026-10-01', ends_on='2026-10-02', visual_closed=True)
    with patch.object(ledger_board, 'live_trips', return_value=[trip]), \
         patch.object(ledger_board, 'current_role', return_value='owner'):
        html = ledger_design.nav_region('example', '')
    # Closed trips are reached from the 여행 목록 state filter, so the shared
    # sidebar contains neither a closed row nor a status-only badge.
    assert "tab=example" not in html
    assert "nv-closed" not in html


def test_trip_close_actions_use_state_specific_icons_without_changing_state(tmp_path):
    store = LedgerStore(tmp_path / 'board.sqlite', seed_demo=True)
    try:
        with patch.object(ledger_board, '_STORE', store):
            opened = ledger_board.trips_page(role='owner')
            assert ui_icons.icon('check') + '마감</button>' in opened
            store.save_trip_visual_close(tab_id='trip-demo-a', expected_closed=False,
                                         closed=True, client_request_id='icon-test')
            closed = ledger_board.trips_page(role='owner')
            assert ui_icons.icon('rotate-ccw') + '마감 해제</button>' in closed
            assert store.trip_visual_close_states()['trip-demo-a']
    finally:
        store.close()


def test_flight_navigation_has_distinct_airplane_icon():
    assert ui_icons.icon('airplane', 18)
    with patch.object(ledger_board, 'current_role', return_value='owner'), \
         patch('webapp.flight_passenger_page.enabled', return_value=True):
        nav = ledger_design._nav_html('', '')
    # Flight passengers is a 거래 subtab in the redesigned shell, not a
    # primary sidebar destination.
    assert "/flight-passengers" not in nav


def test_default_uses_first_open_trip_in_sidebar_order():
    trips = [
        dict(tab_id='past', starts_on='2026-01-01'),
        dict(tab_id='archived', starts_on='2026-07-01', archived=True),
        dict(tab_id='closed', starts_on='2026-07-02', visual_closed=True),
        dict(tab_id='first', starts_on='2026-07-03'),
        dict(tab_id='second', starts_on='2026-07-04'),
    ]
    with patch.object(ledger_board, 'live_trips', return_value=trips):
        assert ledger_board.default_board_tab() == 'first'
        trips[3]['visual_closed'] = True
        assert ledger_board.default_board_tab() == 'second'
        trips[4]['visual_closed'] = True
        assert ledger_board.default_board_tab() == 'unclassified'
