"""Derive schedule authority from the company's manual-ledger trip tabs.

The workbook tab is a stronger internal trip registry than the legacy
``mm/dd/window`` list, but it is still parsed conservatively.  A tab becomes
authoritative only when its title contains an explicit year and an explicit
start/end range.  The tab name identifies the trip; it is never used to
invent an end date.  Rows inside the expense table are deliberately ignored.

This module is read-only with respect to the workbook.  It produces the
existing ``trip-schedule-authority-v3`` document plus a separate diagnostic
candidate report for tabs that are incomplete or contradictory.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from openpyxl import load_workbook

from ledger.domain.direct_trip_schedule_authority import (
    END_SEMANTICS,
    SCHEMA_VERSION,
    canonical_json,
    validate_document,
)


MANUAL_TAB_RULE_VERSION = "manual-ledger-tab-title-v2-exclusive-end"
MANUAL_TAB_CANDIDATE_SCHEMA_VERSION = "manual-ledger-tab-schedule-candidates-v2"
MANUAL_TAB_END_SEMANTICS = "exclusive_checkout_date"
YEAR_RE = re.compile(r"(?<![0-9])([0-9]{4})년")
DATE_RANGE_RE = re.compile(
    r"(?<![0-9])([0-9]{2})([0-9]{2})[_-]([0-9]{2})([0-9]{2})(?![0-9])"
)
DUPLICATE_SUFFIX_RE = re.compile(r"\s+\([0-9]+\)$")
TRIP_TAB_RE = re.compile(r"^(?:[0-9]{4}|[0-9]+월)_.+")
NON_TRIP_PREFIXES = ("2분기_",)


@dataclass(frozen=True)
class ManualTabObservation:
    """One physical workbook tab after schedule-only inspection."""

    canonical_tab: str
    sheet_names: tuple[str, ...]
    event_year: int | None
    starts_on: str | None
    ends_on: str | None
    region: str
    title: str | None
    source_locator: str
    source_sha256: str
    status: str
    reason: str | None

    @property
    def is_authoritative(self) -> bool:
        return self.status == "authoritative"

    def as_candidate_dict(self) -> dict[str, object]:
        return {
            "trip_code": self.canonical_tab,
            "sheet_names": list(self.sheet_names),
            "event_year": self.event_year,
            "starts_on": self.starts_on,
            "ends_on": self.ends_on,
            "source_end_semantics": MANUAL_TAB_END_SEMANTICS,
            "region": self.region,
            "title": self.title,
            "source_locator": self.source_locator,
            "source_sha256": self.source_sha256,
            "authority_status": self.status,
            "reason": self.reason,
        }

    def as_authority_record(self) -> dict[str, object]:
        if not self.is_authoritative:
            raise ValueError("manual_tab_observation_not_authoritative")
        if self.event_year is None or self.starts_on is None or self.ends_on is None:
            raise ValueError("manual_tab_authority_period_missing")
        return {
            "trip_code": self.canonical_tab,
            "event_year": self.event_year,
            "starts_on": self.starts_on,
            "ends_on": self.ends_on,
            "region": self.region,
            "authority_kind": "explicit_trip_registry",
            "source_locator": self.source_locator,
            "source_sha256": self.source_sha256,
            "authority_status": "authoritative",
            "end_semantics": END_SEMANTICS,
        }


def canonical_tab_name(sheet_name: str) -> str:
    """Collapse Excel's copy suffix without changing the base tab name."""

    return DUPLICATE_SUFFIX_RE.sub("", str(sheet_name).strip())


def is_travel_tab(sheet_name: str) -> bool:
    return bool(TRIP_TAB_RE.fullmatch(str(sheet_name).strip())) and not any(
        str(sheet_name).startswith(prefix) for prefix in NON_TRIP_PREFIXES
    )


def _value_token(value: object) -> dict[str, str]:
    if value is None:
        return {"type": "null", "value": ""}
    if hasattr(value, "isoformat"):
        try:
            return {"type": type(value).__name__, "value": value.isoformat()}
        except (AttributeError, TypeError):
            pass
    return {"type": type(value).__name__, "value": str(value)}


def _sheet_cells(sheet) -> list[dict[str, object]]:
    cells: list[dict[str, object]] = []
    for row_number, row in enumerate(sheet.iter_rows(), start=1):
        for column_number, cell in enumerate(row, start=1):
            if cell.value is None:
                continue
            cells.append(
                {
                    "row": row_number,
                    "column": column_number,
                    "value": _value_token(cell.value),
                }
            )
    return cells


def _top_text(sheet) -> list[str]:
    values: list[str] = []
    for row in sheet.iter_rows(min_row=1, max_row=8, values_only=True):
        for value in row:
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    return values


def _sheet_title(sheet) -> str | None:
    return next((value for value in _top_text(sheet) if "매출 확인자료" in value), None)


def _parse_title_period(title: str | None) -> tuple[int | None, str | None, str | None, str | None]:
    """Return explicit year/start/end or a stable hold reason.

    Dates are read from the stored workbook title only.  The tab's ``0404``
    prefix is intentionally not treated as a date source, and no duration is
    inferred when the title omits an end date.  The title's end value is the
    inclusive last service date (trip last day).
    """

    if not title:
        return None, None, None, "title_missing"
    year_match = YEAR_RE.search(title)
    if not year_match:
        return None, None, None, "explicit_year_missing"
    event_year = int(year_match.group(1))
    range_match = DATE_RANGE_RE.search(title)
    if not range_match:
        return event_year, None, None, "explicit_period_missing"
    start_month, start_day, end_month, end_day = map(int, range_match.groups())
    try:
        starts = date(event_year, start_month, start_day)
        end_year = event_year if (end_month, end_day) >= (start_month, start_day) else event_year + 1
        end_exclusive = date(end_year, end_month, end_day)
        if end_exclusive <= starts:
            return event_year, None, None, "explicit_period_invalid"
        ends = end_exclusive
    except ValueError:
        return event_year, None, None, "explicit_period_invalid"
    return event_year, starts.isoformat(), ends.isoformat(), None


