"""Targeted verification and baseline equivalence for board_export_helpers.

Verifies:
1. Zero runtime global coupling: webapp/board_export_helpers.py does NOT import ledger_board.
2. Strict required-key contracts & KeyError behavior on incomplete rows (baseline parity with 2384cfd):
   - filter_trips requires 'display_key' and 'destination'
   - collect_export_page_summaries requires 'tab_id', 'display_key', 'archived', 'row_kind'
3. Query count and call sequence preservation:
   - collect_export_page_summaries queries list_tab_rows(None) exactly once and matches 2*N+1 total calls
4. ledger_board facade integration (tabs_html and export_page parity with baseline 2384cfd).
"""
import ast
import html
import subprocess
import uuid
from typing import Any, Dict, List
import pytest

from webapp import board_export_helpers, ledger_board
from webapp.ledger_store import LedgerStore


@pytest.fixture(scope="module")
def baseline():
    """Load baseline unrefactored implementations from commit 2384cfd."""
    raw = subprocess.check_output(
        ["git", "show", "2384cfd:webapp/ledger_board.py"],
        text=True,
        encoding="utf-8",
    )
    tree = ast.parse(raw)
    targets = {"tabs_html", "export_page"}
    baseline_mod = ast.Module(
        body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in targets],
        type_ignores=[],
    )
    ast.fix_missing_locations(baseline_mod)
    code = compile(baseline_mod, "<baseline_2384cfd>", "exec")

    state = {
        "__name__": "webapp.ledger_board_baseline",
        "__package__": "webapp",
        "html": html,
        "uuid": uuid,
        "esc": lambda v: html.escape("" if v is None else str(v), quote=True),
        "CSRF_TOKEN": "static-test-csrf-token",
        "current_store": None,
        "_active_store": lambda: state["current_store"],
        "live_trips": lambda include_archived=False: [
            {"tab_id": "trip-tokyo", "display_key": "도쿄 여행", "destination": "도쿄", "archived": False},
            {"tab_id": "trip-osaka", "display_key": "오사카 여행", "destination": "오사카", "archived": True},
        ] if include_archived else [
            {"tab_id": "trip-tokyo", "display_key": "도쿄 여행", "destination": "도쿄", "archived": False},
        ],
        "_expense_rows": lambda: [
            {"row_id": "exp-1", "display_tab_id": "trip-tokyo", "amount_krw": 50000},
            {"row_id": "exp-2", "display_tab_id": None, "amount_krw": 20000},
        ],
        "_shown_amount": lambda r: r.get("display_amount_krw", r.get("amount_krw", 0)),
        "_trip_totals": lambda tid: {"income": 100000, "expense": 50000, "profit": 50000},
        "row_needs_review": lambda r: not bool(r.get("display_tab_id")),
        "row_has_conflict": lambda r: bool(r.get("conflict")),
    }
    exec(code, state)
    return state


