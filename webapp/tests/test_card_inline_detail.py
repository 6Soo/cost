"""Source-only detail, owner boundary, escaping and no-write guarantees."""
import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

from webapp import card_transactions as ct, cards_all, ledger_board as board, ledger_design
from webapp.tests.test_cards_all import card_db_path
from webapp.tests.test_card_transactions import MockHandler


def test_source_detail_is_read_only_masked_escaped_and_independent_of_ledger(card_db_path):
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET merchant=?,description=?,display_tab_id=? WHERE transaction_id='TX-A-01'",
                     ('<img src=x onerror=alert(1)>', '<script>secret()</script>', 'quarter:2026:3'))
        before = list(conn.iterdump())
    detail = ct.transaction_detail('TX-A-01', card_db_path)
    assert detail['card_label'] == 'CARD · •••• 1234'
    assert 'card_tail' not in detail
    assert detail['amount_krw'] == 150000
    html = cards_all.card_detail_html(detail)
    assert '<script>' not in html and '<img' not in html
    assert '&lt;script&gt;' in html and '2026년 3분기 기타비용' in html
    assert '2025년 4분기 기타비용' in cards_all.card_detail_html(
        dict(detail, display_tab_id='unclassified', trip_id='quarter:2025:4'))
    assert ct.transaction_detail("' OR 1=1 --", card_db_path) is None
    with patch.object(board, 'find_row', return_value=('expense', None)), \
         patch.object(board, 'current_role', return_value='owner'), \
         patch.object(board, '_get_card_db_path', return_value=card_db_path), \
         patch.object(ledger_design, '_STORE_missing', return_value=False):
        fallback = ledger_design.panel_part('card-TX-A-01')
        assert '카드 거래 상세' in fallback and '없는 거래' not in fallback
        assert '150,000원' in fallback
        with patch.object(board, 'current_role', return_value='viewer'), \
             patch.object(ct, 'transaction_detail') as query:
            ledger_design.panel_part('card-TX-A-01')
            query.assert_not_called()
    with closing(sqlite3.connect(card_db_path)) as conn:
        assert list(conn.iterdump()) == before


def test_detail_http_owner_only_and_404_does_not_query_ledger(card_db_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_DB', card_db_path)
    with patch.object(board, 'ACCESS_ENFORCEMENT', False), patch.object(board, 'current_role', return_value='owner'), \
         patch.object(board, 'find_row', side_effect=AssertionError('ledger lookup forbidden')):
        handler = MockHandler('/api/cards/transactions/detail', 'id=TX-A-01')
        handler.do_GET()
        assert handler.responses['code'] == 200
        assert 'MERCURE' in json.loads(handler.responses['body'])['html']
        missing = MockHandler('/api/cards/transactions/detail', 'id=missing')
        missing.do_GET()
        assert missing.responses['code'] == 404
        invalid = MockHandler('/api/cards/transactions/detail')
        invalid.do_GET()
        assert invalid.responses['code'] == 400
    with patch.object(board, 'ACCESS_ENFORCEMENT', False), patch.object(board, 'current_role', return_value='viewer'), \
         patch.object(ct, 'transaction_detail') as query:
        handler = MockHandler('/api/cards/transactions/detail', 'id=TX-A-01')
        handler.do_GET()
        assert handler.responses['code'] == 403
        query.assert_not_called()
    with patch.object(board, 'ACCESS_ENFORCEMENT', True), patch.object(board, 'current_session', return_value=None), \
         patch.object(ct, 'transaction_detail') as query:
        handler = MockHandler('/api/cards/transactions/detail', 'id=TX-A-01')
        handler.do_GET()
        assert handler.responses['code'] == 401
        query.assert_not_called()
