"""Synthetic tests for RF-101 pure revision conflict and idempotency rules extraction.

Verifies:
- check_revision_conflict behavior, error codes, and messages
- match_board_save_request idempotency comparison
- match_board_revert_request idempotency criteria
- match_allocation_save_request plan normalization and principal comparison
- verify_correction_reused_request parameter validation
- match_rule_lifecycle_request and match_rule_apply_request verification
- LedgerStore facade integration (stored result replay vs REQUEST_ID_REUSED)
"""
from __future__ import annotations

import pytest

from webapp.ledger_store import LedgerStore, SaveError
from webapp.ledger_store_allocation_validation import normalize_plan_for_compare
from webapp.ledger_store_idempotency import (
    check_revision_conflict,
    match_allocation_save_request,
    match_board_revert_request,
    match_board_save_request,
    match_rule_apply_request,
    match_rule_lifecycle_request,
    verify_correction_reused_request,
)


def test_check_revision_conflict_rules():
    # Matching revision passes cleanly
    check_revision_conflict(3, 3)
    check_revision_conflict(1, 1)

    # Mismatched revision raises EDIT_CONFLICT
    with pytest.raises(SaveError) as exc:
        check_revision_conflict(3, 2)
    assert exc.value.code == "EDIT_CONFLICT"
    assert exc.value.args[0] == "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요"

    with pytest.raises(SaveError) as exc:
        check_revision_conflict(1, 2)
    assert exc.value.code == "EDIT_CONFLICT"


def test_match_board_save_request():
    stored = {
        "row_id": "row-1",
        "expected_revision": 2,
        "changes": {"amount_krw": 5000},
        "change_mode": "manual",
        "result": {"outcome": "saved", "revision": 3},
    }

    # Exact match returns result
    res = match_board_save_request(
        stored,
        row_id="row-1",
        expected_revision=2,
        changes={"amount_krw": 5000},
        change_mode="manual",
    )
    assert res == {"outcome": "saved", "revision": 3}

    # Mismatches raise REQUEST_ID_REUSED
    for bad_args in [
        {"row_id": "row-2", "expected_revision": 2, "changes": {"amount_krw": 5000}, "change_mode": "manual"},
        {"row_id": "row-1", "expected_revision": 1, "changes": {"amount_krw": 5000}, "change_mode": "manual"},
        {"row_id": "row-1", "expected_revision": 2, "changes": {"amount_krw": 9999}, "change_mode": "manual"},
        {"row_id": "row-1", "expected_revision": 2, "changes": {"amount_krw": 5000}, "change_mode": "auto"},
    ]:
        with pytest.raises(SaveError) as exc:
            match_board_save_request(stored, **bad_args)
        assert exc.value.code == "REQUEST_ID_REUSED"
        assert exc.value.args[0] == "같은 요청 ID로 다른 내용을 보냈어요"


def test_match_board_revert_request():
    stored = {
        "row_id": "row-1",
        "expected_revision": 2,
        "changes": {"revert": 1},
        "result": {"outcome": "reverted", "revision": 3},
    }

    # Matches when expected_revision matches
    res1 = match_board_revert_request(
        stored,
        row_id="row-1",
        expected_revision=2,
        want_changes=None,
    )
    assert res1 == stored["result"]

    # Matches when changes matches want_changes
    res2 = match_board_revert_request(
        stored,
        row_id="row-1",
        expected_revision=5,
        want_changes={"revert": 1},
    )
    assert res2 == stored["result"]

    # Mismatches raise REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        match_board_revert_request(stored, row_id="row-2", expected_revision=2, want_changes=None)
    assert exc.value.code == "REQUEST_ID_REUSED"

    with pytest.raises(SaveError) as exc:
        match_board_revert_request(stored, row_id="row-1", expected_revision=5, want_changes={"revert": 9})
    assert exc.value.code == "REQUEST_ID_REUSED"


