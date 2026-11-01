"""One masked selector for domestic/overseas sources; source rows stay intact."""
import html
import re
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

from webapp import card_transactions as ct, cards_all
from webapp.tests.test_cards_all import card_db_path


def test_unified_card_filter_counts_pages_undated_and_labels(card_db_path, monkeypatch):
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET card_tail='4850',card_kind='국내' "
                     "WHERE transaction_id IN ('TX-A-01','TX-UND-01')")
        conn.execute("UPDATE transactions SET card_tail='4850',card_kind='해외' "
                     "WHERE transaction_id IN ('TX-A-02','TX-UND-02')")
        # The same suffix at another issuer must remain a separate card.
        conn.execute("UPDATE transactions SET card_tail='4850',issuer='OTHER' "
                     "WHERE transaction_id='TX-B-01'")
        before = list(conn.iterdump())
    domestic = ct.card_identity('CARD', '국내', '4850')
    assert domestic == ct.card_identity('CARD', '해외', '4850')
    assert domestic['card_label'] == 'CARD · •••• 4850 김동언 대장'
    key = domestic['card_key']
    options = ct.card_options(card_db_path)
    assert options.count(domestic) == 1
    assert ct.card_identity('OTHER', '국내', '4850')['card_key'] != key
    summary = ct.year_summary(card_db_path, 2026, card=key)
    assert summary['months'][3] == 2 and summary['undated_count'] == 2
    assert summary['months'][4] == 0
    first = ct.list_for_month(card_db_path, 2026, 3, per_page=1, card=key)
    second = ct.list_for_month(card_db_path, 2026, 3, per_page=1,
                               card=key, cursor=first['cursor'])
    assert {r['transaction_id'] for r in first['items'] + second['items']} == {'TX-A-01', 'TX-A-02'}
    assert first['has_more'] and not second['has_more']
    assert ct.search_for_year(card_db_path, 2026, card=key)['total_count'] == 2
    assert ct.search_for_year(card_db_path, 2026, card=key, search='LAWSON')['count'] == 1
    assert ct.undated_list(card_db_path, card=key)['count'] == 2
    assert ct.transaction_detail('TX-A-01', card_db_path)['card_label'] == domestic['card_label']
    assert ct.card_identity('CARD', '国内', '1234')['card_label'] == 'CARD · •••• 1234'
    monkeypatch.setattr(cards_all, '_trip_context', lambda: ({}, set()))
    monkeypatch.setattr(cards_all, 'PAGE_SIZE', 1)
    query = {'period': ['2026-03'], 'card': [key]}
    page = cards_all.cards_all_page(query, db_path=card_db_path)
    assert page.count(f"<option value='{key}'") == 1
    assert domestic['card_label'] in page
    href = re.search(r"href='([^']*cursor=[^']*)'", page).group(1)
    next_query = parse_qs(urlsplit(html.unescape(href)).query)
    assert next_query['card'] == [key]
    next_page = cards_all.cards_all_page(next_query, db_path=card_db_path)
    assert "data-tx-id='TX-A-02'" in page and "data-tx-id='TX-A-01'" in next_page
    with closing(sqlite3.connect(card_db_path)) as conn:
        assert list(conn.iterdump()) == before
