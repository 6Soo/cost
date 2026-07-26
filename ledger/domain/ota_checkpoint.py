#!/usr/bin/env python3
"""Durable, per-booking checkpoints for authenticated OTA portal collection.

The browser collector calls :meth:`OtaCheckpointStore.capture` immediately
after reading one booking.  Each call is its own SQLite transaction, so a
network loss or browser restart cannot discard previously committed bookings.

This store is deliberately separate from the accounting projection.  It keeps
append-only observations and exposes only completed, privacy-allowlisted rows
to the existing direct OTA importer.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlparse

from .source_adapters import (
    OTA_REDACTION_VERSION,
    forbidden_ota_fields,
    sanitize_ota_record,
)


SCHEMA_VERSION = 1
DEFAULT_REQUIRED_FIELDS = (
    "current_url",
    "portal_list_position",
    "observed_at",
    "product_type",
    "merchant",
    "service_start_on",
    "status",
)
_PROVIDER_ALIASES = {
    "booking": "booking.com",
    "trip": "trip.com",
    "trip_hotel": "trip.com",
    "trip_flight": "trip.com",
}


@dataclass(frozen=True)
class CaptureResult:
    observation_id: int
    provider: str
    booking_id: str
    complete: bool
    missing_fields: tuple[str, ...]
    inserted: bool


@dataclass(frozen=True)
class ResumeState:
    provider: str
    current_url: str | None
    portal_list_name: str | None
    last_completed_position: int | None
    next_position: int | None
    last_completed_booking_id: str | None
    observed_at: str | None
    completed_booking_ids: tuple[str, ...]


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _provider(value: object) -> str:
    normalized = _text(value).lower()
    normalized = _PROVIDER_ALIASES.get(normalized, normalized)
    if not normalized:
        raise ValueError("provider is required")
    return normalized


def _booking_id(record: Mapping[str, object]) -> str:
    value = _text(
        record.get("booking_id")
        or record.get("booking_number")
        or record.get("bookingNo")
    )
    if not value:
        raise ValueError("booking_id is required")
    return value


def _observed_at(value: object) -> str:
    text = _text(value)
    if not text:
        raise ValueError("observed_at is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _current_url(value: object) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("current_url must be an absolute HTTP(S) URL")
    return text


def _position(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("portal_list_position must be a non-negative integer")
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "portal_list_position must be a non-negative integer"
        ) from exc
    if result < 0:
        raise ValueError("portal_list_position must be a non-negative integer")
    return result


def _validate_scope(record: Mapping[str, object]) -> None:
    raw = record.get("service_start_on") or record.get("serviceStartOn")
    if raw in (None, ""):
        return
    try:
        service_date = date.fromisoformat(_text(raw))
    except ValueError as exc:
        raise ValueError("service_start_on must be an ISO date") from exc
    if service_date.year < 2025:
        raise ValueError("pre-2025 OTA bookings are outside the current scope")


def _normalize_required_fields(fields: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(_text(field) for field in fields if _text(field)))
    if not normalized:
        raise ValueError("required_fields cannot be empty")
    return normalized


class OtaCheckpointStore:
    """SQLite-backed append-only booking observation store."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        # Each capture must be durable before browser navigation continues.
        self.db.execute("PRAGMA synchronous = FULL")
        self._initialize()

    def __enter__(self) -> "OtaCheckpointStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def _initialize(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS ota_checkpoint_schema (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO ota_checkpoint_schema(version) VALUES (1);

            CREATE TABLE IF NOT EXISTS ota_booking_observations (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                booking_id TEXT NOT NULL,
                current_url TEXT NOT NULL,
                portal_list_name TEXT,
                portal_list_position INTEGER NOT NULL
                    CHECK(portal_list_position >= 0),
                observed_at TEXT NOT NULL,
                required_fields_json TEXT NOT NULL,
                missing_fields_json TEXT NOT NULL,
                complete INTEGER NOT NULL CHECK(complete IN (0, 1)),
                payload_json TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, booking_id, content_sha256)
            );

            CREATE INDEX IF NOT EXISTS ota_observations_by_provider_position
            ON ota_booking_observations(
                provider, portal_list_name, portal_list_position, observed_at
            );

            CREATE TABLE IF NOT EXISTS ota_booking_current (
                provider TEXT NOT NULL,
                booking_id TEXT NOT NULL,
                observation_id INTEGER NOT NULL
                    REFERENCES ota_booking_observations(id),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(provider, booking_id)
            );

            CREATE TABLE IF NOT EXISTS ota_provider_cursor (
                provider TEXT PRIMARY KEY,
                observation_id INTEGER NOT NULL
                    REFERENCES ota_booking_observations(id),
                current_url TEXT NOT NULL,
                portal_list_name TEXT,
                portal_list_position INTEGER NOT NULL,
                last_completed_booking_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.db.commit()

    def capture(
        self,
        record: Mapping[str, object],
        *,
        required_fields: Iterable[str] = DEFAULT_REQUIRED_FIELDS,
        complete: bool | None = None,
    ) -> CaptureResult:
        """Commit one portal observation before the collector navigates away.

        Exact retries are idempotent.  A materially changed observation is
        appended, while ``ota_booking_current`` advances only to an equal or
        newer ``observed_at`` value.  Setting ``complete=True`` with missing
        required fields raises before any row is written.
        """
        provider = _provider(record.get("provider"))
        booking_id = _booking_id(record)
        _validate_scope(record)
        current_url = _current_url(record.get("current_url"))
        observed_at = _observed_at(record.get("observed_at"))
        position = _position(
            record.get("portal_list_position", record.get("portalListPosition"))
        )
        list_name = _text(
            record.get("portal_list_name", record.get("portalListName"))
        ) or None
        required = _normalize_required_fields(required_fields)

        portal_record = dict(record)
        portal_record.update(
            provider=provider,
            booking_number=booking_id,
            message_id=_text(record.get("message_id"))
            or f"portal:{provider}:{booking_id}",
            source_channel="authenticated_booking_portal",
            observed_at=observed_at,
            portal_list_position=position,
            extraction_sources=["authenticated_portal_dom"],
        )
        if list_name is not None:
            portal_record["portal_list_name"] = list_name
        clean = sanitize_ota_record(portal_record)
        # URL is checkpoint-only.  It intentionally cannot cross the existing
        # OTA privacy allowlist into accounting evidence.
        clean.pop("current_url", None)
        if forbidden_ota_fields(clean):
            raise ValueError("sanitized OTA payload contains forbidden fields")

        values_for_completeness = dict(clean)
        values_for_completeness.update(
            current_url=current_url,
            observed_at=observed_at,
            portal_list_position=position,
        )
        missing = tuple(
            field
            for field in required
            if values_for_completeness.get(field) in (None, "", [], ())
        )
        calculated_complete = not missing
        if complete is True and missing:
            raise ValueError(
                "complete checkpoint is missing required fields: "
                + ", ".join(missing)
            )
        is_complete = calculated_complete if complete is None else bool(complete)

        durable = {
            "provider": provider,
            "booking_id": booking_id,
            "current_url": current_url,
            "portal_list_name": list_name,
            "portal_list_position": position,
            "observed_at": observed_at,
            "required_fields": required,
            "missing_fields": missing,
            "complete": is_complete,
            "payload": clean,
        }
        digest = _canonical_hash(durable)
        before = self.db.total_changes
        with self.db:
            self.db.execute(
                """
                INSERT OR IGNORE INTO ota_booking_observations(
                    provider, booking_id, current_url, portal_list_name,
                    portal_list_position, observed_at, required_fields_json,
                    missing_fields_json, complete, payload_json, content_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    booking_id,
                    current_url,
                    list_name,
                    position,
                    observed_at,
                    json.dumps(required, ensure_ascii=False),
                    json.dumps(missing, ensure_ascii=False),
                    int(is_complete),
                    json.dumps(clean, ensure_ascii=False, sort_keys=True),
                    digest,
                ),
            )
            inserted = self.db.total_changes > before
            row = self.db.execute(
                """
                SELECT id FROM ota_booking_observations
                WHERE provider=? AND booking_id=? AND content_sha256=?
                """,
                (provider, booking_id, digest),
            ).fetchone()
            observation_id = int(row["id"])
            current = self.db.execute(
                """
                SELECT observation.observed_at
                FROM ota_booking_current current
                JOIN ota_booking_observations observation
                  ON observation.id=current.observation_id
                WHERE current.provider=? AND current.booking_id=?
                """,
                (provider, booking_id),
            ).fetchone()
            if current is None or observed_at >= str(current["observed_at"]):
                self.db.execute(
                    """
                    INSERT INTO ota_booking_current(
                        provider, booking_id, observation_id
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(provider, booking_id) DO UPDATE SET
                        observation_id=excluded.observation_id,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (provider, booking_id, observation_id),
                )
            cursor = self.db.execute(
                "SELECT observed_at FROM ota_provider_cursor WHERE provider=?",
                (provider,),
            ).fetchone()
            if is_complete and (
                cursor is None or observed_at >= str(cursor["observed_at"])
            ):
                self.db.execute(
                    """
                    INSERT INTO ota_provider_cursor(
                        provider, observation_id, current_url, portal_list_name,
                        portal_list_position, last_completed_booking_id,
                        observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider) DO UPDATE SET
                        observation_id=excluded.observation_id,
                        current_url=excluded.current_url,
                        portal_list_name=excluded.portal_list_name,
                        portal_list_position=excluded.portal_list_position,
                        last_completed_booking_id=excluded.last_completed_booking_id,
                        observed_at=excluded.observed_at,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        provider,
                        observation_id,
                        current_url,
                        list_name,
                        position,
                        booking_id,
                        observed_at,
                    ),
                )
        return CaptureResult(
            observation_id=observation_id,
            provider=provider,
            booking_id=booking_id,
            complete=is_complete,
            missing_fields=missing,
            inserted=inserted,
        )

    def resume_state(self, provider: str) -> ResumeState:
        """Return cursor hints plus IDs to skip after a restart.

        List positions can move when an OTA resorts its UI, so callers should
        use ``next_position`` only as a navigation hint and always skip the
        returned provider+booking IDs.
        """
        normalized = _provider(provider)
        cursor = self.db.execute(
            "SELECT * FROM ota_provider_cursor WHERE provider=?",
            (normalized,),
        ).fetchone()
        completed = tuple(
            str(row["booking_id"])
            for row in self.db.execute(
                """
                SELECT current.booking_id
                FROM ota_booking_current current
                JOIN ota_booking_observations observation
                  ON observation.id=current.observation_id
                WHERE current.provider=? AND observation.complete=1
                ORDER BY observation.portal_list_position, current.booking_id
                """,
                (normalized,),
            ).fetchall()
        )
        if cursor is None:
            return ResumeState(
                normalized, None, None, None, None, None, None, completed
            )
        position = int(cursor["portal_list_position"])
        return ResumeState(
            provider=normalized,
            current_url=str(cursor["current_url"]),
            portal_list_name=cursor["portal_list_name"],
            last_completed_position=position,
            next_position=position + 1,
            last_completed_booking_id=str(cursor["last_completed_booking_id"]),
            observed_at=str(cursor["observed_at"]),
            completed_booking_ids=completed,
        )

    def completed_records(self, provider: str | None = None) -> list[dict[str, object]]:
        """Return current complete rows in the direct OTA importer contract."""
        params: tuple[object, ...] = ()
        where = "WHERE observation.complete=1"
        if provider is not None:
            where += " AND current.provider=?"
            params = (_provider(provider),)
        rows = self.db.execute(
            f"""
            SELECT observation.payload_json
            FROM ota_booking_current current
            JOIN ota_booking_observations observation
              ON observation.id=current.observation_id
            {where}
            ORDER BY current.provider, observation.portal_list_position,
                     current.booking_id
            """,
            params,
        ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]
