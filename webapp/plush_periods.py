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

    The precedence itself is ``ledger_stay_evidence.read_period`` — the rule the
    legacy board already uses.  A row with no stored decision is therefore
    computed from the evidence index exactly as the legacy screen computes it
    (source ``computed``), instead of silently reading as unknown; a stored
    decision is still only read and never recomputed, and a record whose source
    changed is never shown at all.
    """
    from app import core_writer
    from . import ledger_stay_evidence
    from . import read_scope

    stored = _stored_records(core_writer)
    manual = ledger_stay_evidence.manual_period_rows(board)

    def compute(row: dict[str, Any]) -> str:
        # Built on the first row that actually needs it, the same memoised read
        # the legacy board makes, so a list and a row detail in one request share
        # it and a request with no computed row never builds it at all.
        #
        # The evidence index is the same read the legacy screen performs, but it
        # must never turn a read problem into a failed request: when the bound
        # object is not a readable store (a test double or an unbound board) the
        # index is treated as empty for this call, which is exactly what an empty
        # index already means — the period stays unknown, not invented.
        index = read_scope.remember("ledger_stay_evidence", _evidence_index(board))
        return ledger_stay_evidence.period_for(row, index)

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
        stale = bool(
            stored_for_row
            and not str(row.get("service_period") or "").strip()
            and not manual_blank
            and _record_is_stale(stored_for_row, current, transaction_id)
        )

        # Keep the shared precedence rules. Removing a stale record here keeps
        # the saved value out of the answer (no-recompute for a decision), while
        # the compute fallback stays available so the screen states a computed
        # period exactly as the legacy screen does instead of a blank.
        row_stored = {} if stale else stored
        value, source = ledger_stay_evidence.read_period(
            row, row_stored, manual, lambda: compute(row))
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
        elif source == "computed" and value:
            # The period came from the evidence index, not from a saved decision,
            # so the row says so instead of presenting it as a stored value.
            projected["_plush_period_status"] = "computed"
        result.append(projected)
    return result


def _transaction_id(row: dict[str, Any]) -> str:
    row_id = str(row.get("row_id") or "")
    if not row_id.startswith("card-"):
        return ""
    transaction_id = str(row.get("source_event_id") or row_id[5:])
    return transaction_id if row_id == "card-" + transaction_id else ""


def _stored_records(core_writer) -> dict | None:
    """Saved periods with their source identity, falling back to a plain read.

    A core file written before the identity columns existed (or one whose
    identity read fails) still describes these rows. The plain period read is
    used there, exactly as the legacy screen reads it, so an old core file does
    not turn a correct saved period into "unknown". The ordinary
    ``stored_periods_enabled()`` gate is preserved: while Python is the writer
    there is no stored decision to read and ``None`` keeps the computed path.
    """
    if not core_writer.stored_periods_enabled():
        return None
    records = core_writer.load_stored_period_records()
    if records:
        return records
    return core_writer.load_stored_periods()


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


def _evidence_index(board: Any):
    """A thunk for the evidence index, degrading to empty on an unreadable store.

    ``ledger_stay_evidence.stay_index`` is the legacy screen's own read and it
    needs a bound store.  A projection over an unbound or test-double board must
    not fail here: an empty index means the period is unknown, which is the same
    answer a store with no evidence gives, and it never invents a period.
    """
    from . import ledger_stay_evidence

    def build():
        try:
            return ledger_stay_evidence.stay_index(board)
        except (AttributeError, TypeError, sqlite3.Error):
            return {}
    return build


def _record_is_stale(record: dict[str, Any], identities: dict | None,
                     transaction_id: str) -> bool:
    """Whether a saved record's source really changed — not merely unverifiable.

    Three states must stay apart, because the legacy screen shows a period in
    all three and the React path must agree:

    * the identity read itself failed (``identities is None``) — nothing can be
      checked, so it fails closed: the saved value is not displayed;
    * the board cannot name this transaction (no entry) — the record still
      describes the row, exactly as a core file written before the board row
      existed does; it is shown;
    * a readable, different identity — the source changed; it is hidden.

    A record without a recorded identity (an old core file) has nothing to
    compare and is shown.
    """
    if not record.get("source_hash") or record.get("revision") is None:
        return False
    if identities is None:
        return True
    current = identities.get(transaction_id)
    if not current:
        return False
    return not _identity_matches(record, current)


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