def _source_locator(path: Path, sheet_names: Iterable[str]) -> str:
    encoded = ",".join(quote(name, safe="") for name in sorted(sheet_names))
    return f"{path.resolve().as_posix()}#sheets={encoded}"


def _group_source_sha256(
    workbook_sha256: str,
    canonical_tab: str,
    sheet_names: list[str],
    sheet_payloads: list[dict[str, object]],
) -> str:
    payload = {
        "rule_version": MANUAL_TAB_RULE_VERSION,
        "source_end_semantics": MANUAL_TAB_END_SEMANTICS,
        "workbook_sha256": workbook_sha256,
        "canonical_tab": canonical_tab,
        "sheet_names": sorted(sheet_names),
        "sheets": sorted(sheet_payloads, key=lambda value: str(value["sheet_name"])),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def inspect_manual_ledger(path: Path) -> tuple[list[ManualTabObservation], dict[str, object]]:
    """Inspect trip tabs without reading transaction rows as schedule facts."""

    if not path.is_file() or path.is_symlink():
        raise ValueError("manual_ledger_workbook_not_regular")
    workbook_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    workbook = load_workbook(path, read_only=True, data_only=False)
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    try:
        for sheet_name in workbook.sheetnames:
            if not is_travel_tab(sheet_name):
                continue
            sheet = workbook[sheet_name]
            title = _sheet_title(sheet)
            event_year, starts_on, ends_on, reason = _parse_title_period(title)
            groups[canonical_tab_name(sheet_name)].append(
                {
                    "sheet_name": sheet_name,
                    "title": title,
                    "event_year": event_year,
                    "starts_on": starts_on,
                    "ends_on": ends_on,
                    "reason": reason,
                    "cells": _sheet_cells(sheet),
                }
            )
    finally:
        workbook.close()

    observations: list[ManualTabObservation] = []
    duplicate_groups = 0
    conflict_groups = 0
    for canonical_tab, members in sorted(groups.items()):
        sheet_names = sorted(str(member["sheet_name"]) for member in members)
        if len(members) > 1:
            duplicate_groups += 1
        source_sha256 = _group_source_sha256(
            workbook_sha256,
            canonical_tab,
            sheet_names,
            [
                {"sheet_name": member["sheet_name"], "cells": member["cells"]}
                for member in members
            ],
        )
        schedule_signatures = {
            (
                member["title"],
                member["event_year"],
                member["starts_on"],
                member["ends_on"],
                member["reason"],
            )
            for member in members
        }
        first = members[0]
        reason = first["reason"]
        status = "authoritative"
        if len(schedule_signatures) > 1:
            conflict_groups += 1
            status = "candidate_only"
            reason = "duplicate_schedule_conflict"
        elif reason is not None:
            status = "candidate_only"
        region = canonical_tab.split("_", 1)[1].strip() if "_" in canonical_tab else canonical_tab
        observations.append(
            ManualTabObservation(
                canonical_tab=canonical_tab,
                sheet_names=tuple(sheet_names),
                event_year=first["event_year"],
                starts_on=first["starts_on"],
                ends_on=first["ends_on"],
                region=region,
                title=first["title"],
                source_locator=_source_locator(path, sheet_names),
                source_sha256=source_sha256,
                status=status,
                reason=reason,
            )
        )

    metadata = {
        "schema_version": MANUAL_TAB_CANDIDATE_SCHEMA_VERSION,
        "rule_version": MANUAL_TAB_RULE_VERSION,
        "source_path": path.resolve().as_posix(),
        "workbook_sha256": workbook_sha256,
        "travel_sheet_instance_count": sum(len(members) for members in groups.values()),
        "canonical_tab_count": len(observations),
        "authoritative_count": sum(item.is_authoritative for item in observations),
        "candidate_only_count": sum(not item.is_authoritative for item in observations),
        "duplicate_group_count": duplicate_groups,
        "duplicate_conflict_count": conflict_groups,
    }
    return observations, metadata


def build_manual_tab_documents(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    observations, metadata = inspect_manual_ledger(path)
    authority = {
        "schema_version": SCHEMA_VERSION,
        "records": [
            item.as_authority_record()
            for item in observations
            if item.is_authoritative
        ],
    }
    validate_document(authority)
    candidates = {
        **metadata,
        "records": [item.as_candidate_dict() for item in observations],
    }
    return authority, candidates


def write_manual_tab_documents(
    workbook_path: Path,
    authority_path: Path,
    candidate_path: Path,
) -> dict[str, object]:
    authority, candidates = build_manual_tab_documents(workbook_path)
    authority_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    authority_bytes = (json.dumps(authority, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    candidate_bytes = (json.dumps(candidates, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    authority_path.write_bytes(authority_bytes)
    candidate_path.write_bytes(candidate_bytes)
    return {
        "authority_path": authority_path.as_posix(),
        "authority_sha256": hashlib.sha256(authority_bytes).hexdigest(),
        "authority_record_count": len(authority["records"]),
        "candidate_path": candidate_path.as_posix(),
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "candidate_record_count": len(candidates["records"]),
        "metadata": {key: value for key, value in candidates.items() if key != "records"},
    }
