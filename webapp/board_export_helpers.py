"""Export formatting and list search/filter helpers for ledger board.

Extracted under RF-102 to separate pure TSV export formatting, trip/row search
filters, and export review count aggregations from the ledger board HTTP handler.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple


def format_trip_expense_tsv(tab_id: str, expenses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Format trip expenses into Google Sheets 7-column TSV (B:H).

    Consumes app.google_tsv.expense_tsv to preserve exact column escaping,
    duplicate detection, formula escaping, and held-row reasons.
    """
    from app.google_tsv import expense_tsv

    rows = []
    for row in expenses:
        rows.append({
            "transaction_id": row.get("source_event_id") or row.get("row_id"),
            "status": "blocked" if row.get("blocked") else "ready",
            "date": row.get("occurred_on"),
            "payee": row.get("source_merchant") or row.get("description") or "",
            "category": row.get("item"),
            "period": row.get("service_period"),
            "reservation_no": row.get("reservation_no"),
            "evidence": {"카드": "card", "영수증": "receipt"}.get(row.get("evidence_type")),
            "amount_krw": row.get("display_amount_krw", row.get("amount_krw")),
        })
    return {**expense_tsv(rows, layout="rev"), "tab_id": tab_id}


def filter_trips(trips: List[Dict[str, Any]], query: str = "") -> List[Dict[str, Any]]:
    """Filter trips matching query text in display_key + destination."""
    if not query:
        return list(trips)
    return [
        t for t in trips
        if query in (t.get("display_key", "") + t.get("destination", ""))
    ]


def is_unclassified_matched(query: str = "") -> bool:
    """Whether the unclassified tab matches the query text."""
    return not query or query in "분류대기"


def filter_tab_rows(rows: List[Dict[str, Any]], tab_id: Optional[str]) -> List[Dict[str, Any]]:
    """Filter rows matching display_tab_id."""
    return [r for r in rows if r.get("display_tab_id") == tab_id]


def filter_expenses_by_search(
    expenses: List[Dict[str, Any]],
    query: str = "",
    kind: str = "",
) -> List[Dict[str, Any]]:
    """Filter expense rows matching query text and evidence kind."""
    out = []
    q = query.strip()
    k = kind.strip()
    for r in expenses:
        if k and r.get("evidence_type") != k:
            continue
        if q:
            haystack = " ".join([
                str(r.get("item") or ""),
                str(r.get("description") or ""),
                str(r.get("source_merchant") or ""),
                str(r.get("reservation_no") or ""),
                str(r.get("operator_note") or ""),
            ])
            if q not in haystack:
                continue
        out.append(r)
    return out


def export_trip_counts(
    trips: List[Dict[str, Any]],
    list_tab_rows_fn: Callable[[Optional[str]], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Calculate income/expense row counts for active/archived trips and unclassified."""
    lines = []
    for t in trips:
        rows = list_tab_rows_fn(t["tab_id"])
        inc = sum(1 for r in rows if r.get("row_kind") == "income")
        exp = sum(1 for r in rows if r.get("row_kind") == "expense")
        lines.append({
            "tab_id": t["tab_id"],
            "display_key": t.get("display_key", ""),
            "archived": bool(t.get("archived")),
            "income_count": inc,
            "expense_count": exp,
        })
    unc = list_tab_rows_fn(None)
    unc_inc = sum(1 for r in unc if r.get("row_kind") == "income")
    unc_exp = sum(1 for r in unc if r.get("row_kind") != "income")
    lines.append({
        "tab_id": None,
        "display_key": "분류대기",
        "archived": False,
        "income_count": unc_inc,
        "expense_count": unc_exp,
    })
    return lines


def export_review_conflict_counts(
    trips: List[Dict[str, Any]],
    list_tab_rows_fn: Callable[[Optional[str]], List[Dict[str, Any]]],
    row_needs_review_fn: Callable[[Dict[str, Any]], bool],
    row_has_conflict_fn: Callable[[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    """Calculate review-needed and conflict counts across all trips and unclassified."""
    review_total = 0
    conflict_total = 0
    per_tab = []
    for t in trips:
        trows = list_tab_rows_fn(t["tab_id"])
        n_review = sum(1 for r in trows if row_needs_review_fn(r))
        n_conflict = sum(1 for r in trows if row_has_conflict_fn(r))
        review_total += n_review
        conflict_total += n_conflict
        if n_review or n_conflict:
            per_tab.append({
                "tab_id": t["tab_id"],
                "display_key": t.get("display_key", ""),
                "review_count": n_review,
                "conflict_count": n_conflict,
            })
    unc = list_tab_rows_fn(None)
    n_unc_review = sum(1 for r in unc if row_needs_review_fn(r))
    n_unc_conflict = sum(1 for r in unc if row_has_conflict_fn(r))
    return {
        "review_total": review_total + n_unc_review,
        "conflict_total": conflict_total + n_unc_conflict,
        "per_tab": per_tab,
    }
