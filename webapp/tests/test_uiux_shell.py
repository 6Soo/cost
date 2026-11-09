"""Focused PR-1 checks for the shared shell and browser error pages."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import patch

from webapp import error_page, flight_passenger_page, insurance_income_match_page
from webapp import ledger_board


ROOT = Path(__file__).resolve().parents[2]


class _Handler:
    command = "GET"

    def __init__(self, accept):
        self.headers = {"Accept": accept}
        self.sent = []

    def _send(self, body, code=200):
        self.sent.append(("html", body, code))

    def _send_json(self, body, status=200):
        self.sent.append(("json", body, status))


def test_uxa03_server_and_client_do_not_reapply_pressed_trip_state():
    js = (ROOT / "webapp/static/js/site_shell.js").read_text(encoding="utf-8")
    design = (ROOT / "webapp/ledger_design.py").read_text(encoding="utf-8")
    css = (ROOT / "webapp/static/css/site_shell.css").read_text(encoding="utf-8")
    assert "cost-nav-trip" not in js
    assert "aria-pressed" not in js
    assert "aria-pressed" not in design
    assert ".nv[aria-current=page]" in css
    assert "aria-current=\\\"page\\\"" in design


def test_uxa04_content_negotiation_for_removed_page():
    browser = _Handler("text/html,application/xhtml+xml")
    assert insurance_income_match_page.dispatch(
        browser,
        urlsplit(insurance_income_match_page.PAGE_PATH),
        is_owner=True,
    )
    kind, body, status = browser.sent[0]
    assert kind == "html"
    assert status == 410
    assert "이 화면은 정리되었습니다" in body
    assert "href='/trips'" in body
    assert 'data-error-page="1"' in body

    api_client = _Handler("application/json")
    insurance_income_match_page.dispatch(
        api_client,
        urlsplit(insurance_income_match_page.PAGE_PATH),
        is_owner=True,
    )
    assert api_client.sent[0][0] == "json"
    assert api_client.sent[0][2] == 410


def test_uxa04_feature_disabled_page_keeps_api_json():
    browser = _Handler("text/html")
    with patch.object(flight_passenger_page, "enabled", return_value=False):
        flight_passenger_page.dispatch(
            browser,
            urlsplit("/flight-passengers"),
            is_owner=True,
            board=object(),
        )
    assert browser.sent[0][0] == "html"
    assert browser.sent[0][2] == 404
    assert "이 기능은 사용하도록 설정되지 않았습니다" in browser.sent[0][1]

    api = _Handler("text/html")
    with patch.object(flight_passenger_page, "enabled", return_value=False):
        flight_passenger_page.dispatch(
            api,
            urlsplit("/api/flight-passengers/candidates"),
            is_owner=True,
            board=object(),
        )
    assert api.sent[0][0] == "json"
    assert api.sent[0][2] == 404


def test_uxa06_profile_inputs_are_labelled_and_button_copy_is_updated():
    source = (ROOT / "webapp/ledger_board.py").read_text(encoding="utf-8")
    assert "<label for='owner-company-name'>회사명</label>" in source
    assert "id='owner-company-name'" in source
    assert "<label for='owner-assignee-name'>기본 담당자명</label>" in source
    assert "id='owner-assignee-name'" in source
    assert "기본 정보 저장" in source


def test_unclassified_copy_uses_connection_language_without_changing_contracts():
    source = (ROOT / "webapp/ledger_board.py").read_text(encoding="utf-8")
    for copy in (
        "여행 연결 해제",
        "여행 연결 없음: 수입",
        "내보내기에 포함되지 않습니다",
        "여행 연결 없음 목록 열기",
        "여행 연결 없음</option>",
    ):
        assert copy in source
    for legacy_copy in (
        "분류대기로 이동",
        "분류대기 열기",
        "분류대기 거래가 포함될 수 있습니다.",
        "분류대기: 수입",
    ):
        assert legacy_copy not in source
    assert '"classification_basis": "목적지 없음, 분류대기"' in source
    assert '"tab_id": "unclassified", "display_key": "분류대기"' in source


def test_uxa08_expense_page_has_one_main_heading_and_primary_save_button():
    page = ledger_board.expense_new_page()
    assert page.count("<main id='main'>") == 1
    assert page.count("<h1>") == 1
    assert "class='btn primary'" in page
    assert "background:#1D4ED8" not in page


def test_error_page_escapes_user_visible_values():
    document = error_page.render(404, "<제목>", "<메시지>", [("홈", "/?q=1&x=2")])
    assert "&lt;제목&gt;" in document
    assert "&lt;메시지&gt;" in document
    assert "href='/?q=1&amp;x=2'" in document
