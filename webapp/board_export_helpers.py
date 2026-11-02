"""Export page count aggregations and list search filters for ledger board.

Extracted under RF-102 to separate pure trip list search filters and export page
summary aggregations from the ledger board HTTP handler.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


def filter_trips(trips: List[Dict[str, Any]], query: str = "") -> List[Dict[str, Any]]:
    """Filter trips matching query text in display_key + destination.

    Enforces required keys display_key and destination, raising KeyError
    when a non-empty query is filtered against an incomplete trip row.
    """
    if not query:
        return list(trips)
    return [
        t for t in trips
        if query in (t["display_key"] + t["destination"])
    ]


def is_unclassified_matched(query: str = "") -> bool:
    """Whether the unclassified tab matches the query text."""
    return not query or query in "분류대기"


def collect_export_page_summaries(
    trips: List[Dict[str, Any]],
    *,
    list_tab_rows_fn: Callable[[Optional[str]], List[Dict[str, Any]]],
    row_needs_review_fn: Callable[[Dict[str, Any]], bool],
    row_has_conflict_fn: Callable[[Dict[str, Any]], bool],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Collect trip row counts and review/conflict summary from one read per tab.

    Enforces required keys row_kind, display_key, and archived.
    Evaluates list_tab_rows_fn once per trip and once for None, then reuses those
    rows for both counts and review/conflict tallies. The remaining store calls
    preserve their original relative order.
    """
    trip_counts: List[Dict[str, Any]] = []
    rows_by_trip: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for t in trips:
        rows = list_tab_rows_fn(t["tab_id"])
        rows_by_trip.append((t, rows))
        inc = sum(1 for r in rows if r["row_kind"] == "income")
        exp = sum(1 for r in rows if r["row_kind"] == "expense")
        trip_counts.append({
            "tab_id": t["tab_id"],
            "display_key": t["display_key"],
            "archived": bool(t["archived"]),
            "income_count": inc,
            "expense_count": exp,
        })
    unc = list_tab_rows_fn(None)
    unc_inc = sum(1 for r in unc if r["row_kind"] == "income")
    unc_exp = sum(1 for r in unc if r["row_kind"] != "income")
    trip_counts.append({
        "tab_id": None,
        "display_key": "분류대기",
        "archived": False,
        "income_count": unc_inc,
        "expense_count": unc_exp,
    })

    review_total = 0
    conflict_total = 0
    per_tab: List[Dict[str, Any]] = []
    for t, trows in rows_by_trip:
        n_review = sum(1 for r in trows if row_needs_review_fn(r))
        n_conflict = sum(1 for r in trows if row_has_conflict_fn(r))
        review_total += n_review
        conflict_total += n_conflict
        if n_review or n_conflict:
            per_tab.append({
                "tab_id": t["tab_id"],
                "display_key": t["display_key"],
                "review_count": n_review,
                "conflict_count": n_conflict,
            })
    n_unc_review = sum(1 for r in unc if row_needs_review_fn(r))
    n_unc_conflict = sum(1 for r in unc if row_has_conflict_fn(r))
    rc_summary = {
        "review_total": review_total + n_unc_review,
        "conflict_total": conflict_total + n_unc_conflict,
        "per_tab": per_tab,
    }
    return trip_counts, rc_summary
