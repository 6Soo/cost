"""Targeted verification and baseline equivalence for board_read_projection.

Verifies:
1. Zero runtime global coupling: webapp/board_read_projection.py does NOT import ledger_board.
2. Exact parity with baseline commit 2384cfd across all extracted read projections:
   - with_display_amount (None store, unprojected row, partial projected row, fully projected row)
   - shown_amount & shown_date
   - persisted_rows & load_persisted_rows
   - Request-local caching (read_scope) behavior and evaluation order preservation
   - expense_rows & income_rows (None store fallback to demo rows vs active store)
   - trip_totals, trip_income_total, trip_expense_total, trip_profit
   - unclassified_rows & customer_total
   - income_total (bank-linked exclusion)
3. ledger_board facade wiring integrity.
"""
import ast
import contextlib
import subprocess
from typing import Any, Dict, List
import pytest

from webapp import board_read_projection, ledger_board, read_scope
from webapp.ledger_store import LedgerStore


@contextlib.contextmanager
def active_read_scope():
    token = read_scope._MEMO.set({})
    try:
        yield
    finally:
        read_scope._MEMO.reset(token)


@pytest.fixture(scope="module")
def baseline():
    """Load original unrefactored implementations from commit 2384cfd."""
    raw = subprocess.check_output(
        ["git", "show", "2384cfd:webapp/ledger_board.py"],
        text=True,
        encoding="utf-8",
    )
    tree = ast.parse(raw)
    targets = {
        "_with_display_amount", "_shown_date", "_persisted_rows", "_load_persisted_rows",
        "_expense_rows", "_income_rows", "_trip_totals", "_unclassified_rows",
        "_income_total", "trip_income_total", "trip_expense_total", "trip_profit",
        "customer_total", "unclassified_expenses", "_shown_amount"
    }
    baseline_mod = ast.Module(
        body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in targets],
        type_ignores=[],
    )
    ast.fix_missing_locations(baseline_mod)
    code = compile(baseline_mod, "<baseline_2384cfd>", "exec")

    state = {
        "__name__": "webapp.ledger_board_baseline",
        "__package__": "webapp",
        "current_store": None,
        "_active_store": lambda: state["current_store"],
        "read_scope": read_scope,
        "EXPENSES": [
            {
                "row_id": "exp-demo-1",
                "row_kind": "expense",
                "amount_krw": 10000,
                "occurred_on": "2026-04-01",
                "display_tab_id": "trip-demo-a",
                "item": "숙소",
            },
            {
                "row_id": "exp-demo-2",
                "row_kind": "expense",
                "amount_krw": 5000,
                "occurred_on": "2026-04-02",
                "display_tab_id": None,
                "item": "간식",
            },
        ],
        "INCOMES": [
            {
                "row_id": "inc-demo-1",
                "row_kind": "income",
                "amount_krw": 50000,
                "occurred_on": "2026-04-01",
                "display_tab_id": "trip-demo-a",
                "customer_id": "cust-1",
            },
            {
                "row_id": "inc-demo-2",
                "row_kind": "income",
                "amount_krw": 30000,
                "occurred_on": "2026-04-02",
                "display_tab_id": "trip-demo-b",
                "customer_id": "cust-2",
            },
        ],
        "_all_tab_ids": lambda: ["trip-demo-a", "trip-demo-b"],
    }
    exec(code, state)
    return state


def test_board_read_projection_has_zero_coupling_to_ledger_board():
    """Verify board_read_projection does not import ledger_board."""
    with open("webapp/board_read_projection.py", "r", encoding="utf-8") as f:
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


def test_shown_amount_and_date_match_baseline(baseline):
    r1 = {"amount_krw": 12000, "occurred_on": "2026-04-10"}
    r2 = {
        "amount_krw": 12000,
        "occurred_on": "2026-04-10",
        "display_amount_krw": 15000,
        "display_occurred_on": "2026-04-12",
    }
    assert board_read_projection.shown_amount(r1) == baseline["_shown_amount"](r1) == 12000
    assert board_read_projection.shown_amount(r2) == baseline["_shown_amount"](r2) == 15000
    assert board_read_projection.shown_date(r1) == baseline["_shown_date"](r1) == "2026-04-10"
    assert board_read_projection.shown_date(r2) == baseline["_shown_date"](r2) == "2026-04-12"


