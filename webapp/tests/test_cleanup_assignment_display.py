"""Persisted active trip is visible without opening the edit controls."""
import pytest

from webapp import card_flow, ledger_board
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows


@pytest.mark.parametrize('active', [True, False])
def test_cleanup_displays_only_current_active_trip(tmp_path, monkeypatch, active):
    board = LedgerStore(tmp_path / 'assignment.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
        _, _, rows = card_rows(board, 1)
        trip = board.create_trip(starts_on='2026-09-28', ends_on='2026-10-05',
                                 destination='합성<여행>', client_request_id='display-trip')
        monkeypatch.setattr(card_flow.CardFlow, 'trip_valid',
                            lambda self, target: active and target == trip['tab_id'])
        # Keep the row in review; completed classified rows leave this queue.
        board.conn.execute("UPDATE transactions SET classification_state='needs_review', trip_id=?, display_tab_id=?, item=?",
                           (trip['tab_id'], trip['tab_id'], '현지<경비>'))
        board.conn.commit()
        before = board.conn.total_changes
        markup = card_flow.render_expense_cleanup(board, 'token')
        if active:
            assert '현재 여행:' in markup
            assert '합성&lt;여행&gt;' in markup
            assert '항목: 현지&lt;경비&gt;' in markup
            assert '현재 여행: 합성<여행>' not in markup
        else:
            assert "<p class='cleanup-assignment'>" not in markup
        assert board.conn.total_changes == before
    finally:
        board.close()
