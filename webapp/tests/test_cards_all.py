# -*- coding: utf-8 -*-
"""Targeted tests for cards_all handler and renderers.
Tests the card-all page rendering, data contracts, and UI behavior.
Uses synthetic fixture matching app/db.py schema (transactions).
"""
import os
import html
import re
import sqlite3
import tempfile
import pytest
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from webapp import cards_all
from webapp import card_transactions as ct


def test_unavailable_card_page_offers_recovery():
    page = cards_all._error_page('카드 자료를 읽을 수 없어요.')
    assert '카드 자료를 읽을 수 없어요.' in page
    assert '문제가 계속되면 관리자에게 문의해 주세요.' in page
    assert "href=''>다시 불러오기</a>" in page


def test_legacy_cleanup_link_has_recovery_action_on_card_history(card_db_path):
    page = cards_all.cards_all_page(
        {'legacy_cleanup': ['1']}, db_path=card_db_path, owner=True)
    assert "class='card-legacy-notice'" in page
    assert '이전 거래 화면을 카드 내역으로 통합했습니다' in page
    assert '거래와 원본 근거를 이 화면에서 확인할 수 있습니다' in page


CARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    issuer TEXT NOT NULL,
    card_tail TEXT NOT NULL,
    card_kind TEXT NOT NULL,
    transaction_direction TEXT NOT NULL,
    transaction_kind TEXT NOT NULL,
    approval_number TEXT NOT NULL,
    original_approval_number TEXT NOT NULL,
    approval_date TEXT NOT NULL,
    posting_date TEXT NOT NULL,
    merchant TEXT NOT NULL,
    merchant_normalized TEXT NOT NULL,
    amount_krw INTEGER,
    foreign_amount TEXT NOT NULL DEFAULT '',
    foreign_currency TEXT NOT NULL DEFAULT '',
    description_raw TEXT NOT NULL DEFAULT '',
    row_index INTEGER NOT NULL,
    raw_row_json TEXT NOT NULL DEFAULT '{}',
    duplicate_of TEXT,
    conflict_reason TEXT NOT NULL DEFAULT '',
    parse_error TEXT NOT NULL DEFAULT '',
    classification_state TEXT NOT NULL DEFAULT 'needs_review',
    classification_source TEXT NOT NULL DEFAULT '',
    classification_basis TEXT NOT NULL DEFAULT '',
    item TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    display_tab_id TEXT NOT NULL DEFAULT '',
    trip_id TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    decided_at TEXT,
    created_at TEXT NOT NULL
);
"""


@pytest.fixture(autouse=True)
def require_card_schema_for_test(monkeypatch):
    """Apply the strict schema contract only while this test is running."""
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'require')


@pytest.fixture
def card_db_path():
    """Create a temporary card transactions database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        path = f.name
    conn = sqlite3.connect(path)
    conn.executescript(CARD_SCHEMA)
    rows = [
        # March 2026 - 3 items (2 same day, 1 next day)
        ("TX-A-01","h1","b1","CARD","1234","credit","debit","card","A001","A001","2026-03-05","2026-03-06","MERCURE","mercure",150000,"","KRW","raw",1,"{}",None,"","","booked","manual","","","HOTEL A","","T-A",1,None,"2026-01-01"),
        ("TX-A-02","h2","b1","CARD","1234","credit","debit","card","A002","A002","2026-03-05T14:30","2026-03-06","LAWSON","lawson",8420,"820","JPY","raw",2,"{}",None,"","","booked","auto_inferred","","","SNACK","","T-B",1,None,"2026-01-01"),
        ("TX-B-01","h3","b2","CARD","9999","credit","debit","card","B001","B001","2026-03-10","2026-03-11","AGODA","agoda",556929,"500000","KRW","raw",3,"{}",None,"","","needs_review","manual","","","HOTEL B","","T-C",1,None,"2026-01-01"),
        # April 2026 - 2 items
        ("TX-APR-01","h4","b3","CARD","1111","credit","debit","card","C001","C001","2026-04-01","2026-04-02","STARBUCKS","starbucks",5500,"","KRW","raw",4,"{}",None,"","","classified","manual","","","FOOD","","T-D",1,None,"2026-01-01"),
        ("TX-APR-02","h5","b3","CARD","1111","credit","debit","card","C002","C002","2026-04-15","2026-04-16","SUBWAY","subway",12000,"","KRW","raw",5,"{}",None,"","","classified","auto_inferred","","","TRANSPORT","","",1,None,"2026-01-01"),
        # Undated (no valid approval_date)
        ("TX-UND-01","h6","b4","CARD","2222","credit","debit","card","U01","U01","","","UNKNOWN","unknown",-543947,"","KRW","raw",6,"{}",None,"","","cancelled","manual","","","","","",1,None,"2026-01-01"),
        ("TX-UND-02","h7","b4","CARD","2222","credit","debit","card","U02","U02","invalid","","UNKNOWN2","unknown2",10000,"","KRW","raw",7,"{}",None,"","","booked","manual","","","ITEM","","T-E",1,None,"2026-01-01"),
        # Other year transactions (should NOT be counted as undated)
        ("TX-2025-01","h8","b5","CARD","3333","credit","debit","card","E01","E01","2025-06-15","2025-06-16","MERCHANT","merchant",10000,"","KRW","raw",8,"{}",None,"","","booked","manual","","","ITEM","","T-F",1,None,"2025-01-01"),
    ]
    place = ",".join(["?"]*33)
    conn.executemany(f"INSERT INTO transactions VALUES ({place})", rows)
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def test_period_selector_replaces_month_cards_and_initial_page_is_lazy(card_db_path, monkeypatch):
    def unexpected_undated_query(**kwargs):
        raise AssertionError("초기 화면은 날짜 확인 필요 목록을 조회하면 안 됩니다")

    monkeypatch.setattr(cards_all._ct, "undated_list", unexpected_undated_query)
    page = cards_all.cards_all_page({}, db_path=card_db_path)
    assert "2026년" in page
    assert "이용일 원문 없음 · 2건" in page
    assert "이용일 원문 없음 목록 보기" in page
    assert "UNKNOWN" not in page
    assert "name='period'" in page and '2026년 전체' in page
    assert 'card-all-tile' not in page and 'card-all-grid' not in page
    assert "name='year'" not in page and "name='month'" not in page
    for month in range(1, 13):
        assert f'2026년 {month}월</option>' in page


