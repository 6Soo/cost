"""Owner-only Google reconciliation status for a ledger row (SPEC §11.2.1 계약 4).

Both entry paths must let the reader check the Google 대사 status of a row, so
this owns the annotation once instead of each caller computing it. It only
reads the already-selected Google snapshot; it never writes the final ledger
and never copies a candidate.

The legacy board's own helper (`ledger_design._google_match_annotations`) is
the rule this was taken from, including the label set and the "abnormal
candidate is not a match" rule.
"""
from __future__ import annotations

from typing import Any

# The statuses a row may be shown under, and the wording the screen uses.
_LABELS = {
    "MATCHED_MANUAL": "장부에 있음 · 복사 제외",
    "MATCHED_EXISTING": "장부에 있음 · 복사 제외",
    "NEW_EXPENSE": "복사 가능",
    "REVIEW_CONFLICT": "중복 확인 필요 · 복사 제외",
}


def annotations(store: Any, tab_id: str | None, rows: list[dict[str, Any]],
                *, owner: bool) -> dict[str, dict]:
    """{row_id: {"status", "label", ...}} for the rows shown to an owner.

    Returns nothing when the caller is not the owner, the tab is not a trip, or
    the Google source is unavailable: an unavailable source is never shown as a
    match. Read-only; the preview is the same call the copy button already
    makes, so no new Google read is added.
    """
    if (not owner or not tab_id
            or str(tab_id) in ("unclassified", "refunds")
            or str(tab_id).startswith("quarter:") or not rows):
        return {}
    try:
        from .sheet_expense_reconciliation import preview_for_trip

        preview = preview_for_trip(store, tab_id, cost_rows=rows,
                                   include_sheet_rows=True, allow_total_mismatch=True)
        if not preview.get("source_available"):
            return {}
        by_id = {str(item.get("transaction_id") or ""): item
                 for item in preview.get("results", [])}
        result: dict[str, dict] = {}
        for row in rows:
            key = str(row.get("transaction_id") or row.get("source_event_id")
                      or row.get("row_id") or "")
            item = by_id.get(key)
            status = str((item or {}).get("status") or "")
            if status not in _LABELS:
                continue
            result[str(row.get("row_id") or "")] = {
                "status": status,
                "label": _LABELS[status],
                "multiple": status == "REVIEW_CONFLICT",
            }
        return result
    except Exception:
        return {}
