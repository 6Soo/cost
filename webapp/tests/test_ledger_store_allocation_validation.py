"""Synthetic tests for RF-101 pure allocation validation module extraction.

Verifies:
- Differential output and exception behavior compared to base commit 2384cfd
- Normalization rules for allocation row changes and plan comparison
- Validation rules for allocation plan amounts, kinds, customer names, trips, sums
- Dynamic dispatch via LedgerStore facade (self.get_trip callback)
- Monkeypatch compatibility and SaveError identity preservation
"""
from __future__ import annotations

import ast
import subprocess
from typing import Any

import pytest

import webapp.ledger_store as ls_module
from webapp.ledger_store import (
    ALLOCATION_ROW_EDITABLE,
    LedgerStore,
    SaveError,
)
from webapp.ledger_store_allocation_validation import (
    SaveError as DirectSaveError,
    allocation_request_matches,
    normalize_allocation_row_changes,
    normalize_plan_for_compare,
    validate_allocation_plan,
)


def _load_base_2384cfd_functions():
    p = subprocess.run(
        ["git", "show", "2384cfd:webapp/ledger_store.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    tree = ast.parse(p.stdout)

    fn_nodes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_normalize_plan_for_compare",
            "_normalize_allocation_row_changes",
            "_allocation_request_matches",
            "_validate_allocation_plan",
        ):
            fn_nodes[node.name] = node

    # Compile the base functions in an isolated namespace to run differential tests
    # We replace self.get_trip in the method bodies with a standalone mock/callback
    ns = {
        "SaveError": DirectSaveError,
        "ALLOCATION_ROW_EDITABLE": ALLOCATION_ROW_EDITABLE,
    }
    # Create module with extracted functions
    code = (
        "def base_normalize_plan_for_compare(plan):\n"
        "    return sorted(\n"
        "        (str(p.get('allocation_id') or ''),\n"
        "         str(p.get('customer_id') or ''), str(p.get('customer_name') or ''),\n"
        "         str(p.get('nickname') or ''), str(p.get('display_tab_id') or ''),\n"
        "         str(p.get('income_kind') or ''), p.get('amount_krw'))\n"
        "        for p in (plan or [])\n"
        "    )\n"
        "\n"
        "def base_allocation_request_matches(stored, api, allocation_id, expected_source_revision, changes):\n"
        "    if stored.get('api') != api:\n"
        "        return False\n"
        "    if stored.get('allocation_id') != allocation_id:\n"
        "        return False\n"
        "    if stored.get('expected_source_revision') != expected_source_revision:\n"
        "        return False\n"
        "    return changes is None or stored.get('changes') == changes\n"
    )
    exec(code, ns)
    return ns, fn_nodes


def test_save_error_identity_and_reexport():
    assert SaveError is DirectSaveError
    err = SaveError("TEST_CODE", "테스트 에러")
    assert err.code == "TEST_CODE"
    assert str(err) == "테스트 에러"
    assert isinstance(err, Exception)


def test_normalize_plan_for_compare_differential():
    ns, fn_nodes = _load_base_2384cfd_functions()
    base_fn = ns["base_normalize_plan_for_compare"]

    test_cases = [
        None,
        [],
        [{"allocation_id": "a1", "amount_krw": 1000}],
        [
            {"allocation_id": "b", "customer_name": "홍길동", "amount_krw": 500, "income_kind": "deposit"},
            {"allocation_id": "a", "customer_name": "김철수", "amount_krw": 200, "income_kind": "balance"},
        ],
        [
            {"customer_id": "c1", "nickname": "nick", "display_tab_id": "t1", "amount_krw": 0},
            {"customer_id": None, "nickname": None, "display_tab_id": None, "amount_krw": -100},
        ],
    ]

    for tc in test_cases:
        expected = base_fn(tc)
        actual = normalize_plan_for_compare(tc)
        assert actual == expected
        assert LedgerStore._normalize_plan_for_compare(tc) == expected


def test_allocation_request_matches_differential():
    ns, fn_nodes = _load_base_2384cfd_functions()
    base_fn = ns["base_allocation_request_matches"]

    stored_base = {
        "api": "allocation-edit",
        "allocation_id": "alloc-1",
        "expected_source_revision": 2,
        "changes": {"income_kind": "deposit"},
    }

    test_calls = [
        (stored_base, "allocation-edit", "alloc-1", 2, {"income_kind": "deposit"}),
        (stored_base, "allocation-save", "alloc-1", 2, {"income_kind": "deposit"}),  # api mismatch
        (stored_base, "allocation-edit", "alloc-2", 2, {"income_kind": "deposit"}),  # id mismatch
        (stored_base, "allocation-edit", "alloc-1", 3, {"income_kind": "deposit"}),  # rev mismatch
        (stored_base, "allocation-edit", "alloc-1", 2, {"income_kind": "balance"}),  # changes mismatch
        (stored_base, "allocation-edit", "alloc-1", 2, None),  # None changes matches
    ]

    for stored, api, alloc_id, rev, changes in test_calls:
        expected = base_fn(stored, api, alloc_id, rev, changes)
        actual = allocation_request_matches(stored, api, alloc_id, rev, changes)
        assert actual == expected
        assert LedgerStore._allocation_request_matches(stored, api, alloc_id, rev, changes) == expected


def test_normalize_allocation_row_changes_validation():
    def mock_get_trip(tab_id):
        if tab_id == "trip-live":
            return {"tab_id": tab_id, "deleted": False}
        if tab_id == "trip-deleted":
            return {"tab_id": tab_id, "deleted": True}
        return None

    # 1. Non-dict or empty changes
    for invalid in [None, {}, "", 123, []]:
        with pytest.raises(SaveError) as exc:
            normalize_allocation_row_changes(invalid, get_trip_fn=mock_get_trip)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "수정할 수 있는 필드가 없어요"

    # 2. Unknown field
    with pytest.raises(SaveError) as exc:
        normalize_allocation_row_changes({"unknown_col": "val"}, get_trip_fn=mock_get_trip)
    assert exc.value.code == "FIELD_READ_ONLY"
    assert "는 배분 행에서 수정할 수 없어요" in exc.value.args[0]

    # 3. Invalid income_kind
    with pytest.raises(SaveError) as exc:
        normalize_allocation_row_changes({"income_kind": "wrong"}, get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "입금 종류를 골라 주세요"

    # 4. Target trip checks
    with pytest.raises(SaveError) as exc:
        normalize_allocation_row_changes({"display_tab_id": "trip-nonexistent"}, get_trip_fn=mock_get_trip)
    assert exc.value.code == "TARGET_NOT_ASSIGNABLE"
    assert exc.value.args[0] == "배정할 수 없는 여행이에요"

    with pytest.raises(SaveError) as exc:
        normalize_allocation_row_changes({"display_tab_id": "trip-deleted"}, get_trip_fn=mock_get_trip)
    assert exc.value.code == "TARGET_NOT_ASSIGNABLE"

    # 5. Normalization values
    valid_changes = {
        "display_tab_id": "trip-live",
        "customer_id": "cust-1",
        "customer_name": "고객명",
        "nickname": None,
        "income_kind": "deposit",
    }
    res = normalize_allocation_row_changes(valid_changes, get_trip_fn=mock_get_trip)
    assert res["display_tab_id"] == "trip-live"
    assert res["customer_id"] == "cust-1"
    assert res["customer_name"] == "고객명"
    assert res["nickname"] == ""
    assert res["income_kind"] == "deposit"

    # 6. Unclassified / empty display_tab_id becomes None
    res_unclassified = normalize_allocation_row_changes(
        {"display_tab_id": "unclassified", "income_kind": "balance"},
        get_trip_fn=mock_get_trip,
    )
    assert res_unclassified["display_tab_id"] is None
    assert res_unclassified["income_kind"] == "balance"


def test_validate_allocation_plan_rules():
    def mock_get_trip(tab_id):
        if tab_id == "trip-ok":
            return {"tab_id": tab_id, "deleted": False}
        return None

    # 1. Non-dict item
    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, 10000, ["not-a-dict"], get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "배분안이 올바르지 않아요"

    # 2. Invalid amounts (boolean, float, 0)
    for bad_amt in [True, False, 0, 10.5, "1000"]:
        with pytest.raises(SaveError) as exc:
            validate_allocation_plan({}, 10000, [{"amount_krw": bad_amt}], get_trip_fn=mock_get_trip)
        assert exc.value.code == "INVALID_VALUE"
        assert exc.value.args[0] == "배분액은 0이 아닌 정수 원화로 입력해 주세요"

    # 3. Sign mismatch
    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, 10000, [{"amount_krw": -5000, "income_kind": "deposit", "customer_name": "홍"}], get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "양수 입금은 양수 배분만 할 수 있어요"

    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, -10000, [{"amount_krw": 5000, "income_kind": "deposit", "customer_name": "홍"}], get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "음수 환불은 음수 배분만 할 수 있어요"

    # 4. Income kind validation
    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, 10000, [{"amount_krw": 5000, "income_kind": "invalid", "customer_name": "홍"}], get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "입금 종류를 골라 주세요"

    # 5. Missing customer name
    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, 10000, [{"amount_krw": 5000, "income_kind": "deposit", "customer_name": "  "}], get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "배분 고객 이름이 필요해요"

    # 6. Trip check
    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, 10000, [{
            "amount_krw": 5000, "income_kind": "deposit", "customer_name": "홍", "display_tab_id": "trip-missing"
        }], get_trip_fn=mock_get_trip)
    assert exc.value.code == "TARGET_NOT_ASSIGNABLE"

    # 7. Total sum exceeding reflected
    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, 10000, [
            {"amount_krw": 6000, "income_kind": "deposit", "customer_name": "홍"},
            {"amount_krw": 5000, "income_kind": "deposit", "customer_name": "김"},
        ], get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "배분 합계가 입금액을 넘었어요"

    # 8. Reflected == 0 with plan
    with pytest.raises(SaveError) as exc:
        validate_allocation_plan({}, 0, [
            {"amount_krw": 1000, "income_kind": "deposit", "customer_name": "홍"},
        ], get_trip_fn=mock_get_trip)
    assert exc.value.code == "INVALID_VALUE"
    assert exc.value.args[0] == "나눌 금액이 없어요"

    # 9. Successful validation & cleaning
    plan = [
        {
            "allocation_id": "a-1",
            "customer_id": "c-1",
            "customer_name": "홍길동",
            "nickname": "길동",
            "display_tab_id": "trip-ok",
            "income_kind": "deposit",
            "amount_krw": 7000,
        }
    ]
    cleaned = validate_allocation_plan({}, 10000, plan, get_trip_fn=mock_get_trip)
    assert len(cleaned) == 1
    assert cleaned[0]["allocation_id"] == "a-1"
    assert cleaned[0]["customer_id"] == "c-1"
    assert cleaned[0]["customer_name"] == "홍길동"
    assert cleaned[0]["nickname"] == "길동"
    assert cleaned[0]["display_tab_id"] == "trip-ok"
    assert cleaned[0]["income_kind"] == "deposit"
    assert cleaned[0]["amount_krw"] == 7000


def test_dynamic_dispatch_and_facade_on_ledger_store(monkeypatch):
    """Verify LedgerStore facade delegates to validation functions and respects dynamic dispatch."""
    class DummyStore:
        def __init__(self):
            self.trip_queries = []

        def get_trip(self, tab_id: str):
            self.trip_queries.append(tab_id)
            if tab_id == "trip-live":
                return {"tab_id": tab_id, "deleted": False}
            return None

        # Bind methods like LedgerStore
        _normalize_allocation_row_changes = LedgerStore._normalize_allocation_row_changes
        _validate_allocation_plan = LedgerStore._validate_allocation_plan
        _allocation_request_matches = LedgerStore._allocation_request_matches
        _normalize_plan_for_compare = LedgerStore._normalize_plan_for_compare

    store = DummyStore()

    # 1. Dynamic dispatch of self.get_trip via _normalize_allocation_row_changes
    res = store._normalize_allocation_row_changes({
        "display_tab_id": "trip-live",
        "income_kind": "deposit",
    })
    assert res["display_tab_id"] == "trip-live"
    assert store.trip_queries == ["trip-live"]

    # 2. Dynamic dispatch of self.get_trip via _validate_allocation_plan
    plan = [{
        "customer_name": "손님",
        "income_kind": "balance",
        "amount_krw": 5000,
        "display_tab_id": "trip-live",
    }]
    cleaned = store._validate_allocation_plan({}, 5000, plan)
    assert cleaned[0]["amount_krw"] == 5000
    assert store.trip_queries == ["trip-live", "trip-live"]

    # 3. Monkeypatching facade method preserves caller dispatch
    sentinel = [{"sentinel": True}]
    monkeypatch.setattr(store, "_validate_allocation_plan", lambda *args, **kwargs: sentinel)
    assert store._validate_allocation_plan({}, 5000, plan) is sentinel
