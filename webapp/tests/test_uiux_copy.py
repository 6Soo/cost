"""PR-1 copy and primary-action rendering checks.

These checks exercise the small render helpers owned by PR-1.  Internal state
keys remain unchanged; only the text emitted to a user is asserted here.
"""

from types import SimpleNamespace

from webapp import board_export_helpers, ledger_design, ota_catalog, trip_workflow
from webapp.card_flow import home_page


FORBIDDEN = ("보류", "분류대기", "미배정")


def _assert_no_forbidden(markup):
    assert not any(word in markup for word in FORBIDDEN), markup


def test_home_primary_uses_the_primary_background_rule(monkeypatch):
    class Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Conn:
        def execute(self, *_args):
            return SimpleNamespace(fetchone=lambda: (0, 0), fetchall=lambda: [])

    board = SimpleNamespace(
        conn=Conn(),
        _lock=Lock(),
        list_trips=lambda: [],
        visible_row_count=lambda: 0,
    )
    monkeypatch.setattr("app.reserve_trips.registrations", lambda _board: {})
    monkeypatch.setattr("app.reserve_trips.sync_status", lambda _board: {})
    monkeypatch.setattr("webapp.ledger_design.render", lambda value: value)
    monkeypatch.setattr("webapp.ledger_design.shell", lambda *args, **kwargs: kwargs["body"])

    markup = home_page(board)
    assert ".page-body a.btn.primary{background:var(--grn);" in markup
    assert "class='btn primary home-primary'" in markup


def test_trip_workflow_and_unclassified_heading_have_no_forbidden_copy(monkeypatch):
    monkeypatch.setattr(
        trip_workflow,
        "build_state",
        lambda *_args: {
            "closure": "open",
            "duplicate_copy": False,
            "google_available": False,
            "last_success_at": None,
            "displayed_holds": 1,
            "receipts": {"available": True, "count": 2, "held": 1},
            "trip_id": "trip-1",
        },
    )
    monkeypatch.setattr("webapp.trip_insurance_policy.domestic_trip", lambda _trip_id: False)
    workflow = trip_workflow.render(
        object(),
        "trip-1",
        [{"blocked": True, "row_id": "row-1", "item": "식비"}],
        {"available": False, "summary": {}},
    )
    _assert_no_forbidden(workflow)
    assert "trip-review-holds" not in workflow

    monkeypatch.setattr(ledger_design, "_context_badge", lambda: "")
    heading = ledger_design._head_html({"is_unclassified": True})
    _assert_no_forbidden(heading)
    assert "이전 귀속 목록" in heading


def test_export_summary_uses_user_safe_bucket_label():
    counts, _ = board_export_helpers.collect_export_page_summaries(
        [],
        list_tab_rows_fn=lambda _tab_id: [],
        row_needs_review_fn=lambda _row: False,
        row_has_conflict_fn=lambda _row: False,
    )
    assert counts[-1]["display_key"] == "이전 귀속 목록"
    _assert_no_forbidden(str(counts))


def test_ota_catalog_render_uses_connection_none_copy():
    data = {
        "rows": [{
            "provider": "agoda",
            "booking_ref": "BOOK-1",
            "booking_ref_display": "BOOK-1",
            "label": "합성 숙소",
            "period": "",
            "status": "예약 확정",
            "conflict": False,
            "trips": [],
            "reason": "no_stay",
            "card_count": 0,
            "card_candidates": [],
            "reservation_links": [],
        }],
        "all_count": 1,
        "unassigned_count": 1,
        "excluded_count": 0,
        "total": 1,
        "page": 1,
        "pages": 1,
        "months": [],
        "providers": ["agoda"],
        "warnings": [],
        "reasons": [{"label": "이용기간 없음", "count": 1}],
        "refresh_state": "ready",
    }
    markup = ota_catalog.render_html(data, {})
    _assert_no_forbidden(markup)
    assert markup.count("여행 연결 없음") >= 3
