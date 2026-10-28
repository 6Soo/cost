"""Targeted tests and baseline differential tests for webapp.board_learning_dialog.

Ensures:
1. webapp.board_learning_dialog has zero import coupling to ledger_board.
2. Exact parity with baseline commit 2384cfd for rule_scope_text, rule_hidden,
   and rule_dialog_page across all dialog states, preview scenarios, and edge cases.
3. ledger_board facade functions delegate cleanly to board_learning_dialog.
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
from typing import Any, Dict, Optional
import pytest

from webapp import board_learning_dialog, ledger_board, ledger_store


def test_zero_coupling_to_ledger_board():
    """Verify board_learning_dialog does not import ledger_board."""
    with open("webapp/board_learning_dialog.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="webapp/board_learning_dialog.py")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "ledger_board" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "ledger_board" not in node.module
            for alias in node.names:
                assert "ledger_board" not in alias.name


def _load_baseline_symbols():
    """Extract baseline functions from git commit 2384cfd:webapp/ledger_board.py."""
    code = subprocess.check_output(
        ["git", "show", "2384cfd:webapp/ledger_board.py"],
        text=True,
        encoding="utf-8",
    )
    # Baseline expects relative imports when executed as webapp.ledger_board_baseline
    ns: Dict[str, Any] = {
        "__name__": "webapp.ledger_board_baseline",
        "__package__": "webapp",
    }
    exec(compile(code, "<baseline:webapp/ledger_board.py>", "exec"), ns)
    return {
        "_rule_scope_text": ns["_rule_scope_text"],
        "_rule_hidden": ns["_rule_hidden"],
        "rule_dialog_page": ns["rule_dialog_page"],
        "CSRF_TOKEN": ns["CSRF_TOKEN"],
    }


def test_rule_scope_text_parity_with_baseline():
    baseline = _load_baseline_symbols()["_rule_scope_text"]

    test_rules = [
        {},
        {"conditions": {}},
        {
            "conditions": {
                "merchant_normalized": {"value": "STARBUCKS"},
            },
        },
        {
            "conditions": {
                "merchant_normalized": {"value": ["A", "B"]},
                "card_kind": {"value": "신용"},
                "transaction_direction": {"value": "국내"},
            },
            "optional_conditions": {
                "amount_range": "10,000 ~ 20,000",
                "date_or_service_period": "2026-05",
            },
            "effects": {
                "item": "식음료",
                "display_tab_id": "T2026_01",
                "description_template": "커피",
            },
            "scope": {
                "trip_id": "T2026_01",
                "event_year": 2026,
            },
        },
        {
            "conditions": {"merchant_normalized": {"value": "TEST"}},
            "effects": {"unknown_key": "val"},
        },
    ]

    for rule in test_rules:
        expected = baseline(rule)
        actual = board_learning_dialog.rule_scope_text(rule)
        assert actual == expected
        assert ledger_board._rule_scope_text(rule) == expected


def test_rule_hidden_parity_with_baseline():
    baseline = _load_baseline_symbols()
    baseline_rule_hidden = baseline["_rule_hidden"]
    baseline_csrf = baseline["CSRF_TOKEN"]

    cases = [
        ("case-1", "req-1", ""),
        ("case-2", "req-2", "<input type='hidden' name='rule_id' value='R1'>"),
        ("case<3>", "req&3", "<extra>"),
    ]

    for case_id, req_id, extra in cases:
        actual = board_learning_dialog.rule_hidden(case_id, req_id, csrf_token=baseline_csrf, extra=extra)
        expected = baseline_rule_hidden(case_id, req_id, extra=extra)
        assert actual == expected

    # Also check ledger_board._rule_hidden facade uses current CSRF_TOKEN
    facade_out = ledger_board._rule_hidden("c1", "r1", "<tag>")
    assert f"value='{ledger_board.CSRF_TOKEN}'" in facade_out
    assert "value='c1'" in facade_out
    assert "value='r1'" in facade_out
    assert "<tag>" in facade_out


def test_rule_dialog_page_parity_no_store():
    actual = board_learning_dialog.rule_dialog_page(
        "case-1", {}, store=None, csrf_token="test-csrf"
    )
    assert "저장소가 연결되지 않았어요" in actual

    orig_active = ledger_board._active_store
    try:
        ledger_board._active_store = lambda: None
        facade_out = ledger_board.rule_dialog_page("case-1", {})
        assert "저장소가 연결되지 않았어요" in facade_out
    finally:
        ledger_board._active_store = orig_active


def test_rule_dialog_page_parity_missing_row(tmp_path: Path):
    store = ledger_store.LedgerStore(tmp_path / "missing_row.sqlite", seed_demo=True)
    store.dialog_page_state = lambda case_id: {
        "row_id": "nonexistent-row",
        "dialog_state": "open",
    }
    actual = board_learning_dialog.rule_dialog_page(
        "case-1", {}, store=store, csrf_token="test-csrf"
    )
    assert "대화에 연결된 행이 없어요" in actual


def test_rule_dialog_page_comprehensive_differential(tmp_path: Path):
    """Exhaustive state differential between baseline and board_learning_dialog."""
    baseline_ns = _load_baseline_symbols()
    baseline = baseline_ns["rule_dialog_page"]
    baseline_csrf = baseline_ns["CSRF_TOKEN"]

    store = ledger_store.LedgerStore(tmp_path / "differential.sqlite", seed_demo=True)

    row = {
        "row_id": "R001",
        "item": "카페",
        "description": "스타벅스 라떼",
        "display_tab_id": "T2026_01",
        "revision": 2,
    }

    base_state = {
        "row_id": "R001",
        "dialog_state": "open",
        "conversation": {
            "active_provider": "gemini",
            "active_model_id": "gemini-2.5-flash",
            "turn_count": 2,
            "turns": [
                {
                    "turn_id": "turn-01",
                    "state": "suggested",
                    "state_label": "제안됨",
                    "adopted_provider": "gemini",
                    "reason_code": "high_confidence",
                    "switch_count": 0,
                    "owner_review": None,
                },
                {
                    "turn_id": "turn-02",
                    "state": "needs_review",
                    "state_label": "확인 필요",
                    "adopted_provider": None,
                    "reason_code": "user_override",
                    "switch_count": 1,
                    "owner_review": {"reason": "conflict"},
                },
            ],
        },
        "pending_draft": {
            "turn_id": "turn-02",
            "draft_error": {"message": "규칙 문법 오류"},
            "rule": {"conditions": {"merchant_normalized": {"value": "STARBUCKS"}}},
            "confirmed": False,
        },
        "rule": {
            "rule_id": "RULE-101",
            "version": 1,
            "status": "active",
            "rule": {
                "conditions": {"merchant_normalized": {"value": "STARBUCKS"}},
                "effects": {"item": "식음료"},
            },
        },
        "provider": {"is_real_call": True},
        "should_not_create_rule": False,
        "note": "업무상 미팅 커피",
        "questions": [
            {
                "question_id": "Q1",
                "question_key": "trip_move_reason",
                "prompt": "여행 탭으로 이동하는 이유를 알려주세요.",
                "answer": None,
                "options": [],
            },
            {
                "question_id": "Q2",
                "question_key": "card_usage_pattern",
                "prompt": "이 카드는 주로 어떤 용도인가요?",
                "answer": "business",
                "options": ["business", "personal"],
            },
            {
                "question_id": "Q3",
                "question_key": "tax_deductible",
                "prompt": "경비 처리 대상인가요?",
                "answer": None,
                "options": ["yes", "no"],
            },
        ],
        "open_questions": True,
        "last_preview": {
            "preview_id": "prev-abc-1234567890",
            "apply_existing": True,
            "apply_future": False,
            "plan": {
                "counts": {"included_rows": 3, "excluded_rows": 1, "matched_rows": 4},
                "amounts": {
                    "T2026_01": {"before": "15,000", "after": "25,000"},
                },
                "candidates": [
                    {"row_id": "R001", "from_tab_id": "T2026_01", "to_tab_id": "T2026_01", "amount_krw": "5,000"},
                    {"row_id": "R002", "from_tab_id": None, "to_tab_id": "T2026_01", "amount_krw": "10,000"},
                ],
                "excluded": [
                    {"row_id": "R003", "reason": "이미 정산 완료됨"},
                ],
            },
        },
    }

    variations = [
        # 1. Full state
        (base_state, {"msg": ["정상 처리되었습니다."]}),
        # 2. PREVIEW_STALE message
        (base_state, {"msg": ["PREVIEW_STALE"]}),
        # 3. Closed dialog
        (dict(base_state, dialog_state="closed"), {}),
        # 4. should_not_create_rule True
        (dict(base_state, should_not_create_rule=True), {}),
        # 5. Not started dialog, no turns, no pending, no rule, mock provider
        (
            {
                "row_id": "R001",
                "dialog_state": "not_started",
                "conversation": {},
                "pending_draft": {},
                "rule": None,
                "provider": {"is_real_call": False},
                "should_not_create_rule": False,
                "note": "",
                "questions": [],
                "open_questions": False,
                "last_preview": None,
            },
            {},
        ),
    ]

    for state_variant, query in variations:
        store.dialog_page_state = lambda case_id, s=state_variant: s
        store.get_row = lambda r_id, r=row: r if r_id == r.get("row_id") else None

        # Baseline execution
        baseline.__globals__["_active_store"] = lambda s=store: s
        expected = baseline("case-1", query)

        # Extracted module execution
        actual = board_learning_dialog.rule_dialog_page(
            "case-1", query, store=store, csrf_token=baseline_csrf
        )

        assert actual == expected

        # Also test ledger_board facade with delegation
        orig_active = ledger_board._active_store
        orig_csrf = ledger_board.CSRF_TOKEN
        try:
            ledger_board._active_store = lambda s=store: s
            ledger_board.CSRF_TOKEN = baseline_csrf
            facade_out = ledger_board.rule_dialog_page("case-1", query)
            assert facade_out == expected
        finally:
            ledger_board._active_store = orig_active
            ledger_board.CSRF_TOKEN = orig_csrf
