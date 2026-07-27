#!/usr/bin/env python3
"""Merge provider checkpoint shards into the pipeline's canonical portal inputs."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ledger.domain.ota_checkpoint import OtaCheckpointStore
from ledger.domain.source_adapters import forbidden_ota_fields


def _current_rows(path: Path) -> list[sqlite3.Row]:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(
            """
            SELECT observation.*
            FROM ota_booking_current current
            JOIN ota_booking_observations observation
              ON observation.id=current.observation_id
            ORDER BY observation.portal_list_position, current.booking_id
            """
        ).fetchall()
    finally:
        db.close()


def _write_json_atomic(path: Path, records: list[dict[str, object]]) -> None:
    payload = {"records": records}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def merge(data_dir: Path, provider: str) -> dict[str, object]:
    target_db = data_dir / f"ota_checkpoints_{provider}.db"
    target_json = data_dir / f"{provider}_direct_browser_evidence.json"
    shards = sorted(data_dir.glob(f"ota_checkpoints_{provider}_*.db"))

    source_current = 0
    inserted = 0
    with OtaCheckpointStore(target_db) as target:
        for shard in shards:
            for row in _current_rows(shard):
                source_current += 1
                payload = json.loads(str(row["payload_json"]))
                record = {
                    **payload,
                    "current_url": str(row["current_url"]),
                    "portal_list_name": row["portal_list_name"],
                    "portal_list_position": int(row["portal_list_position"]),
                    "observed_at": str(row["observed_at"]),
                }
                result = target.capture(
                    record,
                    required_fields=json.loads(
                        str(row["required_fields_json"])
                    ),
                    complete=bool(row["complete"]),
                )
                inserted += int(result.inserted)

        rows = target.db.execute(
            """
            SELECT observation.payload_json
            FROM ota_booking_current current
            JOIN ota_booking_observations observation
              ON observation.id=current.observation_id
            WHERE current.provider=?
            ORDER BY observation.portal_list_position, current.booking_id
            """,
            (provider,),
        ).fetchall()
        records = [json.loads(str(row["payload_json"])) for row in rows]
        forbidden = sorted(
            {
                field
                for record in records
                for field in forbidden_ota_fields(record)
            }
        )
        if forbidden:
            raise ValueError(
                "merged records contain forbidden fields: "
                + ", ".join(forbidden)
            )
        integrity = str(
            target.db.execute("PRAGMA integrity_check").fetchone()[0]
        )
        if integrity != "ok":
            raise RuntimeError(f"target database integrity check failed: {integrity}")

    _write_json_atomic(target_json, records)
    return {
        "provider": provider,
        "shards": [path.name for path in shards],
        "source_current_rows": source_current,
        "inserted_observations": inserted,
        "merged_current_records": len(records),
        "target_db": str(target_db),
        "target_json": str(target_json),
        "integrity": integrity,
        "forbidden_fields": forbidden,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument(
        "--data-dir", type=Path, default=Path("ledger/data")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            merge(args.data_dir, args.provider),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
