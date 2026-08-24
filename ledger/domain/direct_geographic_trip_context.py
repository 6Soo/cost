"""Typed, non-transaction context for current geographic trip inference.

This source describes a trip target recovered from historical context.  It is
not a transaction fact and is never promoted as independent evidence.  The
classifier may use it only together with a current card row whose merchant
contains an explicit Taiwan marker and whose occurred date is inside the
exact, year-bound context window.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import date, timedelta
from typing import Iterable, Mapping


SOURCE_KIND = "geographic_trip_context"
SCHEMA_VERSION = "current-geographic-trip-context-v1"
TARGET_CODE = "0107_대만"
TAIWAN_TOKENS = (
    "TAIWAN",
    "TAIPEI",
    "TAICHUNG",
    "TAINAN",
    "TAITUNG",
    "NANTOU",
    "HUALIAN",
    "KAOHSIUNG",
    "PINGTUNG",
    "SUNMOONLAKE",
    "HUALIEN",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return "".join(char for char in text if char.isalnum())


def is_taiwan_marker(value: object) -> bool:
    """Recognize Taiwan/city markers without treating TWIN or NETWORK as TW."""
    raw = unicodedata.normalize("NFKC", str(value or "")).upper()
    normalized = _norm(raw)
    if any(token in normalized for token in TAIWAN_TOKENS):
        return True
    return re.search(r"(?<![A-Z])TW(?![A-Z])", raw) is not None


def _clean_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value


def _validate_context_row(row: object, index: int) -> dict[str, object]:
    if not isinstance(row, dict):
        raise ValueError(f"geographic_trip_context_row_invalid:{index}")
    required = {
        "tab", "mm", "dd", "region", "window",
        "current_card_geography_required", "payment_date_is_service_date",
        "transaction_evidence_allowed", "provenance",
    }
    if set(row) != required:
        raise ValueError(f"geographic_trip_context_fields_invalid:{index}")
    if (
        not _clean_text(row["tab"])
        or not _clean_text(row["region"])
        or type(row["mm"]) is not int
        or type(row["dd"]) is not int
        or type(row["window"]) is not int
        or not 1 <= row["window"] <= 60
        or type(row["current_card_geography_required"]) is not bool
        or type(row["payment_date_is_service_date"]) is not bool
        or type(row["transaction_evidence_allowed"]) is not bool
        or not isinstance(row["provenance"], dict)
    ):
        raise ValueError(f"geographic_trip_context_values_invalid:{index}")
    if row["tab"] != TARGET_CODE or row["region"] != "대만":
        raise ValueError(f"geographic_trip_context_target_invalid:{index}")
    if (
        row["current_card_geography_required"] is not True
        or row["payment_date_is_service_date"] is not False
        or row["transaction_evidence_allowed"] is not False
    ):
        raise ValueError(f"geographic_trip_context_authority_invalid:{index}")
    try:
        date(2026, row["mm"], row["dd"])
    except ValueError as exc:
        raise ValueError(f"geographic_trip_context_date_invalid:{index}") from exc
    provenance = row["provenance"]
    if (
        set(provenance) != {"kind", "source_path", "source_rows", "note"}
        or provenance.get("kind") != "historical_context_only"
        or not _clean_text(provenance.get("source_path"))
        or not isinstance(provenance.get("source_rows"), list)
        or not provenance.get("source_rows")
        or any(not _clean_text(item) for item in provenance["source_rows"])
        or not _clean_text(provenance.get("note"))
    ):
        raise ValueError(f"geographic_trip_context_provenance_invalid:{index}")
    return dict(row)


def validate_geographic_trip_context_document(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "records"}:
        raise ValueError("geographic_trip_context_root_invalid")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise ValueError("geographic_trip_context_schema_version_invalid")
    records = raw["records"]
    if not isinstance(records, list) or not records:
        raise ValueError("geographic_trip_context_records_invalid")
    parsed = [_validate_context_row(row, index) for index, row in enumerate(records)]
    tabs = [str(row["tab"]) for row in parsed]
    if len(tabs) != len(set(tabs)):
        raise ValueError("geographic_trip_context_duplicate_target")
    return parsed


def context_keys(raw_bytes: bytes) -> list[str]:
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("geographic_trip_context_json_invalid") from exc
    return [str(row["tab"]) for row in validate_geographic_trip_context_document(raw)]


def _allocation_row(
    row: Mapping[str, object], source_sha256: str,
) -> dict[str, object]:
    service_year = 2026
    start = date(2026, int(row["mm"]), int(row["dd"]))
    return {
        "tab": str(row["tab"]),
        "mm": int(row["mm"]),
        "dd": int(row["dd"]),
        "region": str(row["region"]),
        "window": int(row["window"]),
        "service_year": service_year,
        "starts_on": start.isoformat(),
        "ends_on": (start + timedelta(days=int(row["window"]) - 1)).isoformat(),
        "source_kind": SOURCE_KIND,
        "source_sha256": str(source_sha256),
    }


def load_geographic_trip_context(
    db: sqlite3.Connection, *, required: bool = True,
) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records
           WHERE source_kind=? ORDER BY source_key""",
        (SOURCE_KIND,),
    ).fetchall()
    if not rows:
        if required:
            raise ValueError("geographic_trip_context_source_missing")
        return []
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for source_key, source_sha256, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("geographic_trip_context_payload_invalid") from exc
        row = _validate_context_row(payload, len(result))
        if str(source_key) != str(row["tab"]):
            raise ValueError("geographic_trip_context_source_key_invalid")
        if _sha(row) != str(source_sha256):
            raise ValueError("geographic_trip_context_digest_invalid")
        if str(row["tab"]) in seen:
            raise ValueError("geographic_trip_context_duplicate_target")
        seen.add(str(row["tab"]))
        result.append({
            **row,
            "service_year": 2026,
            "source_sha256": str(source_sha256),
            "starts_on": date(2026, int(row["mm"]), int(row["dd"])).isoformat(),
            "ends_on": (
                date(2026, int(row["mm"]), int(row["dd"]))
                + timedelta(days=int(row["window"]) - 1)
            ).isoformat(),
        })
    return result


def load_verified_trip_target_schedule(
    db: sqlite3.Connection,
) -> dict[str, dict[str, object]]:
    """Load canonical targets plus typed external-fact context targets.

    This lookup is for validating an already authenticated external service
    fact.  It is not the allocator's generic schedule.
    """
    from ledger.domain.direct_verified_ota_lodging import (
        load_authoritative_trip_schedule,
    )

    result = load_authoritative_trip_schedule(db)
    for row in load_geographic_trip_context(db, required=False):
        target = str(row["tab"])
        if target in result:
            raise ValueError("geographic_trip_context_target_overlaps_schedule")
        result[target] = _allocation_row(row, str(row["source_sha256"]))
    return result


def load_allocation_trip_schedule(
    db: sqlite3.Connection,
) -> dict[str, dict[str, object]]:
    """Load only canonical trips accepted by the normal allocator."""
    from ledger.domain.direct_verified_ota_lodging import (
        load_authoritative_trip_schedule,
    )

    return load_authoritative_trip_schedule(db)


def context_manifest(context: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "tab": str(row["tab"]),
            "mm": int(row["mm"]),
            "dd": int(row["dd"]),
            "window": int(row["window"]),
            "region": str(row["region"]),
            "source_sha256": str(row["source_sha256"]),
            "transaction_evidence_allowed": bool(
                row["transaction_evidence_allowed"]
            ),
            "payment_date_is_service_date": bool(
                row["payment_date_is_service_date"]
            ),
        }
        for row in context
    ]
