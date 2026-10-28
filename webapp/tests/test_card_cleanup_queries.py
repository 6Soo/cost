"""Synthetic database coverage for cleanup reason filters and page contracts."""
from webapp import ledger_board
from webapp.card_flow import cleanup_total, render_expense_cleanup
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows, unassigned_row


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
        assert "기타 검토 22건" in all_html
        assert len([row for row in ids if f"data-transaction='{row}'" in render_expense_cleanup(board, 'csrf', reason='other_review')]) == 20
        no_item = render_expense_cleanup(board, 'csrf', reason='no_item')
        assert f"data-transaction='{ids[0]}'" in no_item
        assert f"data-transaction='{ids[1]}'" not in no_item
        assert "항목 미분류 1건 중 1~1건 표시" in no_item
        no_trip = render_expense_cleanup(board, 'csrf', reason='no_trip')
        assert f"data-transaction='{ids[1]}'" in no_trip
        assert "data-row-id='cleanup-ledger'" in no_trip
        assert "여행 미배정 2건" in no_trip
        protected = render_expense_cleanup(board, 'csrf', reason='protected')
        assert f"data-transaction='{ids[3]}'" in protected
        assert "보류·오류 1건" in protected
        assert f"cleanup_reason=other_review#expense-cleanup" in render_expense_cleanup(board, 'csrf', reason='other_review', page=2)
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_empty_filter_and_invalid_reason_fall_back_safely(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'cleanup-empty-filter.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        card_rows(board, 1)
        monkeypatch.setattr('webapp.card_flow._ota_entries_by_card', lambda _board, **kw: {'__snapshot_status__': {'fresh': True, 'status': 'ready'}})
        empty = render_expense_cleanup(board, 'csrf', reason='no_item')
        assert '항목 미분류 거래가 없습니다.' in empty
        assert "aria-current='page'" in empty
        assert "항목 미분류 0건" in empty
        assert "data-kind='card'" not in empty
        assert render_expense_cleanup(board, 'csrf', reason='unexpected') == render_expense_cleanup(board, 'csrf')
    finally:
        ledger_board.bind_store(None)
        board.close()
