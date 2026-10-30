"""Synthetic rendering and responsive-contract checks for GEMN UI."""
from html.parser import HTMLParser

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
    cell = ui.status_cell({"status": "partial", "cost_count": 5, "google_count": 2})
    assert "<td" in cell and "role='status'" in cell
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


def test_desktop_visibility_is_css_viewport_only_at_900px():
    css = ui.styles()
    assert ".gemn-desktop{display:none}" in css
    assert "@media(min-width:900px)" in css
    assert ".gemn-desktop{display:block}" in css
    assert ".gemn-status-cell{display:table-cell}" in css
    assert "899px" not in css and "user-agent" not in css.casefold()
    for markup in (ui.header_cell(), ui.status_cell({"status": "matched"}),
                   ui.render_summary(STATE), ui.render_groups(STATE)):
        parser = _Tags()
        parser.feed(markup)
        assert any("gemn-desktop" in attrs.get("class", "") for _, attrs in parser.tags)
    # At 899px the default display rule hides every component, including details triggers;
    # at exactly 900px the media rule reveals them. This checks the browser CSS contract.
    assert "display:none" in css and "min-width:900px" in css


def test_unavailable_groups_do_not_render_false_zero_or_green_match():
    markup = ui.render_groups({"available": False, "reason": "snapshot stale", "groups": []})
    assert "snapshot stale" in markup
    assert "COST 지출 원행" not in markup
    assert "Google 지출 원행" not in markup
    assert "stale" in ui.render_summary({"available": False, "reason": "stale"})
