"""Read-only DTO builders for the authenticated Plush UI.

The projection layer deliberately works from ``LedgerStore`` read methods and
the access store's allowlist.  It never copies the board's HTML, and it keeps
internal notes, history and source payloads out of viewer responses.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable

from . import ledger_query

# 소유자 결정 2026-11-19: an income this ledger cannot confirm shows one em dash.
# The board has no income rows at all (54 of 54 trips), so a word like "미확인"
# would be a permanent sentence rather than a state that can change.
UNKNOWN_INCOME = "—"


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


def trip_summary(trip: dict[str, Any], rows: Iterable[dict[str, Any]],
                 *, linked: set | None = None) -> dict[str, Any]:
    """The trip's three figures, with COST and Google income kept apart.

    GGL-003 (보호): internal COST income and Google income are never summed.
    The summary's ``income`` is the COST figure — the same number the legacy
    KPI shows — and the Google block is separate evidence reported through
    ``income_source``. GGL-014: an unverified Google amount never enters the
    confirmed 수입 or 차액.

    R06: ``linked`` names the bank rows that are evidence for a direct income.
    They are the same money, so they never become a second COST income here —
    otherwise this figure would disagree with ``store.tab_totals`` and with the
    legacy KPI that already excludes them.

    The legacy rule this mirrors (``ledger_design._trip_kpi_html``): COST income
    wins whenever any recorded income row exists; a *verified* Google block
    substitutes only when the tab has no COST income at all; otherwise the
    figure is unknown, which is not the same as zero.
    """
    linked = linked or set()
    rows = list(rows)
    cost_income = [row for row in rows
                   if row.get("row_kind") == "income" and not row.get("google_income")
                   and row.get("row_id") not in linked]
    google_rows = [row for row in rows
                   if row.get("row_kind") == "income" and row.get("google_income")]
    expense = sum(ledger_query.display_amount(row) for row in rows
                  if row.get("row_kind") != "income")
    if cost_income:
        # An unreadable COST amount is not a zero either (SPEC §11.2.1 계약 4,
        # GGL-014). Summing it would present a confirmed figure lower than what
        # the rows say, so it must reach the same answer the Google branch is
        # already required to give.
        if any(row.get("amount_missing") for row in cost_income):
            income = None
        else:
            income = sum(ledger_query.display_amount(row) for row in cost_income)
    elif google_rows and trip.get("google_verified"):
        # Only a verified block may stand in for a missing COST figure, and only
        # when every row it relies on has a readable amount (GGL-014).
        if any(row.get("amount_missing") for row in google_rows):
            income = None
        else:
            income = sum(ledger_query.display_amount(row) for row in google_rows)
    else:
        # No COST income and no verified Google block: unknown, never a
        # confirmed zero (SPEC §11.2.1 계약 4).
        income = None
    return {
        "id": str(trip.get("tab_id") or ""),
        "title": str(trip.get("display_title") or trip.get("display_key") or trip.get("destination") or ""),
        "display_key": str(trip.get("display_key") or ""),
        "kind": trip_kind(trip),
        "previous": is_previous(trip),
        "starts_on": str(trip.get("starts_on") or ""),
        "ends_on": str(trip.get("ends_on") or ""),
        "income": money(income) if income is not None else UNKNOWN_INCOME,
        "expense": money(expense),
        # The 차액 is only computable when the income figure is known.
        "profit": money(income - expense) if income is not None else UNKNOWN_INCOME,
        "closed": bool(trip.get("visual_closed") or trip.get("archived")),
        "archived": bool(trip.get("archived")),
    }


def _display_date(row: dict[str, Any]) -> str:
    return str(row.get("display_occurred_on") or row.get("occurred_on") or "")


def ledger_row(row: dict[str, Any], *, read_only: bool = False,
               period: str | None = None,
               period_source: str | None = None,
               period_label: str | None = None,
               period_label_full: str | None = None,
               google_match: dict[str, Any] | None = None) -> dict[str, Any]:
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
    label = str(period_label if period_label is not None
                else row.get("_plush_period_label") or "")
    stored_period = str(period if period is not None else row.get("service_period") or "")
    # 소유자 결정 2026-11-19: a blank period cell means "no date", never "the raw
    # stored range". The screen falls back to `period` when it has no label, so
    # the two must agree at the source: when the label is blank the row carries
    # no period value either. A real date still travels in both fields.
    if not label:
        stored_period = ""
    result = {
        "id": str(row.get("row_id") or ""),
        "date": _display_date(row),
        "merchant": str(merchant or ""),
        "description": str(description or ""),
        "category": str(category or ""),
        "amount": money(ledger_query.display_amount(row)),
        # amount is the board's won-denominated display amount.  A source
        # currency must never relabel the KRW amount (e.g. 135000 USD).
        "currency": "KRW",
        "payment": str(payment or ""),
        "period": stored_period,
        "period_source": str(period_source or ""),
        # The compact and full labels the legacy cell already prints, so both
        # entry paths show the same wording (SPEC §11.2.1 계약 4). Empty when the
        # formatter could not describe this row, which is also when `period` is
        # emptied above, so a blank cell cannot be refilled by the other field.
        "period_label": label,
        "period_label_full": str(period_label_full if period_label_full is not None
                                 else row.get("_plush_period_label_full") or ""),
        "google_match": google_match,
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


def search_text(row: dict[str, Any], *, owner: bool = False) -> str:
    """The text a search runs against, over the fields this caller may read.

    The legacy board searches a row's own recorded fields, including the
    operator's note; the React list searched only the displayed projection, so
    a query that matched a memo found the row on one path and not the other.
    ``operator_note`` is a viewer-denied field (``access_control.VIEWER_DENIED_
    FIELDS``), so it is included for the owner only — a viewer's search cannot
    reach it and cannot use it as an oracle for text they may not see.
    """
    projected = ledger_row(row)
    parts = [str(projected.get(key) or "") for key in (
        "date", "merchant", "description", "category", "payment", "period", "evidence_summary")]
    # The legacy board searches the row's own recorded fields, including the
    # stored period range (``ledger_design._matches``). The displayed ``period``
    # is blank whenever the cell is blank (소유자 결정 2026-11-19), so the search
    # has to read the stored field itself or a query that finds the row on the
    # legacy path would miss it on this one (SPEC §11.2.1 계약 1).
    parts.extend(str(row.get(key) or "") for key in (
        "item", "reservation_no", "source_merchant", "customer_name", "service_period"))
    if owner:
        parts.append(str(row.get("operator_note") or ""))
    return " ".join(parts).casefold()
