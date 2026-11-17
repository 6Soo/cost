"""Read stored use periods for the Plush ledger without rerunning OTA inference."""
from __future__ import annotations

import sqlite3
from typing import Any


def annotate(rows: list[dict[str, Any]], board: Any) -> list[dict[str, Any]]:
    """Apply row/manual/core precedence and reject core records for stale sources.

    The core read is one bounded batch.  Its source hash and revision are
    checked against the current board transactions in one read before any
    saved period is used.  This is display-only: a stale record stays blank,
    and the React request never runs OTA inference.
    """
    from app import core_writer
    from . import ledger_stay_evidence

    stored = core_writer.load_stored_period_records()
    manual = ledger_stay_evidence.manual_period_rows(board)

    # Only source identities that can affect a blank, non-manual card row need
    # to be read. Explicit row values and manual blanks retain precedence.
    candidates = {
        transaction_id
        for row in rows
        if not str(row.get("service_period") or "").strip()
        and str(row.get("row_id") or "") not in manual
        if (transaction_id := _transaction_id(row))
        and stored is not None and transaction_id in stored
    }
    current = _current_source_identities(board, candidates) if candidates else {}

    result = []
    for row in rows:
        projected = dict(row)
        transaction_id = _transaction_id(row)
        stored_for_row = _stored_for(row, stored)
        row_id = str(row.get("row_id") or "")
        manual_blank = row_id in manual and not str(row.get("service_period") or "").strip()
        current_identity = current.get(transaction_id) if current is not None else None
        stale = bool(
            stored_for_row
            and not str(row.get("service_period") or "").strip()
            and not manual_blank
            and not _identity_matches(stored_for_row, current_identity)
        )

        # Keep the shared precedence rules. Removing a stale record here makes
        # read_period return an empty result via the existing no-recompute path.
        row_stored = {} if stale else stored
        value, source = ledger_stay_evidence.read_period(
            row, row_stored, manual, lambda: "")
        projected["_plush_period"] = value
        if manual_blank:
            projected["_plush_period_status"] = "unknown"
            projected["_plush_period_manual_blank"] = True
        elif stale:
            projected["_plush_period_status"] = "stale"
        elif source == "decision_inferred":
            projected["_plush_period_status"] = "inferred"
            if stored_for_row and stored_for_row.get("basis"):
                projected["_plush_period_basis"] = str(stored_for_row["basis"])
        elif source == "decision":
            if stored_for_row and stored_for_row.get("kind") in {"verified", "unknown"}:
                projected["_plush_period_status"] = stored_for_row["kind"]
        result.append(projected)
    return result


def _transaction_id(row: dict[str, Any]) -> str:
    row_id = str(row.get("row_id") or "")
    if not row_id.startswith("card-"):
        return ""
    transaction_id = str(row.get("source_event_id") or row_id[5:])
    return transaction_id if row_id == "card-" + transaction_id else ""


def _stored_for(row: dict[str, Any], stored: dict | None) -> dict | None:
    transaction_id = _transaction_id(row)
    if not transaction_id or stored is None:
        return None
    value = stored.get(transaction_id)
    return value if isinstance(value, dict) else None


def _current_source_identities(board: Any, transaction_ids: set[str]) -> dict[str, dict[str, Any]] | None:
    """Read current source_hash/revision values in one locked SQLite query.

    ``None`` means the current identity could not be read; callers then fail
    closed and mark saved records stale. An absent transaction simply has no
    matching identity.
    """
    if (not transaction_ids or not hasattr(board, "conn")
            or not hasattr(board, "_lock")):
        return None
    ids = sorted(transaction_ids)
    placeholders = ",".join("?" for _ in ids)
    try:
        with board._lock:
            found = board.conn.execute(
                "SELECT transaction_id,source_hash,revision FROM transactions "
                f"WHERE transaction_id IN ({placeholders})", ids).fetchall()
    except (sqlite3.Error, AttributeError, TypeError):
        return None
    return {
        str(transaction_id): {"source_hash": source_hash, "revision": revision}
        for transaction_id, source_hash, revision in found
    }


def _identity_matches(record: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if not current:
        return False
    source_hash = record.get("source_hash")
    current_hash = current.get("source_hash")
    revision = record.get("revision")
    current_revision = current.get("revision")
    if not source_hash or not current_hash or str(source_hash) != str(current_hash):
        return False
    try:
        return int(revision) == int(current_revision)
    except (TypeError, ValueError, OverflowError):
        return False
