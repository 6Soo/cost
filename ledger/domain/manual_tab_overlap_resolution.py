"""Resolve the Osaka/Aomori schedule overlap from the manual-ledger evidence.

The 2026 Osaka field-trip tab overlaps the Aomori trip for a few calendar
days.  It is not safe to make the whole overlap Osaka: the Osaka tab contains
only the expense rows that were actually recorded for that reconnaissance
trip.  This module therefore makes the exception explicit and content-bound:

* an Agoda lodging row is assigned to Osaka only when one unique Osaka
  manual-ledger lodging row matches its payment date, KRW amount, and
  checkout-exclusive service period; and
* every other Agoda row in the exact Osaka/Aomori overlap is assigned to
  Aomori.

The workbook is bound by its SHA-256 and the eligible manual-row digests.  A
changed workbook therefore cannot silently change the exception's meaning.
The module never writes to the workbook or the database.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ledger.domain.direct_trip_schedule_authority import canonical_json, file_sha256
from ledger.domain.manual_ledger_booking_link import ManualBookingRow, load_manual_expense_rows


RULE_ID = "manual-ledger-osaka-reconnaissance-overlap-v1"
SCHEMA_VERSION = "manual-ledger-overlap-resolution-v1"
OSAKA_TARGET = "0420_오사카"
AOMORI_TARGET = "0417_아오모리"
OVERLAP_TARGETS = (AOMORI_TARGET, OSAKA_TARGET)
_PERIOD_RE = re.compile(r"^(\d{2})(\d{2})_(\d{2})(\d{2})$")


@dataclass(frozen=True)
class OverlapDecision:
    selected_target: str
    reason: str
    manual_evidence_digest: str | None

    def as_dict(self, *, resolution_document_sha256: str) -> dict[str, object]:
        return {
            "rule_id": RULE_ID,
            "resolution_document_sha256": resolution_document_sha256,
            "overlap_targets": list(OVERLAP_TARGETS),
            "selected_target": self.selected_target,
            "reason": self.reason,
            "manual_evidence_digest": self.manual_evidence_digest,
        }


def _text(value: object) -> str:
    return str(value or "").strip()


def _is_agoda_lodging(row: ManualBookingRow) -> bool:
    merchant = _text(row.merchant).casefold()
    evidence = _text(row.evidence).casefold()
    content = _text(row.content)
    return content in {"숙박", "숙박비"} and (
        "agoda" in merchant or "아고다" in merchant or "아고다" in evidence
    )


def manual_row_digest(row: ManualBookingRow) -> str:
    """Hash one row without publishing its booking number or free text."""

    payload = {
        "target": row.target,
        "occurred_on": row.occurred_on.isoformat() if row.occurred_on else None,
        "merchant": row.merchant,
        "content": row.content,
        "period": row.period,
        "booking_number": row.booking_number,
        "evidence": row.evidence,
        "amount_krw": row.amount_krw,
        "sheet_name": row.sheet_name,
        "source_row": row.source_row,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_resolution_document(workbook_path: Path) -> dict[str, object]:
    """Build a redacted, content-bound exception document from the workbook."""

    workbook_sha256 = file_sha256(workbook_path)
    rows = [
        row
        for row in load_manual_expense_rows(workbook_path)
        if row.target == OSAKA_TARGET and _is_agoda_lodging(row)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "rule_id": RULE_ID,
        "source_workbook_sha256": workbook_sha256,
        "manual_tab": OSAKA_TARGET,
        "overlap_targets": list(OVERLAP_TARGETS),
        "preferred_target": OSAKA_TARGET,
        "fallback_target": AOMORI_TARGET,
        "eligible_manual_row_count": len(rows),
        "eligible_manual_row_digests": sorted(manual_row_digest(row) for row in rows),
    }


def resolution_document_sha256(document: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def load_verified_manual_rows(
    workbook_path: Path, document: Mapping[str, object]
) -> tuple[ManualBookingRow, ...]:
    """Verify the workbook and return exactly the rows bound by the document."""

    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("manual_overlap_resolution_schema_invalid")
    if document.get("rule_id") != RULE_ID:
        raise ValueError("manual_overlap_resolution_rule_invalid")
    if tuple(document.get("overlap_targets", ())) != OVERLAP_TARGETS:
        raise ValueError("manual_overlap_resolution_targets_invalid")
    if document.get("preferred_target") != OSAKA_TARGET or document.get("fallback_target") != AOMORI_TARGET:
        raise ValueError("manual_overlap_resolution_defaults_invalid")
    if file_sha256(workbook_path) != str(document.get("source_workbook_sha256")):
        raise ValueError("manual_overlap_workbook_sha256_mismatch")

    expected = sorted(str(value) for value in document.get("eligible_manual_row_digests", ()))
    actual_rows = [
        row
        for row in load_manual_expense_rows(workbook_path)
        if row.target == OSAKA_TARGET and _is_agoda_lodging(row)
    ]
    actual = sorted(manual_row_digest(row) for row in actual_rows)
    if actual != expected or len(actual_rows) != int(document.get("eligible_manual_row_count", -1)):
        raise ValueError("manual_overlap_evidence_digest_mismatch")
    return tuple(actual_rows)


def _period_bounds(period: str, year: int) -> tuple[str, str] | None:
    match = _PERIOD_RE.fullmatch(_text(period))
    if match is None:
        return None
    start_month, start_day, end_month, end_day = map(int, match.groups())
    try:
        starts = date(year, start_month, start_day)
        end_year = year if (end_month, end_day) >= (start_month, start_day) else year + 1
        ends_exclusive = date(end_year, end_month, end_day)
    except ValueError:
        return None
    if ends_exclusive <= starts:
        return None
    return starts.isoformat(), ends_exclusive.isoformat()


def resolve_overlap_target(
    *,
    candidate_targets: Sequence[str],
    occurred_on: str,
    amount_krw: int,
    merchant: str,
    service_start_on: str,
    service_end_on: str,
    manual_rows: Iterable[ManualBookingRow],
    resolution_sha256: str,
) -> OverlapDecision | None:
    """Select Osaka only for one exact manual Agoda lodging match."""

    if tuple(sorted(candidate_targets)) != tuple(sorted(OVERLAP_TARGETS)):
        return None
    if "agoda" not in _text(merchant).casefold() and "아고다" not in _text(merchant).casefold():
        return OverlapDecision(AOMORI_TARGET, "overlap_default_non_agoda_source", None)

    try:
        event_year = date.fromisoformat(service_start_on).year
        date.fromisoformat(occurred_on)
    except ValueError:
        return OverlapDecision(AOMORI_TARGET, "overlap_default_invalid_date", None)

    matches: list[ManualBookingRow] = []
    for row in manual_rows:
        if row.amount_krw != int(amount_krw) or row.occurred_on is None:
            continue
        if row.occurred_on.isoformat() != occurred_on:
            continue
        if _period_bounds(row.period, event_year) != (service_start_on, service_end_on):
            continue
        matches.append(row)

    if len(matches) == 1:
        return OverlapDecision(
            OSAKA_TARGET,
            "unique_google_manual_agoda_lodging_row",
            manual_row_digest(matches[0]),
        )
    return OverlapDecision(AOMORI_TARGET, "overlap_default_no_unique_manual_row", None)

