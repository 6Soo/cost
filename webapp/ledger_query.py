"""Common server-side ledger read query (SPEC §11.2.1 장부 조회 통합).

Single source of truth for the display row set, kind/search selection, screen
totals and per-row period source / Google reconciliation status.  Both the
legacy HTML board (``ledger_design``) and the Plush JSON API (``plush_api``)
consume these helpers so the same snapshot, permission, tab and filter yield
identical rows and totals regardless of entry path.

This module is read-only.  It never writes ledger rows, decisions, refund
links or the Google final ledger; permission, closure, retention, manual
correction and concurrent-edit checks stay with the existing server boundaries.
"""
from __future__ import annotations

from typing import Any

# The legacy HTML board uses kind=in/ex; the Plush API uses income/expense.
# SPEC §11.2.1 적용 순서 2: both spellings are the same filter.
KIND_ALIASES = {"in": "income", "ex": "expense"}
VALID_KINDS = {"", "income", "expense"}

# Stored-read status -> the source label clients already render.
_ANNOTATED_PERIOD_SOURCES = {
    "verified": "decision",
    "unknown": "decision",
    "inferred": "decision_inferred",
}


def normalize_kind(kind: Any) -> str:
    value = str(kind or "").strip()
    return KIND_ALIASES.get(value, value)


def kind_bucket(row: dict[str, Any]) -> str:
    return "income" if row.get("row_kind") == "income" else "expense"


