"""Import the privacy-safe schedule export produced by reservation.

This is an explicit boundary between the reservation tour master and the cost
ledger.  It accepts stored dates only; it never parses a cafe post and never
uses a payment date to manufacture a trip year or end date.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from typing import Mapping

from ledger.domain.direct_sources import _insert_source, _strict_json_bytes
from ledger.domain.direct_trip_schedule_authority import (
    END_SEMANTICS,
    sha256_value,
    validate_record,
)
from ledger.domain.direct_verified_ota_lodging import load_authoritative_trip_schedule


EXPORT_SCHEMA_VERSION = "reservation-trip-schedule-export-v2"
PARSER_CONTRACT = "reservation:cafeParse:R1-1"
REDACTION_VERSION = EXPORT_SCHEMA_VERSION
ACTIVITY_COMMENT_THRESHOLD = 10
ACTIVITY_STATUSES = {
    "activity_confirmed",
    "activity_insufficient",
    "activity_incomplete",
    "activity_unavailable",
    "not_observable_yet",
}
ACTIVITY_SOURCE_STATUSES = {
    "archived_snapshot_available",
    "no_archived_snapshot",
}
ROOT_KEYS = {"schema_version", "parser_contract", "exported_at", "records"}
RECORD_KEYS = {
    "trip_code",
    "cafe_fldid",
    "cafe_datanum",
    "event_year",
    "starts_on",
    "ends_on",
    "region",
    "date_source",
    "authority_kind",
    "authority_status",
    "source_locator",
    "source_post_sha256",
    "end_semantics",
    "hold_reason",
    "comment_count",
    "listed_comment_count",
    "fetched_unique_comment_count",
    "comment_threshold",
    "comment_census_complete",
    "comment_observed_at",
    "activity_status",
    "activity_source_status",
    "activity_snapshot_sha256",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stable_export_document(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": value["schema_version"],
        "parser_contract": value["parser_contract"],
        "records": [
            {
                key: field_value
                for key, field_value in dict(record).items()
                if key != "comment_observed_at"
            }
            for record in value["records"]
        ],
    }


def _export_sha256(value: Mapping[str, object]) -> str:
    # exported_at is transport metadata and changes on every export.  It must
    # not change the content identity used by the idempotent import boundary.
    return hashlib.sha256(
        _canonical_json(_stable_export_document(value)).encode("utf-8")
    ).hexdigest()


def _activity_hashable(record: Mapping[str, object]) -> dict[str, object]:
    # This deliberately excludes comment_observed_at.  Rechecking an
    # unchanged archive on a later day must remain idempotent; a real content
    # or decision-state change creates a new activity snapshot instead.
    return {
        "cafe_fldid": record["cafe_fldid"],
        "cafe_datanum": record["cafe_datanum"],
        "source_post_sha256": record["source_post_sha256"],
        "comment_count": record["comment_count"],
        "listed_comment_count": record["listed_comment_count"],
        "fetched_unique_comment_count": record["fetched_unique_comment_count"],
        "comment_threshold": record["comment_threshold"],
        "comment_census_complete": record["comment_census_complete"],
        "activity_status": record["activity_status"],
        "activity_source_status": record["activity_source_status"],
    }


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or "\n" in value:
        raise ValueError(f"reservation_schedule_{field}_invalid")
    return value.strip()


def _date(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not ISO_DATE_RE.fullmatch(value):
        raise ValueError(f"reservation_schedule_{field}_invalid")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"reservation_schedule_{field}_invalid") from exc
    return value


def _sha(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"reservation_schedule_{field}_invalid")
    return value


def _count(value: object, field: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"reservation_schedule_{field}_invalid")
    return value


def _load_raw(raw: bytes | str | Mapping[str, object]) -> dict[str, object]:
    if isinstance(raw, bytes):
        value = _strict_json_bytes(raw, "reservation_schedule_export")
    elif isinstance(raw, str):
        value = _strict_json_bytes(raw.encode("utf-8"), "reservation_schedule_export")
    elif isinstance(raw, Mapping):
        value = dict(raw)
    else:
        raise ValueError("reservation_schedule_export_root_invalid")
    if not isinstance(value, dict) or set(value) != ROOT_KEYS:
        raise ValueError("reservation_schedule_export_root_invalid")
    if value["schema_version"] != EXPORT_SCHEMA_VERSION:
        raise ValueError("reservation_schedule_export_schema_version_invalid")
    if value["parser_contract"] != PARSER_CONTRACT:
        raise ValueError("reservation_schedule_export_parser_contract_invalid")
    exported_at = _text(value["exported_at"], "exported_at")
    try:
        datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reservation_schedule_exported_at_invalid") from exc
    if not isinstance(value["records"], list):
        raise ValueError("reservation_schedule_export_records_invalid")
    return value


def _validate_record(raw: object, index: int, observation_date: str) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != RECORD_KEYS:
        raise ValueError(f"reservation_schedule_record_shape_invalid:{index}")
    trip_code = _text(raw["trip_code"], "trip_code")
    cafe_fldid = _text(raw["cafe_fldid"], "cafe_fldid")
    cafe_datanum = raw["cafe_datanum"]
    if cafe_datanum is not None:
        cafe_datanum = _text(cafe_datanum, "cafe_datanum")
    starts_on = _date(raw["starts_on"], "starts_on", nullable=True)
    ends_on = _date(raw["ends_on"], "ends_on", nullable=True)
    if starts_on and ends_on and ends_on < starts_on:
        raise ValueError(f"reservation_schedule_date_order_invalid:{index}")
    event_year = raw["event_year"]
    if event_year is not None:
        if type(event_year) is not int or not 1900 <= event_year <= 2200:
            raise ValueError(f"reservation_schedule_event_year_invalid:{index}")
        if starts_on and event_year != int(starts_on[:4]):
            raise ValueError(f"reservation_schedule_event_year_mismatch:{index}")
    elif starts_on:
        raise ValueError(f"reservation_schedule_event_year_missing:{index}")
    date_source = raw["date_source"]
    if date_source not in {None, "parsed", "manual"}:
        raise ValueError(f"reservation_schedule_date_source_invalid:{index}")
    authority_status = raw["authority_status"]
    authority_kind = raw["authority_kind"]
    if authority_status not in {"authoritative", "candidate_only"}:
        raise ValueError(f"reservation_schedule_authority_status_invalid:{index}")
    if authority_status == "authoritative":
        if authority_kind not in {"explicit_trip_registry", "official_event_schedule", "user_confirmed_schedule"}:
            raise ValueError(f"reservation_schedule_authority_kind_invalid:{index}")
        if not starts_on or not ends_on or not event_year:
            raise ValueError(f"reservation_schedule_authoritative_period_missing:{index}")
        if date_source == "parsed" and raw["source_post_sha256"] is None:
            raise ValueError(f"reservation_schedule_parsed_source_missing:{index}")
        if date_source not in {"parsed", "manual"}:
            raise ValueError(f"reservation_schedule_authoritative_source_invalid:{index}")
    else:
        if authority_kind != "legacy_window_candidate":
            raise ValueError(f"reservation_schedule_candidate_kind_invalid:{index}")
    if raw["end_semantics"] not in {None, END_SEMANTICS}:
        raise ValueError(f"reservation_schedule_end_semantics_invalid:{index}")
    if bool(starts_on and ends_on) != (raw["end_semantics"] == END_SEMANTICS):
        raise ValueError(f"reservation_schedule_end_semantics_missing:{index}")
    source_post_sha256 = _sha(raw["source_post_sha256"], "source_post_sha256", nullable=True)
    _text(raw["region"], "region")
    _text(raw["source_locator"], "source_locator")
    hold_reason = raw["hold_reason"]
    if hold_reason is not None:
        _text(hold_reason, "hold_reason")
    comment_count = _count(raw["comment_count"], "comment_count", nullable=True)
    listed_comment_count = _count(raw["listed_comment_count"], "listed_comment_count", nullable=True)
    fetched_unique_comment_count = _count(
        raw["fetched_unique_comment_count"],
        "fetched_unique_comment_count",
        nullable=True,
    )
    if comment_count != listed_comment_count:
        raise ValueError(f"reservation_schedule_comment_count_mismatch:{index}")
    comment_threshold = raw["comment_threshold"]
    if type(comment_threshold) is not int or comment_threshold != ACTIVITY_COMMENT_THRESHOLD:
        raise ValueError(f"reservation_schedule_comment_threshold_invalid:{index}")
    comment_census_complete = raw["comment_census_complete"]
    if type(comment_census_complete) is not bool:
        raise ValueError(f"reservation_schedule_comment_census_complete_invalid:{index}")
    comment_observed_at = raw["comment_observed_at"]
    if comment_observed_at is not None:
        comment_observed_at = _text(comment_observed_at, "comment_observed_at")
        try:
            datetime.fromisoformat(comment_observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"reservation_schedule_comment_observed_at_invalid:{index}") from exc
    activity_status = raw["activity_status"]
    if activity_status not in ACTIVITY_STATUSES:
        raise ValueError(f"reservation_schedule_activity_status_invalid:{index}")
    activity_source_status = raw["activity_source_status"]
    if activity_source_status not in ACTIVITY_SOURCE_STATUSES:
        raise ValueError(f"reservation_schedule_activity_source_status_invalid:{index}")
    activity_snapshot_sha256 = _sha(
        raw["activity_snapshot_sha256"],
        "activity_snapshot_sha256",
        nullable=True,
    )
    if activity_source_status == "no_archived_snapshot":
        if any(value is not None for value in (comment_count, listed_comment_count, fetched_unique_comment_count)):
            raise ValueError(f"reservation_schedule_activity_count_without_snapshot:{index}")
        if comment_census_complete or activity_snapshot_sha256 is not None:
            raise ValueError(f"reservation_schedule_activity_snapshot_shape_invalid:{index}")
    else:
        if comment_count is None or listed_comment_count is None:
            raise ValueError(f"reservation_schedule_activity_count_missing:{index}")
        if comment_census_complete and fetched_unique_comment_count != listed_comment_count:
            raise ValueError(f"reservation_schedule_activity_census_mismatch:{index}")
        if activity_snapshot_sha256 is None:
            raise ValueError(f"reservation_schedule_activity_snapshot_missing:{index}")
    if activity_status == "activity_confirmed":
        if (
            activity_source_status != "archived_snapshot_available"
            or not comment_census_complete
            or comment_count is None
            or comment_count < ACTIVITY_COMMENT_THRESHOLD
            or not ends_on
            or observation_date <= ends_on
        ):
            raise ValueError(f"reservation_schedule_activity_confirmation_invalid:{index}")
    elif activity_status == "activity_insufficient":
        if (
            activity_source_status != "archived_snapshot_available"
            or not comment_census_complete
            or comment_count is None
            or comment_count >= ACTIVITY_COMMENT_THRESHOLD
            or not ends_on
            or observation_date <= ends_on
        ):
            raise ValueError(f"reservation_schedule_activity_insufficient_invalid:{index}")
    elif activity_status == "activity_incomplete":
        if activity_source_status != "archived_snapshot_available" or comment_census_complete:
            raise ValueError(f"reservation_schedule_activity_incomplete_invalid:{index}")
    elif activity_status == "activity_unavailable":
        if activity_source_status != "no_archived_snapshot" or not ends_on or observation_date <= ends_on:
            raise ValueError(f"reservation_schedule_activity_unavailable_invalid:{index}")
    elif activity_status == "not_observable_yet":
        if ends_on and observation_date > ends_on:
            raise ValueError(f"reservation_schedule_activity_observation_window_invalid:{index}")
    if activity_snapshot_sha256 is not None:
        expected_activity_sha256 = hashlib.sha256(
            _canonical_json(_activity_hashable({
                "cafe_fldid": cafe_fldid,
                "cafe_datanum": cafe_datanum,
                "source_post_sha256": source_post_sha256,
                "comment_count": comment_count,
                "listed_comment_count": listed_comment_count,
                "fetched_unique_comment_count": fetched_unique_comment_count,
                "comment_threshold": comment_threshold,
                "comment_census_complete": comment_census_complete,
                "activity_status": activity_status,
                "activity_source_status": activity_source_status,
            })).encode("utf-8")
        ).hexdigest()
        if activity_snapshot_sha256 != expected_activity_sha256:
            raise ValueError(f"reservation_schedule_activity_snapshot_digest_invalid:{index}")
    return {
        "trip_code": trip_code,
        "cafe_fldid": cafe_fldid,
        "cafe_datanum": cafe_datanum,
        "event_year": event_year,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "region": str(raw["region"]).strip(),
        "date_source": date_source,
        "authority_kind": authority_kind,
        "authority_status": authority_status,
        "source_locator": str(raw["source_locator"]).strip(),
        "source_post_sha256": source_post_sha256,
        "end_semantics": raw["end_semantics"],
        "hold_reason": hold_reason,
        "comment_count": comment_count,
        "listed_comment_count": listed_comment_count,
        "fetched_unique_comment_count": fetched_unique_comment_count,
        "comment_threshold": comment_threshold,
        "comment_census_complete": comment_census_complete,
        "comment_observed_at": comment_observed_at,
        "activity_status": activity_status,
        "activity_source_status": activity_source_status,
        "activity_snapshot_sha256": activity_snapshot_sha256,
    }


def validate_schedule_export(raw: bytes | str | Mapping[str, object]) -> dict[str, object]:
    """Validate and return a normalized, still-PII-free export document."""
    document = _load_raw(raw)
    records = [
        _validate_record(value, index, str(document["exported_at"])[:10])
        for index, value in enumerate(document["records"])
    ]
    trip_codes = [str(record["trip_code"]) for record in records]
    if len(trip_codes) != len(set(trip_codes)):
        raise ValueError("reservation_schedule_duplicate_trip_code")
    return {
        "schema_version": document["schema_version"],
        "parser_contract": document["parser_contract"],
        "exported_at": document["exported_at"],
        "records": records,
    }


def _trip_schedule_payload(record: Mapping[str, object]) -> dict[str, object]:
    payload = {
        "tab": record["trip_code"],
        "event_year": record["event_year"],
        "starts_on": record["starts_on"],
        "ends_on": record["ends_on"],
        "region": record["region"],
        "authority_kind": record["authority_kind"],
        "authority_status": "authoritative",
        "end_semantics": END_SEMANTICS,
    }
    # Validate with the same authority contract before persisting it.  The
    # source digest is computed over this exact normalized payload below.
    source_sha256 = sha256_value(payload)
    validate_record({
        "trip_code": payload["tab"],
        "event_year": payload["event_year"],
        "starts_on": payload["starts_on"],
        "ends_on": payload["ends_on"],
        "region": payload["region"],
        "authority_kind": payload["authority_kind"],
        "source_locator": f"reservation://schedule/{payload['tab']}",
        "source_sha256": source_sha256,
        "authority_status": payload["authority_status"],
        "end_semantics": END_SEMANTICS,
    })
    return payload


def import_reservation_schedule_export(
    db: sqlite3.Connection,
    raw: bytes | str | Mapping[str, object],
    *,
    source_key: str | None = None,
) -> dict[str, object]:
    """Validate, content-address, and idempotently import a reservation export.

    Complete authoritative records become ``trip_schedule`` source rows.  An
    incomplete or unconfirmed row is retained as audit evidence only and is
    reported as candidate-only; it cannot affect allocation or posting.
    """
    document = validate_schedule_export(raw)
    export_sha256 = _export_sha256(document)
    stable_document = _stable_export_document(document)
    root_key = source_key or f"reservation-export:{export_sha256}"
    if not root_key.strip() or "\n" in root_key:
        raise ValueError("reservation_schedule_source_key_invalid")

    savepoint = "reservation_schedule_export_import"
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        _, root_created = _insert_source(
            db,
            "reservation_schedule_export",
            root_key,
            stable_document,
            REDACTION_VERSION,
        )
        inserted = int(root_created)
        authoritative_count = 0
        candidate_count = 0
        candidate_reasons: list[dict[str, object]] = []
        authority_trip_codes: list[str] = []
        activity_counts: dict[str, int] = {}
        for record in document["records"]:
            record = dict(record)
            trip_code = str(record["trip_code"])
            stable_record = {
                key: field_value
                for key, field_value in record.items()
                if key != "comment_observed_at"
            }
            lineage = {**stable_record, "export_sha256": export_sha256}
            _, record_created = _insert_source(
                db,
                "reservation_schedule_record",
                f"{trip_code}:{export_sha256}",
                lineage,
                REDACTION_VERSION,
            )
            inserted += int(record_created)
            activity_status = str(record["activity_status"])
            activity_counts[activity_status] = activity_counts.get(activity_status, 0) + 1
            activity_snapshot_sha256 = record["activity_snapshot_sha256"]
            if activity_snapshot_sha256 is not None:
                activity_payload = {
                    "trip_code": trip_code,
                    "cafe_fldid": record["cafe_fldid"],
                    "cafe_datanum": record["cafe_datanum"],
                    "source_post_sha256": record["source_post_sha256"],
                    "comment_count": record["comment_count"],
                    "listed_comment_count": record["listed_comment_count"],
                    "fetched_unique_comment_count": record["fetched_unique_comment_count"],
                    "comment_threshold": record["comment_threshold"],
                    "comment_census_complete": record["comment_census_complete"],
                    "activity_status": record["activity_status"],
                    "activity_source_status": record["activity_source_status"],
                    "activity_snapshot_sha256": activity_snapshot_sha256,
                }
                _, activity_created = _insert_source(
                    db,
                    "reservation_schedule_activity",
                    f"{trip_code}:{activity_snapshot_sha256}",
                    activity_payload,
                    REDACTION_VERSION,
                )
                inserted += int(activity_created)
                comment_observed_at = record["comment_observed_at"]
                if comment_observed_at is not None:
                    observation_payload = {
                        "trip_code": trip_code,
                        "activity_snapshot_sha256": activity_snapshot_sha256,
                        "comment_observed_at": comment_observed_at,
                    }
                    _, observation_created = _insert_source(
                        db,
                        "reservation_schedule_activity_observation",
                        f"{trip_code}:{activity_snapshot_sha256}:{comment_observed_at}",
                        observation_payload,
                        REDACTION_VERSION,
                    )
                    inserted += int(observation_created)
            if record["authority_status"] != "authoritative":
                candidate_count += 1
                candidate_reasons.append({
                    "trip_code": trip_code,
                    "reason": record["hold_reason"],
                })
                continue
            payload = _trip_schedule_payload(record)
            _, schedule_created = _insert_source(
                db,
                "trip_schedule",
                trip_code,
                payload,
                REDACTION_VERSION,
            )
            inserted += int(schedule_created)
            authoritative_count += 1
            authority_trip_codes.append(trip_code)
        if authoritative_count:
            # Read through the production authority loader once so an export
            # cannot report success while its normalized rows are unreadable.
            load_authoritative_trip_schedule(db)
        db.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        db.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    return {
        "records": len(document["records"]),
        "inserted": inserted,
        "authoritative": authoritative_count,
        "candidate_only": candidate_count,
        "candidate_reasons": candidate_reasons,
        "authority_trip_codes": authority_trip_codes,
        "activity_counts": activity_counts,
        "export_sha256": export_sha256,
    }
