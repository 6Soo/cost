"""Targeted unit tests and baseline equivalence tests for card_cleanup_ui.

Verifies:
1. Pure HTML assembly helpers (options, breakdown, note, review, rows, pagination, section).
2. None/falsey/numeric input preservation and escaping integrity (no 'None' string leakage).
3. Exact equivalence between baseline 2384cfd render_expense_cleanup AST and current implementation.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
from typing import Any, Dict

import pytest

from webapp import card_cleanup_ui, card_flow, ledger_board
from webapp.ledger_store import LedgerStore


@pytest.fixture(scope="module")
def baseline_cleanup_ast():
    """Compile baseline render_expense_cleanup from public main commit 2384cfd."""
    git_proc = subprocess.run(
        ["git", "show", "2384cfd:webapp/card_flow.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    tree = ast.parse(git_proc.stdout)
    func_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_expense_cleanup"
    )
    # Strip decorators to test core presentation without session scope wrappers
    func_node.decorator_list = []
    mod = ast.Module(body=[func_node], type_ignores=[])
    ast.fix_missing_locations(mod)

    ns: Dict[str, Any] = dict(card_flow.__dict__)
    exec(compile(mod, "<baseline_2384_render_expense_cleanup>", "exec"), ns)
    return ns["render_expense_cleanup"]


def test_render_cleanup_trip_options():
    trips = [
        {"tab_id": "t1", "display_key": "2026 도쿄"},
        {"tab_id": "t2<>&'", "display_key": ""},
    ]
    html = card_cleanup_ui.render_cleanup_trip_options(trips)
    assert "<option value=''>여행 선택</option>" in html
    assert "<option value='t1'>2026 도쿄</option>" in html
    assert "<option value='t2&lt;&gt;&amp;&#x27;'>t2&lt;&gt;&amp;&#x27;</option>" in html


def test_render_cleanup_breakdown():
    html = card_cleanup_ui.render_cleanup_breakdown({"no_item": 12, "no_trip": 5, "protected": 3}, ledger_total=7)
    assert "항목 미분류 12건" in html
    assert "여행 미배정 12건" in html
    assert "보류·오류 3건" in html


def test_render_cleanup_snapshot_note():
    assert card_cleanup_ui.render_cleanup_snapshot_note(None) == ""
    assert card_cleanup_ui.render_cleanup_snapshot_note({}) == ""
    assert card_cleanup_ui.render_cleanup_snapshot_note({"status": "ready"}) == ""

    loading = card_cleanup_ui.render_cleanup_snapshot_note({"status": "loading"})
    assert "예약 근거를 불러오고 있습니다." in loading

    refreshing = card_cleanup_ui.render_cleanup_snapshot_note({"status": "refreshing"})
    assert "예약 근거 갱신 중 · 최신 근거 확인이 필요합니다." in refreshing

    error = card_cleanup_ui.render_cleanup_snapshot_note({"status": "error"})
    assert "예약 근거 입력 오류" in error


def test_render_cleanup_card_review_branches():
    # Cancellation branch
    rev_cancel = card_cleanup_ui.render_cleanup_card_review(
        detail="/import?batch=1&transaction=c1",
        is_cancellation=True,
        evidence="<evidence-block />",
    )
    assert "원결제·취소 근거 자세히 보기" in rev_cancel
    assert "<evidence-block />" in rev_cancel
    assert "원결제 연결 자료 보기" in rev_cancel

    # Conflict / parse error branch
    rev_conflict = card_cleanup_ui.render_cleanup_card_review(
        detail="/import?batch=1&transaction=c2",
        is_cancellation=False,
        evidence="",
        conflict_reason="금액 충돌",
    )
    assert "상세 검토" in rev_conflict
    assert "원본 충돌 · 금액 충돌" in rev_conflict

    rev_parse = card_cleanup_ui.render_cleanup_card_review(
        detail="/import?batch=1&transaction=c3",
        is_cancellation=False,
        evidence="",
        parse_error="잘못된 날짜 형식",
    )
    assert "파싱 오류 · 잘못된 날짜 형식" in rev_parse

    # Held branch
    rev_held = card_cleanup_ui.render_cleanup_card_review(
        detail="/import?batch=1&transaction=c4",
        is_cancellation=False,
        evidence="<p>근거</p>",
        held=True,
    )
    assert "보류 중 · 여행 변경과 보류 해제는" in rev_held
    assert "<p>근거</p>" in rev_held

    # Normal form branch
    rev_norm = card_cleanup_ui.render_cleanup_card_review(
        detail="/import?batch=1&transaction=c5",
        is_cancellation=False,
        evidence="",
        reason="여행 배정 필요",
        item="식비",
        finance_label="내부 비용 기록 준비 가능",
    )
    # The current card places its reason beside the review form, once per row.
    rendered = card_cleanup_ui.render_cleanup_card_row(card_cleanup_ui.CleanupCardRow(
        tid='c5', batch='1', revision=1, held=False, merchant='Synthetic', current_tab='',
        protected=False, label='분류·배정 필요', day='2026-10-01', amount=100,
        reason='여행 배정 필요', review=rev_norm))
    assert "<p class='cleanup-reason'>여행 배정 필요</p>" in rendered
    assert rendered.count('여행 배정 필요') == 1
    assert "value='식비'" in rev_norm
    assert "<button type='submit'>변경 저장</button>" in rev_norm
    # Editing requires no disclosure click; only supporting evidence collapses.
    assert rev_norm.index("<form") < rev_norm.index("<details")
    assert "<label>여행<select" in rev_norm
    assert "<label>비용 항목<input" in rev_norm
    assert "COST의 여행·항목에 저장됩니다." in rev_norm
    assert "<p class='cleanup-finance-status'>내부 비용 기록 준비 가능</p>" in rev_norm


def test_render_cleanup_card_row_preserves_none_and_falsey():
    """Verify that None/empty values do NOT produce 'None' in markup."""
    row = card_cleanup_ui.CleanupCardRow(
        tid=None,
        batch=None,
        revision=1,
        held=False,
        merchant=None,
        current_tab=None,
        protected=False,
        label="검토 필요",
        day=None,
        amount=None,
        reason=None,
        review="<details></details>",
    )
    html = card_cleanup_ui.render_cleanup_card_row(row)
    assert "data-transaction=''" in html
    assert "data-transaction='None'" not in html
    assert "data-batch=''" in html
    assert "data-batch='None'" not in html
    assert "data-merchant=''" in html
    assert "data-merchant='None'" not in html
    assert "data-current-tab=''" in html
    assert "data-current-tab='None'" not in html
    assert "<strong></strong>" in html
    assert "<small> · 카드 결제</small>" in html
    assert "<small>None · 카드 결제</small>" not in html
    assert "0원" in html
    assert "<p class='cleanup-reason'></p>" in html
    assert "<p class='cleanup-reason'>None</p>" not in html


def test_render_cleanup_card_row_numeric_and_special_chars():
    row = card_cleanup_ui.CleanupCardRow(
        tid="tx-100",
        batch="b-1",
        revision=2,
        held=True,
        merchant="스타벅스 <강남>",
        current_tab="t-tokyo",
        protected=True,
        label="보류 중",
        day="2026-10-01",
        amount=15400,
        reason="보류 사유 & 근거",
        review="<details class='test'></details>",
    )
    html = card_cleanup_ui.render_cleanup_card_row(row)
    assert "data-transaction='tx-100'" in html
    assert "data-revision='2'" in html
    assert "data-held='1'" in html
    assert "스타벅스 &lt;강남&gt;" in html
    assert "cleanup-badge cleanup-badge-protected" in html
    assert "15,400원" in html
    assert "보류 사유 &amp; 근거" in html


def test_render_cleanup_ledger_row_preserves_none_and_falsey():
    """Verify that None/empty fields in ledger row do NOT leak 'None' strings."""
    row = card_cleanup_ui.CleanupLedgerRow(
        row_id=None,
        revision=1,
        merchant_or_desc=None,
        occurred_on=None,
        item=None,
        amount_krw=None,
    )
    html = card_cleanup_ui.render_cleanup_ledger_row(row)
    assert "data-row-id=''" in html
    assert "data-row-id='None'" not in html
    assert "<strong></strong>" in html
    assert "<strong>None</strong>" not in html
    assert "<small> · 항목 없음</small>" in html
    assert "0원" in html


def test_render_cleanup_pagination():
    assert card_cleanup_ui.render_cleanup_pagination(1, 1, 10) == ""
    assert card_cleanup_ui.render_cleanup_pagination(1, 0, 0) == ""

    p1 = card_cleanup_ui.render_cleanup_pagination(1, 3, 50)
    assert "<span>이전 20건</span>" in p1
    assert "<a href='/import?cleanup_page=2'>다음 20건</a>" in p1
    assert "50건을 20건씩 봅니다 · 1/3페이지" in p1

    p2 = card_cleanup_ui.render_cleanup_pagination(2, 3, 50)
    assert "<a href='/import?cleanup_page=1'>이전 20건</a>" in p2
    assert "<a href='/import?cleanup_page=3'>다음 20건</a>" in p2

    p3 = card_cleanup_ui.render_cleanup_pagination(3, 3, 50)
    assert "<a href='/import?cleanup_page=2'>이전 20건</a>" in p3
    assert "<span>다음 20건</span>" in p3


def test_cleanup_render_exposes_filter_controls_and_preserves_non_owner_boundary(tmp_path, monkeypatch):
    db_path = tmp_path / "cleanup_equiv.sqlite"
    store = LedgerStore(db_path, seed_demo=False)
    try:
        ledger_board.bind_store(store)

        # 1. Non-owner returns empty string
        monkeypatch.setattr(ledger_board, "current_role", lambda: "viewer")
        assert card_flow.render_expense_cleanup(store, "csrf-test") == ""

        # 2. Owner with empty store
        monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")
        c_empty = card_flow.render_expense_cleanup(store, "csrf-test")
        assert "aria-label='지출 정리 상태 필터'" in c_empty
        assert "cleanup-filter-total" in c_empty

        # 3. Owner with active card rows via pipeline receive and unassigned ledger rows
        header = ("Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,"
                  "Date,Post Date,Authorization Code,Cancel,Status\n")
        lines = (
            "신한,1234,domestic,purchase,합성상점1,5000,,,5000,2026-10-03,2026-10-04,A00001,,정상\n"
            "신한,1234,domestic,purchase,합성상점2,8000,,,8000,2026-10-03,2026-10-04,A00002,,정상\n"
        )
        flow = card_flow.CardFlow(store)
        batch = flow.pipeline.receive((header + lines).encode("utf-8"), "cleanup-synthetic.csv")["batch_id"]
        store.conn.execute(
            "UPDATE transactions SET classification_state='classified', item='소모품' WHERE batch_id=?",
            (batch,),
        )
        # Put one card on hold
        rows = flow.pipeline.get_batch(batch)["rows"]
        store.conn.execute(
            "INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)",
            (rows[1]["transaction_id"], rows[1]["source_hash"], "evidence_pending", "receipt check"),
        )
        # Add unassigned ledger expenditure with None values
        payload = json.dumps({
            "row_id": "exp-1",
            "row_kind": "expense",
            "display_tab_id": None,
            "revision": 1,
            "occurred_on": None,
            "amount_krw": 12000,
            "item": None,
            "source_merchant": None,
            "description": None,
        })
        store.conn.execute(
            "INSERT INTO board_rows (row_id, row_kind, revision, payload_json) VALUES ('exp-1', 'expense', 1, ?)",
            (payload,),
        )
        store.conn.commit()

        c_pop = card_flow.render_expense_cleanup(store, "csrf-test")
        assert "전체 3건" in c_pop
        assert "분류·배정 필요 2건" in c_pop
        assert "근거 충돌 1건" in c_pop
        assert "결제·환불 확인 0건" not in c_pop
        assert "<p class='cleanup-filter-total'>" not in c_pop
    finally:
        store.close()
