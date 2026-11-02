"""A completed classification must not require a second approval in cleanup."""
from webapp import ledger_board
from webapp.card_flow import CardFlow, _cleanup_card_items, _cleanup_card_breakdown, cleanup_total, render_expense_cleanup
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows


def test_persisted_assignment_completes_review_without_internal_record(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'completed.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        flow, _, rows = card_rows(board, 3)
        trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
            destination='Synthetic trip', client_request_id='trip')['tab_id']
        monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: target == trip)
        ids = [r['transaction_id'] for r in rows]
        for tid, source, basis in zip(ids, ['inference', 'rule', 'manual'],
                ['AUTO_INFERRED · 낮음 · 카드 이용일과 여행 기간 거리 0일', 'merchant rule', 'owner correction']):
            board.conn.execute("UPDATE transactions SET item='현지경비',trip_id=?,display_tab_id=?,classification_source=?,classification_basis=? WHERE transaction_id=?", (trip, trip, source, basis, tid))
        board.conn.commit()
        before = board.conn.total_changes
        assert cleanup_total(board) == 0
        assert _cleanup_card_items(board) == []
        assert sum(_cleanup_card_breakdown(board).values()) == 0
        html = render_expense_cleanup(board, 'csrf')
        assert all(f"data-transaction='{tid}'" not in html for tid in ids)
        # Completion must neither invent a ledger entry nor a user decision.
        assert not board.conn.execute('SELECT 1 FROM ledger_entries').fetchone()
        assert not board.conn.execute('SELECT 1 FROM review_decisions').fetchone()
        assert board.conn.total_changes == before
        # A later loss of authority must immediately return to the queue.
        monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: False)
        assert cleanup_total(board) == 3
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_completed_assignments_keep_refund_source_hold_and_missing_data_protections(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'protected.sqlite', seed_demo=False)
    try:
        _, _, rows = card_rows(board, 9)
        ids = [r['transaction_id'] for r in rows]
        monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: target == 'valid-trip')
        board.conn.execute("UPDATE transactions SET classification_source='inference',classification_basis='AUTO_INFERRED · 낮음',trip_id='valid-trip',display_tab_id='valid-trip'")
        board.conn.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?", (ids[1],))
        board.conn.execute("UPDATE transactions SET conflict_reason='synthetic' WHERE transaction_id=?", (ids[2],))
        board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)', (ids[3],rows[3]['source_hash'],'user_hold','synthetic'))
        board.conn.execute("UPDATE transactions SET item='' WHERE transaction_id=?", (ids[4],))
        board.conn.execute("UPDATE transactions SET trip_id='',display_tab_id='' WHERE transaction_id=?", (ids[5],))
        # An unresolved partial cancellation keeps both sides visible, even
        # when merchant and amount differ and the cancellation is on another page.
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-1004,original_approval_number=? WHERE transaction_id=?", (rows[6]['approval_number'], ids[7]))
        board.conn.execute("UPDATE transactions SET classification_state='needs_review' WHERE transaction_id=?", (ids[8],))
        board.conn.commit()
        before = board.conn.total_changes
        assert {r[0] for r in _cleanup_card_items(board)} == set(ids[1:])
        assert cleanup_total(board) == 8
        assert sum(_cleanup_card_breakdown(board).values()) == 8
        assert board.conn.total_changes == before
    finally:
        board.close()