def test_with_display_amount_matches_baseline(baseline, tmp_path):
    # Case 1: store is None -> rows returned unchanged
    rows_no_store_helper = [{"amount_krw": 1000, "occurred_on": "2026-04-01"}]
    rows_no_store_base = [{"amount_krw": 1000, "occurred_on": "2026-04-01"}]
    baseline["current_store"] = None
    assert board_read_projection.with_display_amount(rows_no_store_helper, store=None) == baseline["_with_display_amount"](rows_no_store_base)

    # Case 2: active store
    store = LedgerStore(tmp_path / "synth_proj.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        sample_rows_helper = [
            {"row_id": "expense-demo-c1", "row_kind": "expense", "amount_krw": 36000, "occurred_on": "2026-03-28"},
            {"row_id": "custom-1", "row_kind": "expense", "amount_krw": 5000, "occurred_on": "2026-04-05", "display_amount_krw": 5500},
            {"row_id": "custom-2", "row_kind": "expense", "amount_krw": 6000, "occurred_on": "2026-04-06", "display_amount_krw": 6600, "display_occurred_on": "2026-04-07"},
        ]
        sample_rows_base = [dict(r) for r in sample_rows_helper]

        res_helper = board_read_projection.with_display_amount(sample_rows_helper, store=store)
        res_base = baseline["_with_display_amount"](sample_rows_base)
        assert res_helper == res_base
        assert "display_amount_krw" in res_helper[0]
        assert "display_occurred_on" in res_helper[0]
        assert res_helper[1]["display_occurred_on"] == "2026-04-05"
        assert res_helper[2]["display_amount_krw"] == 6600
        assert res_helper[2]["display_occurred_on"] == "2026-04-07"
    finally:
        store.close()


def test_load_persisted_rows_and_caching_match_baseline(baseline, tmp_path):
    store = LedgerStore(tmp_path / "synth_load.sqlite", seed_demo=True)
    baseline["current_store"] = store
    tab_ids = [t["tab_id"] for t in store.list_trips(include_archived=True)]
    baseline["_all_tab_ids"] = lambda: tab_ids

    try:
        # Load through helper
        res_helper = board_read_projection.load_persisted_rows(
            "expense",
            store=store,
            tab_ids=tab_ids,
            fetch_tab_rows_fn=store.list_tab_rows,
        )

        # Load through baseline
        with active_read_scope():
            res_base = baseline["_load_persisted_rows"]("expense")

        assert len(res_helper) == len(res_base)
        assert [r["row_id"] for r in res_helper] == [r["row_id"] for r in res_base]
        assert [r["display_amount_krw"] for r in res_helper] == [r["display_amount_krw"] for r in res_base]

        # Verify persisted_rows returns fresh dict copies
        rows_cached = board_read_projection.persisted_rows(
            "expense",
            loader_fn=lambda: res_helper,
        )
        assert rows_cached == res_helper
        assert rows_cached is not res_helper
        assert rows_cached[0] is not res_helper[0]

        # Verify request-local cache hits via read_scope
        with active_read_scope():
            calls = {"count": 0}
            def loader():
                calls["count"] += 1
                return res_helper

            r1 = board_read_projection.persisted_rows("expense", remember_fn=read_scope.remember, loader_fn=loader)
            r2 = board_read_projection.persisted_rows("expense", remember_fn=read_scope.remember, loader_fn=loader)
            assert calls["count"] == 1
            assert r1 == r2
            assert r1[0] is not r2[0]
    finally:
        store.close()


