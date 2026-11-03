"""Synthetic database coverage for cleanup reason filters and page contracts."""
from webapp import ledger_board
from webapp.card_flow import cleanup_total, render_expense_cleanup
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows, unassigned_row


def test_completed_historical_costs_leave_cleanup_but_protected_rows_remain(tmp_path):
    board = LedgerStore(tmp_path / 'historical-cleanup.sqlite', seed_demo=False)
    try:
        _, _, rows = card_rows(board, 8)
        ids = [row['transaction_id'] for row in rows]
        board.conn.executemany(
            "UPDATE transactions SET classification_state='classified',item='기타경비',"
            "trip_id='',display_tab_id='unclassified',classification_basis=? WHERE transaction_id=?",
            [('등록된 유효 여행 없음 · 비용 항목 분류 완료 · complete-card-inference-v1', tid) for tid in ids])
        board.conn.execute("UPDATE transactions SET item='' WHERE transaction_id=?", (ids[1],))
        board.conn.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?", (ids[2],))
        board.conn.execute("UPDATE transactions SET conflict_reason='synthetic' WHERE transaction_id=?", (ids[3],))
        board.conn.execute("INSERT INTO transaction_review_holds VALUES (?,?,?,?)",
                           (ids[4], rows[4]['source_hash'], 'user_hold', 'synthetic'))
        board.conn.execute("UPDATE transactions SET classification_state='needs_review' WHERE transaction_id=?", (ids[5],))
        board.conn.execute("UPDATE transactions SET trip_id='trip-1',display_tab_id='trip-1',classification_basis='AUTO_INFERRED · complete-card-inference-v1' WHERE transaction_id=?", (ids[6],))
        board.conn.execute("UPDATE transactions SET classification_source='refund_original',classification_basis='verified original inherited' WHERE transaction_id=?", (ids[7],))
        board.conn.commit()
        from webapp.card_flow import _cleanup_card_items
        before = board.conn.total_changes
        assert cleanup_total(board) == 5
        assert {row[0] for row in _cleanup_card_items(board)} == set(ids[1:6])
        assert board.conn.total_changes == before
    finally:
        board.close()


def test_cleanup_reasons_are_exclusive_and_filtered_on_the_full_population(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'cleanup-reasons.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        _, batch, rows = card_rows(board, 25)
        ids = [row['transaction_id'] for row in rows]
        board.conn.execute("UPDATE transactions SET display_tab_id='trip-1' WHERE batch_id=?", (batch,))
        board.conn.execute("UPDATE transactions SET item='' WHERE transaction_id=?", (ids[0],))
        board.conn.execute("UPDATE transactions SET display_tab_id='unclassified' WHERE transaction_id=?", (ids[1],))
        board.conn.execute("UPDATE transactions SET item='식비',display_tab_id='trip-1' WHERE transaction_id=?", (ids[2],))
        source_hash = rows[3]['source_hash']
        board.conn.execute("INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)",
                           (ids[3], source_hash, 'evidence_pending', 'synthetic hold'))
        board.conn.commit()
        unassigned_row(board, row_id='cleanup-ledger')
        monkeypatch.setattr('webapp.card_flow._ota_entries_by_card', lambda _board, **kw: {'__snapshot_status__': {'fresh': True, 'status': 'ready'}})

        all_html = render_expense_cleanup(board, 'csrf')
        assert cleanup_total(board) == 26
        assert "전체 26건" in all_html
        assert "분류·배정 필요 3건" in all_html
        assert "기록 상태 확인 22건" in all_html
        classification = render_expense_cleanup(board, 'csrf', reason='classification')
        assert f"data-transaction='{ids[0]}'" in classification
        assert f"data-transaction='{ids[1]}'" in classification
        assert "data-row-id='cleanup-ledger'" in classification
        second = render_expense_cleanup(board, 'csrf', reason='recording', page=2)
        assert "기록 상태 확인 22건 중 21~22건 표시" in second
        protected = render_expense_cleanup(board, 'csrf', reason='evidence')
        assert f"data-transaction='{ids[3]}'" in protected
        assert "근거 충돌 1건" in protected
        assert f"cleanup_reason=recording#expense-cleanup" in second
        assert render_expense_cleanup(board, 'csrf', reason='no_trip') == render_expense_cleanup(board, 'csrf', reason='classification')
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_empty_filter_and_invalid_reason_fall_back_safely(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'cleanup-empty-filter.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        card_rows(board, 1)
        monkeypatch.setattr('webapp.card_flow._ota_entries_by_card', lambda _board, **kw: {'__snapshot_status__': {'fresh': True, 'status': 'ready'}})
        empty = render_expense_cleanup(board, 'csrf', reason='finance')
        assert '결제·환불 확인 거래가 없습니다.' in empty
        assert "aria-current='page'" in empty
        assert "결제·환불 확인 0건" in empty
        assert "data-kind='card'" not in empty
        assert render_expense_cleanup(board, 'csrf', reason='unexpected') == render_expense_cleanup(board, 'csrf')
    finally:
        ledger_board.bind_store(None)
        board.close()
