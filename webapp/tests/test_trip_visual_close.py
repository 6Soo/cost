from unittest.mock import patch

import pytest

from webapp import ledger_board, ledger_design
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
    assert "nv sel nv-closed" in html
    assert 'aria-label=\'Example · 마감\'' in html
    assert '>마감<' not in html
