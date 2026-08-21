#!/usr/bin/env python3
"""Atomically merge disjoint Agoda detail worker databases.

The merger only produces a resumable private detail work database.  It never
touches the candidate ledger, classifications, allocations, journals, or
postings.  A separate full-census revalidation and ``seal`` step remain
mandatory before amount reconciliation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from tools.agoda_portal_detail_capture import (
        CaptureError,
        SourceBooking,
        SourceSnapshot,
        TERMINAL_SOURCE_RESERVATION_STATUSES,
        _attestation_membership_is_valid,
        _browser_lock_path,
        _canonical_json,
        _file_sha256,
        _load_source_snapshot,
        _require_tmp,
        _secure_create_work_db,
        _sha256_text,
        _terminal_kind_matches_detail_status,
        _utc_now,
    )
except ModuleNotFoundError:
    from agoda_portal_detail_capture import (
        CaptureError,
        SourceBooking,
        SourceSnapshot,
        TERMINAL_SOURCE_RESERVATION_STATUSES,
        _attestation_membership_is_valid,
        _browser_lock_path,
        _canonical_json,
        _file_sha256,
        _load_source_snapshot,
        _require_tmp,
        _secure_create_work_db,
        _sha256_text,
        _terminal_kind_matches_detail_status,
        _utc_now,
    )


class ParallelMergeError(CaptureError):
    pass


@dataclass(frozen=True)
class WorkerInput:
    label: str
    path: Path
    run_id: str


REQUIRED_TABLES = {
    "capture_run_manifest",
    "capture_attempts",
    "booking_detail_snapshots",
    "price_components",
    "payment_events",
    "booking_detail_observations",
    "page_attestations",
    "page_attestation_members",
}
EXPECTED_WORKER_LABELS = tuple(f"W{index:02d}" for index in range(1, 11))


def _worker_input(value: str) -> WorkerInput:
    parts = value.split(",")
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError("input_requires_label_path_run_id")
    return WorkerInput(parts[0], Path(parts[1]), parts[2])


def _private_immutable(path: Path) -> sqlite3.Connection:
    resolved = _require_tmp(path, must_exist=True)
    if resolved.is_symlink() or (os.name != "nt" and (resolved.stat().st_mode & 0o077) != 0):
        raise ParallelMergeError("worker_database_permissions_invalid")
    if any(os.path.lexists(str(resolved) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        raise ParallelMergeError("worker_database_sidecar_present")
    connection = sqlite3.connect(
        f"file:{resolved}?mode=ro&immutable=1", uri=True
    )
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        connection.close()
        raise ParallelMergeError("worker_database_integrity_invalid")
    return connection


def _acquire_worker_locks(
    inputs: Sequence[WorkerInput],
) -> list[tuple[Path, int, tuple[int, int]]]:
    """Atomically exclude every capture actor for the full merge lifetime.

    Detail capture uses an O_EXCL sentinel derived from the work DB and run ID.
    Creating the same sentinel closes both command-line-shape bypasses and the
    check-then-start race: either the existing capture owns it, or the merger
    owns it and no capture can start until cleanup.
    """
    owned: list[tuple[Path, int, tuple[int, int]]] = []
    try:
        for worker in sorted(inputs, key=lambda item: item.label):
            lock_path = _browser_lock_path(worker.path.resolve(), worker.run_id)
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as exc:
                raise ParallelMergeError(
                    "worker_database_still_has_active_or_stale_writer_lock"
                ) from exc
            marker = _canonical_json(
                {"kind": "parallel_merge", "label": worker.label}
            ).encode("utf-8")
            os.write(descriptor, marker)
            os.fsync(descriptor)
            lock_stat = os.fstat(descriptor)
            owned.append(
                (
                    lock_path,
                    descriptor,
                    (lock_stat.st_dev, lock_stat.st_ino),
                )
            )
        return owned
    except Exception:
        _release_worker_locks(owned)
        raise


def _release_worker_locks(
    owned: Sequence[tuple[Path, int, tuple[int, int]]],
) -> None:
    for lock_path, descriptor, owned_inode in reversed(owned):
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            current = lock_path.stat()
        except FileNotFoundError:
            continue
        if os.name == "nt" or (current.st_dev, current.st_ino) == owned_inode:
            lock_path.unlink(missing_ok=True)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _insert_copy(
    target: sqlite3.Connection,
    table: str,
    row: sqlite3.Row,
    *,
    omit: Iterable[str] = (),
    overrides: dict[str, Any] | None = None,
) -> int:
    excluded = set(omit)
    replacements = overrides or {}
    columns = [column for column in row.keys() if column not in excluded]
    values = [replacements.get(column, row[column]) for column in columns]
    placeholders = ",".join("?" for _ in columns)
    cursor = target.execute(
        f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",
        values,
    )
    return int(cursor.lastrowid)


def _source_booking_matches(row: sqlite3.Row, source: SourceBooking) -> bool:
    return (
        str(row["booking_id_sha256"]) == source.booking_id_sha256
        and str(row["booking_pseudonym_hmac"])
        == source.booking_pseudonym_hmac
        and str(row["tab_name"]) == source.tab_name
        and row["source_service_start_on"] == source.service_start_on
        and row["source_service_end_on"] == source.service_end_on
        and str(row["source_scope_status"]) == source.source_scope_status
        and str(row["source_reservation_status"])
        == source.reservation_status
        and str(row["list_card_sha256"]) == source.list_card_sha256
    )


def _validate_worker(
    worker: WorkerInput,
    connection: sqlite3.Connection,
    snapshot: SourceSnapshot,
    expected: dict[str, SourceBooking],
    expected_app: str,
) -> tuple[set[str], dict[str, int]]:
    tables = _table_names(connection)
    if not REQUIRED_TABLES <= tables:
        raise ParallelMergeError("worker_database_schema_incomplete")
    manifests = connection.execute(
        "SELECT * FROM capture_run_manifest"
    ).fetchall()
    if len(manifests) != 1:
        raise ParallelMergeError("worker_manifest_cardinality_invalid")
    manifest = manifests[0]
    if (
        str(manifest["run_id"]) != worker.run_id
        or str(manifest["source_path"]) != str(snapshot.path)
        or str(manifest["source_file_sha256"]) != snapshot.file_sha256
        or str(manifest["source_run_id"]) != snapshot.source_run_id
        or str(manifest["source_capture_set_sha256"])
        != snapshot.source_capture_set_sha256
        or str(manifest["membership_ordered_sha256"])
        != snapshot.membership_ordered_sha256
        or str(manifest["membership_set_sha256"])
        != snapshot.membership_set_sha256
        or int(manifest["source_population_count"])
        != snapshot.population_count
        or int(manifest["target_count"]) != len(snapshot.bookings)
        or int(manifest["target_2026_count"]) != snapshot.target_2026_count
        or int(manifest["competitor_count"]) != snapshot.competitor_count
        or int(manifest["target_year"]) != 2026
        or str(manifest["pseudonym_key_id"])
        != snapshot.pseudonym_key_id
        or str(manifest["app_name"]) != expected_app
        or str(manifest["epoch_status"]) != "capturing"
    ):
        raise ParallelMergeError("worker_manifest_source_mismatch")

    run_scoped_tables = [
        "capture_attempts",
        "booking_detail_snapshots",
        "booking_detail_observations",
        "page_attestations",
    ]
    if "window_rebind_audit" in tables:
        run_scoped_tables.append("window_rebind_audit")
    if any(
        int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id<>?",
                (worker.run_id,),
            ).fetchone()[0]
        )
        for table in run_scoped_tables
    ):
        raise ParallelMergeError("worker_database_contains_foreign_run_rows")

    snapshots = connection.execute(
        "SELECT * FROM booking_detail_snapshots WHERE run_id=?",
        (worker.run_id,),
    ).fetchall()
    observations = connection.execute(
        "SELECT * FROM booking_detail_observations WHERE run_id=?",
        (worker.run_id,),
    ).fetchall()
    snapshot_keys = [str(row["booking_id_sha256"]) for row in snapshots]
    observation_keys = [str(row["booking_id_sha256"]) for row in observations]
    keys = snapshot_keys + observation_keys
    if len(keys) != len(set(keys)):
        raise ParallelMergeError("worker_result_membership_not_unique")
    if any(key not in expected for key in keys):
        raise ParallelMergeError("worker_contains_noncanonical_booking")
    for row in snapshots:
        source = expected[str(row["booking_id_sha256"])]
        if not _source_booking_matches(row, source):
            raise ParallelMergeError("worker_snapshot_source_binding_invalid")
        if _sha256_text(str(row["booking_id"])) != source.booking_id_sha256:
            raise ParallelMergeError("worker_snapshot_booking_id_hash_invalid")
        snapshot_id = int(row["snapshot_id"])
        if not connection.execute(
            "SELECT EXISTS(SELECT 1 FROM price_components WHERE snapshot_id=?)",
            (snapshot_id,),
        ).fetchone()[0]:
            raise ParallelMergeError("worker_snapshot_price_components_missing")
    for row in observations:
        source = expected[str(row["booking_id_sha256"])]
        if not _source_booking_matches(row, source):
            raise ParallelMergeError("worker_observation_source_binding_invalid")
        if (
            str(row["attested_source_page_set_sha256"])
            != snapshot.source_capture_set_sha256
            or row["source_service_start_on"] != row["detail_service_start_on"]
            or row["source_service_end_on"] != row["detail_service_end_on"]
            or str(row["source_reservation_status"])
            not in TERMINAL_SOURCE_RESERVATION_STATUSES
            or str(row["reservation_status"]) != "cancelled"
            or not _terminal_kind_matches_detail_status(
                row["observation_kind"], row["detail_reservation_status"]
            )
            or int(row["gross_total_present"]) != 0
            or int(row["visible_money_value_count"]) != 0
            or int(row["amount_matching_eligible"]) != 0
            or int(row["unresolved_competitor"]) != 1
        ):
            raise ParallelMergeError("worker_observation_contract_invalid")
        attestation_id = int(row["list_attestation_id"])
        attestation = connection.execute(
            "SELECT * FROM page_attestations WHERE attestation_id=?",
            (attestation_id,),
        ).fetchone()
        if (
            attestation is None
            or str(attestation["run_id"]) != worker.run_id
            or str(attestation["tab_name"]) != "Cancelled"
            or int(attestation["page_no"]) != int(row["page_no"])
            or str(attestation["phase"]) != "before_click"
            or str(attestation["ordered_membership_sha256"])
            != str(row["attested_ordered_membership_sha256"])
            or str(attestation["set_membership_sha256"])
            != str(row["attested_set_membership_sha256"])
            or str(attestation["source_page_set_sha256"])
            != snapshot.source_capture_set_sha256
            or not _attestation_membership_is_valid(
                connection,
                attestation_id=attestation_id,
                ordered_membership_sha256=str(
                    row["attested_ordered_membership_sha256"]
                ),
                set_membership_sha256=str(
                    row["attested_set_membership_sha256"]
                ),
                expected_booking_pseudonym_hmac=source.booking_pseudonym_hmac,
                expected_list_card_sha256=source.list_card_sha256,
            )
        ):
            raise ParallelMergeError("worker_observation_attestation_invalid")

    orphan_components = int(
        connection.execute(
            "SELECT COUNT(*) FROM price_components p LEFT JOIN "
            "booking_detail_snapshots s ON s.snapshot_id=p.snapshot_id "
            "WHERE s.snapshot_id IS NULL"
        ).fetchone()[0]
    )
    orphan_events = int(
        connection.execute(
            "SELECT COUNT(*) FROM payment_events e LEFT JOIN "
            "booking_detail_snapshots s ON s.snapshot_id=e.snapshot_id "
            "WHERE s.snapshot_id IS NULL"
        ).fetchone()[0]
    )
    if orphan_components or orphan_events:
        raise ParallelMergeError("worker_child_row_orphaned")
    return set(keys), {
        "price_snapshot_count": len(snapshots),
        "terminal_no_price_count": len(observations),
    }


def _copy_worker(
    target: sqlite3.Connection,
    source: sqlite3.Connection,
    worker: WorkerInput,
    merged_run_id: str,
) -> None:
    attestation_map: dict[int, int] = {}
    for row in source.execute(
        "SELECT * FROM page_attestations WHERE run_id=? "
        "ORDER BY attestation_id",
        (worker.run_id,),
    ):
        old_id = int(row["attestation_id"])
        attestation_map[old_id] = _insert_copy(
            target,
            "page_attestations",
            row,
            omit={"attestation_id"},
            overrides={"run_id": merged_run_id},
        )
    for row in source.execute(
        "SELECT m.* FROM page_attestation_members m "
        "JOIN page_attestations a ON a.attestation_id=m.attestation_id "
        "WHERE a.run_id=? ORDER BY m.attestation_id,m.ordinal",
        (worker.run_id,),
    ):
        old_id = int(row["attestation_id"])
        if old_id not in attestation_map:
            raise ParallelMergeError("worker_attestation_member_orphaned")
        _insert_copy(
            target,
            "page_attestation_members",
            row,
            overrides={"attestation_id": attestation_map[old_id]},
        )

    for row in source.execute(
        "SELECT * FROM capture_attempts WHERE run_id=? ORDER BY attempt_id",
        (worker.run_id,),
    ):
        _insert_copy(
            target,
            "capture_attempts",
            row,
            omit={"attempt_id"},
            overrides={"run_id": merged_run_id},
        )

    snapshot_map: dict[int, int] = {}
    for row in source.execute(
        "SELECT * FROM booking_detail_snapshots WHERE run_id=? "
        "ORDER BY snapshot_id",
        (worker.run_id,),
    ):
        old_id = int(row["snapshot_id"])
        snapshot_map[old_id] = _insert_copy(
            target,
            "booking_detail_snapshots",
            row,
            omit={"snapshot_id"},
            overrides={"run_id": merged_run_id},
        )
    for row in source.execute(
        "SELECT p.* FROM price_components p "
        "JOIN booking_detail_snapshots s ON s.snapshot_id=p.snapshot_id "
        "WHERE s.run_id=? ORDER BY p.snapshot_id,p.ordinal",
        (worker.run_id,),
    ):
        old_id = int(row["snapshot_id"])
        if old_id not in snapshot_map:
            raise ParallelMergeError("worker_price_component_orphaned")
        _insert_copy(
            target,
            "price_components",
            row,
            overrides={"snapshot_id": snapshot_map[old_id]},
        )
    for row in source.execute(
        "SELECT e.* FROM payment_events e "
        "JOIN booking_detail_snapshots s ON s.snapshot_id=e.snapshot_id "
        "WHERE s.run_id=? ORDER BY e.event_id",
        (worker.run_id,),
    ):
        old_id = int(row["snapshot_id"])
        if old_id not in snapshot_map:
            raise ParallelMergeError("worker_payment_event_orphaned")
        _insert_copy(
            target,
            "payment_events",
            row,
            omit={"event_id"},
            overrides={"snapshot_id": snapshot_map[old_id]},
        )

    for row in source.execute(
        "SELECT * FROM booking_detail_observations WHERE run_id=? "
        "ORDER BY observation_id",
        (worker.run_id,),
    ):
        old_attestation_id = int(row["list_attestation_id"])
        if old_attestation_id not in attestation_map:
            raise ParallelMergeError("worker_observation_attestation_orphaned")
        _insert_copy(
            target,
            "booking_detail_observations",
            row,
            omit={"observation_id"},
            overrides={
                "run_id": merged_run_id,
                "list_attestation_id": attestation_map[old_attestation_id],
            },
        )

    if "window_rebind_audit" in _table_names(source):
        for row in source.execute(
            "SELECT * FROM window_rebind_audit WHERE run_id=? "
            "ORDER BY rebind_id",
            (worker.run_id,),
        ):
            _insert_copy(
                target,
                "window_rebind_audit",
                row,
                omit={"rebind_id"},
                overrides={"run_id": merged_run_id},
            )


def merge_parallel_work_databases(
    *,
    snapshot: SourceSnapshot,
    inputs: Sequence[WorkerInput],
    output_work_db: Path,
    run_id: str,
    app: str,
    window_id: int,
) -> dict[str, Any]:
    if (
        len(inputs) != len(EXPECTED_WORKER_LABELS)
        or {worker.label for worker in inputs} != set(EXPECTED_WORKER_LABELS)
    ):
        raise ParallelMergeError("parallel_merge_requires_exact_w01_w10_inputs")
    if len({worker.path.resolve() for worker in inputs}) != len(inputs):
        raise ParallelMergeError("worker_paths_must_be_unique")
    if len({worker.run_id for worker in inputs}) != len(inputs):
        raise ParallelMergeError("worker_run_ids_must_be_unique")
    target_path = _require_tmp(output_work_db)
    if target_path.exists() or target_path.is_symlink():
        raise ParallelMergeError("merged_work_database_already_exists")

    expected = {
        booking.booking_id_sha256: booking for booking in snapshot.bookings
    }
    input_connections: list[tuple[WorkerInput, sqlite3.Connection, str]] = []
    worker_locks = _acquire_worker_locks(inputs)
    union: set[str] = set()
    input_summaries: list[dict[str, Any]] = []
    try:
        for worker in inputs:
            before_hash = _file_sha256(worker.path)
            connection = _private_immutable(worker.path)
            input_connections.append((worker, connection, before_hash))
            keys, counts = _validate_worker(
                worker, connection, snapshot, expected, app
            )
            if union & keys:
                raise ParallelMergeError("worker_result_membership_overlaps")
            if not keys:
                raise ParallelMergeError("worker_result_membership_empty")
            union |= keys
            input_summaries.append(
                {
                    "label": worker.label,
                    "file_sha256": before_hash,
                    "result_count": len(keys),
                    **counts,
                }
            )
        if union != set(expected):
            raise ParallelMergeError("worker_result_union_not_canonical_complete")

        target_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target_path.name}.", suffix=".merge", dir=target_path.parent
        )
        os.close(fd)
        temp_path = Path(temp_name)
        temp_path.unlink()
        target = _secure_create_work_db(
            temp_path, snapshot, run_id, app, window_id
        )
        owned_publish_inode: tuple[int, int] | None = None
        publish_link_created = False
        try:
            target.execute("PRAGMA foreign_keys=ON")
            target.executescript(
                """
                CREATE TABLE parallel_merge_manifest(
                    run_id TEXT PRIMARY KEY,
                    input_count INTEGER NOT NULL,
                    input_set_sha256 TEXT NOT NULL,
                    merged_result_count INTEGER NOT NULL,
                    price_snapshot_count INTEGER NOT NULL,
                    terminal_no_price_count INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status='ready_for_final_revalidation'),
                    merged_at_utc TEXT NOT NULL
                );
                CREATE TABLE parallel_merge_inputs(
                    label TEXT PRIMARY KEY,
                    file_sha256 TEXT NOT NULL,
                    result_count INTEGER NOT NULL,
                    price_snapshot_count INTEGER NOT NULL,
                    terminal_no_price_count INTEGER NOT NULL
                );
                """
            )
            target.execute("BEGIN IMMEDIATE")
            for worker, source, _source_hash in input_connections:
                _copy_worker(target, source, worker, run_id)
            input_set_sha256 = hashlib.sha256(
                _canonical_json(
                    sorted(input_summaries, key=lambda item: item["label"])
                ).encode("utf-8")
            ).hexdigest()
            priced = int(
                target.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_snapshots WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
            )
            observed = int(
                target.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_observations WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
            )
            if priced + observed != len(snapshot.bookings):
                raise ParallelMergeError("merged_result_count_invalid")
            target.executemany(
                "INSERT INTO parallel_merge_inputs VALUES (?,?,?,?,?)",
                [
                    (
                        item["label"],
                        item["file_sha256"],
                        item["result_count"],
                        item["price_snapshot_count"],
                        item["terminal_no_price_count"],
                    )
                    for item in input_summaries
                ],
            )
            target.execute(
                "INSERT INTO parallel_merge_manifest VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    len(inputs),
                    input_set_sha256,
                    len(snapshot.bookings),
                    priced,
                    observed,
                    "ready_for_final_revalidation",
                    _utc_now(),
                ),
            )
            if target.execute("PRAGMA foreign_key_check").fetchall():
                raise ParallelMergeError("merged_foreign_key_check_failed")
            target.commit()
            target.close()
            with temp_path.open("r+b") as stream:
                os.fsync(stream.fileno())
            os.chmod(temp_path, 0o600)
            owned_stat = temp_path.stat()
            owned_publish_inode = (owned_stat.st_dev, owned_stat.st_ino)
            os.link(temp_path, target_path)
            publish_link_created = True
            _fsync_directory(target_path.parent)
            temp_path.unlink()
            _fsync_directory(target_path.parent)
            verified = _private_immutable(target_path)
            try:
                verified_count = int(
                    verified.execute(
                        "SELECT COUNT(*) FROM booking_detail_snapshots"
                    ).fetchone()[0]
                ) + int(
                    verified.execute(
                        "SELECT COUNT(*) FROM booking_detail_observations"
                    ).fetchone()[0]
                )
                if verified_count != len(snapshot.bookings):
                    raise ParallelMergeError("merged_immutable_verification_failed")
            finally:
                verified.close()
            for worker, _source, before_hash in input_connections:
                if _file_sha256(worker.path) != before_hash:
                    raise ParallelMergeError("worker_database_changed_during_merge")
            return {
                "run_id": run_id,
                "work_db": str(target_path),
                "work_db_sha256": _file_sha256(target_path),
                "input_count": len(inputs),
                "merged_result_count": len(snapshot.bookings),
                "price_snapshot_count": priced,
                "terminal_no_price_count": observed,
                "ready_for_final_revalidation": True,
                "ledger_writes": 0,
                "candidate_writes": 0,
            }
        except Exception:
            if not target is None:
                try:
                    if target.in_transaction:
                        target.rollback()
                    target.close()
                except sqlite3.Error:
                    pass
            temp_path.unlink(missing_ok=True)
            if publish_link_created and owned_publish_inode is not None:
                try:
                    current = target_path.stat()
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) == owned_publish_inode:
                        target_path.unlink()
                        _fsync_directory(target_path.parent)
            raise
    finally:
        for _worker, connection, _source_hash in input_connections:
            connection.close()
        _release_worker_locks(worker_locks)


def merge_from_paths(
    *,
    source_db: Path,
    hmac_key_file: Path,
    inputs: Sequence[WorkerInput],
    output_work_db: Path,
    run_id: str,
    app: str,
    window_id: int,
) -> dict[str, Any]:
    snapshot = _load_source_snapshot(source_db, hmac_key_file)
    return merge_parallel_work_databases(
        snapshot=snapshot,
        inputs=inputs,
        output_work_db=output_work_db,
        run_id=run_id,
        app=app,
        window_id=window_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--input", action="append", type=_worker_input, required=True)
    parser.add_argument("--work-db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--app", default="msedge")
    parser.add_argument("--window-id", type=int, required=True)
    args = parser.parse_args()
    result = merge_from_paths(
        source_db=args.source_db,
        hmac_key_file=args.hmac_key_file,
        inputs=args.input,
        output_work_db=args.work_db,
        run_id=args.run_id,
        app=args.app,
        window_id=args.window_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
