"""Strict, year-aware trip schedule authority for Agoda accounting.

The active accounting path accepts only records with explicit dates and
``authority_status='authoritative'``.  The old ``trips.json`` month/day
format is retained only by the historical replay adapter below; it is not a
candidate source for current allocation or posting.

Schedule dates are inclusive last-service dates.  A lodging booking's
``service_end_on`` is checkout-exclusive, so matching uses the booking's last
night (``service_end_on - 1 day``).  No year is inferred from a month/day
template.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA_VERSION = "trip-schedule-authority-v3"
ROOT_KEYS = {"schema_version", "records"}
RECORD_KEYS = {
    "trip_code",
    "event_year",
    "starts_on",
    "ends_on",
    "region",
    "authority_kind",
    "source_locator",
    "source_sha256",
    "authority_status",
    "end_semantics",
}
AUTHORITATIVE_KINDS = {
    "official_event_schedule",
    "explicit_trip_registry",
    "user_confirmed_schedule",
}
CANDIDATE_ONLY_KINDS = {"legacy_window_candidate"}
AUTHORITY_STATUSES = {"authoritative", "candidate_only"}
END_SEMANTICS = "inclusive_last_service_date"
EXCLUSIVE_SERVICE_END_SEMANTICS = "exclusive_service_end"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_value(value: object) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _clean_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value


def _iso_date(value: object, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"trip_schedule_{field}_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"trip_schedule_{field}_invalid") from exc


@dataclass(frozen=True)
class ScheduleRecord:
    trip_code: str
    event_year: int
    starts_on: date
    ends_on: date
    region: str
    authority_kind: str
    source_locator: str
    source_sha256: str
    authority_status: str
    end_semantics: str = END_SEMANTICS

    @property
    def is_authoritative(self) -> bool:
        return self.authority_status == "authoritative"

    def as_dict(self) -> dict[str, object]:
        return {
            "trip_code": self.trip_code,
            "event_year": self.event_year,
            "starts_on": self.starts_on.isoformat(),
            "ends_on": self.ends_on.isoformat(),
            "region": self.region,
            "authority_kind": self.authority_kind,
            "source_locator": self.source_locator,
            "source_sha256": self.source_sha256,
            "authority_status": self.authority_status,
            "end_semantics": self.end_semantics,
        }


@dataclass(frozen=True)
class NormalizedServicePeriod:
    """A service period with one explicit end-date convention.

    OTA lodging facts use a checkout-exclusive ``service_end_on``.  Schedule
    authority records use an inclusive last-service date.  Keeping both forms
    here prevents callers from independently reimplementing the easy-to-miss
    ``checkout - 1 day`` rule.
    """

    service_start_on: date
    service_end_on_exclusive: date
    last_service_on: date

    @property
    def end_semantics(self) -> str:
        return "exclusive_checkout_date"


def normalize_service_period(
    service_start_on: str | date,
    service_end_on: str | date,
) -> NormalizedServicePeriod:
    """Validate and normalize an OTA/service period.

    ``service_end_on`` is exclusive for lodging and other reservation facts.
    No date is inferred from a payment date or an unstructured label.
    """

    def as_date(value: str | date, field: str) -> date:
        if isinstance(value, date):
            return value
        return _iso_date(value, field)

    start = as_date(service_start_on, "service_start_on")
    end = as_date(service_end_on, "service_end_on")
    if end <= start:
        raise ValueError("booking_service_period_invalid")
    return NormalizedServicePeriod(
        service_start_on=start,
        service_end_on_exclusive=end,
        last_service_on=end - timedelta(days=1),
    )


def validate_record(raw: object, index: int = 0) -> ScheduleRecord:
    if not isinstance(raw, dict) or set(raw) != RECORD_KEYS:
        raise ValueError(f"trip_schedule_authority_record_shape_invalid:{index}")
    if (
        not _clean_text(raw["trip_code"])
        or not _clean_text(raw["region"])
        or not _clean_text(raw["authority_kind"])
        or not _clean_text(raw["source_locator"])
        or type(raw["event_year"]) is not int
        or raw["event_year"] < 1900
        or raw["event_year"] > 2200
        or raw["authority_status"] not in AUTHORITY_STATUSES
        or raw["end_semantics"] != END_SEMANTICS
        or not isinstance(raw["source_sha256"], str)
        or SHA256_RE.fullmatch(raw["source_sha256"]) is None
    ):
        raise ValueError(f"trip_schedule_authority_record_invalid:{index}")
    if raw["authority_status"] == "authoritative":
        if raw["authority_kind"] not in AUTHORITATIVE_KINDS:
            raise ValueError(f"trip_schedule_authority_kind_invalid:{index}")
    elif raw["authority_kind"] not in CANDIDATE_ONLY_KINDS:
        raise ValueError(f"trip_schedule_candidate_kind_invalid:{index}")
    starts_on = _iso_date(raw["starts_on"], "starts_on")
    ends_on = _iso_date(raw["ends_on"], "ends_on")
    if ends_on < starts_on:
        raise ValueError(f"trip_schedule_date_order_invalid:{index}")
    if not starts_on.year <= raw["event_year"] <= ends_on.year:
        raise ValueError(f"trip_schedule_event_year_outside_period:{index}")
    return ScheduleRecord(
        trip_code=str(raw["trip_code"]),
        event_year=int(raw["event_year"]),
        starts_on=starts_on,
        ends_on=ends_on,
        region=str(raw["region"]),
        authority_kind=str(raw["authority_kind"]),
        source_locator=str(raw["source_locator"]),
        source_sha256=str(raw["source_sha256"]),
        authority_status=str(raw["authority_status"]),
        end_semantics=END_SEMANTICS,
    )


def validate_document(raw: object) -> list[ScheduleRecord]:
    if not isinstance(raw, dict) or set(raw) != ROOT_KEYS:
        raise ValueError("trip_schedule_authority_root_invalid")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise ValueError("trip_schedule_authority_schema_version_invalid")
    if not isinstance(raw["records"], list):
        raise ValueError("trip_schedule_authority_records_invalid")
    records = [validate_record(value, index) for index, value in enumerate(raw["records"])]
    trip_codes = [record.trip_code for record in records]
    if len(trip_codes) != len(set(trip_codes)):
        raise ValueError("trip_schedule_authority_duplicate_trip_code")
    return records


def load_document(path: Path) -> tuple[list[ScheduleRecord], str]:
    raw_bytes = path.read_bytes()
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("trip_schedule_authority_json_invalid") from exc
    return validate_document(raw), sha256_bytes(raw_bytes)


def legacy_window_candidates(path: Path) -> tuple[list[ScheduleRecord], str]:
    """Convert legacy windows to explicit *candidate-only* intervals.

    This conversion is intentionally not an authority upgrade.  The source
    file hash and locator are retained so the report can explain exactly why a
    row remains provisional.
    """
    raw_bytes = path.read_bytes()
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("legacy_trip_schedule_json_invalid") from exc
    if not isinstance(raw, list):
        raise ValueError("legacy_trip_schedule_root_invalid")
    source_hash = sha256_bytes(raw_bytes)
    records: list[ScheduleRecord] = []
    seen: set[str] = set()
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"legacy_trip_schedule_row_invalid:{index}")
        required = {"tab", "mm", "dd", "region", "window"}
        if set(row) != required or row["tab"] in seen:
            raise ValueError(f"legacy_trip_schedule_row_invalid:{index}")
        if (
            not _clean_text(row["tab"])
            or not _clean_text(row["region"])
            or type(row["mm"]) is not int
            or type(row["dd"]) is not int
            or type(row["window"]) is not int
            or not 1 <= row["window"] <= 60
        ):
            raise ValueError(f"legacy_trip_schedule_row_invalid:{index}")
        starts_on = _iso_date(f"2026-{row['mm']:02d}-{row['dd']:02d}", "legacy_date")
        ends_on = starts_on + timedelta(days=int(row["window"]) - 1)
        seen.add(str(row["tab"]))
        records.append(
            ScheduleRecord(
                trip_code=str(row["tab"]),
                event_year=2026,
                starts_on=starts_on,
                ends_on=ends_on,
                region=str(row["region"]),
                authority_kind="legacy_window_candidate",
                source_locator=f"{path.as_posix()}#/records/{index}",
                source_sha256=source_hash,
                authority_status="candidate_only",
            )
        )
    return records, source_hash


def match_service_period(
    service_start_on: str,
    service_end_on: str,
    records: Iterable[ScheduleRecord],
    *,
    authoritative_only: bool = True,
) -> list[ScheduleRecord]:
    """Return containing schedules using checkout-exclusive booking dates."""
    period = normalize_service_period(service_start_on, service_end_on)
    return sorted(
        (
            record
            for record in records
            if (not authoritative_only or record.is_authoritative)
            and record.starts_on <= period.service_start_on
            and period.last_service_on <= record.ends_on
        ),
        key=lambda record: record.trip_code,
    )


def manifest(records: Iterable[ScheduleRecord]) -> list[dict[str, object]]:
    return [record.as_dict() for record in sorted(records, key=lambda item: item.trip_code)]
