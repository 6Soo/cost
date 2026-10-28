"""Synthetic tests for RF-101 pure revision conflict and idempotency rules extraction.

Verifies:
- check_revision_conflict behavior, error codes, and messages
- match_board_save_request KeyError contracts and idempotency comparison
- match_board_revert_request lazy evaluation and short-circuit callback counts
- match_allocation_save_request plan normalization and principal comparison
- verify_correction_reused_request parameter validation
- match_rule_lifecycle_request and match_rule_apply_request short-circuit with malformed JSON
- LedgerStore facade integration:
  - revert_status lazy call count preservation
  - malformed result_json short-circuit on request mismatch
  - save idempotency replay vs REQUEST_ID_REUSED
"""
from __future__ import annotations

import json
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


def test_match_board_save_request_and_keyerror_contract():
    stored = {
        "row_id": "row-1",
        "expected_revision": 2,
        "changes": {"amount_krw": 5000},
        "change_mode": "exception",
        "result": {"outcome": "saved", "revision": 3},
    }

    # Exact match returns result
    res = match_board_save_request(
        stored,
        row_id="row-1",
        expected_revision=2,
        changes={"amount_krw": 5000},
        change_mode="exception",
    )
    assert res == {"outcome": "saved", "revision": 3}

    # Missing required keys in stored dictionary raises KeyError (strict contract preserved)
    for missing_key in ["row_id", "expected_revision", "changes", "change_mode"]:
        bad_stored = dict(stored)
        del bad_stored[missing_key]
        with pytest.raises(KeyError):
            match_board_save_request(
                bad_stored,
                row_id="row-1",
                expected_revision=2,
                changes={"amount_krw": 5000},
                change_mode="exception",
            )

    # Mismatches raise REQUEST_ID_REUSED
    for bad_args in [
        {"row_id": "row-2", "expected_revision": 2, "changes": {"amount_krw": 5000}, "change_mode": "exception"},
        {"row_id": "row-1", "expected_revision": 1, "changes": {"amount_krw": 5000}, "change_mode": "exception"},
        {"row_id": "row-1", "expected_revision": 2, "changes": {"amount_krw": 9999}, "change_mode": "exception"},
        {"row_id": "row-1", "expected_revision": 2, "changes": {"amount_krw": 5000}, "change_mode": "rule_change"},
    ]:
        with pytest.raises(SaveError) as exc:
            match_board_save_request(stored, **bad_args)
        assert exc.value.code == "REQUEST_ID_REUSED"
        assert exc.value.args[0] == "같은 요청 ID로 다른 내용을 보냈어요"


def test_match_board_revert_request_lazy_callback_counts():
    stored = {
        "row_id": "row-1",
        "expected_revision": 2,
        "changes": {"revert": 1},
        "result": {"outcome": "reverted", "revision": 3},
    }

    callback_count = 0

    def mock_get_want_changes():
        nonlocal callback_count
        callback_count += 1
        return {"revert": 1}

    # 1. Row ID mismatch -> raises REQUEST_ID_REUSED without invoking callback
    callback_count = 0
    with pytest.raises(SaveError) as exc:
        match_board_revert_request(
            stored,
            row_id="row-different",
            expected_revision=2,
            get_want_changes_fn=mock_get_want_changes,
        )
    assert exc.value.code == "REQUEST_ID_REUSED"
    assert callback_count == 0  # Not called!

    # 2. expected_revision matches -> returns stored["result"] without invoking callback
    callback_count = 0
    res_fast = match_board_revert_request(
        stored,
        row_id="row-1",
        expected_revision=2,
        get_want_changes_fn=mock_get_want_changes,
    )
    assert res_fast == stored["result"]
    assert callback_count == 0  # Not called!

    # 3. expected_revision mismatches -> invokes callback once to check want_changes
    callback_count = 0
    res_slow = match_board_revert_request(
        stored,
        row_id="row-1",
        expected_revision=999,  # different expected revision
        get_want_changes_fn=mock_get_want_changes,
    )
    assert res_slow == stored["result"]
    assert callback_count == 1  # Invoked exactly once!

    # 4. Missing row_id in stored raises KeyError
    bad_stored = dict(stored)
    del bad_stored["row_id"]
    with pytest.raises(KeyError):
        match_board_revert_request(
            bad_stored,
            row_id="row-1",
            expected_revision=2,
            get_want_changes_fn=mock_get_want_changes,
        )


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


def test_match_rule_requests_short_circuit_with_malformed_json():
    # 1. Operation mismatch short-circuits: invalid JSON in stored_request_json is NOT parsed
    assert not match_rule_lifecycle_request(
        "operation_a", "MALFORMED_JSON{{{", "operation_b", {"dummy": True}
    )

    # 2. Matching operation with valid JSON compares dictionary
    valid_req_json = json.dumps({"rule_id": "r1"})
    assert match_rule_lifecycle_request("op1", valid_req_json, "op1", {"rule_id": "r1"})
    assert not match_rule_lifecycle_request("op1", valid_req_json, "op1", {"rule_id": "r2"})

    # 3. Rule apply request compares request JSON
    assert match_rule_apply_request(json.dumps({"preview_id": "p1"}), {"preview_id": "p1"})
    assert not match_rule_apply_request(json.dumps({"preview_id": "p1"}), {"preview_id": "p2"})


def test_facade_revert_lazy_and_malformed_result_json(tmp_path, monkeypatch):
    """Verify facade revert_row lazy evaluation and lifecycle replay short-circuit."""
    db_path = str(tmp_path / "test_revert_lazy.db")
    store = LedgerStore(db_path)

    # Insert a synthetic board request
    stored_result = {"outcome": "reverted", "revision": 2}
    store.conn.execute(
        "INSERT INTO board_requests(client_request_id, row_id, expected_revision, result_json, ledger_pending, created_at)"
        " VALUES ('req-revert-1', 'row-1', 1, ?, 0, '2026-10-28T00:00:00Z')",
        (json.dumps({"row_id": "row-1", "expected_revision": 1, "result": stored_result}),)
    )
    # Insert row-1 in board_rows
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES ('row-1', 'expense', 'tab-1', 2, '{}')"
    )
    store.conn.commit()

    revert_status_count = 0
    original_revert_status = store.revert_status

    def tracked_revert_status(r_id):
        nonlocal revert_status_count
        revert_status_count += 1
        return original_revert_status(r_id)

    monkeypatch.setattr(store, "revert_status", tracked_revert_status)

    # Calling revert_row with expected_revision=1 matching stored request
    # MUST NOT invoke revert_status!
    res = store.revert_row(row_id="row-1", expected_revision=1, client_request_id="req-revert-1")
    assert res == stored_result
    assert revert_status_count == 0  # Strict lazy evaluation preserved!

    # Test lifecycle replay with malformed result_json:
    # If operation mismatches, SaveError("REQUEST_ID_REUSED") must be raised without JSONDecodeError
    store.conn.execute(
        "INSERT INTO rule_lifecycle_requests(client_request_id, operation, request_json, result_json, created_at)"
        " VALUES ('req-life-bad', 'create', '{}', 'MALFORMED_RESULT_JSON{{{', '2026-10-28T00:00:00Z')"
    )
    store.conn.commit()

    with pytest.raises(SaveError) as exc:
        store._lifecycle_replay("req-life-bad", "delete", {})
    assert exc.value.code == "REQUEST_ID_REUSED"  # Result JSON not parsed on operation mismatch!

    store.conn.close()