def test_match_allocation_save_request():
    stored = {
        "plan": [
            {"allocation_id": "a1", "customer_name": "홍길동", "amount_krw": 5000, "income_kind": "deposit"},
        ],
        "new_principal": {"amount_krw": 10000},
        "result": {"outcome": "allocated", "revision": 2},
    }

    # Matching plan (regardless of order or dict permutation) and matching new_principal
    res = match_allocation_save_request(
        stored,
        allocations=[
            {"allocation_id": "a1", "customer_name": "홍길동", "amount_krw": 5000, "income_kind": "deposit"},
        ],
        new_principal={"amount_krw": 10000},
        normalize_plan_fn=normalize_plan_for_compare,
    )
    assert res == stored["result"]

    # Mismatched plan raises REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        match_allocation_save_request(
            stored,
            allocations=[{"allocation_id": "a2", "amount_krw": 1000}],
            new_principal={"amount_krw": 10000},
            normalize_plan_fn=normalize_plan_for_compare,
        )
    assert exc.value.code == "REQUEST_ID_REUSED"

    # Mismatched new_principal raises REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        match_allocation_save_request(
            stored,
            allocations=[{"allocation_id": "a1", "customer_name": "홍길동", "amount_krw": 5000, "income_kind": "deposit"}],
            new_principal={"amount_krw": 99999},
            normalize_plan_fn=normalize_plan_for_compare,
        )
    assert exc.value.code == "REQUEST_ID_REUSED"


def test_verify_correction_reused_request():
    # Exact match passes
    verify_correction_reused_request(10000, "2026-10-28", 10000, "2026-10-28")
    # None and empty string date equivalence
    verify_correction_reused_request(5000, None, 5000, "")

    # Mismatch in amount raises REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        verify_correction_reused_request(10000, "2026-10-28", 20000, "2026-10-28")
    assert exc.value.code == "REQUEST_ID_REUSED"

    # Mismatch in date raises REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        verify_correction_reused_request(10000, "2026-10-28", 10000, "2026-10-29")
    assert exc.value.code == "REQUEST_ID_REUSED"


def test_match_rule_requests():
    # Rule lifecycle request match
    stored_req = {"rule_id": "r1", "name": "test"}
    stored_res = {"status": "ok"}
    res1 = match_rule_lifecycle_request(
        "create", "create", stored_req, {"rule_id": "r1", "name": "test"}, stored_res
    )
    assert res1 == stored_res

    with pytest.raises(SaveError) as exc:
        match_rule_lifecycle_request("create", "delete", stored_req, stored_req, stored_res)
    assert exc.value.code == "REQUEST_ID_REUSED"

    with pytest.raises(SaveError) as exc:
        match_rule_lifecycle_request("create", "create", stored_req, {"different": True}, stored_res)
    assert exc.value.code == "REQUEST_ID_REUSED"

    # Rule apply request match
    res2 = match_rule_apply_request({"preview_id": "p1"}, {"preview_id": "p1"}, stored_res)
    assert res2 == stored_res

    with pytest.raises(SaveError) as exc:
        match_rule_apply_request({"preview_id": "p1"}, {"preview_id": "p2"}, stored_res)
    assert exc.value.code == "REQUEST_ID_REUSED"


def test_facade_save_row_idempotency_and_conflict(tmp_path):
    db_path = str(tmp_path / "test_idempotency.db")
    store = LedgerStore(db_path)

    # 1. Create a manual expense row
    create_res = store.create_manual_expense(
        fields={
            "display_tab_id": "tab-1",
            "occurred_on": "2026-10-28",
            "amount_krw": 15000,
            "item": "식비",
            "pay_method": "현금",
            "description": "점심식사",
        },
        client_request_id="req-create-12345678",
    )
    row_id = create_res["row_id"]
    assert row_id is not None
    assert create_res["revision"] == 1

    # 2. Save changes (revision 1 -> 2)
    save_res = store.save(
        row_id=row_id,
        expected_revision=1,
        client_request_id="req-save-1",
        change_mode="exception",
        changes={"amount_krw": 20000},
    )
    assert save_res["revision"] == 2

    # 3. Idempotent replay with same client_request_id returns stored result
    replay_res = store.save(
        row_id=row_id,
        expected_revision=1,
        client_request_id="req-save-1",
        change_mode="exception",
        changes={"amount_krw": 20000},
    )
    assert replay_res == save_res

    # 4. Reusing client_request_id with different changes raises REQUEST_ID_REUSED
    with pytest.raises(SaveError) as exc:
        store.save(
            row_id=row_id,
            expected_revision=1,
            client_request_id="req-save-1",
            change_mode="exception",
            changes={"amount_krw": 99999},
        )
    assert exc.value.code == "REQUEST_ID_REUSED"

    # 5. Stale expected_revision raises EDIT_CONFLICT
    with pytest.raises(SaveError) as exc:
        store.save(
            row_id=row_id,
            expected_revision=1,
            client_request_id="req-save-2",
            change_mode="exception",
            changes={"amount_krw": 25000},
        )
    assert exc.value.code == "EDIT_CONFLICT"

    store.conn.close()
