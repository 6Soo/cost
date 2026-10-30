"""Synthetic rendering and responsive-contract checks for GEMN UI."""
from html.parser import HTMLParser

import pytest
from playwright.sync_api import sync_playwright

from webapp import expense_amount_group_ui as ui


STATE = {
    "available": True,
    "summary": {"matched": 1, "partial": 1, "unrecorded": 1, "google_only": 1},
    "groups": [{
        "status": "partial", "amount_krw": 50000, "cost_count": 2,
        "google_count": 3, "candidate_count": 6,
        "cost_rows": [{"row_id": 'c1"<script>', "description": "식사 <img src=x>"},
                      {"row_id": "c2", "date": "2026-10-01"}],
        "google_rows": [{"ref": 'A1" onmouseover="x', "payee": "다른 가맹점"},
                        {"ref": "B2"}, {"ref": "C3"}],
    }],
}


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_helpers_render_semantic_status_summary_and_candidate_lists_safely():
    annotation = {"status": "partial", "cost_count": 5, "google_count": 2, "group_id": 'unsafe"<id>'}
    cell = ui.status_cell(annotation)
    assert "<td" in cell and "<button" in cell and "data-gemn-group='gemn-group-" in cell
    assert "차이 3건" in cell and "개별 행" in cell
    assert "scope='col'" in ui.header_cell()
    summary = ui.render_summary({**STATE, "available": False, "reason": '<bad & stale', "last_success_at": "2026-10-30"})
    assert "비교 불가" in summary and "&lt;bad &amp; stale" in summary
    assert "2026-10-30" in summary

    rendered = ui.render_groups(STATE)
    assert "6개 관계" in rendered and "COST 지출 원행 (2건)" in rendered
    assert "Google 지출 원행 (3건)" in rendered
    assert "c1&amp;quot;&amp;lt;script&amp;gt;" not in rendered
    assert "c1" in rendered and "&lt;script&gt;" in rendered
    assert "식사 &lt;img src=x&gt;" in rendered
    assert 'A1&quot; onmouseover=&quot;x' in rendered
    assert "<script>" not in rendered and "<img" not in rendered
    assert rendered.count("<li>") == 5  # m+n records; never materialize m*n pairs.
    detail_parser = _Tags()
    detail_parser.feed(rendered)
    group_id = next(attrs["id"] for tag, attrs in detail_parser.tags if tag == "details")
    button_parser = _Tags()
    button_parser.feed(ui.status_cell({**STATE["groups"][0], "group_id": STATE["groups"][0].get("group_id")}))
    button = next(attrs for tag, attrs in button_parser.tags if tag == "button")
    # Reconcile fallback identity and ensure all emitted DOM identifiers are opaque safe tokens.
    assert group_id.startswith("gemn-group-") and group_id.replace("-", "").isalnum() and len(group_id) == len("gemn-group-") + 20
    assert button["data-gemn-group"].startswith("gemn-group-")
    assert button["aria-controls"] == button["data-gemn-group"]


def test_chromium_desktop_visibility_and_table_semantics_at_899_and_900px():
    css = ui.styles()
    assert "user-agent" not in css.casefold()
    annotation = {**STATE["groups"][0], "group_id": "opaque-key"}
    page_markup = ("<style>html{--shell-paper:#fff;--shell-ink:#111;--shell-muted:#555;"
                   "--shell-warn:#a50;--shell-accent:#070;--shell-line:#ddd}</style>"
                   f"{css}<table><thead><tr>{ui.header_cell()}</tr></thead><tbody><tr>"
                   f"<td>row</td>{ui.status_cell(annotation)}</tr></tbody></table>"
                   f"{ui.render_summary(STATE)}{ui.render_groups({**STATE, 'groups': [annotation]})}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(page_markup)
        for width, expected in ((899, "none"), (900, "table-cell")):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.locator("th.gemn-desktop").evaluate("e => getComputedStyle(e).display") == expected
            assert page.locator("td.gemn-status-cell").evaluate("e => getComputedStyle(e).display") == expected
            assert page.locator(".gemn-summary").evaluate("e => getComputedStyle(e).display") == ("none" if width == 899 else "flex")
            assert page.locator(".gemn-groups").evaluate("e => getComputedStyle(e).display") == ("none" if width == 899 else "block")
            assert page.locator(".gemn-group summary").evaluate("e => getComputedStyle(e).display") == ("none" if width == 899 else "flex")
        assert page.locator("th.gemn-desktop").evaluate("e => e.tagName") == "TH"
        assert page.locator("td.gemn-status-cell").evaluate("e => e.tagName") == "TD"
        assert page.locator(".gemn-status-button").get_attribute("data-gemn-group") == page.locator(".gemn-group").get_attribute("id")
        browser.close()


def test_unavailable_groups_do_not_render_false_zero_or_green_match():
    markup = ui.render_groups({"available": False, "reason": "snapshot stale", "groups": []})
    assert "snapshot stale" in markup
    assert "COST 지출 원행" not in markup
    assert "Google 지출 원행" not in markup
    assert "stale" in ui.render_summary({"available": False, "reason": "stale"})
