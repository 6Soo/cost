"""Pure allocation validation and normalization rules for LedgerStore.

Extracted under RF-101 (Store decomposition allocation validation bundle).
Preserves exact execution semantics, exceptions, Korean messages, types,
and dynamic dispatch behaviors of the original store.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .ledger_store_records import ALLOCATION_ROW_EDITABLE


class SaveError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_plan_for_compare(plan: Any) -> list:
    return sorted(
        (str(p.get("allocation_id") or ""),
         str(p.get("customer_id") or ""), str(p.get("customer_name") or ""),
         str(p.get("nickname") or ""), str(p.get("display_tab_id") or ""),
         str(p.get("income_kind") or ""), p.get("amount_krw"))
        for p in (plan or [])
    )


def normalize_allocation_row_changes(
    changes: Any,
    *,
    get_trip_fn: Optional[Callable[[str], Optional[dict]]] = None,
    save_error_cls: type[Exception] = SaveError,
) -> dict:
    if not isinstance(changes, dict) or not changes:
        raise save_error_cls("INVALID_VALUE", "수정할 수 있는 필드가 없어요")
    unknown = [field for field in changes if field not in ALLOCATION_ROW_EDITABLE]
    if unknown:
        raise save_error_cls("FIELD_READ_ONLY", f"{unknown[0]}는 배분 행에서 수정할 수 없어요")
    normalized = {}
    for field in ALLOCATION_ROW_EDITABLE:
        if field not in changes:
            continue
        value = changes[field]
        if field == "display_tab_id":
            value = None if value is None or str(value).strip() in ("", "unclassified") else str(value)
        elif field == "customer_id":
            value = None if value is None or str(value).strip() == "" else str(value)
        elif field in ("customer_name", "nickname"):
            value = "" if value is None else str(value)
        elif field == "income_kind":
            value = str(value or "")
            if value not in ("deposit", "balance", "additional"):
                raise save_error_cls("INVALID_VALUE", "입금 종류를 골라 주세요")
        normalized[field] = value
    if not normalized:
        raise save_error_cls("INVALID_VALUE", "수정할 수 있는 필드가 없어요")
    destination = normalized.get("display_tab_id")
    if destination is not None:
        if get_trip_fn is None:
            raise save_error_cls("TARGET_NOT_ASSIGNABLE", "배정할 수 없는 여행이에요")
        trip = get_trip_fn(destination)
        if trip is None or trip["deleted"]:
            raise save_error_cls("TARGET_NOT_ASSIGNABLE", "배정할 수 없는 여행이에요")
    return normalized


def allocation_request_matches(
    stored: dict,
    api: str,
    allocation_id: str,
    expected_source_revision: int,
    changes: Any,
) -> bool:
    if stored.get("api") != api:
        return False
    if stored.get("allocation_id") != allocation_id:
        return False
    if stored.get("expected_source_revision") != expected_source_revision:
        return False
    return changes is None or stored.get("changes") == changes


def validate_allocation_plan(
    source: dict,
    reflected: int,
    plan: list,
    *,
    get_trip_fn: Optional[Callable[[str], Optional[dict]]] = None,
    save_error_cls: type[Exception] = SaveError,
) -> list:
    cleaned = []
    for index, item in enumerate(plan):
        if not isinstance(item, dict):
            raise save_error_cls("INVALID_VALUE", "배분안이 올바르지 않아요")
        amount = item.get("amount_krw")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0:
            raise save_error_cls("INVALID_VALUE", "배분액은 0이 아닌 정수 원화로 입력해 주세요")
        if reflected > 0 and amount < 0:
            raise save_error_cls("INVALID_VALUE", "양수 입금은 양수 배분만 할 수 있어요")
        if reflected < 0 and amount > 0:
            raise save_error_cls("INVALID_VALUE", "음수 환불은 음수 배분만 할 수 있어요")
        kind = item.get("income_kind")
        if kind not in ("deposit", "balance", "additional"):
            raise save_error_cls("INVALID_VALUE", "입금 종류를 골라 주세요")
        if not str(item.get("customer_name") or "").strip():
            raise save_error_cls("INVALID_VALUE", "배분 고객 이름이 필요해요")
        tab = item.get("display_tab_id")
        if tab is not None:
            if get_trip_fn is None:
                raise save_error_cls("TARGET_NOT_ASSIGNABLE", "배정할 수 없는 여행이에요")
            trip = get_trip_fn(tab)
            if trip is None or trip["deleted"]:
                raise save_error_cls("TARGET_NOT_ASSIGNABLE", "배정할 수 없는 여행이에요")
        cleaned.append({
            "allocation_id": str(item.get("allocation_id") or ""),
            "customer_id": item.get("customer_id"),
            "customer_name": str(item.get("customer_name") or ""),
            "nickname": str(item.get("nickname") or ""),
            "display_tab_id": tab,
            "income_kind": kind,
            "amount_krw": amount,
        })
    total = sum(c["amount_krw"] for c in cleaned)
    if reflected == 0:
        if cleaned:
            raise save_error_cls("INVALID_VALUE", "나눌 금액이 없어요")
    elif abs(total) > abs(reflected):
        raise save_error_cls("INVALID_VALUE", "배분 합계가 입금액을 넘었어요")
    return cleaned


__all__ = [
    "ALLOCATION_ROW_EDITABLE",
    "SaveError",
    "allocation_request_matches",
    "normalize_allocation_row_changes",
    "normalize_plan_for_compare",
    "validate_allocation_plan",
]
