"""Pure, header-bound normalization for Hana approval-sheet amounts."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Sequence

HAN_NORMALIZER_VERSION = "han-approval-sheet-v1"
HEADER_ALIASES = {
    "approval_amount": ("승인금액",),
    "cancel_amount": ("승인취소금액",),
    "purchase_amount": ("매입금액",),
}

@dataclass(frozen=True)
class HanColumnMap:
    approval_amount: int
    cancel_amount: int
    purchase_amount: int

@dataclass(frozen=True)
class HanRawAmounts:
    approval_amount: int
    purchase_amount: int
    cancel_amount: int

@dataclass(frozen=True)
class HanComponent:
    role: Literal["single", "approval", "cancellation"]
    signed_amount_krw: int
    transaction_type: Literal["purchase", "cancellation"]
    selection_reason: Literal["purchase_amount_nonzero", "approval_amount_fallback",
                              "split_approval_amount", "split_cancel_amount"]

def _header(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))

def normalize_han_identity_text(value: object) -> str:
    """Normalize optional sheet identity cells without turning None into text."""
    return str(value or "").strip()

def _amount(value: object, field: str, *, allow_negative: bool = False) -> int:
    if isinstance(value, bool): raise ValueError(f"han_amount_bool:{field}")
    if value is None or (isinstance(value, str) and not value.strip()): return 0
    text = str(value).replace(",", "").strip()
    if text.endswith("원"): text = text[:-1].strip()
    try: amount = Decimal(text)
    except InvalidOperation as exc: raise ValueError(f"han_amount_invalid:{field}") from exc
    if not amount.is_finite(): raise ValueError(f"han_amount_nonfinite:{field}")
    if amount != amount.to_integral_value(): raise ValueError(f"han_amount_fractional:{field}")
    result = int(amount)
    if result < 0 and not allow_negative: raise ValueError(f"han_amount_negative:{field}")
    return result

def validate_han_header(header: Sequence[object]) -> HanColumnMap:
    if isinstance(header, (str, bytes)) or not isinstance(header, Sequence):
        raise ValueError("han_header_invalid")
    normalized = [_header(value) for value in header]
    found: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        indices = [index for index, value in enumerate(normalized) if value in aliases]
        if not indices: raise ValueError(f"han_header_missing:{field}")
        if len(indices) != 1: raise ValueError(f"han_header_duplicate:{field}")
        found[field] = indices[0]
    if len(set(found.values())) != len(found): raise ValueError("han_header_alias_collision")
    return HanColumnMap(**found)

def parse_han_amounts(row: Sequence[object], columns: HanColumnMap) -> HanRawAmounts:
    if isinstance(row, (str, bytes)) or not isinstance(row, Sequence): raise ValueError("han_row_invalid")
    if max(columns.approval_amount, columns.cancel_amount, columns.purchase_amount) >= len(row):
        raise ValueError("han_row_short")
    return HanRawAmounts(
        approval_amount=_amount(row[columns.approval_amount], "approval_amount"),
        purchase_amount=_amount(row[columns.purchase_amount], "purchase_amount"),
        cancel_amount=_amount(row[columns.cancel_amount], "cancel_amount", allow_negative=True),
    )

def normalize_han_components(amounts: HanRawAmounts) -> tuple[HanComponent, ...]:
    if not isinstance(amounts, HanRawAmounts): raise TypeError("han_amounts_type")
    if (any(isinstance(value, bool) or not isinstance(value, int) for value in
            (amounts.approval_amount, amounts.purchase_amount, amounts.cancel_amount)) or
        amounts.approval_amount < 0 or amounts.purchase_amount < 0):
        raise ValueError("han_amounts_domain")
    if amounts.approval_amount == 0 and (amounts.purchase_amount or amounts.cancel_amount):
        raise ValueError("han_approval_amount_required")
    if amounts.cancel_amount:
        return (
            HanComponent("approval", abs(amounts.approval_amount), "purchase", "split_approval_amount"),
            HanComponent("cancellation", -abs(amounts.cancel_amount), "cancellation", "split_cancel_amount"),
        )
    if amounts.purchase_amount:
        return (HanComponent("single", amounts.purchase_amount, "purchase", "purchase_amount_nonzero"),)
    return (HanComponent("single", amounts.approval_amount, "purchase", "approval_amount_fallback"),)

def is_han_transaction(amounts: HanRawAmounts, *, identity_present: bool = False) -> bool:
    """Validate the amount tuple and distinguish the one allowed empty row."""
    normalize_han_components(amounts)
    populated = bool(amounts.approval_amount or amounts.purchase_amount or amounts.cancel_amount)
    if not populated and identity_present: raise ValueError("han_zero_amount_transaction")
    return populated

_CONTRACT = {"version": HAN_NORMALIZER_VERSION, "header_aliases": HEADER_ALIASES,
    "numeric": "blank=0,integer-krw,approval/purchase-nonnegative,cancel-signed,no-bool,no-nonfinite,no-fraction",
    "single": "purchase-nonzero-else-approval", "split": "approval-positive,cancel-negative",
    "row_domain": "card-or-approval-identity-first;identity-text=str(value-or-empty).strip;identified-zero-rejected;identity-absent-footer-only-skip;NO-cell-not-a-gate;approval-required-if-purchase-or-cancel-nonzero"}
HAN_NORMALIZER_CONTRACT_SHA256 = hashlib.sha256(json.dumps(
    _CONTRACT, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
).encode()).hexdigest()
