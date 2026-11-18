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
        "display_key": str(trip.get("display_key") or ""),
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


def ledger_row(row: dict[str, Any], *, read_only: bool = False,
               period: str | None = None,
               period_source: str | None = None) -> dict[str, Any]:
    """Project a board row into the stable Plush table shape.

    ``period``/``period_source`` come from the shared stored/manual read
    (``ledger_periods``). A caller that does not resolve them keeps the stored
    ``service_period`` exactly as before.
    """
    kind = str(row.get("row_kind") or "expense")
    merchant = (row.get("source_merchant") if kind != "income" else row.get("customer_name"))
    merchant = merchant or row.get("item") or row.get("income_kind") or ""
    description = row.get("description") or row.get("item") or row.get("income_kind") or ""
    # ``item`` is the human-facing category (숙박·교통·식비).  The
    # classification state is a decision status and belongs in the detail DTO.
    category = row.get("item") if kind != "income" else row.get("income_kind")
    payment = row.get("pay_method") or row.get("card_kind") or row.get("source_kind") or ""
    evidence = row.get("evidence_type") or row.get("source_kind") or ""
    result = {
        "id": str(row.get("row_id") or ""),
        "date": _display_date(row),
        "merchant": str(merchant or ""),
        "description": str(description or ""),
        "category": str(category or ""),
        "amount": money(_display_amount(row)),
        # amount is the board's won-denominated display amount.  A source
        # currency must never relabel the KRW amount (e.g. 135000 USD).
        "currency": "KRW",
        "payment": str(payment or ""),
        "period": str(period if period is not None else row.get("service_period") or ""),
        "period_source": str(period_source or ""),
        "evidence_summary": str(evidence or ""),
        "revision": row.get("revision"),
        "read_only": bool(read_only),
    }
    status = row.get("_plush_period_status")
    if status in {"verified", "inferred", "unknown", "stale", "computed"}:
        result["period_status"] = status
    if row.get("_plush_period_basis"):
        result["period_basis"] = str(row["_plush_period_basis"])
    if row.get("_plush_period_manual_blank") is True:
        result["period_manual_blank"] = True
    source_amount = row.get("foreign_amount", row.get("amount"))
    if row.get('google_income') and row.get('amount_missing'):
        result['amount'] = '미확인'
    source_currency = (row.get("foreign_currency") or row.get("source_currency")
                       or row.get("currency"))
    if source_amount is not None and source_currency:
        result["source_amount"] = str(source_amount)
        result["source_currency"] = str(source_currency)
    return result


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


def origin_label(row: dict[str, Any]) -> str:
    """The stored classification origin as the standard short label, or "".

    Uses ``app.classification_provenance`` unchanged so the badge means the
    same thing wherever it appears: a revision bump or ``confirmed_by`` never
    decides it.  An unknown origin yields no label; the row simply shows none.
    """
    from app.classification_provenance import LABELS, origin

    value = origin(row)
    return "" if value == "unknown" else LABELS[value]


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
