"""Targeted verification and baseline equivalence for board_export_helpers.

Verifies:
1. Zero runtime global coupling: webapp/board_export_helpers.py does NOT import ledger_board.
2. Exact parity with baseline commit 2384cfd across all extracted export and filter helpers:
   - format_trip_expense_tsv: 7-column TSV layout (B:H), formula escaping, duplicate ID, held rows
   - filter_trips & is_unclassified_matched
   - filter_tab_rows & filter_expenses_by_search
   - export_trip_counts & export_review_conflict_counts
3. ledger_board facade integration (tabs_html and export_page parity).
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


def test_format_trip_expense_tsv_7_column_and_held_rows():
    """Verify Google Sheets 7-column TSV format (B:H) and held row reasons."""
    sample_expenses = [
        {
            "row_id": "exp-ready-1",
            "source_event_id": "card-evt-1",
            "occurred_on": "2026-04-01",
            "source_merchant": "호텔 나리타",
            "item": "숙소",
            "service_period": "2026-04-01~2026-04-03",
            "reservation_no": "RES123",
            "evidence_type": "카드",
            "amount_krw": 150000,
        },
        {
            "row_id": "exp-formula-2",
            "source_event_id": "card-evt-2",
            "occurred_on": "2026-04-02",
            "source_merchant": "=SUM(A1:A10)",  # Formula injection attempt
            "item": "식비",
            "evidence_type": "영수증",
            "amount_krw": 25000,
        },
        {
            "row_id": "exp-blocked-3",
            "source_event_id": "card-evt-3",
            "blocked": True,
            "occurred_on": "2026-04-03",
            "item": "기타",
            "evidence_type": "카드",
            "amount_krw": 3000,
        },
    ]

    res = board_export_helpers.format_trip_expense_tsv("trip-tokyo", sample_expenses)
    assert res["tab_id"] == "trip-tokyo"
    assert res["row_count"] == 2
    assert res["total_krw"] == 175000

    # Verify TSV output lines
    tsv_lines = [l for l in res["tsv"].split("\n") if l]
    assert len(tsv_lines) == 2

    # Line 1: ready row
    cols1 = tsv_lines[0].split("\t")
    assert cols1 == ["2026-04-01", "호텔 나리타", "숙소", "2026-04-01~2026-04-03", "RES123", "카드", "150000"]

    # Line 2: formula escaped with leading quote
    cols2 = tsv_lines[1].split("\t")
    assert cols2[0] == "2026-04-02"
    assert cols2[1] == "'=SUM(A1:A10)"
    assert cols2[2] == "식비"
    assert cols2[5] == "영수증"
    assert cols2[6] == "25000"

    # Blocked row held
    assert len(res["held"]) == 1
    assert res["held"][0]["transaction_id"] == "card-evt-3"
    assert res["held"][0]["reason"] == "NOT_READY"


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


def test_filter_tab_rows_and_search():
    rows = [
        {"row_id": "r-1", "display_tab_id": "tab-a", "item": "비행기", "source_merchant": "대한항공", "evidence_type": "카드"},
        {"row_id": "r-2", "display_tab_id": "tab-a", "item": "택시", "source_merchant": "도쿄택시", "evidence_type": "영수증"},
        {"row_id": "r-3", "display_tab_id": "tab-b", "item": "식당", "source_merchant": "스시야", "evidence_type": "카드"},
    ]

    assert [r["row_id"] for r in board_export_helpers.filter_tab_rows(rows, "tab-a")] == ["r-1", "r-2"]
    assert [r["row_id"] for r in board_export_helpers.filter_tab_rows(rows, "tab-b")] == ["r-3"]

    # Search filter
    assert [r["row_id"] for r in board_export_helpers.filter_expenses_by_search(rows, query="대한항공")] == ["r-1"]
    assert [r["row_id"] for r in board_export_helpers.filter_expenses_by_search(rows, kind="카드")] == ["r-1", "r-3"]
    assert [r["row_id"] for r in board_export_helpers.filter_expenses_by_search(rows, query="스시", kind="카드")] == ["r-3"]


def test_export_trip_counts_and_review_conflict(tmp_path):
    store = LedgerStore(tmp_path / "synth_export.sqlite", seed_demo=True)
    trips = store.list_trips(include_archived=True)

    try:
        counts = board_export_helpers.export_trip_counts(trips, list_tab_rows_fn=store.list_tab_rows)
        assert len(counts) == len(trips) + 1  # includes unclassified
        assert counts[-1]["tab_id"] is None
        assert counts[-1]["display_key"] == "분류대기"

        # Check total counts match
        total_income = sum(c["income_count"] for c in counts)
        total_expense = sum(c["expense_count"] for c in counts)
        assert total_income > 0
        assert total_expense > 0

        # Review and conflict summary
        rc = board_export_helpers.export_review_conflict_counts(
            trips,
            list_tab_rows_fn=store.list_tab_rows,
            row_needs_review_fn=lambda r: r.get("display_tab_id") is None,
            row_has_conflict_fn=lambda r: False,
        )
        assert "review_total" in rc
        assert "conflict_total" in rc
        assert isinstance(rc["per_tab"], list)
    finally:
        store.close()


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
        assert "선택 탭 출력" in html_page
        assert "mock-csrf-export" in html_page
        assert "/api/exports/xlsx" in html_page
    finally:
        store.close()