def test_cards_all_page_uses_strict_date_and_undated_api_contract(card_db_path):
    """화면과 조회 API가 날짜시각과 날짜 미상 집계를 같은 기준으로 나눈다."""
    month_page = cards_all.cards_all_page(
        {"year": ["2026"], "month": ["3"]}, db_path=card_db_path)
    assert "TX-A-02" in month_page
    assert "이용일 원문 없음 · 2건" in month_page

    undated_page = cards_all.cards_all_page(
        {"year": ["2026"], "undated": ["1"]}, db_path=card_db_path)
    assert "이용일 원문 없음 · 2건" in undated_page
    assert "TX-UND-01" in undated_page
    assert "TX-UND-02" in undated_page


def test_request_params_canonicalize_invalid_and_conflicting_modes():
    assert cards_all._request_params({"month": ["13"], "undated": ["1"]}) == (
        2026, None, None, None, False)
    assert cards_all._request_params({"month": ["3"], "cursor": [
        "2026-03-05|TX-1"], "undated": ["1"]}) == (
        2026, None, None, None, True)


def test_explicit_midnight_is_displayed_as_an_existing_time():
    assert cards_all._format_use_date("2026-03-05T00:00:00") == "2026-03-05 00:00:00"


def test_month_rows_keep_second_precision_order():
    items = [
        {"transaction_id": "TX-LATE", "approval_date": "2026-03-05T08:15:30",
         "amount_krw": 1, "foreign_currency": "KRW"},
        {"transaction_id": "TX-EARLY", "approval_date": "2026-03-05T08:15:00",
         "amount_krw": 1, "foreign_currency": "KRW"},
    ]
    rendered = cards_all._render_month_rows(items, include_detail_link=False)
    assert rendered.index("TX-EARLY") < rendered.index("TX-LATE")
    assert "2026-03-05 08:15:00" in rendered
    assert "2026-03-05 08:15:30" in rendered


def test_merchant_markup_is_escaped_and_original_text_is_preserved():
    merchant = '<script>alert("x")</script><img src=x onerror="alert(1)"> "Cafe" & Market'
    rendered = cards_all._render_month_rows([{
        "transaction_id": "TX-XSS-SYNTHETIC",
        "approval_date": "2026-03-05",
        "merchant": merchant,
        "amount_krw": -123,
        "foreign_currency": "KRW",
    }], include_detail_link=False)

    class MerchantMarkupParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_merchant = False
            self.merchant_text = []
            self.active_markup = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "span" and attrs.get("class") == "merchant-name":
                self.in_merchant = True
            if tag in ("script", "img") or any(name.lower().startswith("on") for name, _ in attrs.items()):
                self.active_markup.append((tag, attrs))

        def handle_endtag(self, tag):
            if tag == "span" and self.in_merchant:
                self.in_merchant = False

        def handle_data(self, data):
            if self.in_merchant:
                self.merchant_text.append(data)

    parser = MerchantMarkupParser()
    parser.feed(rendered)
    assert parser.active_markup == []
    assert "".join(parser.merchant_text) == merchant
    assert "&lt;script&gt;" in rendered
    assert "&lt;img" in rendered
    assert "onerror=&quot;alert(1)&quot;" in rendered
    assert "&quot;Cafe&quot; &amp; Market" in rendered


