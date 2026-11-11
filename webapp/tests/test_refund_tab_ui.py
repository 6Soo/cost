"""Targeted unit tests and baseline equivalence tests for refund_tab_ui.

Verifies:
1. Pure projection: assemble_refund_groups, filter_refund_groups.
2. Pure HTML assembly: line, card, summary, tab rendering.
3. Decimal, float, int signed amounts formatting and None/missing error parity.
4. Missing/None fields handling (date fallback, unassigned trips, escaping).
5. 1:N cancellation links, identity preservation, and inferred status.
6. Financial projection equivalence with the baseline while the approved page shell evolves.
"""
from __future__ import annotations

import ast
from decimal import Decimal
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


def test_assemble_refund_groups_1_to_n_and_sorting_and_identity():
    ref1_dict = {"transaction_id": "ref1", "merchant": "Agoda", "amount_krw": -40000, "occurred_on": "2026-10-02", "item": "숙소"}
    ref2_dict = {"transaction_id": "ref2", "merchant": "Agoda", "amount_krw": -60000, "occurred_on": "2026-10-03", "item": "숙소"}
    sources = {
        "orig1": {"transaction_id": "orig1", "merchant": "Agoda", "amount_krw": 100000, "occurred_on": "2026-10-01", "item": "숙소"},
        "ref1": ref1_dict,
        "ref2": ref2_dict,
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
    # Object identity of refund row must be preserved (not copied)
    assert g[1] is ref1_dict
    assert g[2] is ref2_dict


def test_assemble_refund_groups_missing_keys_contract():
    # If original transaction is missing in sources, KeyError is raised
    sources = {"ref1": {"transaction_id": "ref1", "amount_krw": -5000, "occurred_on": "2026-10-01"}}
    links = {"ref1": {"original_id": "orig_missing"}}
    with pytest.raises(KeyError):
        refund_tab_ui.assemble_refund_groups(sources, links)

    # If amount_krw is missing in source, KeyError is raised during sum
    sources_no_amount = {
        "orig1": {"transaction_id": "orig1", "occurred_on": "2026-10-01"},
        "ref1": {"transaction_id": "ref1", "occurred_on": "2026-10-02"},
    }
    links = {"ref1": {"original_id": "orig1"}}
    with pytest.raises(KeyError):
        refund_tab_ui.assemble_refund_groups(sources_no_amount, links)


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

    # Kind == 'in' clears all after evaluating
    assert refund_tab_ui.filter_refund_groups(all_groups, kind="in") == []

    # Query merchant
    assert refund_tab_ui.filter_refund_groups(all_groups, query="스타벅스") == [g1]

    # Query item
    assert refund_tab_ui.filter_refund_groups(all_groups, query="숙박") == [g2]

    # Query saved description
    saved = {"tx1": {"description": "특별한 커피"}}
    assert refund_tab_ui.filter_refund_groups(all_groups, query="특별한", saved=saved) == [g1]

    # Query evaluation accesses transaction_id; missing transaction_id raises KeyError even if kind == 'in'
    bad_group = [[{"merchant": "M", "item": "I", "occurred_on": "2026-10-01"}]]
    with pytest.raises(KeyError):
        refund_tab_ui.filter_refund_groups(bad_group, query="X", kind="in", saved={})


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
    assert "<a href='/cards/all'>카드 거래 보기</a>" in line_orig

    # Recorded refund line with negative amount and trip
    ref_src = {
        "transaction_id": "ref1",
        "merchant": "상점 <A&B>",
        "amount_krw": -25000,
        "occurred_on": None,  # Missing date fallback
        "item": "식비",
    }
    saved_row = {"row_id": "row-456", "item": "재정의 항목", "display_tab_id": "t1"}
    line_ref = refund_tab_ui.render_refund_line(ref_src, index=1, row=saved_row, trip="2026 도쿄")
    assert "환불 · 이용일 원문 없음" in line_ref
    assert "<strong>-25,000원</strong>" in line_ref
    assert "재정의 항목" in line_ref
    assert "장부 기록됨 · 2026 도쿄" in line_ref
    assert "<a href='/row?id=row-456&amp;back=%2Fboard%3Ftab%3Drefunds'>자료 검토</a>" in line_ref

    # Decimal amount formatting contract
    dec_src = {
        "transaction_id": "ref2",
        "merchant": "환전",
        "amount_krw": Decimal("-1234567"),
        "occurred_on": "2026-10-02",
        "item": "환전",
    }
    line_dec = refund_tab_ui.render_refund_line(dec_src, index=1, row=None)
    assert "<strong>-1,234,567원</strong>" in line_dec

    # None amount raises TypeError identically to f'{None:,}원'
    none_amount_src = dict(orig_src, amount_krw=None)
    with pytest.raises(TypeError):
        refund_tab_ui.render_refund_line(none_amount_src, index=0)

    # None merchant raises AttributeError identically to html.escape(None)
    none_merchant_src = dict(orig_src, merchant=None)
    with pytest.raises(AttributeError):
        refund_tab_ui.render_refund_line(none_merchant_src, index=0)


def test_render_refund_card_titles_and_inferred():
    # 1. Full refund (net == 0)
    g_full = [
        {"transaction_id": "o", "amount_krw": 30000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -30000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_full = refund_tab_ui.render_refund_card(g_full)
    assert "<h2 class='ui-card__heading'>전액 환불 · 순액 0원</h2>" in card_full

    # 2. Excess refund (net < 0)
    g_excess = [
        {"transaction_id": "o", "amount_krw": 20000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -30000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_excess = refund_tab_ui.render_refund_card(g_excess)
    assert "<h2 class='ui-card__heading'>초과 환불 검토 필요 · 순액 -10,000원</h2>" in card_excess

    # 3. Partial refund (net > 0)
    g_partial = [
        {"transaction_id": "o", "amount_krw": 50000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -30000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_partial = refund_tab_ui.render_refund_card(g_partial)
    assert "<h2 class='ui-card__heading'>부분 환불 · 순액 20,000원</h2>" in card_partial

    # 4. Inferred group
    g_inferred = [
        {"transaction_id": "o", "amount_krw": 15000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I", "inferred": True},
        {"transaction_id": "r", "amount_krw": -15000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_inferred = refund_tab_ui.render_refund_card(g_inferred)
    assert "<h2 class='ui-card__heading'>원결제 추론 연결 · 기록 전 확인 · 환급 완료 아님 · 순액 0원</h2>" in card_inferred

    # 5. Decimal net amount in card
    g_dec = [
        {"transaction_id": "o", "amount_krw": Decimal("10000.5"), "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": Decimal("-10000.5"), "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    card_dec = refund_tab_ui.render_refund_card(g_dec)
    assert "<h2 class='ui-card__heading'>전액 환불 · 순액 0.0원</h2>" in card_dec


def test_render_refund_summary_and_empty_tab():
    empty_html = refund_tab_ui.render_refund_tab([])
    assert 'class="empty-state"' in empty_html
    assert '환불·취소 거래가 없습니다.' in empty_html

    g = [
        {"transaction_id": "o", "amount_krw": 40000, "occurred_on": "2026-10-01", "merchant": "M", "item": "I"},
        {"transaction_id": "r", "amount_krw": -40000, "occurred_on": "2026-10-02", "merchant": "M", "item": "I"},
    ]
    html = refund_tab_ui.render_refund_tab([g])
    assert "환불 쌍 1개" in html
    assert "<dt>원결제</dt><dd>40,000원</dd>" in html
    assert "<dt>환불</dt><dd>-40,000원</dd>" in html
    assert "<dt>순액</dt><dd>0원</dd>" in html
    assert "<section class='ui-card refund-card'>" in html
    assert "class='ui-card__heading'" in html
    assert "<style>" not in html
    assert 'class="empty-state"' in refund_tab_ui.render_refund_tab([])


def test_baseline_equivalence_with_22e134b(baseline_refund_tab_ast, pair, tmp_path, monkeypatch):
    """Keep the financial projection equal while allowing the approved new shell."""
    # 1. Empty store before transactions table exists
    empty_db = tmp_path / "empty.sqlite"
    empty_store = LedgerStore(empty_db, seed_demo=False)
    try:
        base_empty = baseline_refund_tab_ast["render"](empty_store)
        curr_empty = refund_tab.render(empty_store)
        assert baseline_refund_tab_ast["groups"](empty_store) == refund_tab.groups(empty_store) == []
        assert "<h1>거래</h1>" in curr_empty
        assert "환불 쌍 0개" in curr_empty
        assert "환불·취소 거래가 없습니다." in curr_empty
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

    # Compare the underlying projection for each filter. The page shell, empty
    # state, KPI labels, and classes intentionally changed in PR-5.
    cases = (("", ""), ("합성항공", ""), ("NonExistent", ""), ("", "in"), ("", "out"))
    # Exercise the recorded-row link as well as the unrecorded refund lines.
    saved_row = {'source_event_id': pair.original, 'row_id': 'synthetic-ledger-row',
                 'item': '항공료', 'display_tab_id': 'trip-synthetic'}
    monkeypatch.setattr(ledger_board, '_expense_rows', lambda: [saved_row])
    monkeypatch.setattr(ledger_board, 'live_trips',
                        lambda **kwargs: [{'tab_id': 'trip-synthetic', 'display_key': '합성여행'}])
    saved = {r.get('source_event_id'): r for r in ledger_board._expense_rows()}
    for query, kind in cases:
        base_groups = baseline_refund_tab_ast["groups"](store)
        expected = refund_tab_ui.filter_refund_groups(
            base_groups, query=query, kind=kind,
            saved=saved,
        )
        curr_html = refund_tab.render(store, query=query, kind=kind)
        base_html = baseline_refund_tab_ast["render"](store, query=query, kind=kind)
        import re

        def cards(markup):
            return re.findall(r"<section class='(?:ui-card )?refund-card'>.*?</section>", markup, re.S)

        def normalize_card(markup):
            return (_normalize_refund_ui(markup)
                    .replace('초과 환불 확인 필요', '초과 환불 검토 필요')
                    .replace('기록 보류', '기록 전 확인')
                    .replace('날짜 확인 필요', '이용일 원문 없음')
                    .replace("<a href='/import'>지출 정리</a>",
                             "<a href='/cards/all'>카드 거래 보기</a>"))

        assert [normalize_card(card) for card in cards(base_html)] == [
            normalize_card(card) for card in cards(curr_html)
        ]
        if expected:
            assert '/row?id=synthetic-ledger-row' in curr_html
        assert f"환불 쌍 {len(expected)}개" in curr_html
        assert curr_html.count("class='ui-card refund-card'") == len(expected)
        assert "<h1>거래</h1>" in curr_html


def _normalize_refund_ui(markup):
    """Ignore only the intentional shared-class and inline-style migration."""
    import re

    markup = re.sub(r"<style>.*?</style>", "", markup)
    return (markup.replace(" class='refund-card'", "")
            .replace(" class='ui-card refund-card'", "")
            .replace(" class='ui-card__heading'", "")
            .replace(" class='ui-state'", ""))
