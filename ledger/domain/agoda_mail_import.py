"""Provider-filtered, idempotent import boundary for Agoda OTA mail indexes.

The historical Agoda portal evidence is deliberately outside this boundary.  A
mail index is treated as supplementary evidence: only rows whose provider is
explicitly Agoda are admitted, and the existing evidence materializer decides
whether a row enriches an existing booking or creates a new one.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ledger.domain.agoda_booking_evidence import (
    ensure_schema,
    materialize_agoda_mail_bookings,
)
from ledger.domain.direct_sources import (
    _insert_source,
    _strict_json_bytes,
)
from ledger.domain.source_adapters import OTA_REDACTION_VERSION, adapt_ota_record


SOURCE_KINDS = frozenset({"ota_mail", "ota_mail_live"})


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_source_kind(source_kind: str) -> str:
    if source_kind not in SOURCE_KINDS:
        allowed = ",".join(sorted(SOURCE_KINDS))
        raise ValueError(f"agoda_mail_source_kind_invalid:{allowed}")
    return source_kind


def _load_records(path: Path) -> list[Mapping[str, object]]:
    raw = _strict_json_bytes(path.read_bytes(), "agoda_mail")
    if not isinstance(raw, dict):
        raise ValueError("agoda_mail_root_invalid")
    records = raw.get("records")
    if not isinstance(records, list):
        raise ValueError("agoda_mail_records_invalid")
    normalized: list[Mapping[str, object]] = []
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise ValueError(f"agoda_mail_record_invalid:{index}")
        normalized.append(row)
    return normalized


def _database_integrity(db: sqlite3.Connection) -> tuple[str, int]:
    integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = len(list(db.execute("PRAGMA foreign_key_check")))
    return integrity, foreign_keys


def import_agoda_mail_index(
    db_path: Path,
    input_path: Path,
    run_id: str,
    *,
    source_kind: str = "ota_mail_live",
) -> dict[str, Any]:
    """Import only explicit Agoda rows and materialize them idempotently.

    ``db_path`` must point at the existing cost ledger.  No portal source row is
    deleted or relabelled.  A malformed row or source conflict rolls back the
    complete import transaction.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("agoda_mail_run_id_invalid")
    _validate_source_kind(source_kind)
    records = _load_records(Path(input_path))

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    inserted = 0
    agoda_records = 0
    skipped_non_agoda = 0
    skipped_missing_provider = 0
    materialized: dict[str, int] = {}
    integrity = "not_checked"
    foreign_key_violations = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        ensure_schema(db)
        for index, row in enumerate(records):
            provider = row.get("provider")
            if not isinstance(provider, str) or not provider.strip():
                skipped_missing_provider += 1
                continue
            if provider.strip().casefold() != "agoda":
                skipped_non_agoda += 1
                continue

            clean = adapt_ota_record(row)
            key = str(clean.get("message_id") or f"row:{index}")
            source_id, created = _insert_source(
                db,
                source_kind,
                key,
                clean,
                OTA_REDACTION_VERSION,
            )
            inserted += int(created)
            agoda_records += 1

        materialized = materialize_agoda_mail_bookings(db)
        if materialized["conflicts"]:
            raise ValueError("agoda_mail_materialization_conflict")
        integrity, foreign_key_violations = _database_integrity(db)
        if integrity != "ok" or foreign_key_violations:
            raise RuntimeError("agoda_mail_import_integrity_failure")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "run_id": run_id,
        "input_records": len(records),
        "agoda_records": agoda_records,
        "skipped_non_agoda": skipped_non_agoda,
        "skipped_missing_provider": skipped_missing_provider,
        "source_inserted": inserted,
        "source_id_count": agoda_records,
        "materialized": materialized.get("materialized", 0),
        "bookings_created": materialized.get("bookings_created", 0),
        "evidence_inserted": materialized.get("evidence_inserted", 0),
        "conflicts": materialized.get("conflicts", 0),
        "unresolved": materialized.get("unresolved", 0),
        "integrity_check": integrity,
        "foreign_key_violations": foreign_key_violations,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-kind", default="ota_mail_live", choices=sorted(SOURCE_KINDS))
    args = parser.parse_args()
    print(_canonical_json(import_agoda_mail_index(
        args.db, args.input, args.run_id, source_kind=args.source_kind
    )))


if __name__ == "__main__":
    main()
