"""Synthetic card history: counts, filtered cursors, invalid trips and masked IDs."""
import html
import re
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

from webapp import card_transactions as ct, cards_all
from webapp.tests.test_cards_all import card_db_path


def test_unassigned_counts_and_pages_share_valid_trip_and_search_contract(card_db_path):
    filters = dict(unassigned=True, valid_trip_ids={'T-A', 'T-D'})
    summary = ct.year_summary(card_db_path, 2026, **filters)
    assert summary['months'][3] == 2 and summary['months'][4] == 1
    assert summary['months'][2] == 0 and summary['undated_count'] == 2
    first = ct.list_for_month(card_db_path, 2026, 3, per_page=1, **filters)
    second = ct.list_for_month(card_db_path, 2026, 3, per_page=1, cursor=first['cursor'], **filters)
    assert [row['transaction_id'] for row in first['items'] + second['items']] == ['TX-A-02', 'TX-B-01']
    assert first['has_more'] and not second['has_more']
    assert ct.year_summary(card_db_path, 2025, **filters)['months'][6] == 1
    assert ct.list_for_month(card_db_path, 2026, 3, search='AGODA', **filters)['count'] == 1
    assert ct.year_summary(card_db_path, 2026, search='MERCURE', **filters)['months'][3] == 0
    # Search is literal and parameterized, including wildcard and quote characters.
    assert ct.list_for_month(card_db_path, 2026, 3, search="%' OR 1=1 --", **filters)['items'] == []


def test_valid_display_destination_and_dangling_override_are_counted_consistently(card_db_path):
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET display_tab_id='VALID',trip_id='MISSING' WHERE transaction_id='TX-A-01'")
        conn.execute("UPDATE transactions SET display_tab_id='MISSING',trip_id='VALID' WHERE transaction_id='TX-A-02'")
    filters = dict(unassigned=True, valid_trip_ids={'VALID'})
    result = ct.list_for_month(card_db_path, 2026, 3, **filters)
    assert {row['transaction_id'] for row in result['items']} == {'TX-A-02', 'TX-B-01'}
    assert ct.year_summary(card_db_path, 2026, **filters)['months'][3] == result['count']


def test_card_identity_uses_only_explicit_last4_and_separates_issuer_and_kind(card_db_path):
    first = ct.card_identity('Bank A', 'credit', '1234')
    assert first == ct.card_identity('Bank A', 'credit', '1234')
    assert first['card_key'] != ct.card_identity('Bank B', 'credit', '1234')['card_key']
    assert first['card_key'] != ct.card_identity('Bank A', 'debit', '1234')['card_key']
    assert '•••• 1234' in first['card_label']
    for tail in ('', None, '123', 'synthetic-invalid-long-number'):
        assert ct.card_identity('Bank A', 'credit', tail) == {'card_key': 'missing', 'card_label': '식별 정보 없음'}
    key = ct.card_identity('CARD', 'credit', '1234')['card_key']
    assert ct.year_summary(card_db_path, 2026, card=key)['months'][3] == 2
    rows = ct.list_for_month(card_db_path, 2026, 3, card=key)['items']
    assert len(rows) == 2 and all(row['card_key'] == key for row in rows)
    assert all('card_tail' not in row for row in rows)
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET card_tail='' WHERE transaction_id='TX-B-01'")
    assert ct.list_for_month(card_db_path, 2026, 3, card='missing')['items'][0]['transaction_id'] == 'TX-B-01'


def test_page_filters_preserve_navigation_reset_cursor_and_render_masked_card(card_db_path, monkeypatch):
    monkeypatch.setattr(cards_all, '_trip_context', lambda: ({'T-A': '합성 여행'}, {'T-A'}))
    monkeypatch.setattr(cards_all, 'PAGE_SIZE', 1)
    key = ct.card_identity('CARD', 'credit', '1234')['card_key']
    query = {'year': ['2026'], 'month': ['3'], 'unassigned': ['1'], 'card': [key], 'q': ['LAWSON']}
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        before = conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    page = cards_all.cards_all_page(query, db_path=card_db_path)
    assert "data-tx-id='TX-A-02'" in page and "data-tx-id='TX-A-01'" not in page
    assert '미배정 1건' in page and '•••• 1234' in page and '카드 식별' in page
    assert '같은 카드사·종류·끝자리' in page
    for form in re.findall(r'<form\b.*?</form>', page, re.S):
        if "action='/cards/all'" not in form:
            continue
        assert "name='cursor'" not in form and "name='undated_cursor'" not in form
    year_form = re.search(r"<form[^>]*class='card-all-year'.*?</form>", page, re.S).group(0)
    assert "name='unassigned' value='1'" in year_form and key in year_form and 'LAWSON' in year_form
    assert "name='month'" not in year_form  # Existing year-change behavior remains a month-grid view.
    reset = re.search(r"href='([^']*)'>필터 초기화", page).group(1)
    assert parse_qs(urlsplit(html.unescape(reset)).query) == {'year': ['2026'], 'month': ['3']}
    empty = cards_all.cards_all_page({**query, 'month': ['2']}, db_path=card_db_path)
    assert "data-tx-id=" not in empty and '조건에 맞는' in empty
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        assert conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == before


def test_filtered_next_page_keeps_card_search_and_unassigned_scope(card_db_path, monkeypatch):
    monkeypatch.setattr(cards_all, '_trip_context', lambda: ({}, set()))
    monkeypatch.setattr(cards_all, 'PAGE_SIZE', 1)
    key = ct.card_identity('CARD', 'credit', '1234')['card_key']
    query = {'year': ['2026'], 'month': ['3'], 'unassigned': ['1'], 'card': [key]}
    first = cards_all.cards_all_page(query, db_path=card_db_path)
    href = re.search(r"href='([^']*cursor=[^']*)'", first).group(1)
    next_query = parse_qs(urlsplit(html.unescape(href)).query)
    assert next_query['card'] == [key] and next_query['unassigned'] == ['1']
    second = cards_all.cards_all_page(next_query, db_path=card_db_path)
    assert "data-tx-id='TX-A-02'" in first and "data-tx-id='TX-A-01'" in second
    assert "data-tx-id='TX-A-02'" not in second