def test_undated_ui_cursor_covers_more_than_500_rows_once(card_db_path):
    conn = sqlite3.connect(card_db_path)
    rows = []
    for index in range(610):
        transaction_id = f"TX-UI-UND-{index:03d}"
        invalid_date = "2026-02-30" if index % 2 == 0 else "2026-03-05 25:00:00"
        rows.append((transaction_id, f"h-ui-{index}", "b-ui", "CARD", "1234",
                     "credit", "debit", "card", f"A{index}", f"A{index}",
                     invalid_date, "", "SYNTHETIC", "synthetic", -12345,
                     "-67.50" if index % 2 == 0 else "",
                     "JPY" if index % 2 == 0 else "KRW",
                     "raw", 100 + index, "{}", None, "", "",
                     "cancelled", "manual", "", "", "ITEM", "", "", 1,
                     None, "2026-01-01"))
    conn.executemany("INSERT INTO transactions VALUES (" + ",".join(["?"] * 33) + ")", rows)
    conn.commit()
    conn.close()

    seen = []
    all_pages = []
    query = {"year": ["2026"], "undated": ["1"]}
    for page_number in range(10):
        page = cards_all.cards_all_page(query, db_path=card_db_path)
        all_pages.append(page)
        page_ids = re.findall(r"data-tx-id='([^']*)'", page)
        seen.extend(page_ids)
        next_link = re.search(
            r"href='([^']*undated_cursor=[^']*)'", page)
        if not next_link:
            break
        href = html.unescape(next_link.group(1))
        query = parse_qs(urlsplit(href).query)
        assert "undated_cursor" in query
        assert "cursor" not in query
        assert page_number < 9

    expected = {f"TX-UI-UND-{index:03d}" for index in range(610)}
    assert len(seen) == 612  # 610 inserted rows and 2 existing undated rows.
    assert len(set(seen)) == 612
    assert expected <= set(seen)
    rendered = "".join(all_pages)
    assert "-67.5 JPY" in rendered
    assert "-12,345원" in rendered


def test_dates_use_selected_period_context_and_preserve_source(card_db_path):
    for query, expected in (({'period': ['2026']}, '3월 5일 14:30'),
                            ({'period': ['2026-03']}, '5일 14:30')):
        page = cards_all.cards_all_page(query, db_path=card_db_path)
        row = re.search(r"<tr[^>]*data-tx-id='TX-A-02'[^>]*>(.*?)</tr>", page, re.S).group(1)
        cell = re.search(r"<td[^>]*class='use-datetime'([^>]*)>(.*?)</td>", row, re.S)
        assert cell.group(2) == expected
        assert "title='2026-03-05 14:30'" in cell.group(1)
    assert cards_all._period_date('2025-03-05', 2026, 3) == '2025-03-05'
    assert cards_all._period_date('2026-04-05', 2026, 3) == '4월 5일'
    assert cards_all._period_date('invalid', 2026, 3) == ''
    with sqlite3.connect(card_db_path) as conn:
        assert conn.execute("SELECT approval_date FROM transactions WHERE transaction_id='TX-A-02'").fetchone()[0] == '2026-03-05T14:30'
    conn.close()


def test_month_detail_renderer_basic(card_db_path):
    """실제 월 상세 렌더러가 날짜 그룹과 거래 행을 표시한다."""

    res = ct.list_for_month(db_path=card_db_path, year=2026, month=3, per_page=100)
    items = res['items']

    html = cards_all._month_detail(2026, 3, items, res.get('cursor'), res.get('has_more', False), 3)

    # Header
    assert '2026년 3월' in html
    assert '3건' in html
    # Date group for 2026-03-05 (should be 2 items now - grouped by date)
    assert '2026-03-05' in html
    assert '2건' in html
    # Date group for 2026-03-10 (1 item)
    assert '2026-03-10' in html
    # Table structure
    assert 'card-all-table' in html
    assert '이용일시' in html
    assert '가맹점명' in html
    assert '금액' in html
    assert "<th scope='col'>귀속</th>" in html
    assert '배정된 여행' not in html
    assert 'detail-cell' not in html
    assert "colspan='4'" in html
    assert "data-detail-id='TX-A-01'" in html
    assert "class='card-all-row-toggle'" in html
    assert "aria-controls='card-detail-TX-A-01'" in html
    # Transaction data
    assert 'MERCURE' in html
    assert 'LAWSON' in html
    assert 'AGODA' in html
    # Currency display
    assert '원' in html
    # Trip display
    assert '자동' in html and '수동' in html
    # Detail link
    assert 'board?row=card-TX-A-01' not in html


