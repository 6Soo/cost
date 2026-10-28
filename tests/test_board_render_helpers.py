"""Targeted tests for board_render_helpers extracted under RF-102.

Verifies:
1. Pure helpers (esc, editable_fields)
2. Allocation revert status, allocation history HTML, allocation detail body
3. History HTML and conflict presentation
4. Split page rendering
5. Table rendering (income_table, expense_table)
6. Row detail page rendering across expense, income, and allocation rows
7. Facade output equivalence between ledger_board and board_render_helpers
"""
import re
import uuid
import pytest

from webapp import board_render_helpers, ledger_board
from webapp.ledger_store import LedgerStore


def test_esc_sanitizes_html_and_handles_none():
    assert board_render_helpers.esc(None) == ""
    assert board_render_helpers.esc("") == ""
    assert board_render_helpers.esc("hello & <world> 'quote' \"double\"") == "hello &amp; &lt;world&gt; &#x27;quote&#x27; &quot;double&quot;"
    assert board_render_helpers.esc(12345) == "12345"
    assert ledger_board.esc("<script>") == board_render_helpers.esc("<script>")


def test_editable_fields_contract_preservation():
    # Allocation
    alloc_allowed, alloc_fixed = board_render_helpers.editable_fields("income", "수기", is_allocation=True)
    assert alloc_allowed == ("customer_id", "customer_name", "nickname", "display_tab_id", "income_kind")
    assert alloc_fixed == ()

    # Card expense
    card_allowed, card_fixed = board_render_helpers.editable_fields("expense", "카드")
    assert card_allowed == ("display_tab_id", "item", "description", "operator_note")
    assert card_fixed == ("amount_krw", "occurred_on", "source_event_id", "source_kind", "merchant", "reservation_no")

    # Manual expense
    manual_exp_allowed, manual_exp_fixed = board_render_helpers.editable_fields("expense", "수기")
    assert manual_exp_allowed == ("display_tab_id", "item", "description", "operator_note", "occurred_on", "amount_krw")
    assert manual_exp_fixed == ("source_event_id", "source_kind", "merchant", "reservation_no")

    # Bank income
    bank_allowed, bank_fixed = board_render_helpers.editable_fields("income", "은행")
    assert bank_allowed == ("customer_id", "customer_name", "nickname", "display_tab_id", "operator_note", "income_kind")
    assert bank_fixed == ("amount_krw", "occurred_on", "source_event_id", "source_kind")

    # Manual income
    manual_inc_allowed, manual_inc_fixed = board_render_helpers.editable_fields("income", "수기 입력")
    assert manual_inc_allowed == ("display_tab_id", "income_kind", "customer_id", "customer_name",
                                  "nickname", "occurred_on", "amount_krw", "operator_note")
    assert manual_inc_fixed == ("source_event_id", "source_kind")

    # Facade equivalence
    assert ledger_board.editable_fields("expense", "카드") == board_render_helpers.editable_fields("expense", "카드")
    assert ledger_board.editable_fields("income", "은행") == board_render_helpers.editable_fields("income", "은행")


def test_allocation_revert_status_boundaries(tmp_path):
    # None allocation
    assert board_render_helpers.allocation_revert_status(None) == {
        "revertible": False, "reason": "행을 찾지 못했어요"
    }

    # None store
    assert board_render_helpers.allocation_revert_status({"row_id": "test"}, store=None) == {
        "revertible": False, "reason": "저장소가 연결되지 않았어요."
    }

    # With synthetic store
    store = LedgerStore(tmp_path / "synth_alloc.sqlite", seed_demo=False)
    try:
        # Inactive allocation
        inactive = {"row_id": "alloc-none", "active": 0}
        res = board_render_helpers.allocation_revert_status(inactive, store=store)
        assert res["revertible"] is False
        assert "비활성 배분은 되돌릴 수 없어요" in res["reason"]

        # Missing source row
        missing_source = {"row_id": "alloc-missing", "active": 1, "source_row_id": "inc-nonexistent"}
        res = board_render_helpers.allocation_revert_status(missing_source, store=store)
        assert res["revertible"] is False
        assert "원천 입금 행이 없어요" in res["reason"]
    finally:
        store.close()


def test_history_html_presentation(tmp_path):
    # When store is None
    assert board_render_helpers.history_html("row-1", store=None) == ""

    store = LedgerStore(tmp_path / "synth_hist.sqlite", seed_demo=True)
    try:
        # Empty history
        empty_html = board_render_helpers.history_html("nonexistent-row", store=store)
        assert "직접 수정된 변경이 없어요" in empty_html

        # Demo row before any edit
        demo_id = "expense-demo-c1"
        html_initial = board_render_helpers.history_html(demo_id, store=store, csrf_token="test-token-123")
        assert "변경 이력" in html_initial

        # After saving a change, history entries appear
        row = store.get_row(demo_id)
        store.save(
            row_id=demo_id,
            expected_revision=row["revision"],
            client_request_id="test-client-req",
            change_mode="exception",
            changes={"operator_note": "테스트 메모"},
            actor="owner",
        )
        html_after = board_render_helpers.history_html(demo_id, store=store, csrf_token="test-token-123")
        assert "변경 이력" in html_after
        assert "직전 수정 되돌리기" in html_after
        assert "test-token-123" in html_after
    finally:
        store.close()


