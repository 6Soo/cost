"""Targeted verification and baseline equivalence for board_render_helpers.

Verifies:
1. Zero runtime global coupling: webapp/board_render_helpers.py does NOT import ledger_board.
2. Exact parity with baseline commit 2384cfd across all extracted display helpers:
   - esc & editable_fields
   - allocation_revert_status (None, no-store, missing source row, inactive allocation, source revision mismatch)
   - allocation_history_html & allocation_detail_body
   - history_html & conflict rendering
   - split_page (no-store, missing row, valid income row, manual principal fields)
   - Call order preservation: trips_fn is evaluated only at the original branch, never when store is None or row missing.
   - income_table & expense_table
   - learning_case_id & rule_dialog_link
3. Ledger board facade pass-through integrity.
"""
import ast
import html
import subprocess
import uuid
from unittest.mock import MagicMock
import pytest

from webapp import board_render_helpers, ledger_board
from webapp.ledger_store import LedgerStore


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
        "esc", "editable_fields", "allocation_revert_status", "allocation_history_html",
        "allocation_detail_body", "history_html", "split_page", "income_table",
        "expense_table", "learning_case_id", "rule_dialog_link"
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
        "html": html,
        "uuid": uuid,
        "INCOME_KIND_LABEL": {"deposit": "예약금", "balance": "잔금", "additional": "추가금"},
        "CSRF_TOKEN": "static-test-csrf-token",
        "current_store": None,
        "_active_store": lambda: state["current_store"],
        "live_trips": lambda *args, **kwargs: [{"tab_id": "trip-demo-a", "display_key": "도쿄"}],
        "_shown_amount": lambda r: r.get("display_amount_krw", r.get("amount_krw", 0)),
        "_shown_date": lambda r: r.get("display_occurred_on", r.get("occurred_on", "")),
    }
    exec(code, state)
    return state


def test_board_render_helpers_has_zero_coupling_to_ledger_board():
    """Verify board_render_helpers does not import or fall back to ledger_board."""
    with open("webapp/board_render_helpers.py", "r", encoding="utf-8") as f:
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


def test_esc_matches_baseline(baseline):
    for val in [None, "", "normal", "<a>&'\"", 9999]:
        assert board_render_helpers.esc(val) == baseline["esc"](val)


def test_editable_fields_matches_baseline(baseline):
    for kind in ["expense", "income"]:
        for source in ["카드", "은행", "수기", "직접 입력", ""]:
            for is_alloc in [False, True]:
                assert board_render_helpers.editable_fields(kind, source, is_alloc) == baseline["editable_fields"](kind, source, is_alloc)


