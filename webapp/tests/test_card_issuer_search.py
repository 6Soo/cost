"""Card-all searches the displayed bank identity without exposing malformed PANs."""
import html
import re
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs,urlsplit
import pytest
from webapp import cards_all,card_transactions as ct
from webapp.tests.test_cards_all import card_db_path


@pytest.fixture
def ibk_db(card_db_path):
    with closing(sqlite3.connect(card_db_path)) as conn,conn:
        conn.execute("UPDATE transactions SET issuer='기업' WHERE transaction_id IN ('TX-A-01','TX-A-02','TX-UND-01')")
        conn.execute("UPDATE transactions SET issuer='국민',merchant='기업 서비스' WHERE transaction_id='TX-APR-01'")
    return card_db_path


@pytest.mark.parametrize('query',['기업카드','기업 카드','기업은행','IBK','ibk기업','IBK 기업카드'])
def test_issuer_alias_matches_dated_and_undated_without_mutating_rows(ibk_db,query):
    with closing(sqlite3.connect(ibk_db)) as conn:
        before='\n'.join(conn.iterdump())
    assert {x['transaction_id'] for x in ct.search_for_year(ibk_db,2026,search=query)['items']}=={'TX-A-01','TX-A-02'}
    assert ct.year_summary(ibk_db,2026,search=query)['months'][3]==2
    assert ct.year_summary(ibk_db,2026,search=query)['undated_count']==1
    assert [x['transaction_id'] for x in ct.undated_list(ibk_db,2026,search=query)['items']]==['TX-UND-01']
    with closing(sqlite3.connect(ibk_db)) as conn:
        assert '\n'.join(conn.iterdump())==before


def test_issuer_search_keeps_literal_merchant_matches_and_card_filter_intersection(ibk_db):
    assert ct.search_for_year(ibk_db,2026,search='기업')['total_count']==3
    assert ct.list_for_month(ibk_db,2026,3,search='기업')['count']==2
    other_key=ct.card_identity('CARD','credit','9999')['card_key']
    assert ct.search_for_year(ibk_db,2026,search='기업',card=other_key)['items']==[]
    assert ct.search_for_year(ibk_db,2025,search='기업카드')['items']==[]
    assert ct.search_for_year(ibk_db,2026,search="기업' OR 1=1 --")['items']==[]


def test_searches_only_explicit_last4_not_malformed_pan_suffix(ibk_db):
    with closing(sqlite3.connect(ibk_db)) as conn,conn:
        conn.execute("UPDATE transactions SET card_tail='12345678907777' WHERE transaction_id='TX-B-01'")
    assert {x['transaction_id'] for x in ct.search_for_year(ibk_db,2026,search='1234')['items']}=={'TX-A-01','TX-A-02'}
    assert ct.search_for_year(ibk_db,2026,search='7777')['items']==[]


def test_filtered_pages_keep_bank_query_totals_and_cursor(ibk_db,monkeypatch):
    monkeypatch.setattr(cards_all,'PAGE_SIZE',1)
    first=cards_all.cards_all_page({'period':['2026'],'q':['기업카드']},db_path=ibk_db)
    assert '검색 결과 · 2건' in first
    assert '카드사·끝4자리' in first
    href=re.search(r"href='([^']*cursor=[^']*)'",first).group(1)
    query=parse_qs(urlsplit(html.unescape(href)).query)
    assert query['q']==['기업카드']
    second=cards_all.cards_all_page(query,db_path=ibk_db)
    assert '검색 결과 · 2건' in second
    assert "data-tx-id='TX-A-02'" in first and "data-tx-id='TX-A-01'" in second