def test_card_history_visual_contract_and_trip_display_names(card_db_path, monkeypatch):
    """Owner view shows official trip labels without changing card trip IDs."""
    from unittest.mock import patch
    row = {
        "transaction_id": "TX-LABEL", "use_date": "2026-03-05 08:15",
        "merchant": "상점", "amount_krw": 12000, "foreign_currency": "KRW",
        "trip_id": "opaque-tab-1", "classification_source": "manual",
        "classification_state": "booked",
    }
    rendered = cards_all._render_month_rows(
        [row], trip_names={"opaque-tab-1": "0630_오제"})
    assert "0630_오제" in rendered
    assert "title='0630_오제'" in rendered
    assert "수동" in rendered
    assert "<span class='card-all-trip-name'" in rendered
    assert row["trip_id"] == "opaque-tab-1"
    fallback = cards_all._render_month_rows([row])
    assert ">기타비용</span>" in fallback

    quarter_row = dict(row, display_tab_id='quarter:2026:3')
    quarter_html = cards_all._render_month_rows([quarter_row])
    assert '>2026년 3분기 기타비용</span>' in quarter_html
    assert '>quarter:2026:3</span>' not in quarter_html
    assert quarter_row['display_tab_id'] == 'quarter:2026:3'

    with patch("webapp.ledger_board.current_role", return_value="owner"), patch(
        "webapp.ledger_board.live_trips",
        return_value=[{"tab_id": "T-A", "display_key": "0630_오제"}],
    ):
        result = cards_all.cards_all_page(
            {"year": ["2026"], "month": ["3"]}, db_path=card_db_path,
            owner=True, csrf='synthetic-csrf')
    assert "id=\"card-all-design\"" in result
    assert "조회 조건" in result
    assert "월별 카드 거래 확인" not in result
    assert "CARD TRANSACTION HISTORY" not in result
    assert "카드 내역" in result
    assert "카드 전체 내역" not in result
    assert "id='card-upload-open'" in result
    assert "data-csrf='synthetic-csrf'" in result
    assert "0630_오제" in result
    assert "title='0630_오제'" in result


def test_initial_month_prompt_removed_but_month_selection_remains_accessible(card_db_path):
    result = cards_all.cards_all_page({'year': ['2026']}, db_path=card_db_path)
    assert '확인할 월을 선택해 줘.' not in result
    assert "class='card-all-prompt'" not in result
    assert '조회 조건' in result
    assert "aria-label='조회 기간'" in result and "value='2026-03'" in result


def test_search_without_month_renders_results_immediately(card_db_path):
    result = cards_all.cards_all_page(
        {'year': ['2026'], 'q': ['9800']}, db_path=card_db_path)
    assert "id='search-heading'" in result
    assert '검색 결과 · 0건' in result
    assert '9800' in result

    result = cards_all.cards_all_page(
        {'year': ['2026'], 'q': ['MERCURE']}, db_path=card_db_path)
    assert '검색 결과 · 1건' in result
    assert "data-tx-id='TX-A-01'" in result


def test_search_zero_results_is_explicit_and_changes_the_page(card_db_path):
    result = cards_all.cards_all_page(
        {'year': ['2026'], 'q': ['없는거래-검색-2026']}, db_path=card_db_path)
    assert '검색 결과 · 0건' in result
    assert '검색 결과가 없습니다' in result
    assert '없는거래-검색-2026' in result


def test_month_detail_empty_month(card_db_path):
    """Empty month shows appropriate message."""
    html = cards_all._month_detail(2026, 1, [], None, False, 0)
    assert '이 기간의 카드 거래가 없습니다.' in html
    assert '카드사 원본에도 없다는 뜻은 아니에요.' not in html


def test_render_month_rows_time_handling(card_db_path):
    """Rows correctly show date only when time is missing, date+time when present."""
    from webapp.cards_all import _render_month_rows

    items = [
        {'use_date': '2026-03-05T14:30', 'merchant': 'MERCURE', 'amount_krw': 150000,
         'foreign_currency': 'KRW', 'trip_id': 'T-A', 'classification_source': 'manual',
         'classification_state': 'booked', 'transaction_id': 'TX-01'},
        {'use_date': '2026-03-05', 'merchant': 'LAWSON', 'amount_krw': 8420,
         'foreign_currency': 'KRW', 'trip_id': 'T-B', 'classification_source': 'auto_inferred',
         'classification_state': 'booked', 'transaction_id': 'TX-02'},
        {'use_date': '', 'merchant': '', 'amount_krw': 5000,
         'foreign_currency': 'KRW', 'trip_id': '', 'classification_source': '',
         'classification_state': 'needs_review', 'transaction_id': 'TX-03'},
    ]

    html = _render_month_rows(items, include_detail_link=True)

    # First row has time
    assert '2026-03-05 14:30' in html
    # Second row has date only
    assert '2026-03-05' in html
    # Third row has no date
    # Merchant fallback
    assert '가맹점 미상' in html
    # Trip display logic
    assert '수동' in html
    assert '자동' in html
    assert '기타비용' in html
    # Foreign currency
    assert 'JPY' not in html  # Not in test data
    # Inline detail controls
    for tid in ('TX-01', 'TX-02', 'TX-03'):
        assert f"aria-controls='card-detail-{tid}'" in html


def test_undated_list_excludes_valid_other_years(card_db_path):
    """undated_list only returns truly undated, not valid dates from other years."""
    res = ct.undated_list(db_path=card_db_path, year=2026, per_page=100)
    ids = [i['transaction_id'] for i in res['items']]

    # Undated items included
    assert 'TX-UND-01' in ids
    assert 'TX-UND-02' in ids
    # Valid date from 2025 excluded
    assert 'TX-2025-01' not in ids