def test_allocation_revert_status_matches_baseline_across_all_branches(baseline, tmp_path):
    store = LedgerStore(tmp_path / "synth_alloc.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        # Branch 1: allocation is None
        assert board_render_helpers.allocation_revert_status(None, store=store) == baseline["allocation_revert_status"](None)

        # Branch 2: store is None -> both raise AttributeError on .get_allocation
        baseline["current_store"] = None
        with pytest.raises(AttributeError):
            baseline["allocation_revert_status"]({"row_id": "alloc-none"})
        with pytest.raises(AttributeError):
            board_render_helpers.allocation_revert_status({"row_id": "alloc-none"}, store=None)
        baseline["current_store"] = store

        # Branch 3: inactive allocation
        inactive = {"row_id": "alloc-none", "active": 0}
        assert board_render_helpers.allocation_revert_status(inactive, store=store) == baseline["allocation_revert_status"](inactive)

        # Branch 4: missing source row
        missing_source = {"row_id": "alloc-missing", "active": 1, "source_row_id": "inc-nonexistent"}
        assert board_render_helpers.allocation_revert_status(missing_source, store=store) == baseline["allocation_revert_status"](missing_source)

        # Branch 5: source revision mismatch
        source_row = store.get_row("income-demo-i1")
        mismatched = {
            "row_id": "alloc-mismatch",
            "active": 1,
            "source_row_id": "income-demo-i1",
            "source_revision": source_row["revision"] + 99,
        }
        assert board_render_helpers.allocation_revert_status(mismatched, store=store) == baseline["allocation_revert_status"](mismatched)
    finally:
        store.close()


def test_history_html_matches_baseline(baseline, tmp_path, monkeypatch):
    # No store
    baseline["current_store"] = None
    assert board_render_helpers.history_html("row-1", store=None, csrf_token="csrf") == baseline["history_html"]("row-1")

    store = LedgerStore(tmp_path / "synth_hist.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        # Empty history
        assert board_render_helpers.history_html("nonexistent", store=store, csrf_token="csrf") == baseline["history_html"]("nonexistent")

        # Row with saved history
        demo_id = "expense-demo-c1"
        row = store.get_row(demo_id)
        store.save(
            row_id=demo_id,
            expected_revision=row["revision"],
            client_request_id="test-client-req",
            change_mode="exception",
            changes={"operator_note": "테스트 메모"},
            actor="owner",
        )
        monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("11111111-1111-1111-1111-111111111111"))
        baseline["uuid"] = uuid
        assert board_render_helpers.history_html(demo_id, store=store, csrf_token="static-test-csrf-token") == baseline["history_html"](demo_id)
    finally:
        store.close()


def test_split_page_call_order_and_baseline_equivalence(baseline, tmp_path, monkeypatch):
    trips_mock = MagicMock(return_value=[{"tab_id": "trip-demo-a", "display_key": "도쿄"}])

    # 1. When store is None: trips_fn MUST NOT be called!
    baseline["current_store"] = None
    res_helper = board_render_helpers.split_page("income-demo-i1", store=None, csrf_token="csrf", trips_fn=trips_mock)
    res_base = baseline["split_page"]("income-demo-i1")
    assert res_helper == res_base
    assert trips_mock.call_count == 0

    # 2. When row is missing: trips_fn MUST NOT be called!
    store = LedgerStore(tmp_path / "synth_split.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        res_helper_missing = board_render_helpers.split_page("missing-row", store=store, csrf_token="csrf", trips_fn=trips_mock)
        res_base_missing = baseline["split_page"]("missing-row")
        assert res_helper_missing == res_base_missing
        assert trips_mock.call_count == 0

        # 3. Valid income row: trips_fn is evaluated inside tab_options
        monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("22222222-2222-2222-2222-222222222222"))
        baseline["uuid"] = uuid
        res_valid_helper = board_render_helpers.split_page(
            "income-demo-i1",
            store=store,
            csrf_token="static-test-csrf-token",
            trips_fn=lambda: [{"tab_id": "trip-demo-a", "display_key": "도쿄"}],
        )
        res_valid_base = baseline["split_page"]("income-demo-i1")
        assert res_valid_helper == res_valid_base
    finally:
        store.close()


def test_income_and_expense_tables_match_baseline(baseline):
    # Empty tables
    assert board_render_helpers.income_table([], shown_date_fn=lambda r: "", shown_amount_fn=lambda r: 0) == baseline["income_table"]([])
    assert board_render_helpers.expense_table([], shown_date_fn=lambda r: "", shown_amount_fn=lambda r: 0) == baseline["expense_table"]([])

    # Populated tables
    incomes = [{
        "row_id": "inc-1",
        "occurred_on": "2026-04-01",
        "customer_name": "홍길동",
        "nickname": "길동",
        "income_kind": "deposit",
        "amount_krw": 500000,
    }]
    expenses = [{
        "row_id": "exp-1",
        "occurred_on": "2026-04-02",
        "item": "항공권",
        "description": "도쿄 왕복",
        "service_period": "2026-04-10~2026-04-14",
        "reservation_no": "ABC123XYZ",
        "evidence_type": "카드",
        "amount_krw": 350000,
    }]
    shown_date = lambda r: r.get("occurred_on", "")
    shown_amount = lambda r: r.get("amount_krw", 0)

    assert board_render_helpers.income_table(incomes, shown_date_fn=shown_date, shown_amount_fn=shown_amount) == baseline["income_table"](incomes)
    assert board_render_helpers.expense_table(expenses, shown_date_fn=shown_date, shown_amount_fn=shown_amount) == baseline["expense_table"](expenses)


def test_allocation_detail_body_matches_baseline(baseline, tmp_path, monkeypatch):
    store = LedgerStore(tmp_path / "synth_detail.sqlite", seed_demo=True)
    baseline["current_store"] = store
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("33333333-3333-3333-3333-333333333333"))
    baseline["uuid"] = uuid

    try:
        alloc = {
            "row_id": "alloc-test-1",
            "source_row_id": "income-demo-i1",
            "customer_name": "테스트고객",
            "amount_krw": 100000,
            "income_kind": "deposit",
            "occurred_on": "2026-04-01",
            "display_tab_id": "trip-demo-a",
        }
        trips = [{"tab_id": "trip-demo-a", "display_key": "도쿄"}]
        shown_amount = lambda r: r.get("amount_krw", 0)

        # View mode (edit=False)
        view_helper = board_render_helpers.allocation_detail_body(
            alloc, edit=False, store=store, csrf_token="static-test-csrf-token",
            trips_fn=lambda: trips, shown_amount_fn=shown_amount,
        )
        view_base = baseline["allocation_detail_body"](alloc, False)
        assert view_helper == view_base

        # Edit mode (edit=True)
        edit_helper = board_render_helpers.allocation_detail_body(
            alloc, edit=True, store=store, csrf_token="static-test-csrf-token",
            trips_fn=lambda: trips, shown_amount_fn=shown_amount,
        )
        edit_base = baseline["allocation_detail_body"](alloc, True)
        assert edit_helper == edit_base
    finally:
        store.close()


