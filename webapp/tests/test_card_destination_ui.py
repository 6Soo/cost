"""Product behavior checks for the card destination only surface."""

from types import SimpleNamespace

from webapp import cards_all, ledger_design
from webapp.card_flow import home_page


def _row(**extra):
    row = {
        "transaction_id": "synthetic-1",
        "merchant": "Synthetic Cafe",
        "approval_date": "2026-05-12",
        "amount_krw": 123456,
        "card_label": "•••• 1234",
        "use_date": "2026-05-12",
        "trip_id": "",
        "display_tab_id": "",
        "classification_source": "code_inference",
    }
    row.update(extra)
    return row


def test_card_rows_render_destination_and_keep_source_evidence():
    html = cards_all._render_month_rows([_row(conflict_reason="source mismatch")],
                                        trip_names={}, year=2026, month=5)

    assert "\uae30\ud0c0\ube44\uc6a9" in html
    assert "\uc6d0\ubcf8 \ucda9\ub3cc" in html
    assert "\ubbf8\ubc30\uc815" not in html
    assert "\ubbf8\ubd84\ub958" not in html
    assert "\ucc98\ub9ac \ud544\uc694" not in html
    assert "my-actions" not in html
    assert "123,456원" in html


def test_home_and_sidebar_have_material_navigation_only(monkeypatch):
    class Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Conn:
        class Result:
            def __iter__(self):
                return iter(())

            def fetchone(self):
                return (3, 0)

            def fetchall(self):
                return []

        def execute(self, *_args):
            return self.Result()

    board = SimpleNamespace(
        conn=Conn(),
        _lock=Lock(),
        list_trips=lambda: [],
        visible_row_count=lambda: 2,
    )
    monkeypatch.setattr("app.reserve_trips.registrations", lambda _board: {})
    monkeypatch.setattr("app.reserve_trips.sync_status", lambda _board: {})
    monkeypatch.setattr("webapp.ledger_design.render", lambda value: value)
    monkeypatch.setattr("webapp.ledger_design.shell", lambda *args, **kwargs: kwargs["body"])

    home = home_page(board)
    assert "my-actions" not in home
    assert "\ub0b4 \ud655\uc778 \ud544\uc694" not in home
    assert "\uc9c1\uc811 \ub2f5\ud560 \uc791\uc5c5" not in home
    assert "\uce74\ub4dc \uc5c5\ub85c\ub4dc" in home

    monkeypatch.setattr(ledger_design.board, "current_role", lambda: "owner")
    sidebar = ledger_design._nav_html("", "", quick_view=True)
    assert "my-actions" not in sidebar
    assert "\ub0b4 \ud655\uc778 \ud544\uc694" not in sidebar
    assert "href='/cards/all'" in sidebar


def test_legacy_cleanup_is_reading_surface_without_queue_copy():
    breakdown = cards_all._status_badges(_row(duplicate_of="source-2"))
    assert "\uc911\ubcf5 \ucd9c\ucc98" in breakdown
    assert "review" not in breakdown
    assert "my-actions" not in breakdown
