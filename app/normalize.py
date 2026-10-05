# -*- coding: utf-8 -*-
"""Normalization, reusing the meanings in source/ledger.

The reference code in `source/ledger/cardindex.py` and
`source/ledger/domain/han_normalizer.py` is the authority for what an amount, a
date and a cancellation mean here. Two of its behaviours are copied on purpose
and one is deliberately *not*:

* Dates fold `2026.04.09`, `2026-04-09`, `20260409` and `2026/4/9` to `2026-04-09`
  (`d10`).
* Amounts accept a thousands separator and a trailing `원`, and are read through
  `Decimal` so a won amount never picks up binary float error (`_amount`).
* `cardindex.i()` returns `0` when it cannot parse. **That is not reproduced.**
  A transaction with an unreadable amount is an error, and an error that would
  otherwise be silently priced at zero won is the one failure this module exists
  to prevent. Zero is a real amount and is returned as zero; only a *failure* to
  read is an error.

An XLSX cell holding a formula with no cached value arrives as `None`. That is
not "no amount", it is "the amount is in this file and we were not given it",
and it raises.
"""

from __future__ import annotations

import datetime
import re
from decimal import Decimal, InvalidOperation

__all__ = [
    "AmountUnreadable",
    "to_amount_krw",
    "to_decimal",
    "to_date",
    "normalize_merchant",
    "normalize_identity_text",
    "is_cancel_text",
    "to_currency_text",
    "CARD_KINDS",
    "DIRECTIONS",
    "CANCEL_WORDS",
]

CARD_KINDS = ("신용", "체크", "캐피탈", "전용", "기타")
DIRECTIONS = ("purchase", "cancellation")
CANCEL_WORDS = ("취소", "매입취소", "부분취소", "cancel", "refund")

_DATE = re.compile(r"^(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})$")
_AMOUNT_NOISE = re.compile(r"[,\s원₩]")


class AmountUnreadable(ValueError):
    """The amount could not be read. Never silently becomes zero."""


def to_decimal(value, field: str = "amount") -> Decimal:
    """Read a number without inventing one.

    Handles `1,234`, `1234원`, `(1,234)` for a negative, and a leading sign.
    Rejects bools, blank cells, text that is not a number, and the `None` that
    an uncached XLSX formula leaves behind.
    """
    if isinstance(value, bool):
        raise AmountUnreadable(f"{field}_bool")
    if value is None:
        raise AmountUnreadable(f"{field}_missing")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        amount = Decimal(str(value))
    else:
        text = str(value).strip()
        if not text:
            raise AmountUnreadable(f"{field}_blank")
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1].strip()
        text = _AMOUNT_NOISE.sub("", text)
        if text.startswith("+"):
            text = text[1:]
        elif text.startswith("-"):
            negative = not negative
            text = text[1:]
        if not text:
            raise AmountUnreadable(f"{field}_blank")
        try:
            amount = Decimal(text)
        except InvalidOperation:
            raise AmountUnreadable(f"{field}_invalid:{value!r}") from None
        if negative:
            amount = -amount
    if not amount.is_finite():
        raise AmountUnreadable(f"{field}_nonfinite")
    return amount


def to_amount_krw(value, field: str = "amount") -> int:
    """A won amount as an exact integer.

    Foreign-currency rows are *not* accepted here: they carry their own amount
    and currency and need an explicit rate, which guessing would invent.
    """
    amount = to_decimal(value, field)
    if amount != amount.to_integral_value():
        raise AmountUnreadable(f"{field}_fractional_won:{amount}")
    return int(amount)


def to_date(value, field: str = "date") -> str:
    """`2026-04-09`, from any of the shapes the card sheets use."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.date().isoformat() if isinstance(
            value, datetime.datetime) else value.isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    if " " in text:
        text = text.split(" ", 1)[0]
    if "T" in text:
        text = text.split("T", 1)[0]
    digits = re.sub(r"\D", "", text)
    match = _DATE.match(text.strip())
    if not match:
        # `2026/4/9` and `20260409` both carry a single-digit month or day.
        loose = re.match(r"^(\d{4})[.\-/]?(\d{1,2})[.\-/]?(\d{1,2})$", text.strip())
        if not loose:
            loose = re.match(r"^(\d{4})(\d{1,2})(\d{1,2})$", digits)
        if not loose:
            return ""
        year, month, day = loose.groups()
        month, day = month.zfill(2), day.zfill(2)
    else:
        year, month, day = match.groups()
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        return ""
    try:
        return datetime.date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return ''


def normalize_merchant(value) -> str:
    """Fold case and repeated spaces only.

    No transliteration, no punctuation stripping, no fuzzy matching: two
    merchants that differ only by punctuation are two merchants as far as this
    pipeline is concerned, because collapsing them would silently widen a rule.
    """
    return " ".join(str(value or "").split()).casefold()


def normalize_identity_text(value) -> str:
    """Optional identity cells: `None` is absence, not the text "None"."""
    if value is None:
        return ""
    return str(value).strip()


def is_cancel_text(value) -> bool:
    """True when the cell says this is a cancellation, in either language."""
    text = str(value or "").strip().casefold()
    if not text:
        return False
    return any(word in text for word in CANCEL_WORDS)


def to_currency_text(value) -> str:
    """Currency code, upper-cased. Blank stays blank: no default currency."""
    text = re.sub(r"[^A-Za-z]", "", str(value or ""))
    return text.upper()[:8]
