"""Synthetic card history: counts, filtered cursors, invalid trips and masked IDs."""
import html
import re
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

from webapp import card_transactions as ct, cards_all
from webapp.tests.test_cards_all import card_db_path


def test_integrated_period_preserves_search_card_scope_and_legacy_links(card_db_path, monkeypatch):
    monkeypatch.setattr(cards_all, '_trip_context', lambda: ({}, set()))
    key = ct.card_identity('CARD', 'credit', '1234')['card_key']
    query = {'period': ['2026-03'], 'q': ['LAWSON'], 'card': [key], 'unassigned': ['1']}
    page = cards_all.cards_all_page(query, db_path=card_db_path)
    assert "data-tx-id='TX-A-02'" in page and "data-tx-id='TX-A-01'" not in page
    assert "value='2026-03' selected" in page
    legacy = cards_all.cards_all_page({**query, 'period': ['2026'], 'q': ['5500'], 'card': ['']}, db_path=card_db_path)
    assert '검색 결과 · 1건' in legacy and "data-tx-id='TX-APR-01'" in legacy
    assert cards_all._request_params({'period': ['2025-06'], 'year': ['2026'], 'month': ['3']})[:2] == (2025, 6)
    for invalid in ('2026-13', '2026-00', '1999-03', 'bad', '2026-3'):
        assert cards_all._request_params({'period': [invalid]})[:2] == (2026, None)


def test_year_period_lists_all_months_with_stable_pagination(card_db_path, monkeypatch):
    monkeypatch.setattr(cards_all, 'PAGE_SIZE', 1)
    first = cards_all.cards_all_page({'period': ['2026']}, db_path=card_db_path)
    assert '2026년 전체 · 5건' in first
    href = re.search(r"href='([^']*cursor=[^']*)'", first).group(1)
    second = cards_all.cards_all_page(parse_qs(urlsplit(html.unescape(href)).query), db_path=card_db_path)
    assert '2026년 전체 · 5건' in second
    assert "data-tx-id='TX-A-02'" in first and "data-tx-id='TX-A-01'" in second
    assert "data-tx-id='TX-A-02'" not in second


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


def test_search_matches_krw_and_foreign_amounts(card_db_path):
    assert [row['transaction_id'] for row in ct.list_for_month(
        card_db_path, 2026, 3, search='8,420')['items']] == ['TX-A-02']
    assert [row['transaction_id'] for row in ct.list_for_month(
        card_db_path, 2026, 3, search='820')['items']] == ['TX-A-02']
    result = ct.search_for_year(card_db_path, 2026, search='5500')
    assert [row['transaction_id'] for row in result['items']] == ['TX-APR-01']
    assert result['total_count'] == 1
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET foreign_amount='1,234.56' WHERE transaction_id='TX-A-02'")
    assert [row['transaction_id'] for row in ct.search_for_year(
        card_db_path, 2026, search='1,234.56')['items']] == ['TX-A-02']
    assert ct.search_for_year(card_db_path, 2026, search=',')['items'] == []
    assert [row['transaction_id'] for row in ct.search_for_year(
        card_db_path, 2026, search='A002')['items']] == ['TX-A-02']


def test_year_search_pagination_preserves_filters_and_never_writes(card_db_path, monkeypatch):
    monkeypatch.setattr(cards_all, '_trip_context', lambda: ({}, set()))
    monkeypatch.setattr(cards_all, 'PAGE_SIZE', 1)
    key = ct.card_identity('CARD', 'credit', '1234')['card_key']
    query = {'year': ['2026'], 'q': ['0'], 'card': [key], 'unassigned': ['1']}
    with closing(sqlite3.connect(card_db_path)) as conn:
        before = conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    first = cards_all.cards_all_page(query, db_path=card_db_path)
    href = re.search(r"href='([^']*cursor=[^']*)'", first).group(1)
    next_query = parse_qs(urlsplit(html.unescape(href)).query)
    assert next_query['q'] == ['0'] and next_query['card'] == [key]
    assert next_query['unassigned'] == ['1'] and 'month' not in next_query
    second = cards_all.cards_all_page(next_query, db_path=card_db_path)
    assert '검색 결과 · 2건' in first and '검색 결과 · 2건' in second
    assert "data-tx-id='TX-A-02'" in first and "data-tx-id='TX-A-01'" in second
    assert "data-tx-id='TX-A-02'" not in second
    assert '미배정' in first
    assert ct.search_for_year(card_db_path, 2026, search='MERCHANT')['items'] == []
    with closing(sqlite3.connect(card_db_path)) as conn:
        assert conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == before


def test_valid_display_destination_and_dangling_override_are_counted_consistently(card_db_path):
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET display_tab_id='VALID',trip_id='MISSING' WHERE transaction_id='TX-A-01'")
        conn.execute("UPDATE transactions SET display_tab_id='MISSING',trip_id='VALID' WHERE transaction_id='TX-A-02'")
    filters = dict(unassigned=True, valid_trip_ids={'VALID'})
    result = ct.list_for_month(card_db_path, 2026, 3, **filters)
    assert {row['transaction_id'] for row in result['items']} == {'TX-A-02', 'TX-B-01'}
    assert ct.year_summary(card_db_path, 2026, **filters)['months'][3] == result['count']


def test_card_identity_uses_only_explicit_last4_and_separates_issuer(card_db_path):
    first = ct.card_identity('Bank A', 'credit', '1234')
    assert first == ct.card_identity('Bank A', 'credit', '1234')
    assert first['card_key'] != ct.card_identity('Bank B', 'credit', '1234')['card_key']
    assert first == ct.card_identity('Bank A', 'debit', '1234')
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
    assert "class='btn' type='submit'" in page and "aria-hidden='true'" in page
    assert '>조회</button>' in page and "<svg class='ic'" in page
    assert '같은 카드사·종류·끝자리' in page
    for form in re.findall(r'<form\b.*?</form>', page, re.S):
        if "action='/cards/all'" not in form:
            continue
        assert "name='cursor'" not in form and "name='undated_cursor'" not in form
    period_form = re.search(r"<form[^>]*class='card-all-filters'.*?</form>", page, re.S).group(0)
    assert "name='unassigned' value='1'" in period_form and key in period_form and 'LAWSON' in period_form
    assert "value='2026-03' selected" in period_form
    assert "name='year'" not in period_form and "name='month'" not in period_form
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
