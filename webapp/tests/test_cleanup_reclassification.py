"""일괄 자동분류는 미정리 구매만 처리하고 금융 원본과 장부를 보존한다."""
from urllib.parse import urlparse

from app.db import StoreError
from webapp import card_flow, ledger_board
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows


def test_bulk_classification_survives_booking_failure_without_changing_protected_data(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'bulk.sqlite', seed_demo=False)
    try:
        flow, batch, rows = card_rows(board, 7)
        ids = [r['transaction_id'] for r in rows]
        for tid, name in zip(ids, ['시장할매국밥', '토요코인 대구동성로', 'agoda',
                                   '보류국밥', '확정국밥', '원본국밥', '환불국밥']):
            board.conn.execute(
                "UPDATE transactions SET merchant=?,merchant_normalized=?,item='',"
                "classification_source='',display_tab_id='' WHERE transaction_id=?", (name, name, tid))
        board.conn.execute(
            "INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)",
            (ids[3], rows[3]['source_hash'], 'evidence_pending', 'synthetic'))
        board.conn.execute("UPDATE transactions SET classification_source='user_decision',item='접대비'"
                           " WHERE transaction_id=?", (ids[4],))
        board.conn.execute("UPDATE transactions SET item='교통비',display_tab_id='verified',trip_id='verified'"
                           " WHERE transaction_id=?", (ids[5],))
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',"
                           "original_approval_number=(SELECT approval_number FROM transactions WHERE transaction_id=?)"
                           " WHERE transaction_id=?", (ids[5], ids[6]))
        board.conn.commit()
        protected = (ids[3], ids[4], ids[5], ids[6])
        before_protected = board.conn.execute(
            'SELECT * FROM transactions WHERE transaction_id IN (?,?,?,?) ORDER BY transaction_id', protected).fetchall()
        before_raw = board.conn.execute(
            'SELECT transaction_id,raw_row_json,amount_krw,approval_date,posting_date FROM transactions ORDER BY transaction_id').fetchall()
        monkeypatch.setattr(card_flow.CardFlow, '_ota_report',
                            lambda _: (_ for _ in ()).throw(StoreError('OTA_EVIDENCE_UNAVAILABLE', 'synthetic')))
        monkeypatch.setattr(card_flow.CardFlow, '_evidence_period_assignments', lambda *args: [])
        monkeypatch.setattr(card_flow.CardFlow, '_guide_airfare_rules', lambda *args: [])
        monkeypatch.setattr(card_flow.CardFlow, '_board_future_rules', lambda *args: [])
        monkeypatch.setattr(card_flow.CardFlow, 'retail_trip', lambda *args: '')
        monkeypatch.setattr(card_flow.CardFlow, '_auto_record_locked',
                            lambda *args: (_ for _ in ()).throw(AssertionError('must not post')))
        result = card_flow.reclassify_cleanup(board)
        assert result['processed'] == 2
        assert result['failures'] == [{'kind': 'ota', 'count': 1, 'code': 'OTA_EVIDENCE_UNAVAILABLE'}]
        assert board.conn.execute('SELECT item FROM transactions WHERE transaction_id=?', (ids[0],)).fetchone()[0] == '식비'
        assert board.conn.execute('SELECT item,display_tab_id FROM transactions WHERE transaction_id=?', (ids[1],)).fetchone() == ('숙박비', 'unclassified')
        assert board.conn.execute('SELECT * FROM transactions WHERE transaction_id IN (?,?,?,?) ORDER BY transaction_id', protected).fetchall() == before_protected
        assert board.conn.execute('SELECT transaction_id,raw_row_json,amount_krw,approval_date,posting_date FROM transactions ORDER BY transaction_id').fetchall() == before_raw
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
        assert board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 0
        after = board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        assert card_flow.reclassify_cleanup(board)['processed'] == 2
        assert board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == after
        monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
        monkeypatch.setattr(card_flow, '_ota_entries_by_card', lambda _: {})
        html = card_flow.render_expense_cleanup(board, 'token')
        assert "id='cleanup-reclassify'" in html
        assert '/api/imports/reclassify-pending' in html
        assert 'location.reload()' in html
    finally:
        board.close()


def test_bulk_route_requires_owner_post_and_csrf(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'route.sqlite', seed_demo=False)
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setattr(ledger_board, '_active_store', lambda: board)
    calls = []
    monkeypatch.setattr(card_flow, 'reclassify_cleanup', lambda _: calls.append(True) or {'processed': 0})
    monkeypatch.setattr(card_flow, 'CardFlow', lambda _: (_ for _ in ()).throw(AssertionError('authorization must run first')))

    class Handler:
        headers = {'X-CSRF-Token': 'token'}
        def _send_json(self, data, status=200):
            self.response = data, status

    handler = Handler()
    route = urlparse('/api/imports/reclassify-pending')
    try:
        for role, raw, csrf, expected in [('viewer', b'{}', 'token', 403),
                                          ('owner', None, 'token', 405),
                                          ('owner', b'{}', '', 403),
                                          ('owner', b'{}', 'wrong', 403),
                                          ('owner', b'{}', 'token', 200)]:
            monkeypatch.setattr(ledger_board, 'current_role', lambda: role)
            assert card_flow.dispatch(handler, route, raw=raw, csrf=csrf)
            assert handler.response[1] == expected
        assert len(calls) == 1
    finally:
        board.close()
