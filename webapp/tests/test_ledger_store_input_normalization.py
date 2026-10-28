"""Synthetic tests for RF-101 pure create input normalization and validation extraction.

Verifies:
- Differential comparison against base commit 2384cfd
- Zero presentation/UI layer imports (no ledger_board or reverse store imports)
- Direct income create input required keys, types, date, request_id validations
- Manual expense create input required keys, payment method/evidence_type, types, date validations
- Canonical input normalization (_normalize_create_input)
- Record building schema correctness
- Facade integration and idempotency replay via LedgerStore
"""
from __future__ import annotations

import ast
import decimal
import inspect
import subprocess
from typing import Any

import pytest

import webapp.ledger_store as ls_module
from webapp.ledger_store import LedgerStore, SaveError
from webapp.ledger_store_input_normalization import (
    build_direct_income_record,
    build_manual_expense_record,
    normalize_create_input,
    validate_direct_income_create_input,
    validate_manual_expense_create_input,
)


def _load_base_2384cfd_normalize_create_input():
    p = subprocess.run(
        ["git", "show", "2384cfd:webapp/ledger_store.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    src = p.stdout

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_normalize_create_input":
            break

    import json
    from webapp.ledger_store_audit import canonical_json

    ns = {
        "json": json,
        "_canonical": canonical_json,
    }
    code = (
        "def base_normalize(fields: dict) -> dict:\n"
        + "\n".join("    " + line for line in ast.get_source_segment(src, node).splitlines()[1:])
    )
    exec(code, ns)
    return ns["base_normalize"]


def test_zero_presentation_dependency_in_input_normalization_module():
    """Verify that ledger_store_input_normalization has zero presentation imports."""
    import webapp.ledger_store_input_normalization as mod

    source = inspect.getsource(mod)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "ledger_board" not in alias.name, f"Forbidden import: {alias.name}"
                assert "ledger_store" not in alias.name, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "ledger_board" not in node.module, f"Forbidden import: {node.module}"
                assert "ledger_store" != node.module.split(".")[-1], f"Forbidden import: {node.module}"


def test_normalize_create_input_differential_with_base_2384cfd():
    """Verify normalize_create_input produces exact output matching base commit."""
    base_fn = _load_base_2384cfd_normalize_create_input()

    sample_inputs = [
        {},
        {"a": 1, "b": "hello", "c": None},
        {"display_tab_id": "tab-1", "amount_krw": 50000, "memo": ""},
        {"z": True, "y": False, "x": None, "arr": [1, 2, 3]},
    ]

    for sample in sample_inputs:
        base_out = base_fn(sample)
        new_out = normalize_create_input(sample)
        facade_out = ls_module._normalize_create_input(sample)
        assert new_out == base_out
        assert facade_out == base_out


def test_validate_direct_income_create_input_differential():
    """Verify direct income creation validations and error messages."""
    req_id = "req-direct-inc-1234567890"

    # 1. Required keys order
    valid_fields = {
        "display_tab_id": "tab-1",
        "occurred_on": "2026-10-28",
        "amount_krw": 25000,
        "income_kind": "deposit",
    }

    for key in ("display_tab_id", "occurred_on", "amount_krw", "income_kind"):
        bad_fields = dict(valid_fields)
        del bad_fields[key]
        with pytest.raises(SaveError) as exc:
            validate_direct_income_create_input(bad_fields, req_id)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == f"{key}가 필요해요"

    # 2. income_kind options
    bad_kind = dict(valid_fields, income_kind="unknown")
    with pytest.raises(SaveError) as exc:
        validate_direct_income_create_input(bad_kind, req_id)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "입금 종류를 골라 주세요"

    for good_kind in ("deposit", "balance", "additional"):
        ok_fields = dict(valid_fields, income_kind=good_kind)
        row_id, want_input = validate_direct_income_create_input(ok_fields, req_id)
        assert row_id == f"inc-{req_id[:16]}"
        assert want_input == normalize_create_input(ok_fields)

    # 3. amount_krw type constraints
    for bad_amt in (True, False, 100.5, decimal.Decimal("100"), "5000"):
        bad_amt_fields = dict(valid_fields, amount_krw=bad_amt)
        with pytest.raises(SaveError) as exc:
            validate_direct_income_create_input(bad_amt_fields, req_id)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "금액은 정수 원화로 입력해 주세요"

    # 4. occurred_on date format
    for bad_date in ("2026/10/28", "2026-02-31", "not-date", 12345):
        bad_date_fields = dict(valid_fields, occurred_on=bad_date)
        with pytest.raises(SaveError) as exc:
            validate_direct_income_create_input(bad_date_fields, req_id)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "날짜 형식이 달라요"

    # 5. client_request_id
    for bad_req in ("", None, 12345):
        with pytest.raises(SaveError) as exc:
            validate_direct_income_create_input(valid_fields, bad_req)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "요청 ID가 필요해요"


def test_validate_manual_expense_create_input_differential():
    """Verify manual expense creation validations and error messages."""
    req_id = "req-manual-exp-1234567890"

    valid_fields = {
        "display_tab_id": "tab-1",
        "occurred_on": "2026-10-28",
        "amount_krw": 12000,
        "item": "식비",
        "pay_method": "현금",
    }

    # 1. Required keys order
    for key in ("display_tab_id", "occurred_on", "amount_krw", "item"):
        bad_fields = dict(valid_fields)
        del bad_fields[key]
        with pytest.raises(SaveError) as exc:
            validate_manual_expense_create_input(bad_fields, req_id)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == f"{key}가 필요해요"

    # 2. Payment method / evidence type
    bad_pay = dict(valid_fields, pay_method="카드")
    with pytest.raises(SaveError) as exc:
        validate_manual_expense_create_input(bad_pay, req_id)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "지급 수단을 현금·계좌이체 중에서 골라 주세요"

    # evidence_type overrides pay_method requirement (e.g. OTA points)
    ota_fields = {
        "display_tab_id": "tab-1",
        "occurred_on": "2026-10-28",
        "amount_krw": 5000,
        "item": "숙박",
        "evidence_type": "OTA포인트",
    }
    row_id, want_input = validate_manual_expense_create_input(ota_fields, req_id)
    assert row_id == f"man-{req_id[:16]}"
    assert want_input == normalize_create_input(ota_fields)

    # 3. amount_krw type constraints
    for bad_amt in (True, False, 100.5, decimal.Decimal("100"), "5000"):
        bad_amt_fields = dict(valid_fields, amount_krw=bad_amt)
        with pytest.raises(SaveError) as exc:
            validate_manual_expense_create_input(bad_amt_fields, req_id)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "금액은 정수 원화로 입력해 주세요"

    # 4. occurred_on date format
    for bad_date in ("2026/10/28", "2026-02-31", "not-date", 12345):
        bad_date_fields = dict(valid_fields, occurred_on=bad_date)
        with pytest.raises(SaveError) as exc:
            validate_manual_expense_create_input(bad_date_fields, req_id)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "날짜 형식이 달라요"

    # 5. client_request_id
    for bad_req in ("", None, 12345):
        with pytest.raises(SaveError) as exc:
            validate_manual_expense_create_input(valid_fields, bad_req)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "요청 ID가 필요해요"


def test_build_record_helpers():
    """Verify record construction maps all fields faithfully."""
    # 1. Direct income record
    inc_fields = {
        "display_tab_id": "tab-income",
        "occurred_on": "2026-10-28",
        "amount_krw": 70000,
        "income_kind": "balance",
        "customer_id": "cust-9",
        "customer_name": "홍길동",
        "nickname": "길동이",
        "memo": "입금 완료",
    }
    inc_rec = build_direct_income_record(
        row_id="inc-test12345678",
        fields=inc_fields,
        client_request_id="req-inc-test",
    )
    assert inc_rec["row_id"] == "inc-test12345678"
    assert inc_rec["row_kind"] == "income"
    assert inc_rec["display_tab_id"] == "tab-income"
    assert inc_rec["revision"] == 1
    assert inc_rec["occurred_on"] == "2026-10-28"
    assert inc_rec["customer_id"] == "cust-9"
    assert inc_rec["customer_name"] == "홍길동"
    assert inc_rec["nickname"] == "길동이"
    assert inc_rec["income_kind"] == "balance"
    assert inc_rec["event_type"] == "receipt"
    assert inc_rec["amount_krw"] == 70000
    assert inc_rec["source_kind"] == "직접 입력"
    assert inc_rec["source_event_id"] == "inc-test12345678"
    assert inc_rec["operator_note"] == "입금 완료"
    assert inc_rec["created_by_request"] == "req-inc-test"

    # 2. Manual expense record
    exp_fields = {
        "display_tab_id": "tab-exp",
        "occurred_on": "2026-10-28",
        "amount_krw": 15000,
        "item": "교통비",
        "pay_method": "계좌이체",
        "description": "택시",
        "service_period": "2026-10-28",
        "reservation_no": "R123",
        "memo": "야간할증",
    }
    exp_rec = build_manual_expense_record(
        row_id="man-test12345678",
        fields=exp_fields,
        client_request_id="req-exp-test",
    )
    assert exp_rec["row_id"] == "man-test12345678"
    assert exp_rec["row_kind"] == "expense"
    assert exp_rec["display_tab_id"] == "tab-exp"
    assert exp_rec["revision"] == 1
    assert exp_rec["occurred_on"] == "2026-10-28"
    assert exp_rec["item"] == "교통비"
    assert exp_rec["description"] == "택시"
    assert exp_rec["service_period"] == "2026-10-28"
    assert exp_rec["reservation_no"] == "R123"
    assert exp_rec["evidence_type"] == "계좌이체"
    assert exp_rec["amount_krw"] == 15000
    assert exp_rec["source_kind"] == "수기"
    assert exp_rec["source_event_id"] == "man-test12345678"
    assert exp_rec["classification_state"] == ""
    assert exp_rec["classification_basis"] == "직접 입력"
    assert exp_rec["operator_note"] == "야간할증"
    assert exp_rec["created_by_request"] == "req-exp-test"


def test_facade_create_and_idempotency_end_to_end(tmp_path):
    """End-to-end LedgerStore integration testing creation and idempotency replay."""
    db_path = str(tmp_path / "test_store_create.db")
    store = LedgerStore(db_path)

    # 1. Create direct income
    inc_req_id = "req-direct-inc-001"
    inc_res = store.create_direct_income(
        fields={
            "display_tab_id": "tab-1",
            "occurred_on": "2026-10-28",
            "amount_krw": 80000,
            "income_kind": "deposit",
            "customer_name": "김철수",
            "memo": "예약금",
        },
        client_request_id=inc_req_id,
    )
    assert inc_res["outcome"] == "saved"
    row_id_inc = inc_res["row_id"]
    assert row_id_inc.startswith("inc-")

    # Idempotent replay with same input returns identical result
    replay_inc = store.create_direct_income(
        fields={
            "display_tab_id": "tab-1",
            "occurred_on": "2026-10-28",
            "amount_krw": 80000,
            "income_kind": "deposit",
            "customer_name": "김철수",
            "memo": "예약금",
        },
        client_request_id=inc_req_id,
    )
    assert replay_inc["row_id"] == inc_res["row_id"]

    # Reused client_request_id with different input raises REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        store.create_direct_income(
            fields={
                "display_tab_id": "tab-1",
                "occurred_on": "2026-10-28",
                "amount_krw": 99999,
                "income_kind": "deposit",
            },
            client_request_id=inc_req_id,
        )
    assert exc.value.code == "REQUEST_ID_REUSED"

    # 2. Create manual expense
    exp_req_id = "req-manual-exp-001"
    exp_res = store.create_manual_expense(
        fields={
            "display_tab_id": "tab-1",
            "occurred_on": "2026-10-28",
            "amount_krw": 18000,
            "item": "식비",
            "pay_method": "현금",
            "memo": "저녁 식사",
        },
        client_request_id=exp_req_id,
    )
    assert exp_res["outcome"] == "saved"
    row_id_exp = exp_res["row_id"]
    assert row_id_exp.startswith("man-")

    # Idempotent replay
    replay_exp = store.create_manual_expense(
        fields={
            "display_tab_id": "tab-1",
            "occurred_on": "2026-10-28",
            "amount_krw": 18000,
            "item": "식비",
            "pay_method": "현금",
            "memo": "저녁 식사",
        },
        client_request_id=exp_req_id,
    )
    assert replay_exp["row_id"] == exp_res["row_id"]

    # Reused request_id with different input raises REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        store.create_manual_expense(
            fields={
                "display_tab_id": "tab-1",
                "occurred_on": "2026-10-28",
                "amount_krw": 99999,
                "item": "식비",
                "pay_method": "현금",
            },
            client_request_id=exp_req_id,
        )
    assert exc.value.code == "REQUEST_ID_REUSED"

    store.conn.close()
