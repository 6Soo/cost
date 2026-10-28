"""Read projection and display calculation helpers for ledger board rows.

Extracted under RF-102 to isolate read-only row projections, display amounts,
persisted row aggregation, and trip totals from the core ledger board request handler.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple


def shown_date(row: Dict[str, Any]) -> str:
    """The display date of a row, falling back to occurred_on."""
    return row.get("display_occurred_on", row.get("occurred_on", ""))


def shown_amount(row: Dict[str, Any]) -> int:
    """The display amount of a row in KRW, falling back to amount_krw."""
    return row.get("display_amount_krw", row.get("amount_krw", 0))


def with_display_amount(
    rows: List[Dict[str, Any]],
    *,
    store: Any,
) -> List[Dict[str, Any]]:
    """Annotate rows in-place with display_amount_krw and display_occurred_on."""
    if store is None:
        return rows
    for r in rows:
        if "display_amount_krw" not in r:
            projected = store.projected(r)
            r["display_amount_krw"] = projected["display_amount_krw"]
            r["display_occurred_on"] = projected["display_occurred_on"]
        elif "display_occurred_on" not in r:
            r["display_occurred_on"] = store.display_occurred_on(r)
    return rows


def load_persisted_rows(
    kind: str,
    *,
    store: Any,
    tab_ids: List[Optional[str]],
    fetch_tab_rows_fn: Callable[[Optional[str]], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Load and project saved rows for one kind across all tabs and unclassified."""
    out: List[Dict[str, Any]] = []
    for tab in tab_ids + [None]:
        saved_rows = fetch_tab_rows_fn(tab)
        for saved in saved_rows:
            if saved.get("row_kind") == kind:
                out.append(dict(saved))
    return with_display_amount(out, store=store)


def persisted_rows(
    kind: str,
    *,
    remember_fn: Optional[Callable[[Tuple[str, str], Callable[[], List[Dict[str, Any]]]], List[Dict[str, Any]]]] = None,
    loader_fn: Callable[[], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return a fresh list of dict copies for one kind, optionally caching via remember_fn."""
    if remember_fn is not None:
        rows = remember_fn(("persisted_rows", kind), loader_fn)
    else:
        rows = loader_fn()
    return [dict(r) for r in rows]


def expense_rows(
    *,
    store: Any,
    fallback_expenses: List[Dict[str, Any]],
    persisted_rows_fn: Callable[[str], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """All expense rows from the store, or fallback demo rows when no store is active."""
    if store is None:
        return [dict(r) for r in fallback_expenses]
    return persisted_rows_fn("expense")


def income_rows(
    *,
    store: Any,
    fallback_incomes: List[Dict[str, Any]],
    persisted_rows_fn: Callable[[str], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """All income rows from the store, or fallback demo rows when no store is active."""
    if store is None:
        return [dict(r) for r in fallback_incomes]
    return persisted_rows_fn("income")


def trip_income_total(tab_id: str, *, rows: List[Dict[str, Any]]) -> int:
    """Sum of income rows for a trip tab."""
    return sum(r["amount_krw"] for r in rows if r.get("display_tab_id") == tab_id)


def trip_expense_total(tab_id: str, *, rows: List[Dict[str, Any]]) -> int:
    """Sum of expense rows for a trip tab."""
    return sum(r["amount_krw"] for r in rows if r.get("display_tab_id") == tab_id)


def trip_profit(income_total: int, expense_total: int) -> int:
    """Profit calculation (income - expense)."""
    return income_total - expense_total


def fallback_trip_totals(
    tab_id: str,
    *,
    incomes: List[Dict[str, Any]],
    expenses: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Calculate fallback totals from static demo lists."""
    inc = trip_income_total(tab_id, rows=incomes)
    exp = trip_expense_total(tab_id, rows=expenses)
    return {
        "income": inc,
        "expense": exp,
        "profit": trip_profit(inc, exp),
    }


def trip_totals(
    tab_id: str,
    *,
    store: Any,
    fallback_totals_fn: Callable[[str], Dict[str, int]],
) -> Dict[str, int]:
    """Trip totals from store, or fallback totals when store is not active."""
    if store is None:
        return fallback_totals_fn(tab_id)
    return store.tab_totals(tab_id)


def unclassified_rows(*, expense_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter rows that have no display_tab_id."""
    return [r for r in expense_rows if r.get("display_tab_id") is None]


def income_total(
    rows: List[Dict[str, Any]],
    *,
    store: Any,
    shown_amount_fn: Callable[[Dict[str, Any]], int] = shown_amount,
) -> int:
    """Sum of display amounts for non-bank-linked income rows."""
    linked: Set[str] = store.linked_bank_row_ids() if store is not None else set()
    return sum(
        shown_amount_fn(r) for r in rows if r.get("row_id") not in linked
    )


def customer_total(customer_id: str, tab_id: str, *, rows: List[Dict[str, Any]]) -> int:
    """Sum of amounts for a specific customer on a trip tab."""
    return sum(
        r["amount_krw"]
        for r in rows
        if r.get("customer_id") == customer_id and r.get("display_tab_id") == tab_id
    )
