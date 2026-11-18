"""Row-level use-period read shared by the React ledger and the legacy board.

SPEC §11.2.1 계약 4 asks a list or row detail to show the same 이용기간 the other
entry path shows, with the stored/manual precedence the legacy screen already
uses and a clear distinction between a confirmed value, an inference and an
unknown one.

This module owns only that read.  It deliberately does not touch amounts, totals,
row sets or Google reconciliation; those live with their own code.
"""
from __future__ import annotations

from typing import Any


# Stored-read status -> the source label clients already render.
_ANNOTATED_PERIOD_SOURCES = {
    "verified": "decision",
    "unknown": "decision",
    "inferred": "decision_inferred",
    "computed": "computed",
}


def annotate(rows: list[dict[str, Any]], board: Any) -> list[dict[str, Any]]:
    """Apply the stored/manual/evidence precedence to the rows on one screen.

    The precedence and the staleness rule both live in :mod:`plush_periods`, the
    module the legacy screen and this one already share; this is the single entry
    the React ledger calls so it cannot drift from that rule.
    """
    from . import plush_periods

    return plush_periods.annotate(rows, board)


def period_for_row(row: dict[str, Any], store: Any) -> tuple[str, str]:
    """(period, period_source) with the existing stored/manual/evidence priority.

    Mirrors ``ledger_design._read_period(verified=False)``: a person's value wins,
    then the stored Rust decision (inferred only on screen), then the evidence
    index.  source is 'row'|'manual'|'decision'|'decision_inferred'|'computed'.
    Degrades to the stored service_period when the evidence path is unavailable.

    When the row already carries :func:`plush_periods.annotate` output, that
    stored read is authoritative: it rejects a record whose source identity
    changed, so a stale saved value is never reported as the row's period.  The
    annotate step then re-derives a ``computed`` period from the evidence index
    the way the legacy screen does, and that value is reported here with its
    ``computed`` source rather than being dropped.
    """
    if row.get("google_income"):
        return "", ""
    if "_plush_period" in row:
        value = str(row.get("_plush_period") or "")
        if row.get("_plush_period_manual_blank") is True:
            return value, "manual"
        status = row.get("_plush_period_status")
        if status == "stale":
            # The stale record's own value was rejected before it reached the
            # row, so this value (if any) came from the compute fallback.
            return (value, "computed") if value else ("", "")
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