def test_year_summary_counts(card_db_path):
    """year_summary returns correct monthly counts and global undated.

    ISO date-time rows with valid calendar/time values belong to their calendar month.
    """
    s = ct.year_summary(db_path=card_db_path, year=2026)
    assert s['year'] == 2026
    assert s['months'][3] == 3  # March
    assert s['months'][4] == 2  # April
    # Only the two genuinely undated rows remain outside the month buckets.
    assert s.get('undated_count', 0) == 2


def test_pagination_stable_cursor(card_db_path):
    """Pagination with cursor works correctly, no missing/duplicate items."""
    # First page
    res1 = ct.list_for_month(db_path=card_db_path, year=2026, month=3, per_page=2)
    assert res1['count'] <= 2
    assert res1['has_more'] is True
    cursor1 = res1['cursor']

    # Second page
    res2 = ct.list_for_month(db_path=card_db_path, year=2026, month=3, cursor=cursor1, per_page=2)
    ids1 = [i['transaction_id'] for i in res1['items']]
    ids2 = [i['transaction_id'] for i in res2['items']]
    # No overlap
    assert not any(i in ids1 for i in ids2)
    # Combined should have all 3 March items
    all_ids = set(ids1 + ids2)
    assert 'TX-A-01' in all_ids
    assert 'TX-A-02' in all_ids
    assert 'TX-B-01' in all_ids


def test_cards_all_route_is_rendered_by_existing_router(card_db_path):
    """페이지 모듈은 핸들러를 만들지 않고 기존 라우터에서 렌더링된다."""
    import inspect
    from webapp.ledger_board import Handler
    source = inspect.getsource(Handler)
    assert 'parsed.path == "/cards/all"' in source
    assert 'cards_all.cards_all_page(' in source
    assert 'owner=owner' in source and 'csrf=CSRF_TOKEN if owner else ""' in source


def test_real_cards_all_handler_records_search_and_render_metrics(card_db_path, monkeypatch):
    import io
    import time
    from types import SimpleNamespace
    from app import request_metrics
    from webapp import ledger_board

    server = SimpleNamespace(store_lock=None, card_store=None)
    handler = object.__new__(ledger_board.Handler)
    handler.server = server
    handler.path = "/cards/all?year=2026&q=SYNTHETIC-SEARCH-MARKER"
    handler.headers = {}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: setattr(handler, "status", status)
    handler.send_header = lambda key, value: None
    handler.end_headers = lambda: None
    monkeypatch.setattr(ledger_board, "_get_card_db_path", lambda: card_db_path)
    monkeypatch.setattr(ledger_board, "ACCESS_ENFORCEMENT", False)
    before = request_metrics.summary()
    ledger_board.Handler.do_GET(handler)
    after = request_metrics.summary()
    added = {key: value for key, value in after.items()
             if key not in before or value["samples"] > before[key]["samples"]}
    assert handler.status == 200
    assert "SYNTHETIC-SEARCH-MARKER" in handler.wfile.getvalue().decode("utf-8")
    assert "card_search.card_search" in added
    assert "payload_serialize.payload_serialize" in added
    assert added["card_search.card_search"]["samples"] == before.get("card_search.card_search", {}).get("samples", 0) + 1
    assert after.get("first_render.first_render", {}).get("samples", 0) == before.get("first_render.first_render", {}).get("samples", 0)
    assert "db_lock_wait.db_lock_wait" not in added  # this test deliberately bypasses the lock decorator
    assert "SYNTHETIC-SEARCH-MARKER" not in str(added)


def test_real_cards_all_initial_render_records_once_and_excludes_send_time(card_db_path, monkeypatch):
    import io
    import time
    from types import SimpleNamespace
    from app import request_metrics
    from webapp import ledger_board

    # The delay belongs to this request, not the process-wide median of earlier tests.
    monkeypatch.setattr(request_metrics, '_REGISTRY', request_metrics.MetricsWindow())

    server = SimpleNamespace(store_lock=None, card_store=None)
    handler = object.__new__(ledger_board.Handler)
    handler.server = server
    handler.path = "/cards/all?year=2026"
    handler.headers = {}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: setattr(handler, "status", status)
    handler.send_header = lambda key, value: None
    handler.end_headers = lambda: None
    monkeypatch.setattr(ledger_board, "_get_card_db_path", lambda: card_db_path)
    monkeypatch.setattr(ledger_board, "ACCESS_ENFORCEMENT", False)
    from webapp import cards_all
    original = cards_all.cards_all_page

    def delayed_render(query, *, db_path=None, owner=False, csrf=''):
        time.sleep(0.04)
        return original(query, db_path=db_path, owner=owner, csrf=csrf)

    monkeypatch.setattr(cards_all, "cards_all_page", delayed_render)
    before = request_metrics.summary()
    ledger_board.Handler.do_GET(handler)
    after = request_metrics.summary()
    expected = before.get("first_render.first_render", {}).get("samples", 0) + 1
    assert after["first_render.first_render"]["samples"] == expected
    assert after["first_render.first_render"]["p50_ms"] >= 35
    assert after["payload_serialize.payload_serialize"]["samples"] == before.get(
        "payload_serialize.payload_serialize", {}).get("samples", 0) + 1


