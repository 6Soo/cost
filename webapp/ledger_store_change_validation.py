"""Pure row change validation rules for LedgerStore.

Extracted under RF-101 (Store decomposition change validation boundary).
Preserves exact execution semantics, error codes, Korean messages, KeyError contracts,
date/number type rules, and short-circuit evaluation order of the original store.

NOTE: This module contains ZERO imports of HTTP/presentation layers (such as ledger_board).
Display tab validation is injected via lazy callback from the façade.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Optional

from .ledger_store_allocation_validation import SaveError

CARD_EDITABLE: tuple[str, ...] = ("display_tab_id", "item", "description", "operator_note")
CARD_READONLY: tuple[str, ...] = (
    "occurred_on",
    "amount_krw",
    "source_event_id",
    "source_kind",
    "merchant",
    "reservation_no",
)
INCOME_EDITABLE: tuple[str, ...] = (
    "display_tab_id",
    "income_kind",
    "customer_id",
    "customer_name",
    "nickname",
    "occurred_on",
    "amount_krw",
    "operator_note",
)


def valid_date(value: Any) -> bool:
    """Validate ISO YYYY-MM-DD date string."""
    if not isinstance(value, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        _dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate_row_changes(
    current: dict,
    changes: dict,
    *,
    card_editable: tuple[str, ...] = CARD_EDITABLE,
    card_readonly: tuple[str, ...] = CARD_READONLY,
    income_editable: tuple[str, ...] = INCOME_EDITABLE,
    get_linked_direct_ids_fn: Optional[Callable[[], set]] = None,
    validate_display_tab_fn: Optional[Callable[[Any], None]] = None,
    valid_date_fn: Callable[[Any], bool] = valid_date,
    save_error_cls: type[Exception] = SaveError,
) -> None:
    """Validate proposed changes to a ledger row against editable rules and constraints.

    Preserves exact KeyError contract: raises KeyError if current lacks 'row_kind'.
    Preserves exact short-circuiting:
      - get_linked_direct_ids_fn is only called when modifying amount_krw or occurred_on
        on non-bank direct income.
      - validate_display_tab_fn is only called when display_tab_id is in changes.
    Preserves exact evaluation and error precedence order:
      1. Field editability / read-only rules (raises FIELD_READ_ONLY or INVALID_VALUE)
      2. display_tab_id validity (raises TARGET_NOT_ASSIGNABLE via validate_display_tab_fn)
      3. amount_krw integer validity (raises INVALID_VALUE)
      4. occurred_on date format/validity (raises INVALID_VALUE)
      5. income_kind validity (raises INVALID_VALUE)
    """
    kind = current["row_kind"]
    source = current.get("source_kind", "")
    if kind == "expense" and source in ("카드", ""):
        for field in changes:
            if field in card_readonly:
                raise save_error_cls("FIELD_READ_ONLY", f"{field}는 고정 필드라 바꿀 수 없어요")
            if field not in card_editable:
                raise save_error_cls("INVALID_VALUE", f"허용하지 않은 필드예요: {field}")
    elif kind == "expense":
        for field in changes:
            if field not in card_editable + ("occurred_on", "amount_krw"):
                raise save_error_cls("INVALID_VALUE", f"허용하지 않은 필드예요: {field}")
    else:
        if source == "은행":
            for field in changes:
                if field not in (
                    "customer_id",
                    "customer_name",
                    "nickname",
                    "display_tab_id",
                    "operator_note",
                    "income_kind",
                ):
                    raise save_error_cls("FIELD_READ_ONLY", f"{field}는 바꿀 수 없어요")
        else:
            for field in changes:
                if field not in income_editable:
                    raise save_error_cls("FIELD_READ_ONLY", f"{field}는 바꿀 수 없어요")
            if "amount_krw" in changes or "occurred_on" in changes:
                try:
                    linked_direct = (
                        get_linked_direct_ids_fn()
                        if get_linked_direct_ids_fn is not None
                        else set()
                    )
                except Exception:
                    linked_direct = set()
                if current.get("row_id") in linked_direct:
                    raise save_error_cls(
                        "FIELD_READ_ONLY",
                        "은행 원천 연결 뒤에는 은행 정정 경로를 써 주세요",
                    )
    if "display_tab_id" in changes:
        if validate_display_tab_fn is not None:
            validate_display_tab_fn(changes["display_tab_id"])
    if "amount_krw" in changes:
        value = changes["amount_krw"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise save_error_cls("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
    if "occurred_on" in changes:
        if not valid_date_fn(changes["occurred_on"]):
            raise save_error_cls("INVALID_VALUE", "날짜 형식이 달라요")
    if "income_kind" in changes:
        if changes["income_kind"] not in ("deposit", "balance", "additional"):
            raise save_error_cls("INVALID_VALUE", "입금 종류를 골라 주세요")


__all__ = [
    "CARD_EDITABLE",
    "CARD_READONLY",
    "INCOME_EDITABLE",
    "valid_date",
    "validate_row_changes",
]
