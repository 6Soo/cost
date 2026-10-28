"""Pure create input validation, normalization, and record building rules for LedgerStore.

Extracted under RF-101 (Store decomposition create input normalization boundary).
Preserves exact execution semantics, error codes, Korean messages, required key checks,
date/number type rules, and record dictionary layout of original store.

NOTE: This module contains ZERO imports of HTTP/presentation layers (ledger_board) or LedgerStore.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .ledger_store_allocation_validation import SaveError
from .ledger_store_audit import canonical_json
from .ledger_store_change_validation import valid_date


def normalize_create_input(fields: dict) -> dict:
    """Normalize fields dict into canonical JSON-roundtripped dictionary.

    Maps None values explicitly and sorts keys canonically.
    """
    return json.loads(canonical_json({
        k: (None if v is None else v) for k, v in (fields or {}).items()
    }))


def validate_direct_income_create_input(
    fields: dict,
    client_request_id: str,
    *,
    valid_date_fn: Callable[[Any], bool] = valid_date,
    normalize_create_input_fn: Callable[[dict], dict] = normalize_create_input,
    save_error_cls: type[Exception] = SaveError,
) -> tuple[str, dict]:
    """Validate direct income creation input and produce (row_id, want_input).

    Required keys check order:
      1. display_tab_id
      2. occurred_on
      3. amount_krw
      4. income_kind
    Constraint checks:
      - income_kind must be in ('deposit', 'balance', 'additional')
      - amount_krw must be int (bool, float, Decimal, str rejected)
      - occurred_on must be valid ISO date string
      - client_request_id must be non-empty string
    """
    for key in ("display_tab_id", "occurred_on", "amount_krw", "income_kind"):
        if key not in fields:
            raise save_error_cls("INVALID_VALUE", f"{key}가 필요해요")
    if fields["income_kind"] not in ("deposit", "balance", "additional"):
        raise save_error_cls("INVALID_VALUE", "입금 종류를 골라 주세요")
    if isinstance(fields["amount_krw"], bool) or not isinstance(fields["amount_krw"], int):
        raise save_error_cls("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
    if not valid_date_fn(str(fields["occurred_on"])):
        raise save_error_cls("INVALID_VALUE", "날짜 형식이 달라요")
    if not client_request_id or not isinstance(client_request_id, str):
        raise save_error_cls("INVALID_VALUE", "요청 ID가 필요해요")

    row_id = f"inc-{client_request_id[:16]}"
    want_input = normalize_create_input_fn(fields)
    return row_id, want_input


def build_direct_income_record(
    *,
    row_id: str,
    fields: dict,
    client_request_id: str,
) -> dict:
    """Build the initial row payload record for direct income."""
    return {
        "row_id": row_id,
        "row_kind": "income",
        "display_tab_id": fields["display_tab_id"],
        "revision": 1,
        "occurred_on": str(fields["occurred_on"]),
        "customer_id": fields.get("customer_id"),
        "customer_name": str(fields.get("customer_name") or ""),
        "nickname": str(fields.get("nickname") or ""),
        "income_kind": fields["income_kind"],
        "event_type": "receipt",
        "amount_krw": fields["amount_krw"],
        "source_kind": "직접 입력",
        "source_event_id": row_id,
        "operator_note": str(fields.get("memo") or ""),
        "created_by_request": client_request_id,
    }


def validate_manual_expense_create_input(
    fields: dict,
    client_request_id: str,
    *,
    valid_date_fn: Callable[[Any], bool] = valid_date,
    normalize_create_input_fn: Callable[[dict], dict] = normalize_create_input,
    save_error_cls: type[Exception] = SaveError,
) -> tuple[str, dict]:
    """Validate manual expense creation input and produce (row_id, want_input).

    Required keys check order:
      1. display_tab_id
      2. occurred_on
      3. amount_krw
      4. item
    Constraint checks:
      - evidence_type or pay_method in ('현금', '계좌이체')
      - amount_krw must be int (bool, float, Decimal, str rejected)
      - occurred_on must be valid ISO date string
      - client_request_id must be non-empty string
    """
    for key in ("display_tab_id", "occurred_on", "amount_krw", "item"):
        if key not in fields:
            raise save_error_cls("INVALID_VALUE", f"{key}가 필요해요")
    if not fields.get("evidence_type") and fields.get("pay_method") not in ("현금", "계좌이체"):
        raise save_error_cls("INVALID_VALUE", "지급 수단을 현금·계좌이체 중에서 골라 주세요")
    if isinstance(fields["amount_krw"], bool) or not isinstance(fields["amount_krw"], int):
        raise save_error_cls("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
    if not valid_date_fn(str(fields["occurred_on"])):
        raise save_error_cls("INVALID_VALUE", "날짜 형식이 달라요")
    if not client_request_id or not isinstance(client_request_id, str):
        raise save_error_cls("INVALID_VALUE", "요청 ID가 필요해요")

    row_id = f"man-{client_request_id[:16]}"
    want_input = normalize_create_input_fn(fields)
    return row_id, want_input


def build_manual_expense_record(
    *,
    row_id: str,
    fields: dict,
    client_request_id: str,
) -> dict:
    """Build the initial row payload record for manual expense."""
    return {
        "row_id": row_id,
        "row_kind": "expense",
        "display_tab_id": fields["display_tab_id"],
        "revision": 1,
        "occurred_on": str(fields["occurred_on"]),
        "item": str(fields["item"]),
        "description": str(fields.get("description") or ""),
        "service_period": str(fields.get("service_period") or ""),
        "reservation_no": str(fields.get("reservation_no") or ""),
        "evidence_type": (
            str(fields["evidence_type"])
            if fields.get("evidence_type")
            else "현금"
            if fields["pay_method"] == "현금"
            else "계좌이체"
        ),
        "amount_krw": fields["amount_krw"],
        "source_kind": "수기",
        "source_event_id": row_id,
        "classification_state": "",
        "classification_basis": "직접 입력",
        "operator_note": str(fields.get("memo") or ""),
        "created_by_request": client_request_id,
    }


__all__ = [
    "build_direct_income_record",
    "build_manual_expense_record",
    "normalize_create_input",
    "validate_direct_income_create_input",
    "validate_manual_expense_create_input",
]