def test_browser_cards_all_fits_required_viewports_with_system_theme(card_db_path):
    from urllib.parse import parse_qs, urlsplit
    from unittest.mock import patch
    from webapp import ledger_board, ledger_design, site_shell
    from playwright.sync_api import sync_playwright, expect

    long_merchant = '합성 가맹점 ' * 18
    with sqlite3.connect(card_db_path) as conn:
        conn.execute("UPDATE transactions SET merchant=? WHERE transaction_id='TX-A-01'",
                     (long_merchant,))
        conn.execute("UPDATE transactions SET merchant='합성 숙박업체 ' || merchant, classification_state='needs_review', trip_id=?, display_tab_id='', classification_source='auto_inferred' WHERE transaction_id='TX-A-01'",
                     ('SYNTHETIC-TRIP',))
        conn.commit()
    conn.close()

    with patch.object(ledger_board, 'current_role', return_value='owner'), patch.object(
            ledger_design, 'nav_region', return_value=''), patch.object(
            ledger_board, 'live_trips', return_value=[{'tab_id': 'SYNTHETIC-TRIP', 'display_key': '합성 여행 이름이 매우 긴 샘플 여행 2026 여름 휴가 일정'}]):
        def serve_page(route):
            parsed = urlsplit(route.request.url)
            query = parse_qs(parsed.query)
            original = cards_all.cards_all_page(
                query, db_path=card_db_path, owner=True, csrf='synthetic-csrf')
            document = site_shell.wrap_document(original, parsed.path)
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body=document)

        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 375, 'height': 812})
                page.route('http://cost.test/cards/all*', serve_page)
                page.goto('http://cost.test/cards/all')
                for width in (375, 390, 759, 760, 1280):
                    page.set_viewport_size({'width': width, 'height': 812})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.emulate_media(color_scheme='dark')
                expect(page.locator(':root')).to_have_css('--shell-bg', '#0F172A')
                page.emulate_media(color_scheme='light')
                expect(page.locator(':root')).to_have_css('--shell-bg', '#F8FAFC')
                assert page.get_by_role('heading', name='거래').is_visible()
                upload_button = page.get_by_role('button', name='카드 업로드', exact=True)
                coverage_button = page.get_by_role('button', name='수집 현황', exact=True)
                assert upload_button.is_visible() and coverage_button.is_visible()
                assert upload_button.evaluate('(element) => element.getBoundingClientRect().height') >= 44
                assert upload_button.evaluate('(e) => getComputedStyle(e.parentElement).justifyContent') == 'flex-end'
                upload_button.focus()
                page.keyboard.press('Enter')
                expect(page.locator('#card-upload-panel')).to_be_visible()
                expect(page).to_have_url(re.compile(r'panel=upload'))
                assert page.locator('#card-upload-files').get_attribute('multiple') is not None
                assert page.locator('#card-upload-panel').evaluate(
                    "e => e.matches(':focus-visible') && getComputedStyle(e).outlineStyle !== 'none'")
                page.keyboard.press('Escape')
                expect(page.locator('#card-upload-panel')).to_be_hidden()
                assert page.evaluate('document.activeElement.id') == 'card-upload-open'
                page.route('**/api/cards/coverage/summary', lambda route: route.fulfill(
                    status=200, content_type='application/json',
                    body='{"available":true,"cards":[],"gaps":[],"files":[],"overview":{}}'))
                page.set_viewport_size({'width': 390, 'height': 812})
                coverage_button.click()
                expect(page.locator('#card-coverage-panel')).to_be_visible()
                header_actions = page.locator('#card-coverage-panel .card-workspace-panel-actions button')
                assert header_actions.count() == 2
                for button in header_actions.all():
                    box = button.bounding_box()
                    assert box and box['height'] >= 44 and box['x'] >= 0 and box['x'] + box['width'] <= 390
                    assert button.evaluate('(e) => getComputedStyle(e).whiteSpace') == 'nowrap'
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                period = page.get_by_label('조회 기간', exact=True)
                period.select_option('2026-03')
                expect(page.get_by_role('heading', name='2026년 3월 · 전체 3건')).to_be_visible()
                assert period.input_value() == '2026-03'
                period.select_option('2026')
                expect(page).to_have_url(re.compile(r'period=2026(?:&|$)'))
                expect(period).to_have_value('2026')

                page.set_viewport_size({'width': 1024, 'height': 812})
                page.evaluate('document.documentElement.style.zoom="200%"')
                page.goto('http://cost.test/cards/all?year=2026&month=3')
                assert page.get_by_role('heading', name='2026년 3월 · 전체 3건').is_visible()
                assert page.locator("tr[data-tx-id='TX-A-01']").is_visible()
                merchant_cell = page.locator("tr[data-tx-id='TX-A-01'] td.merchant")
                assert merchant_cell.get_attribute('title').endswith(long_merchant.strip())
                assert page.locator("tr[data-tx-id='TX-A-01'] .use-datetime").inner_text() == '5일'
                assert page.locator("tr[data-tx-id='TX-A-01'] .use-datetime").get_attribute('title') == '2026-03-05'
                assert page.locator("tr[data-tx-id='TX-A-02']").is_visible()
                assert page.locator("tr[data-tx-id='TX-B-01']").is_visible()
                assert page.locator('.card-all-row-toggle').count() == 3
                assert page.locator('.card-all-row-toggle.site-action-icon').count() == 0
                assert page.locator('.filter-bar select[name=period]').bounding_box()['y'] == page.locator('.filter-bar select[name=card]').bounding_box()['y']
                tx_row = page.locator("tr[data-tx-id='TX-A-01']")
                assert tx_row.locator('td.trip .card-all-trip-name').inner_text() == '합성 여행 이름이 매우 긴 샘플 여행 2026 여름 휴가 일정'
                assert tx_row.locator('td.trip .card-all-trip-source').inner_text() == '자동'
                assert tx_row.locator('td.merchant .card-identity').count() == 1
                assert tx_row.locator('td.trip .chip').count() == 1
                assert tx_row.locator('td.trip .card-identity, td.trip .card-all-badge').count() == 0
                assert tx_row.get_attribute('data-detail-id') == 'TX-A-01'
                assert tx_row.locator('.card-all-row-toggle').get_attribute('aria-expanded') == 'false'
                assert page.get_by_role('columnheader', name='상세', exact=True).count() == 0
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert period.is_visible()
                period.focus()
                assert period.evaluate('(el)=>el===document.activeElement')
                page.goto('http://cost.test/cards/all?year=2026')
                page.locator('.filter-bar input[name=q]').fill('8,420')
                page.get_by_role('button', name='조회', exact=True).click()
                expect(page.locator('#search-heading')).to_have_text('검색 결과 · 1건')
                assert page.locator("tr[data-tx-id='TX-A-02']").is_visible()
                for width in (320, 390, 760, 1280):
                    page.set_viewport_size({'width': width, 'height': 812})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    for selector in ('.filter-bar input[name=q]', 'select[name=card]', '.filter-bar button'):
                        box = page.locator(selector).bounding_box()
                        assert box['x'] >= 0 and box['x'] + box['width'] <= width
                page.locator('.filter-bar input[name=q]').fill('검색결과없음')
                page.get_by_role('button', name='조회', exact=True).click()
                expect(page.locator('#search-heading')).to_have_text('검색 결과 · 0건')
                expect(page.locator('.card-all-search-result')).to_contain_text('검색결과없음')
                assert page.locator('tr[data-tx-id]').count() == 0
                page.goto('http://cost.test/cards/all?year=2026&q=합성')
                assert page.locator('td.trip .card-all-trip-name').inner_text() == '합성 여행 이름이 매우 긴 샘플 여행 2026 여름 휴가 일정'
                page.goto('http://cost.test/cards/all?panel=upload')
                expect(page.locator('#card-upload-panel')).to_be_visible()
                assert page.get_by_role('heading', name='거래', exact=True).count() == 1
                expect(page.get_by_role('heading', name='업로드 후 확인', exact=True)).to_be_visible()
                page.locator("button[data-card-panel-close='upload']").click()
                expect(page).to_have_url('http://cost.test/cards/all')
                expect(page.get_by_role('heading', name='거래', exact=True)).to_be_visible()

                page.goto('http://cost.test/cards/all?cleanup_reason=recording&legacy_cleanup=1#expense-cleanup')
                expect(page).to_have_url('http://cost.test/cards/all')
                expect(page.get_by_role('heading', name='거래', exact=True)).to_be_visible()
            finally:
                browser.close()