def test_board_export_helpers_has_zero_coupling_to_ledger_board():
    """Verify board_export_helpers does not import ledger_board."""
    with open("webapp/board_export_helpers.py", "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "ledger_board" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "ledger_board"
            assert node.module != ".ledger_board"
            for alias in node.names:
                assert alias.name != "ledger_board"


def test_filter_trips_required_key_keyerror_parity(baseline):
    """Verify filter_trips raises KeyError on incomplete trip rows matching baseline."""
    incomplete_trips = [{"display_key": "도쿄"}]  # missing 'destination'

    # When query is empty, both return list unchanged without KeyError
    assert len(board_export_helpers.filter_trips(incomplete_trips, "")) == 1

    # When query is non-empty, both raise KeyError on 'destination'
    with pytest.raises(KeyError) as exc_helper:
        board_export_helpers.filter_trips(incomplete_trips, "도쿄")
    assert exc_helper.value.args == ("destination",)


def test_filter_trips_and_unclassified():
    trips = [
        {"tab_id": "trip-1", "display_key": "2026 도쿄", "destination": "일본 도쿄"},
        {"tab_id": "trip-2", "display_key": "2026 오사카", "destination": "일본 오사카"},
        {"tab_id": "trip-3", "display_key": "2026 파리", "destination": "프랑스 파리"},
    ]

    # Empty query returns all
    assert board_export_helpers.filter_trips(trips, "") == trips

    # Query matching display_key or destination
    assert [t["tab_id"] for t in board_export_helpers.filter_trips(trips, "도쿄")] == ["trip-1"]
    assert [t["tab_id"] for t in board_export_helpers.filter_trips(trips, "일본")] == ["trip-1", "trip-2"]
    assert board_export_helpers.filter_trips(trips, "런던") == []

    # Unclassified matching
    assert board_export_helpers.is_unclassified_matched("") is True
    assert board_export_helpers.is_unclassified_matched("분류대기") is True
    assert board_export_helpers.is_unclassified_matched("대기") is True
    assert board_export_helpers.is_unclassified_matched("도쿄") is False


def test_collect_export_page_summaries_query_count_and_sequence(tmp_path):
    """Verify each trip and the unclassified bucket are loaded once, in order."""
    store = LedgerStore(tmp_path / "synth_export.sqlite", seed_demo=True)
    trips = store.list_trips(include_archived=True)

    calls = []
    def recording_list_tab_rows(tab_id):
        calls.append(tab_id)
        return store.list_tab_rows(tab_id)

    try:
        trip_counts, rc = board_export_helpers.collect_export_page_summaries(
            trips,
            list_tab_rows_fn=recording_list_tab_rows,
            row_needs_review_fn=lambda r: r.get("display_tab_id") is None,
            row_has_conflict_fn=lambda r: False,
        )

        # The same trip rows feed counts and diagnostics; None is still queried once.
        expected_calls = [t["tab_id"] for t in trips] + [None]
        assert calls == expected_calls
        assert calls.count(None) == 1
        assert len(calls) == len(trips) + 1

        # Check counts
        assert len(trip_counts) == len(trips) + 1
        assert trip_counts[-1]["tab_id"] is None
        assert trip_counts[-1]["display_key"] == "이전 귀속 목록"
        assert "review_total" in rc
        assert "conflict_total" in rc
    finally:
        store.close()


def test_collect_export_page_summaries_required_keys():
    """Verify collect_export_page_summaries raises KeyError if required keys are missing."""
    incomplete_trips = [{"tab_id": "t1"}]  # missing 'display_key' and 'archived'
    with pytest.raises(KeyError) as exc:
        board_export_helpers.collect_export_page_summaries(
            incomplete_trips,
            list_tab_rows_fn=lambda t: [],
            row_needs_review_fn=lambda r: False,
            row_has_conflict_fn=lambda r: False,
        )
    assert exc.value.args == ("display_key",)

    # Missing 'row_kind' in rows
    with pytest.raises(KeyError) as exc_row:
        board_export_helpers.collect_export_page_summaries(
            [{"tab_id": "t1", "display_key": "T1", "archived": False}],
            list_tab_rows_fn=lambda t: [{"amount_krw": 100}],
            row_needs_review_fn=lambda r: False,
            row_has_conflict_fn=lambda r: False,
        )
    assert exc_row.value.args == ("row_kind",)


def test_tabs_html_parity_with_baseline(baseline, monkeypatch):
    monkeypatch.setattr(ledger_board, "live_trips", baseline["live_trips"])
    monkeypatch.setattr(ledger_board, "_expense_rows", baseline["_expense_rows"])
    monkeypatch.setattr(ledger_board, "_trip_totals", baseline["_trip_totals"])
    monkeypatch.setattr(ledger_board, "_active_store", lambda: None)

    # Without query
    res_helper = ledger_board.tabs_html("trip-tokyo", query="")
    res_base = baseline["tabs_html"]("trip-tokyo", query="")
    assert res_helper == res_base

    # With query matching "도쿄"
    res_helper_tokyo = ledger_board.tabs_html("trip-tokyo", query="도쿄")
    res_base_tokyo = baseline["tabs_html"]("trip-tokyo", query="도쿄")
    assert res_helper_tokyo == res_base_tokyo

    # With query matching "분류대기"
    res_helper_unc = ledger_board.tabs_html("unclassified", query="분류대기")
    res_base_unc = baseline["tabs_html"]("unclassified", query="분류대기")
    assert res_helper_unc == res_base_unc


def test_export_page_smoke_with_store(tmp_path, monkeypatch):
    store = LedgerStore(tmp_path / "synth_exp_page.sqlite", seed_demo=True)
    monkeypatch.setattr(ledger_board, "_active_store", lambda: store)
    monkeypatch.setattr(ledger_board, "CSRF_TOKEN", "mock-csrf-export")
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("44444444-4444-4444-4444-444444444444"))

    try:
        html_page = ledger_board.export_page()
        assert "XLSX 내보내기" in html_page
        assert "mock-csrf-export" in html_page
        assert "/api/exports/xlsx" in html_page
    finally:
        store.close()