def display_amount(row: dict[str, Any]) -> int:
    """Signed KRW display amount; an unreadable amount is never silently zeroed."""
    value = row.get("display_amount_krw", row.get("amount_krw", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def project_rows(store: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the store's authoritative display correction projection (R05)."""
    if store is not None and hasattr(store, "projected"):
        return [store.projected(row) for row in rows]
    return list(rows)


def recorded_rows(store: Any, tab_id: str | None) -> list[dict[str, Any]]:
    """Projected recorded rows for one tab (expenses, income, allocations).

    ``list_tab_rows`` is the store's per-tab read; it already replaces split
    sources with their active allocations and nonzero remainder.
    """
    if store is None or not hasattr(store, "list_tab_rows"):
        return []
    return project_rows(store, list(store.list_tab_rows(tab_id)))


def refund_excluded_event_ids(store: Any, owner: bool) -> set:
    """RFND-022 / ITEM-011: completed full-refund groups belong to the refund tab.

    Their member transactions are not exposed or summed again in general
    expenses.  Partial refunds (net nonzero) stay in the trip (RFND-021).
    Only the owner sees the refund-tab attribution; viewers keep the existing
    expense projection.
    """
    if not owner or store is None:
        return set()
    try:
        from . import refund_tab

        return set(refund_tab.member_ids(store))
    except Exception:
        return set()


def apply_refund_exclusion(rows: list[dict[str, Any]], excluded_ids: set) -> list[dict[str, Any]]:
    if not excluded_ids:
        return list(rows)
    return [row for row in rows
            if kind_bucket(row) == "income"
            or row.get("source_event_id") not in excluded_ids]


def refund_tab_rows(store: Any, owner: bool) -> list[dict[str, Any]]:
    """Refund-tab display rows by board row ID (RFND-022 / ITEM-011).

    The completed net-zero groups excluded from general expenses are exactly
    the rows this tab serves, with their original signs preserved.  Owner-only,
    matching the refund attribution scope; the legacy group view keeps its own
    render.  Reads the same expense projection the refund attribution uses.
    """
    members = refund_excluded_event_ids(store, owner)
    if not members:
        return []
    from . import ledger_board as board

    rows = [row for row in board._expense_rows()
            if row.get("source_event_id") in members]
    return project_rows(store, rows)


def google_income(store: Any, access: Any, session: Any, owner: bool,
                  tab_id: str | None) -> dict[str, Any]:
    """Google income read projection with the existing canonical-copy/grant rules."""
    from . import plush_income

    if tab_id in (None, "", "unclassified", "refunds"):
        return dict(available=False, verified=False, rows=[], total=None,
                    reason="NOT_CONNECTED")
    visible = set() if owner else set(access.visible_tabs(session.user_id))
    return plush_income.load(tab_id, owner=owner, session=session, visible_tabs=visible)


def merge_income(rows: list[dict[str, Any]], income: dict[str, Any]) -> list[dict[str, Any]]:
    ids = {row.get("row_id") for row in rows}
    return [*rows, *(row for row in income.get("rows", []) if row.get("row_id") not in ids)]


def unified_rows(store: Any, access: Any, session: Any, owner: bool,
                 tab_id: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The display row set for a tab: recorded rows (refund-excluded) + Google income."""
    rows = recorded_rows(store, tab_id)
    rows = apply_refund_exclusion(rows, refund_excluded_event_ids(store, owner))
    income = google_income(store, access, session, owner, tab_id)
    return merge_income(rows, income), income


def search_blob(row: dict[str, Any], *, owner: bool = False) -> str:
    """Unified search text: the projected display fields plus the recorded fields
    the legacy HTML board searches.  ``operator_note`` is owner-only so a viewer
    cannot probe internal notes (SPEC §13 보호 경계).
    """
    from . import plush_projection as projection

    shown = projection.ledger_row(row)
    parts = [shown.get(key) or "" for key in (
        "date", "merchant", "description", "category", "payment", "period", "evidence_summary")]
    parts.extend(row.get(key) or "" for key in (
        "item", "reservation_no", "source_merchant", "customer_name"))
    if owner:
        parts.append(row.get("operator_note") or "")
    return " ".join(str(part) for part in parts).casefold()


def select_rows(rows: list[dict[str, Any]], *, kind: str = "", q: str = "",
                owner: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (kind_rows, searched).

    ``kind_rows`` applies permission/tab/kind only — the overall set counted and
    summed BEFORE search (SPEC §11.2.1 조회 계약 2).  ``searched`` additionally
    applies the search text and spans every page.
    """
    normalized = normalize_kind(kind)
    if normalized not in VALID_KINDS:
        raise ValueError("INVALID_KIND")
    if normalized:
        kind_rows = [row for row in rows if kind_bucket(row) == normalized]
    else:
        kind_rows = list(rows)
    text = str(q or "").strip().casefold()
    if text:
        searched = [row for row in kind_rows if text in search_blob(row, owner=owner)]
    else:
        searched = list(kind_rows)
    return kind_rows, searched


def linked_bank_ids(store: Any) -> set:
    """Bank income attached as evidence to a direct income is not summed twice (R06)."""
    if store is None or not hasattr(store, "linked_bank_row_ids"):
        return set()
    try:
        return set(store.linked_bank_row_ids())
    except Exception:
        return set()


def totals(rows: list[dict[str, Any]], *, linked: set | None = None) -> dict[str, Any]:
    """Screen income/expense/profit and counts over one row set.

    Linked bank evidence rows are excluded from income so the figure matches the
    store's ``tab_totals``.  Google income rows carry their own ``amount_missing``
    state; an unconfirmed amount contributes nothing here and is surfaced through
    ``income_source.verified`` rather than as a confirmed zero.

    GGL-003: internal COST income and Google income are never summed.  The
    income figure is COST alone and the Google block is reported separately in
    ``google_income``/``google_income_count`` so a caller can show both sources
    without adding them.
    """
    linked = linked or set()
    income = google_income = 0
    expense = 0
    income_count = google_income_count = 0
    expense_count = 0
    for row in rows:
        if kind_bucket(row) == "income":
            if row.get("row_id") in linked:
                continue
            if row.get("google_income"):
                google_income += display_amount(row)
                google_income_count += 1
                continue
            income += display_amount(row)
            income_count += 1
        else:
            expense += display_amount(row)
            expense_count += 1
    return {"income": income, "expense": expense, "profit": income - expense,
            "google_income": google_income, "income_count": income_count,
            "google_income_count": google_income_count, "expense_count": expense_count}


def display_totals(rows: list[dict[str, Any]], *, google_verified: bool = False,
                   linked: set | None = None) -> dict[str, Any]:
    """Signed 조회 합계 over one row set, split by source (GGL-003·GGL-014·R06).

    Every row in the set is reported once and the set is the same on both entry
    paths (SPEC §11.2.1 계약 1·2).  Numeric figures are strings — the existing
    money contract — so a large amount keeps its digits instead of passing
    through a JavaScript number (2^53).  COST and Google income are separate
    entries and are never added together: ``total`` is the COST figure (income
    plus expenses), exactly what the legacy board sums.

    A Google amount that cannot be read stays unknown, never a confirmed zero
    (SPEC §11.2.1 계약 4 / GGL-014). Every Google figure is therefore
    ``str | None``: ``google_income`` is ``None`` when the set holds a Google
    row whose amount is unknown or no Google amount is present, and
    ``google_incomplete`` says the figure is a partial sum (some rows counted,
    at least one unknown). ``google_income_count`` is the row count, and
    ``google_unknown_count`` the number of rows whose amount could not be read,
    so a caller can state the incompleteness instead of showing a number.
    ``google_verified`` from the caller marks the source block; it is reported
    back as ``google_verified`` and never turns a missing amount into zero.

    R06: ``linked`` names the bank rows attached as evidence to a direct income.
    They are the same money recorded twice, so they contribute nothing here —
    otherwise the figure would disagree with ``store.tab_totals``, which is the
    baseline the legacy KPI, React and the viewer rail must all match
    (SPEC §11.2.1 계약 1·2). Their count is kept out of ``income_count`` too.
    """
    linked = linked or set()
    income = google_income = expense = 0
    income_count = google_income_count = google_unknown_count = 0
    for row in rows:
        if kind_bucket(row) == "income":
            if row.get("google_income"):
                google_income_count += 1
                if row.get("amount_missing"):
                    google_unknown_count += 1
                else:
                    google_income += display_amount(row)
            elif row.get("row_id") in linked:
                # R06: the linked bank evidence row is not a second income.
                continue
            else:
                income += display_amount(row)
                income_count += 1
        else:
            expense += display_amount(row)
    known_google_rows = google_income_count - google_unknown_count
    google_figure: str | None
    if known_google_rows <= 0:
        # No Google amount was present at all, or every present row was unreadable.
        google_figure = None if google_income_count else "0"
    else:
        google_figure = str(google_income)
    return {
        "income": str(income), "income_count": str(income_count),
        "expense": str(expense), "total": str(income + expense),
        "google_income": google_figure,
        "google_income_count": str(google_income_count),
        "google_unknown_count": str(google_unknown_count),
        "google_incomplete": str(bool(google_unknown_count and google_figure is not None)),
        "google_verified": str(bool(google_verified)),
    }


def signed_sum(rows: list[dict[str, Any]]) -> int:
    return sum(display_amount(row) for row in rows)


def confirmed_income(rows: list[dict[str, Any]], *, linked: set | None = None,
                     google_verified: bool = False,
                     google_total: int | None = None,
                     prefiltered: bool = False,
                     amount: Any = None) -> tuple[int, bool]:
    """Tab-wide confirmed income and whether it is known at all (계약 2·4).

    Recorded COST income wins (GGL-003: internal COST income and Google income
    are never summed — Google is user-entered and COST only reads it).  Google
    income substitutes only when no usable COST income row exists, and only
    when its source block is verified; an unverified or unconnected ledger
    never becomes a confirmed zero (GGL-014 / GGL-013).  Returns
    ``(income, known)`` — ``known`` is False when neither recorded income rows
    nor a verified Google block exist, and the caller must show the unknown
    state instead of an amount.  ``google_total`` defaults to the Google row
    sum so the figure comes from the same row set as the list.

    ``prefiltered`` says the caller already selected the tab's income rows (the
    legacy KPI reads ``board._income_rows()``), so no row-kind test is applied;
    the merged ledger row set keeps that test via the default.  ``amount`` lets
    that caller keep its own display-amount projection; it defaults to the row's
    stored display/amount value.
    """
    linked = linked or set()
    shown = amount or display_amount
    recorded = [row for row in rows
                if not row.get("google_income") and row.get("row_id") not in linked
                and (prefiltered or kind_bucket(row) == "income")]
    if recorded:
        return sum(int(shown(row) or 0) for row in recorded), True
    if not google_verified:
        return 0, False
    if google_total is None:
        google_total = sum(display_amount(row) for row in rows
                           if row.get("google_income"))
    return int(google_total or 0), True


def period_for_row(row: dict[str, Any], store: Any) -> tuple[str, str]:
    """(period, period_source) with the existing stored/manual/evidence priority.

    Mirrors ``ledger_design._read_period(verified=False)``: a person's value wins,
    then the stored Rust decision (inferred only on screen), then the evidence
    index.  source is 'row'|'manual'|'decision'|'decision_inferred'|'computed'.
    Degrades to the stored service_period when the evidence path is unavailable.

    When the row already carries :func:`plush_periods.annotate` output, that
    stored read is authoritative: it rejects a record whose source identity
    changed, so a stale or explicitly blank period is reported as unknown here
    too instead of being re-inferred for the screen.
    """
    if row.get("google_income"):
        return "", ""
    if "_plush_period" in row:
        value = str(row.get("_plush_period") or "")
        if row.get("_plush_period_manual_blank") is True:
            return value, "manual"
        if row.get("_plush_period_status") == "stale":
            return "", ""
        status = row.get("_plush_period_status")
        if status in _ANNOTATED_PERIOD_SOURCES:
            return value, _ANNOTATED_PERIOD_SOURCES[status]
        if value:
            return value, "row"
        return "", ""
    stored_period = str(row.get("service_period") or "").strip()
    try:
        from . import ledger_stay_evidence, read_scope
        from app import core_writer

        stored = read_scope.remember("stored_periods", core_writer.load_stored_periods)
        manual = (read_scope.remember("manual_period_rows",
                                      lambda: ledger_stay_evidence.manual_period_rows(store))
                  if stored is not None else set())
        index = read_scope.remember("ledger_stay_evidence",
                                    lambda: ledger_stay_evidence.stay_index(store))
        return ledger_stay_evidence.read_period(
            row, stored, manual,
            lambda: ledger_stay_evidence.period_for(row, index), export=False)
    except Exception:
        return stored_period, ("row" if stored_period else "")


_GOOGLE_MATCH_LABELS = {
    "MATCHED_MANUAL": "장부에 있음 · 복사 제외",
    "MATCHED_EXISTING": "장부에 있음 · 복사 제외",
    "NEW_EXPENSE": "복사 가능",
    "REVIEW_CONFLICT": "중복 확인 필요 · 복사 제외",
}


def google_match_annotations(store: Any, tab_id: str | None,
                             rows: list[dict[str, Any]], *, owner: bool) -> dict[str, dict]:
    """Per-row Google reconciliation status for owner-only display (read-only).

    Returns {row_id: {"status", "label"}} from the existing trip expense
    reconciliation preview.  Empty when not owner, not a trip tab, or the Google
    source is unavailable — an unavailable source is never shown as a match.
    """
    if (not owner or not tab_id or tab_id in ("unclassified", "refunds")
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
        annotations: dict[str, dict] = {}
        for row in rows:
            key = str(row.get("transaction_id") or row.get("source_event_id")
                      or row.get("row_id") or "")
            item = by_id.get(key)
            status = str((item or {}).get("status") or "")
            if status in _GOOGLE_MATCH_LABELS:
                annotations[str(row.get("row_id") or "")] = {
                    "status": status, "label": _GOOGLE_MATCH_LABELS[status]}
        return annotations
    except Exception:
        return {}