def test_foreign_currency_display(card_db_path):
    """Foreign currency amounts display correctly."""
    from webapp.cards_all import _render_month_rows

    items = [
        {'use_date': '2026-03-05', 'merchant': 'TEST', 'amount_krw': 50000,
         'foreign_currency': 'JPY', 'foreign_amount': '5000',
         'trip_id': '', 'classification_source': '', 'classification_state': '',
         'transaction_id': 'TX-JPY'},
        {'use_date': '2026-03-05', 'merchant': 'TEST2', 'amount_krw': 100000,
         'foreign_currency': 'USD', 'foreign_amount': '100',
         'trip_id': '', 'classification_source': '', 'classification_state': '',
         'transaction_id': 'TX-USD'},
    ]

    html = _render_month_rows(items, include_detail_link=False)
    # Should show foreign currency code and amount
    assert 'JPY' in html
    assert 'USD' in html


def test_undated_page_has_total_and_next_cursor_without_overlap(monkeypatch):
    monkeypatch.setattr(cards_all._ct, 'card_options', lambda **kwargs: [])
    first_page = [{"transaction_id": f"TX-{i:03}", "approval_date": "2026-02-30",
                   "merchant": f"M{i}", "amount_krw": i, "foreign_currency": "KRW"}
                  for i in range(100)]
    later_page = [{"transaction_id": f"TX-{i:03}", "approval_date": "2026-13-01",
                   "merchant": f"M{i}", "amount_krw": i, "foreign_currency": "KRW"}
                  for i in range(100, 200)]
    calls = []

    def fake_undated_list(**kwargs):
        calls.append(kwargs)
        return {"items": first_page if kwargs["cursor"] is None else later_page,
                "total_count": 550, "count": 100, "has_more": True,
                "cursor": "0000-00-00|TX-099" if kwargs["cursor"] is None else "0000-00-00|TX-199"}

    monkeypatch.setattr(cards_all._ct, "undated_list", fake_undated_list)
    monkeypatch.setattr(cards_all._ct, "year_summary",
                        lambda **kwargs: {"year": kwargs["year"],
                                          "months": {month: 0 for month in range(1, 13)},
                                          "undated_count": 550})
    monkeypatch.setattr(cards_all._ct, "available_years",
                        lambda **kwargs: {"years": [2026], "default": 2026})
    page1 = cards_all.cards_all_page({"undated": ["1"]}, db_path="synthetic.sqlite")
    assert "이용일 원문 없음 · 550건" in page1
    assert "다음 이용일 원문 없음 거래 100건 보기" in page1
    assert "undated_cursor=0000-00-00%7CTX-099" in page1
    page2 = cards_all.cards_all_page({"undated": ["1"],
                                      "undated_cursor": ["0000-00-00|TX-099"]},
                                     db_path="synthetic.sqlite")
    first_ids = {f"TX-{i:03}" for i in range(100)}
    second_ids = {f"TX-{i:03}" for i in range(100, 200)}
    assert not first_ids.intersection(second_ids)
    assert "data-tx-id='TX-100'" in page2 and "data-tx-id='TX-099'" not in page2
    assert calls[0]["per_page"] == 100
    assert calls[1]["cursor"] == "0000-00-00|TX-099"


