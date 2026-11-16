"""Read-only DTO builders for the authenticated Plush UI.

The projection layer deliberately works from ``LedgerStore`` read methods and
the access store's allowlist.  It never copies the board's HTML, and it keeps
internal notes, history and source payloads out of viewer responses.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable


def money(value: Any) -> str:
    """Return a stable integer KRW string without locale formatting."""
    try:
        return str(int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return "0"


def trip_kind(trip: dict[str, Any]) -> str:
    return "quarter" if str(trip.get("tab_kind") or "") in {"quarter", "other"} else "trip"


def is_previous(trip: dict[str, Any]) -> bool:
    try:
        return _dt.date.fromisoformat(str(trip.get("starts_on") or "")) <= _dt.date(2026, 6, 25)
    except (TypeError, ValueError):
        return False


def trip_summary(trip: dict[str, Any], rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    income = sum(_display_amount(row) for row in rows if row.get("row_kind") == "income")
    expense = sum(_display_amount(row) for row in rows if row.get("row_kind") != "income")
    return {
        "id": str(trip.get("tab_id") or ""),
        "title": str(trip.get("display_title") or trip.get("display_key") or trip.get("destination") or ""),
        "kind": trip_kind(trip),
        "previous": is_previous(trip),
        "starts_on": str(trip.get("starts_on") or ""),
        "ends_on": str(trip.get("ends_on") or ""),
        "income": money(income),
        "expense": money(expense),
        "profit": money(income - expense),
        "closed": bool(trip.get("visual_closed") or trip.get("archived")),
        "archived": bool(trip.get("archived")),
    }


def _display_amount(row: dict[str, Any]) -> int:
    value = row.get("display_amount_krw", row.get("amount_krw", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _display_date(row: dict[str, Any]) -> str:
    return str(row.get("display_occurred_on") or row.get("occurred_on") or "")


def ledger_row(row: dict[str, Any], *, read_only: bool = False) -> dict[str, Any]:
    """Project a board row into the stable Plush table shape."""
    kind = str(row.get("row_kind") or "expense")
    merchant = (row.get("source_merchant") if kind != "income" else row.get("customer_name"))
    merchant = merchant or row.get("item") or row.get("income_kind") or ""
    description = row.get("description") or row.get("item") or row.get("income_kind") or ""
    category = row.get("classification_state") or row.get("income_kind") or ""
    payment = row.get("pay_method") or row.get("card_kind") or row.get("source_kind") or ""
    evidence = row.get("evidence_type") or row.get("source_kind") or ""
    return {
        "id": str(row.get("row_id") or ""),
        "date": _display_date(row),
        "merchant": str(merchant or ""),
        "description": str(description or ""),
        "category": str(category or ""),
        "amount": money(_display_amount(row)),
        "currency": str(row.get("currency") or "KRW"),
        "payment": str(payment or ""),
        "period": str(row.get("service_period") or ""),
        "evidence_summary": str(evidence or ""),
        "revision": row.get("revision"),
        "read_only": bool(read_only),
    }


def safe_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(row.get("source_kind") or ""),
        "event_id": str(row.get("source_event_id") or ""),
        "merchant": str(row.get("source_merchant") or ""),
        "evidence_type": str(row.get("evidence_type") or ""),
        "has_source": bool(row.get("source_event_id") or row.get("source_kind")),
    }


def safe_decision(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": str(row.get("classification_state") or ""),
        "basis": str(row.get("classification_basis") or ""),
        "category": str(row.get("income_kind") or row.get("item") or ""),
    }


def safe_detail(row: dict[str, Any]) -> dict[str, Any]:
    """Owner-visible structured fields, excluding raw notes and payloads."""
    allowed = (
        "row_id", "row_kind", "display_tab_id", "occurred_on", "item", "description",
        "amount_krw", "source_kind", "source_event_id", "source_merchant", "evidence_type",
        "service_period", "reservation_no", "customer_id", "customer_name", "nickname",
        "income_kind", "event_type", "revision", "classification_state", "classification_basis",
    )
    return {key: row.get(key) for key in allowed if key in row}


def search_text(row: dict[str, Any]) -> str:
    projected = ledger_row(row)
    return " ".join(str(projected.get(key) or "") for key in (
        "date", "merchant", "description", "category", "payment", "period", "evidence_summary"
    )).casefold()

