"""Pure revision conflict and request idempotency comparison rules for LedgerStore.

Extracted under RF-101 (Store decomposition revision & idempotency boundary).
Preserves exact execution semantics, error codes, Korean messages, KeyError contracts,
lazy evaluation, and short-circuit decode order of the original store.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .ledger_store_allocation_validation import SaveError


def check_revision_conflict(
    current_revision: int,
    expected_revision: int,
    *,
    save_error_cls: type[Exception] = SaveError,
) -> None:
    """Validate that the target row/entity revision has not advanced."""
    if current_revision != expected_revision:
        raise save_error_cls(
            "EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요"
        )


def match_board_save_request(
    stored: dict,
    *,
    row_id: str,
    expected_revision: int,
    changes: dict,
    change_mode: str,
    save_error_cls: type[Exception] = SaveError,
) -> dict:
    """Match a stored board save request against incoming arguments for idempotency.

    Preserves exact [] indexing contract: raises KeyError if a required key is missing.
    """
    if (
        stored["row_id"] != row_id
        or stored["expected_revision"] != expected_revision
        or stored["changes"] != changes
        or stored["change_mode"] != change_mode
    ):
        raise save_error_cls("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
    return stored["result"]


def match_board_revert_request(
    stored: dict,
    *,
    row_id: str,
    expected_revision: int,
    get_want_changes_fn: Optional[Callable[[], Optional[dict]]] = None,
    want_changes: Optional[dict] = None,
    save_error_cls: type[Exception] = SaveError,
) -> dict:
    """Match a stored revert row request against expected target revision and changes.

    Preserves exact evaluation and lazy evaluation:
    - stored["row_id"] uses [] indexing
    - if row_id mismatches or expected_revision matches, get_want_changes_fn is never invoked
    """
    if stored["row_id"] != row_id:
        raise save_error_cls("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
    if stored.get("expected_revision") == expected_revision:
        return stored["result"]
    expected_changes = (
        get_want_changes_fn() if get_want_changes_fn is not None else want_changes
    )
    if stored.get("changes") != expected_changes:
        raise save_error_cls("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
    return stored["result"]


def match_allocation_save_request(
    stored: dict,
    *,
    allocations: Any,
    new_principal: Any,
    normalize_plan_fn: Callable[[Any], list],
    save_error_cls: type[Exception] = SaveError,
) -> dict:
    """Match a stored allocation plan save request for idempotency."""
    if (
        normalize_plan_fn(stored.get("plan"))
        != normalize_plan_fn(list(allocations or []))
        or stored.get("new_principal") != (new_principal or None)
    ):
        raise save_error_cls("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
    return stored["result"]


def verify_correction_reused_request(
    existing_amount: int,
    existing_date: Any,
    corrected_amount_krw: int,
    corrected_occurred_on: Any,
    *,
    save_error_cls: type[Exception] = SaveError,
) -> None:
    """Verify that a reused client_request_id matches existing correction parameters."""
    if (
        existing_amount != corrected_amount_krw
        or (existing_date or None) != (corrected_occurred_on or None)
    ):
        raise save_error_cls("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")


def match_rule_lifecycle_request(
    stored_operation: str,
    stored_request_json: str,
    operation: str,
    request: dict,
) -> bool:
    """Return True if stored rule lifecycle request matches, False otherwise.

    Short-circuits: does not call json.loads if operation mismatches.
    Never decodes result JSON.
    """
    if stored_operation != operation:
        return False
    return json.loads(stored_request_json) == request


def match_rule_apply_request(
    stored_request_json: str,
    request: dict,
) -> bool:
    """Return True if stored rule apply request matches, False otherwise.

    Compares request payload before result JSON is decoded.
    """
    return json.loads(stored_request_json) == request


__all__ = [
    "check_revision_conflict",
    "match_allocation_save_request",
    "match_board_revert_request",
    "match_board_save_request",
    "match_rule_apply_request",
    "match_rule_lifecycle_request",
    "verify_correction_reused_request",
]
