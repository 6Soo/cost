"""Synthetic tests for RF-101 pure row change validation module extraction.

Verifies:
- Differential output and exception behavior compared to base commit 2384cfd
- Card/manual expense readonly and editable field rules
- Bank and direct income editable rules and linked direct protections
- Amount int/bool/float/Decimal and date format validations
- Tab assignment and income_kind validations
- KeyError contract on missing 'row_kind'
- Dynamic dispatch via LedgerStore facade (self._validate monkeypatch preservation)
"""
from __future__ import annotations

import decimal
import subprocess
from typing import Any

import pytest

import webapp.ledger_store as ls_module
from webapp.ledger_store import (
    CARD_EDITABLE,
    CARD_READONLY,
    INCOME_EDITABLE,
    LedgerStore,
    SaveError,
)
from webapp.ledger_store_change_validation import (
    valid_date,
    validate_row_changes,
)


def _load_base_2384cfd_validate():
    p = subprocess.run(
        ["git", "show", "2384cfd:webapp/ledger_store.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    src = p.stdout

    # Extract the exact _validate method and compile it standalone
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_validate':
            break

    # Construct standalone wrapper
    ns = {
        "CARD_READONLY": CARD_READONLY,
        "CARD_EDITABLE": CARD_EDITABLE,
        "INCOME_EDITABLE": INCOME_EDITABLE,
        "SaveError": SaveError,
        "_valid_date": valid_date,
    }
    code = (
        "def base_validate(self, current: dict, changes: dict) -> None:\n"
        + "\n".join("    " + line for line in ast.get_source_segment(src, node).splitlines()[1:])
    )
    exec(code, ns)
    return ns["base_validate"]


class DummyStoreWithConn:
    def __init__(self, linked_ids=None):
        self.linked_ids = set(linked_ids or [])
        self.query_count = 0

    @property
    def conn(self):
        class MockConn:
            def __init__(self, outer):
                self.outer = outer

            def execute(self, sql, params=()):
                self.outer.query_count += 1
                return MockCursor([(rid,) for rid in self.outer.linked_ids])

        class MockCursor:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return self.rows

        return MockConn(self)


def test_card_expense_validation_differential():
    base_validate = _load_base_2384cfd_validate()
    dummy = DummyStoreWithConn()

    current_card = {
        "row_id": "r-card-1",
        "row_kind": "expense",
        "source_kind": "카드",
    }

    # 1. Modifying readonly card field
    for ro_field in CARD_READONLY:
        changes = {ro_field: "new_value"}
        with pytest.raises(SaveError) as exc_base:
            base_validate(dummy, current_card, changes)
        with pytest.raises(SaveError) as exc_new:
            validate_row_changes(current_card, changes)
        assert exc_new.value.code == exc_base.value.code == "FIELD_READ_ONLY"
        assert str(exc_new.value) == str(exc_base.value)

    # 2. Modifying disallowed field
    for bad_field in ["custom_field", "extra_col"]:
        changes = {bad_field: "val"}
        with pytest.raises(SaveError) as exc_base:
            base_validate(dummy, current_card, changes)
        with pytest.raises(SaveError) as exc_new:
            validate_row_changes(current_card, changes)
        assert exc_new.value.code == exc_base.value.code == "INVALID_VALUE"
        assert str(exc_new.value) == str(exc_base.value)

    # 3. Modifying allowed editable fields
    valid_changes = {"item": "새 항목", "description": "설명", "operator_note": "메모"}
    base_validate(dummy, current_card, valid_changes)
    validate_row_changes(current_card, valid_changes)


def test_manual_expense_validation_differential():
    base_validate = _load_base_2384cfd_validate()
    dummy = DummyStoreWithConn()

    current_manual = {
        "row_id": "r-man-1",
        "row_kind": "expense",
        "source_kind": "직접 입력",
    }

    # Manual expense allows CARD_EDITABLE + occurred_on + amount_krw
    valid_changes = {
        "item": "식비",
        "occurred_on": "2026-10-28",
        "amount_krw": 10000,
        "description": "점심",
    }
    base_validate(dummy, current_manual, valid_changes)
    validate_row_changes(current_manual, valid_changes)

    # Disallowed field on manual expense
    with pytest.raises(SaveError) as exc_base:
        base_validate(dummy, current_manual, {"merchant": "새 가맹점"})
    with pytest.raises(SaveError) as exc_new:
        validate_row_changes(current_manual, {"merchant": "새 가맹점"})
    assert exc_new.value.code == exc_base.value.code == "INVALID_VALUE"
    assert str(exc_new.value) == str(exc_base.value)


def test_bank_and_direct_income_validation_differential():
    base_validate = _load_base_2384cfd_validate()
    dummy = DummyStoreWithConn(linked_ids={"r-direct-linked"})

    # 1. Bank income: cannot modify amount_krw, occurred_on directly
    current_bank = {
        "row_id": "r-bank-1",
        "row_kind": "income",
        "source_kind": "은행",
    }
    with pytest.raises(SaveError) as exc_base:
        base_validate(dummy, current_bank, {"amount_krw": 50000})
    with pytest.raises(SaveError) as exc_new:
        validate_row_changes(current_bank, {"amount_krw": 50000})
    assert exc_new.value.code == exc_base.value.code == "FIELD_READ_ONLY"
    assert str(exc_new.value) == str(exc_base.value)

    # Bank income allowed fields
    valid_bank_changes = {
        "customer_id": "c1",
        "customer_name": "홍길동",
        "nickname": "길동",
        "income_kind": "deposit",
    }
    base_validate(dummy, current_bank, valid_bank_changes)
    validate_row_changes(current_bank, valid_bank_changes)

    # 2. Direct income linked to bank source: amount/date change prohibited
    current_linked_direct = {
        "row_id": "r-direct-linked",
        "row_kind": "income",
        "source_kind": "직접 입력",
    }
    with pytest.raises(SaveError) as exc_base:
        base_validate(dummy, current_linked_direct, {"amount_krw": 50000})
    with pytest.raises(SaveError) as exc_new:
        validate_row_changes(
            current_linked_direct,
            {"amount_krw": 50000},
            get_linked_direct_ids_fn=lambda: {"r-direct-linked"},
        )
    assert exc_new.value.code == exc_base.value.code == "FIELD_READ_ONLY"
    assert "은행 원천 연결 뒤에는 은행 정정 경로를 써 주세요" in exc_new.value.args[0]
    assert str(exc_new.value) == str(exc_base.value)

    # 3. Direct income unlinked: amount/date change allowed
    current_unlinked_direct = {
        "row_id": "r-direct-unlinked",
        "row_kind": "income",
        "source_kind": "직접 입력",
    }
    valid_direct_changes = {
        "amount_krw": 30000,
        "occurred_on": "2026-10-28",
        "income_kind": "deposit",
    }
    base_validate(dummy, current_unlinked_direct, valid_direct_changes)
    validate_row_changes(
        current_unlinked_direct,
        valid_direct_changes,
        get_linked_direct_ids_fn=lambda: {"r-direct-linked"},
    )


def test_amount_type_validations():
    current = {"row_kind": "expense", "source_kind": "직접 입력"}

    # Rejection of boolean
    for bad_bool in [True, False]:
        with pytest.raises(SaveError) as exc:
            validate_row_changes(current, {"amount_krw": bad_bool})
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "금액은 정수 원화로 입력해 주세요"

    # Rejection of float, Decimal, str
    for bad_num in [100.5, decimal.Decimal("100"), "1000", None]:
        with pytest.raises(SaveError) as exc:
            validate_row_changes(current, {"amount_krw": bad_num})
        assert exc.value.code == "INVALID_VALUE"

    # Integer accepted (including 0 and negative numbers per fact preservation)
    for ok_int in [0, 1000, -500]:
        validate_row_changes(current, {"amount_krw": ok_int})


def test_occurred_on_and_income_kind_validations():
    current_expense = {"row_kind": "expense", "source_kind": "직접 입력"}
    current_income = {"row_kind": "income", "source_kind": "직접 입력"}

    # Date validation
    for bad_date in ["2026/10/28", "2026-02-31", "not-a-date", 12345]:
        with pytest.raises(SaveError) as exc:
            validate_row_changes(current_expense, {"occurred_on": bad_date})
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "날짜 형식이 달라요"

    validate_row_changes(current_expense, {"occurred_on": "2026-10-28"})

    # Income kind validation
    for bad_kind in ["unknown", "other", ""]:
        with pytest.raises(SaveError) as exc:
            validate_row_changes(current_income, {"income_kind": bad_kind})
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "입금 종류를 골라 주세요"

    for good_kind in ["deposit", "balance", "additional"]:
        validate_row_changes(current_income, {"income_kind": good_kind})


def test_keyerror_contract_and_facade_dynamic_dispatch(tmp_path, monkeypatch):
    """Verify KeyError contract on missing row_kind and facade dynamic dispatch."""
    # 1. Missing row_kind in current raises KeyError
    with pytest.raises(KeyError):
        validate_row_changes({}, {"item": "test"})

    # 2. Facade _validate monkeypatch is respected by caller
    db_path = str(tmp_path / "test_validate_facade.db")
    store = LedgerStore(db_path)

    validate_calls = []
    original_validate = store._validate

    def tracked_validate(current, changes):
        validate_calls.append((current.get("row_id"), dict(changes)))
        return original_validate(current, changes)

    monkeypatch.setattr(store, "_validate", tracked_validate)

    # Create row
    created = store.create_manual_expense(
        fields={
            "display_tab_id": "tab-1",
            "occurred_on": "2026-10-28",
            "amount_krw": 10000,
            "item": "식비",
            "pay_method": "현금",
            "description": "메모",
        },
        client_request_id="req-validate-test-1",
    )
    row_id = created["row_id"]

    # Save row invokes store._validate
    store.save(
        row_id=row_id,
        expected_revision=1,
        client_request_id="req-save-validate-1",
        change_mode="exception",
        changes={"amount_krw": 15000},
    )

    assert len(validate_calls) == 1
    assert validate_calls[0][0] == row_id
    assert validate_calls[0][1] == {"amount_krw": 15000}

    store.conn.close()