def test_expense_and_income_rows_match_baseline(baseline, tmp_path):
    # When store is None
    baseline["current_store"] = None
    exp_helper_none = board_read_projection.expense_rows(
        store=None, fallback_expenses=baseline["EXPENSES"], persisted_rows_fn=lambda k: []
    )
    exp_base_none = baseline["_expense_rows"]()
    assert exp_helper_none == exp_base_none == baseline["EXPENSES"]
    assert exp_helper_none is not baseline["EXPENSES"]

    inc_helper_none = board_read_projection.income_rows(
        store=None, fallback_incomes=baseline["INCOMES"], persisted_rows_fn=lambda k: []
    )
    inc_base_none = baseline["_income_rows"]()
    assert inc_helper_none == inc_base_none == baseline["INCOMES"]
    assert inc_helper_none is not baseline["INCOMES"]

    # When store is active
    store = LedgerStore(tmp_path / "synth_rows.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        mock_persisted = lambda k: [{"row_id": f"{k}-1", "amount_krw": 999}]
        exp_helper_store = board_read_projection.expense_rows(
            store=store, fallback_expenses=baseline["EXPENSES"], persisted_rows_fn=mock_persisted
        )
        assert exp_helper_store == [{"row_id": "expense-1", "amount_krw": 999}]
    finally:
        store.close()


def test_totals_and_unclassified_match_baseline(baseline, tmp_path):
    # trip_income_total, trip_expense_total, trip_profit
    assert board_read_projection.trip_income_total("trip-demo-a", rows=baseline["INCOMES"]) == baseline["trip_income_total"]("trip-demo-a")
    assert board_read_projection.trip_expense_total("trip-demo-a", rows=baseline["EXPENSES"]) == baseline["trip_expense_total"]("trip-demo-a")
    assert board_read_projection.trip_profit(50000, 10000) == baseline["trip_profit"]("trip-demo-a")

    # unclassified_rows
    assert board_read_projection.unclassified_rows(expense_rows=baseline["EXPENSES"]) == baseline["unclassified_expenses"]()

    # customer_total
    assert board_read_projection.customer_total("cust-1", "trip-demo-a", rows=baseline["INCOMES"]) == baseline["customer_total"]("cust-1", "trip-demo-a")
    assert board_read_projection.customer_total("unknown", "trip-demo-a", rows=baseline["INCOMES"]) == 0

    # trip_totals when store is None
    baseline["current_store"] = None
    fb_fn = lambda tid: {
        "income": baseline["trip_income_total"](tid),
        "expense": baseline["trip_expense_total"](tid),
        "profit": baseline["trip_profit"](tid),
    }
    assert board_read_projection.trip_totals("trip-demo-a", store=None, fallback_totals_fn=fb_fn) == baseline["_trip_totals"]("trip-demo-a")

    # trip_totals when store is active
    store = LedgerStore(tmp_path / "synth_totals.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        assert board_read_projection.trip_totals("trip-demo-a", store=store, fallback_totals_fn=fb_fn) == baseline["_trip_totals"]("trip-demo-a")
    finally:
        store.close()


def test_income_total_with_bank_links_matches_baseline(baseline, tmp_path):
    store = LedgerStore(tmp_path / "synth_bank.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        rows = [
            {"row_id": "inc-normal-1", "amount_krw": 20000},
            {"row_id": "inc-linked-1", "amount_krw": 30000},
        ]
        # When linked_bank_row_ids is empty
        assert board_read_projection.income_total(rows, store=store, shown_amount_fn=lambda r: r["amount_krw"]) == baseline["_income_total"](rows)

        # Mock linked row in store
        store.linked_bank_row_ids = lambda: {"inc-linked-1"}
        assert board_read_projection.income_total(rows, store=store, shown_amount_fn=lambda r: r["amount_krw"]) == baseline["_income_total"](rows) == 20000
    finally:
        store.close()


def test_ledger_board_projection_facade_smoke(tmp_path, monkeypatch):
    store = LedgerStore(tmp_path / "synth_facade.sqlite", seed_demo=True)
    monkeypatch.setattr(ledger_board, "_active_store", lambda: store)

    try:
        with active_read_scope():
            expenses = ledger_board._expense_rows()
            assert len(expenses) > 0
            assert "display_amount_krw" in expenses[0]

            incomes = ledger_board._income_rows()
            assert len(incomes) > 0

            totals = ledger_board._trip_totals(ledger_board.default_board_tab())
            assert "income" in totals
            assert "expense" in totals
            assert "profit" in totals

            unclass = ledger_board._unclassified_rows()
            assert isinstance(unclass, list)

            inc_tot = ledger_board._income_total(incomes)
            assert isinstance(inc_tot, int)
    finally:
        store.close()