def test_data_integrity_all_states_preserved(card_db_path):
    """All financial states preserved in projection: booked, cancelled, needs_review, etc."""
    res = ct.list_for_month(db_path=card_db_path, year=2026, month=3, per_page=100)
    states = {i['classification_state'] for i in res['items']}
    sources = {i['classification_source'] for i in res['items']}

    assert 'booked' in states
    assert 'needs_review' in states
    assert 'manual' in sources
    assert 'auto_inferred' in sources

    # Undated has cancelled
    res_und = ct.undated_list(db_path=card_db_path, year=2026, per_page=100)
    states_und = {i['classification_state'] for i in res_und['items']}
    assert 'cancelled' in states_und


def test_readonly_no_writes(card_db_path):
    """Verify card_transactions module is read-only (mode=ro)."""
    # Connect to the card DB in read-only mode
    conn = ct._connect(card_db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO transactions (transaction_id, source_hash, batch_id, issuer, card_tail, card_kind, transaction_direction, transaction_kind, approval_number, original_approval_number, approval_date, posting_date, merchant, merchant_normalized, amount_krw, foreign_amount, foreign_currency, description_raw, row_index, raw_row_json, duplicate_of, conflict_reason, parse_error, classification_state, classification_source, classification_basis, item, description, display_tab_id, trip_id, revision, decided_at, created_at) VALUES ('TEST-WRITE', 'h', 'b', 'C', '1', 'c', 'd', 'k', 'a', 'a', '2026-01-01', '2026-01-01', 'm', 'm', 100, '', '', 'r', 1, '{}', '', '', '', 'n', '', '', '', '', '', 1, '', '2026-01-01')")
    finally:
        conn.close()


def test_missing_card_db_raises_config_error():
    """Missing card DB path raises RuntimeError."""
    old_env = os.environ.pop('WEBLEDGER_DB', None)
    try:
        with pytest.raises(RuntimeError, match="카드 원본 DB 경로가 설정되지 않았습니다"):
            ct.year_summary(year=2026)
    finally:
        if old_env:
            os.environ['WEBLEDGER_DB'] = old_env


def test_mode_ro_prevents_file_creation():
    """SQLite mode=ro prevents file creation on missing path."""
    missing_path = "/tmp/this_path_does_not_exist_12345.sqlite"
    assert not Path(missing_path).exists()
    with pytest.raises(sqlite3.OperationalError):
        ct._connect(missing_path)
    assert not Path(missing_path).exists()


def test_available_years_includes_2026(card_db_path):
    """available_years returns 2026 as default and other years with data."""
    res = ct.available_years(db_path=card_db_path)
    assert 2026 in res['years']
    assert 2025 in res['years']
    assert res['default'] == 2026


# Evidence path: this file + card_transactions projection + cards_all renderer
# Test coverage: renderers, data contracts, pagination, validation, read-only
# Run with: pytest webapp/tests/test_cards_all.py -v
