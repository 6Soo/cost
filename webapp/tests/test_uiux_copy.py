"""PR-1 copy and primary-action rendering checks.

These checks exercise the small render helpers owned by PR-1.  Internal state
keys remain unchanged; only the text emitted to a user is asserted here.
"""

from types import SimpleNamespace
import re

from webapp import board_export_helpers, ledger_board, ledger_design, ota_catalog, receipt_review, refund_tab_ui, trip_workflow
from webapp import cards_all
from webapp.card_flow import home_page


FORBIDDEN = (
    "확인 필요", "확인필요", "보류", "분류대기", "분류 대기", "미배정", "미분류",
    "처리 필요", "처리필요", "내 확인", "웹 장부", "선택 탭 출력", "분류 검사 통과",
    "코드 추론", "OTA records",
)
CASUAL_ENDINGS = re.compile(r"(?:해요|어요|없어\.)")


def _assert_no_forbidden(markup):
    assert not any(word in markup for word in FORBIDDEN), markup
    assert not CASUAL_ENDINGS.search(markup), markup


def _shell_passthrough(monkeypatch):
    monkeypatch.setattr(ledger_design, "render", lambda value, **_kwargs: value)
    monkeypatch.setattr(ledger_design, "shell", lambda *args, **kwargs: kwargs["body"])


class _QueryResult(list):
    """PROC-072(#815) completed_period_sql iterates conn.execute(); other reads use fetchone/fetchall."""

    def fetchone(self):
        return (0, 0)

    def fetchall(self):
        return []


class _TripStore:
    conn = SimpleNamespace(execute=lambda *_args: SimpleNamespace(fetchone=lambda: None))

    def owner_profile(self):
        return {"company_name": "합성 회사", "assignee_name": "합성 담당자", "revision": 0}

    def trip_management_summaries(self):
        return {"trip-synth": {"income_count": 0, "income_total": 0,
                               "expense_count": 0, "expense_total": 0}}

    def pending_applications(self):
        return []

    def list_reservation_persons(self):
        return []

    def list_tab_rows(self, _tab_id):
        return []

    def conflicting_row_ids(self):
        return set()


def test_representative_rendered_pages_have_spec_copy(monkeypatch):
    """UXA-37/38: exercise representative HTML projections, not source grep only."""
    _shell_passthrough(monkeypatch)
    monkeypatch.setattr("app.reserve_trips.registrations", lambda _store: {})
    monkeypatch.setattr(ledger_board, "_active_store", lambda: _TripStore())
    monkeypatch.setattr(ledger_board, "live_trips", lambda include_archived=False: [{
        "tab_id": "trip-synth", "display_key": "합성여행", "display_title": "합성여행",
        "starts_on": "2026-08-01", "ends_on": "2026-08-03", "destination": "합성",
        "archived": False, "visual_closed": False, "deleted": False,
        "prepared_on": "", "prepared_by_name": "", "revision": 0,
        "owner_id": "owner", "owner_alias": "합성",
    }])
    home_board = SimpleNamespace(
        conn=SimpleNamespace(execute=lambda *_args: _QueryResult()),
        _lock=type("Lock", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_args: False})(),
        list_trips=lambda: [], visible_row_count=lambda: 0,
        trip_management_summaries=lambda: {},
    )
    monkeypatch.setattr("app.reserve_trips.sync_status", lambda _board: {})
    monkeypatch.setattr(ledger_board, "_active_store", lambda: None)
    export_html = ledger_board.export_page()
    monkeypatch.setattr(ledger_board, "_active_store", lambda: _TripStore())
    pages = [
        home_page(home_board),
        ledger_board.trips_page(),
        ledger_design._table_html([], kind="expense", selected="", unclassified=False),
        cards_all._error_page("카드 원본 DB를 확인해 주세요."),
        ota_catalog.render_html({
            "rows": [], "all_count": 0, "unassigned_count": 0, "excluded_count": 0,
            "total": 0, "page": 1, "pages": 1, "months": [], "providers": [],
            "warnings": [], "reasons": [], "refresh_state": "ready",
        }, {}),
        refund_tab_ui.render_refund_tab([]),
        receipt_review.render_html({"candidates": [], "holds": [], "images": [], "pdfs": [], "uploads": [], "drafts": []}, "csrf-synth"),
        export_html,
        ledger_board.access_control_render_owner_admin(None, _TripStore()),
    ]
    for page in pages:
        _assert_no_forbidden(page)


def test_home_primary_uses_the_primary_background_rule(monkeypatch):
    class Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Conn:
        def execute(self, *_args):
            return _QueryResult()

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