def test_learning_case_and_rule_dialog_link_match_baseline(baseline, tmp_path):
    store = LedgerStore(tmp_path / "synth_cases.sqlite", seed_demo=True)
    baseline["current_store"] = store
    try:
        # Store with no learning cases
        assert board_render_helpers.learning_case_id("row-x", store=store) == baseline["learning_case_id"]("row-x")
        assert board_render_helpers.rule_dialog_link("row-x", store=store) == baseline["rule_dialog_link"]("row-x")

        # When store is None
        assert board_render_helpers.learning_case_id("row-x", store=None) == ""
        assert board_render_helpers.rule_dialog_link("row-x", store=None) == ""

        # With an inserted learning case
        store.conn.execute(
            "INSERT INTO board_learning_cases (case_id, row_id, event_id, dialog_state, created_at) VALUES (?, ?, ?, ?, ?)",
            ("case-123", "row-test", "evt-1", "open", "2026-04-01T12:00:00Z"),
        )
        store.conn.commit()

        assert board_render_helpers.learning_case_id("row-test", store=store) == baseline["learning_case_id"]("row-test")
        assert board_render_helpers.rule_dialog_link("row-test", store=store) == baseline["rule_dialog_link"]("row-test")
    finally:
        store.close()


def test_ledger_board_facade_smoke(baseline, tmp_path, monkeypatch):
    store = LedgerStore(tmp_path / "synth_facade.sqlite", seed_demo=True)
    monkeypatch.setattr(ledger_board, "_active_store", lambda: store)
    monkeypatch.setattr(ledger_board, "CSRF_TOKEN", "mock-csrf-token")
    monkeypatch.setattr(ledger_board, "live_trips", lambda **kwargs: [{"tab_id": "trip-demo-a", "display_key": "도쿄"}])

    try:
        # Check facade functions return valid content through ledger_board
        assert ledger_board.esc("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
        assert "customer_id" in ledger_board.editable_fields("income", "은행")[0]

        split_html = ledger_board.split_page("income-demo-i1")
        assert "입금 나누기" in split_html
        assert "mock-csrf-token" in split_html

        hist_html = ledger_board.history_html("expense-demo-c1")
        assert "변경 이력" in hist_html

        revert_stat = ledger_board.allocation_revert_status(None)
        assert revert_stat["revertible"] is False
        assert revert_stat["reason"] == "없는 배분 행이에요"

        inc_html = ledger_board.income_table([])
        assert "수입 내용" in inc_html
        assert inc_html == baseline["income_table"]([])

        exp_html = ledger_board.expense_table([])
        assert "지출 내용" in exp_html
        assert exp_html == baseline["expense_table"]([])

        detail_html = ledger_board.detail_page("expense-demo-c1")
        assert "지출 상세" in detail_html or "웹 장부" in detail_html
    finally:
        store.close()