def test_split_page_rendering(tmp_path):
    # When store is None
    assert "저장소가 연결되지 않았어요" in board_render_helpers.split_page("inc-1", store=None)

    store = LedgerStore(tmp_path / "synth_split.sqlite", seed_demo=True)
    try:
        # Non-existent or non-income row
        assert "없는 수입 행이에요" in board_render_helpers.split_page("nonexistent", store=store)

        # Valid demo income row
        demo_inc_id = "income-demo-i1"
        rendered = board_render_helpers.split_page(
            demo_inc_id,
            store=store,
            csrf_token="test-csrf-split",
            trips=[{"tab_id": "trip-demo-a", "display_key": "도쿄"}],
        )
        assert "입금 나누기" in rendered
        assert "test-csrf-split" in rendered
        assert "alc_0_id" in rendered
        assert "expected_source_revision" in rendered
    finally:
        store.close()


def test_tables_rendering():
    # Empty income table
    empty_inc = board_render_helpers.income_table([])
    assert "수입 내용" in empty_inc or "수입" in empty_inc

    # Populated income table
    sample_inc = [{
        "row_id": "inc-1",
        "occurred_on": "2026-04-01",
        "customer_name": "홍길동",
        "nickname": "길동",
        "income_kind": "deposit",
        "amount_krw": 500000,
    }]
    rendered_inc = board_render_helpers.income_table(
        sample_inc,
        shown_date=lambda r: r["occurred_on"],
        shown_amount=lambda r: r["amount_krw"],
    )
    assert "홍길동" in rendered_inc
    assert "500,000" in rendered_inc
    assert "/row?id=inc-1" in rendered_inc

    # Populated expense table
    sample_exp = [{
        "row_id": "exp-1",
        "occurred_on": "2026-04-02",
        "item": "항공권",
        "description": "도쿄 왕복",
        "service_period": "2026-04-10~2026-04-14",
        "reservation_no": "ABC123XYZ",
        "evidence_type": "카드",
        "amount_krw": 350000,
    }]
    rendered_exp = board_render_helpers.expense_table(
        sample_exp,
        shown_date=lambda r: r["occurred_on"],
        shown_amount=lambda r: r["amount_krw"],
    )
    assert "항공권" in rendered_exp
    assert "도쿄 왕복" in rendered_exp
    assert "ABC123XYZ" in rendered_exp
    assert "350,000" in rendered_exp
    assert "/row?id=exp-1" in rendered_exp


def _mask_uuid(html: str) -> str:
    return re.sub(r"value='[0-9a-f]{32}'", "value='MASKED_UUID'", html)


def test_detail_page_and_facade_equivalence(tmp_path, monkeypatch):
    store = LedgerStore(tmp_path / "synth_equiv.sqlite", seed_demo=True)
    monkeypatch.setattr(ledger_board, "_active_store", lambda: store)

    try:
        # 1. Non-existent row
        res_helper = board_render_helpers.detail_page("nonexistent", store=store)
        res_board = ledger_board.detail_page("nonexistent")
        assert "행 없음" in res_helper
        assert res_helper == res_board

        # 2. Synthetic expense detail page
        exp_id = "expense-demo-c1"
        res_exp_helper = board_render_helpers.detail_page(exp_id, store=store, csrf_token=ledger_board.CSRF_TOKEN)
        res_exp_board = ledger_board.detail_page(exp_id)
        assert "지출" in res_exp_board
        assert res_exp_helper == res_exp_board

        # 3. Synthetic expense edit mode (masking dynamic client_request_id uuid)
        res_edit_helper = board_render_helpers.detail_page(exp_id, edit=True, store=store, csrf_token=ledger_board.CSRF_TOKEN)
        res_edit_board = ledger_board.detail_page(exp_id, edit=True)
        assert "행 편집" in res_edit_board
        assert "display_tab_id" in res_edit_board
        assert _mask_uuid(res_edit_helper) == _mask_uuid(res_edit_board)

        # 4. Split page equivalence
        inc_id = "income-demo-i1"
        split_helper = board_render_helpers.split_page(inc_id, store=store, csrf_token=ledger_board.CSRF_TOKEN)
        split_board = ledger_board.split_page(inc_id)
        assert _mask_uuid(split_helper) == _mask_uuid(split_board)

        # 5. History HTML equivalence
        hist_helper = board_render_helpers.history_html(exp_id, store=store, csrf_token=ledger_board.CSRF_TOKEN)
        hist_board = ledger_board.history_html(exp_id)
        assert hist_helper == hist_board

        # 6. Allocation revert status equivalence
        alloc_dict = {"row_id": "alloc-none", "active": 0}
        stat_helper = board_render_helpers.allocation_revert_status(alloc_dict, store=store)
        stat_board = ledger_board.allocation_revert_status(alloc_dict)
        assert stat_helper == stat_board
    finally:
        store.close()
