"""Targeted unit tests and baseline equivalence tests for refund_tab_ui.

Verifies:
1. Pure projection: assemble_refund_groups, filter_refund_groups.
2. Pure HTML assembly: line, card, summary, tab rendering.
3. Signed amounts formatting (positive, negative, zero).
4. Missing/None fields handling (date fallback, unassigned trips, escaping).
5. 1:N cancellation links and inferred status preservation.
6. Exact equivalence between baseline 22e134b refund_tab AST and current implementation.
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
from typing import Any, Dict

import pytest

from webapp import ledger_board, refund_tab, refund_tab_ui
from webapp.ledger_store import LedgerStore
from webapp.tests import test_refund_group_commit as fixtures


@pytest.fixture
def pair():
    case = fixtures.RefundGroupCommitTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


@pytest.fixture(scope="module")
def baseline_refund_tab_ast():
    """Compile baseline groups and render from public main commit 22e134b."""
    git_proc = subprocess.run(
        ["git", "show", "22e134b:webapp/refund_tab.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    tree = ast.parse(git_proc.stdout)
    mod = ast.Module(body=tree.body, type_ignores=[])
    ast.fix_missing_locations(mod)

    ns: Dict[str, Any] = dict(refund_tab.__dict__)
    exec(compile(mod, "<baseline_22e134b_refund_tab>", "exec"), ns)
    return ns


def test_assemble_refund_groups_1_to_n_and_sorting():
    sources = {
        "orig1": {"transaction_id": "orig1", "merchant": "Agoda", "amount_krw": 100000, "occurred_on": "2026-10-01", "item": "숙소"},
        "ref1": {"transaction_id": "ref1", "merchant": "Agoda", "amount_krw": -40000, "occurred_on": "2026-10-02", "item": "숙소"},
        "ref2": {"transaction_id": "ref2", "merchant": "Agoda", "amount_krw": -60000, "occurred_on": "2026-10-03", "item": "숙소"},
        # An unlinked refund
        "ref_unlinked": {"transaction_id": "ref_unlinked", "merchant": "Other", "amount_krw": -20000, "occurred_on": "2026-10-04", "item": "기타"},
        # Incomplete (partial) group: sum != 0
        "orig_partial": {"transaction_id": "orig_partial", "merchant": "Trip", "amount_krw": 50000, "occurred_on": "2026-10-05", "item": "항공"},
        "ref_partial": {"transaction_id": "ref_partial", "merchant": "Trip", "amount_krw": -20000, "occurred_on": "2026-10-06", "item": "항공"},
    }
    links = {
        "ref1": {"original_id": "orig1", "basis": "original_approval_number", "inferred": False},
        "ref2": {"original_id": "orig1", "basis": "original_approval_number", "inferred": False},
        "ref_partial": {"original_id": "orig_partial", "basis": "original_approval_number", "inferred": False},
    }

    groups = refund_tab_ui.assemble_refund_groups(sources, links)
    # Only orig1 group has net sum 0
    assert len(groups) == 1
    g = groups[0]
    assert len(g) == 3
    assert g[0]["transaction_id"] == "orig1"
    assert g[0]["amount_krw"] == 100000
    assert g[0]["inferred"] is False
    assert g[0]["refund_basis"] == "original_approval_number"
    assert {r["transaction_id"] for r in g[1:]} == {"ref1", "ref2"}


def test_assemble_refund_groups_preserved_periods_exclusion():
    sources = {
        "orig": {"transaction_id": "orig", "merchant": "Store", "amount_krw": 5000, "occurred_on": "2026-08-01", "item": "비용"},
        "ref": {"transaction_id": "ref", "merchant": "Store", "amount_krw": -5000, "occurred_on": "2026-08-02", "item": "비용"},
    }
    links = {"ref": {"original_id": "orig", "inferred": False}}

    # When is_preserved_fn returns True, group is omitted
    omitted = refund_tab_ui.assemble_refund_groups(sources, links, is_preserved_fn=lambda periods: True)
    assert omitted == []

    # When is_preserved_fn returns False, group is kept
    kept = refund_tab_ui.assemble_refund_groups(sources, links, is_preserved_fn=lambda periods: False)
    assert len(kept) == 1


def test_filter_refund_groups():
    g1 = [
        {"transaction_id": "tx1", "merchant": "스타벅스", "item": "음료", "occurred_on": "2026-10-01", "amount_krw": 10000},
        {"transaction_id": "ref1", "merchant": "스타벅스", "item": "음료", "occurred_on": "2026-10-02", "amount_krw": -10000},
    ]
    g2 = [
        {"transaction_id": "tx2", "merchant": "호텔", "item": "숙박", "occurred_on": "2026-10-05", "amount_krw": 80000},
        {"transaction_id": "ref2", "merchant": "호텔", "item": "숙박", "occurred_on": "2026-10-06", "amount_krw": -80000},
    ]
    all_groups = [g1, g2]

    # Empty query matches all
    assert refund_tab_ui.filter_refund_groups(all_groups, query="") == all_groups

    # Kind == 'in' clears all
    assert refund_tab_ui.filter_refund_groups(all_groups, kind="in") == []

    # Query merchant
    assert refund_tab_ui.filter_refund_groups(all_groups, query="스타벅스") == [g1]

    # Query item
    assert refund_tab_ui.filter_refund_groups(all_groups, query="숙박") == [g2]

    # Query saved description
    saved = {"tx1": {"description": "특별한 커피"}}
    assert refund_tab_ui.filter_refund_groups(all_groups, query="특별한", saved=saved) == [g1]


def test_render_refund_line_signed_amounts_and_escaping():
    orig_src = {
        "transaction_id": "tx1",
        "merchant": "상점 <A&B>",
        "amount_krw": 25000,
        "occurred_on": "2026-10-01",
        "item": "식비",
    }
    # Unrecorded original line
    line_orig = refund_tab_ui.render_refund_line(orig_src, index=0, row=None)
    assert "원결제 · 2026-10-01" in line_orig
    assert "<strong>25,000원</strong>" in line_orig
    assert "상점 &lt;A&amp;B&gt; · 식비" in line_orig
    assert "미기록" in line_orig
    assert "<a href='/import'>지출 정리</a>" in line_orig

    # Recorded refund line with negative amount and trip
    ref_src = {
        "transaction_id": "ref1",
        "merchant": "상점 <A&B>",
        "amount_krw": -25000,
        "occurred_on": None,  # Missing date fallback
        "item": "식비",
    }
    saved_row = {"row_id": "row-456", "item": "재정의 항목", "display_tab_id": "t1"}
    line_ref = refund_tab_ui.render_refund_line(ref_src, index=1, row=saved_row, trip_name="2026 도쿄")
    assert "환불 · 날짜 확인 필요" in line_ref
    assert "<strong>-25,000원</strong>" in line_ref
    assert "재정의 항목" in line_ref
    assert "장부 기록됨 · 2026 도쿄" in line_ref
    assert "<a href='/row?id=row-456&amp;back=%2Fboard%3Ftab%3Drefunds'>자료 검토</a>" in line_ref


def test_render_refund_card_titles_and_inferred():
    # 1. Full refund (net == 0)
    g_full = [
        {"transaction_id": "o", "amount_krw": 30000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -30000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_full = refund_tab_ui.render_refund_card(g_full)
    assert "<h2>전액 환불 · 순액 0원</h2>" in card_full

    # 2. Excess refund (net < 0)
    g_excess = [
        {"transaction_id": "o", "amount_krw": 20000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -30000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_excess = refund_tab_ui.render_refund_card(g_excess)
    assert "<h2>초과 환불 확인 필요 · 순액 -10,000원</h2>" in card_excess

    # 3. Partial refund (net > 0)
    g_partial = [
        {"transaction_id": "o", "amount_krw": 50000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -30000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_partial = refund_tab_ui.render_refund_card(g_partial)
    assert "<h2>부분 환불 · 순액 20,000원</h2>" in card_partial

    # 4. Inferred group
    g_inferred = [
        {"transaction_id": "o", "amount_krw": 15000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I", "inferred": True},
        {"transaction_id": "r", "amount_krw": -15000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_inferred = refund_tab_ui.render_refund_card(g_inferred)
    assert "<h2>원결제 추론 연결 · 기록 보류 · 환급 완료 아님 · 순액 0원</h2>" in card_inferred


def test_render_refund_summary_and_empty_tab():
    assert "<p>환불 쌍이 없습니다.</p>" in refund_tab_ui.render_refund_tab([])

    g = [
        {"transaction_id": "o", "amount_krw": 40000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -40000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    html = refund_tab_ui.render_refund_tab([g])
    assert "카드 환불 1쌍" in html
    assert "원결제 <b>40,000원</b>" in html
    assert "환불 <b>-40,000원</b>" in html
    assert "순액 <b>0원</b>" in html
    assert "<section class='refund-card'>" in html


def test_baseline_equivalence_with_22e134b(baseline_refund_tab_ast, pair, tmp_path):
    """Full differential test against 22e134b baseline across empty and populated stores."""
    # 1. Empty store before transactions table exists
    empty_db = tmp_path / "empty.sqlite"
    empty_store = LedgerStore(empty_db, seed_demo=False)
    try:
        base_empty = baseline_refund_tab_ast["render"](empty_store)
        curr_empty = refund_tab.render(empty_store)
        assert base_empty == curr_empty
        assert baseline_refund_tab_ast["groups"](empty_store) == refund_tab.groups(empty_store) == []
    finally:
        empty_store.close()

    # 2. Populated store via pair fixture
    store = pair.board
    conn = store.conn
    conn.execute(
        "UPDATE transactions SET transaction_direction='cancellation', amount_krw=-300000, "
        "original_approval_number='100' WHERE transaction_id=?",
        (pair.other,),
    )
    conn.commit()

    # Compare groups
    base_groups = baseline_refund_tab_ast["groups"](store)
    curr_groups = refund_tab.groups(store)
    assert base_groups == curr_groups

    # Compare render across default, query, and kind
    base_html = baseline_refund_tab_ast["render"](store)
    curr_html = refund_tab.render(store)
    assert base_html == curr_html

    assert baseline_refund_tab_ast["render"](store, query="합성항공") == refund_tab.render(store, query="합성항공")
    assert baseline_refund_tab_ast["render"](store, query="NonExistent") == refund_tab.render(store, query="NonExistent")
    assert baseline_refund_tab_ast["render"](store, kind="in") == refund_tab.render(store, kind="in")
    assert baseline_refund_tab_ast["render"](store, kind="out") == refund_tab.render(store, kind="out")
