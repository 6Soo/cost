"""Read-only archived Google ledger expenses for the Plush ledger projection.

The helper is owner-only and never writes: it reads one consistent snapshot and
its private rows generation, resolves the owner's selected copy and hands the
archived expense rows back to the caller. Unavailable, non-archive, stale,
ambiguous or non-owner reads return ``None`` so a surface can fall back to the
native ledger instead of guessing at a figure.

The row shape is the consumer contract:

    {"rows": [{"row": int, "date": str, "date_year": int | None, "payee": str,
               "category": str, "period": str, "evidence": str,
               "amount": str | None}],
     "verified": bool}

``amount`` is ``None`` when the source itself did not carry a confirmed amount;
it is never coerced to zero. ``date`` keeps the source string exactly as read;
``date_year`` is the trip ledger year callers may pass to a date parser, and
``None`` when the trip carries none. Reservation numbers and participant names
are not part of this projection.
"""
from __future__ import annotations

from . import google_ledger_page
from app import google_authority

ARCHIVE_SOURCE = "archive"
# A copy choice never lifts these: they say the trip identity is uncertain or
# the read may be stale. Reusing owner_payload's selection basis keeps the same
# boundary.
_ID_BLOCKERS = google_ledger_page.OWNER_CHOICE_BLOCKERS
# The only selection blocker that does not hide the archived expense rows: the
# copy exists, its figures are simply not verified. A nonstandard layout is a
# labelled, normalized read (google_expense_rows), not a reason to hide rows.
_FLAG_NOT_VERIFIED = {"COPY_NOT_VERIFIED"}
_UNTRUSTED = (google_authority.SnapshotError, OSError, ValueError, KeyError, TypeError,
              AttributeError)


def _text(value) -> str:
    return "" if value is None else str(value)


def _amount(value) -> str | None:
    # A missing amount is unconfirmed, never zero; a real zero stays "0".
    if value is None or isinstance(value, bool):
        return None
    return str(value)


def load(tab_id, *, owner: bool, native_expenses: list) -> dict | None:
    """Return archived expense rows for one mapped trip, or ``None`` when unusable.

    ``owner`` must have been established by the caller's scope check; a viewer
    read is refused here as well. ``native_expenses`` carries the trip's native
    expense rows so a Google copy is never shown beside the ledger row that
    already carries the same money.
    """
    if not owner:
        return None
    if not isinstance(tab_id, str):
        return None
    tab_id = tab_id.strip()
    if not tab_id or tab_id == "unclassified":
        return None
    if native_expenses:
        return None
    try:
        path = google_ledger_page.snapshot_path()
        rows_path = google_ledger_page.rows_path()
        snapshot, rows = google_authority.load_consistent(path, rows_path)
        snapshot = google_ledger_page.snapshot_for_display(snapshot)
        mapping = google_ledger_page.load_mapping(path)
        keys = [key for key, mapped in mapping.items() if str(mapped) == tab_id]
        if len(keys) != 1:
            # No mapping, or a tab several Google trips claim: either way the
            # archived copy is ambiguous, so the read is refused.
            return None
        key = keys[0]
        payload = google_ledger_page.owner_payload(snapshot, google_ledger_page.load_choices(path))
        matches = [trip for trip in payload.get("trips", []) if trip.get("key") == key]
        if len(matches) != 1:
            return None
        trip = matches[0]
        source = trip.get("chosen_source")
        if source != ARCHIVE_SOURCE:
            return None
        if trip.get("closure") != "closed" or not trip.get("closure_current"):
            return None
        source_record = (payload.get("sources") or {}).get(source) or {}
        if source_record.get("status") != "ok" or source_record.get("stale"):
            return None
        copy_record = (trip.get("copies") or {}).get(source) or {}
        if copy_record.get("layout") not in ("rev", "nonstandard"):
            return None
        if set(trip.get("blocked_by") or ()) - _FLAG_NOT_VERIFIED:
            return None
        if set(trip.get("review") or ()) & _ID_BLOCKERS:
            return None
        detail = google_ledger_page.owner_rows(rows, key, source)
        if detail is None:
            return None
        period = trip.get("period") if isinstance(trip.get("period"), dict) else {}
        rendered = [
            {
                "row": row.get("row"),
                "date": _text(row.get("date")),
                "date_year": period.get("year"),
                "payee": _text(row.get("payee")),
                "category": _text(row.get("category")),
                "period": _text(row.get("period")),
                "evidence": _text(row.get("evidence")),
                "amount": _amount(row.get("amount")),
            }
            for row in detail.get("expense") or []
        ]
        return {"rows": rendered, "verified": bool(trip.get("verified"))}
    except _UNTRUSTED:
        return None
