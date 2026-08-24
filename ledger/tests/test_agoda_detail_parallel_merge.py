from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _connect(path: Path | str) -> contextlib.AbstractContextManager[sqlite3.Connection]:
    return contextlib.closing(sqlite3.connect(path))

try:
    import tools.agoda_detail_parallel_merge as merge_module
    from tools.agoda_detail_parallel_merge import (
        ParallelMergeError,
        WorkerInput,
        merge_parallel_work_databases,
    )
    from tools.agoda_portal_detail_capture import (
        SourceBooking,
        SourceSnapshot,
        _browser_lock_path,
        _canonical_json,
        _file_sha256,
        _secure_create_work_db,
        _sha256_text,
    )

    _IMPORT_ERROR = None
except ImportError as _e:  # retired portal capture (92288ba)
    _IMPORT_ERROR = str(_e)
    merge_module = None  # type: ignore[assignment]


def booking(
    value: str,
    *,
    tab: str = "Completed",
    position: int = 1,
) -> SourceBooking:
    booking_hash = _sha256_text(value)
    return SourceBooking(
        page_no=1,
        booking_id=value,
        booking_id_sha256=booking_hash,
        service_start_on="2026-05-01",
        service_end_on="2026-05-02",
        reservation_status=tab,
        list_card_sha256=_sha256_text(f"semantic:{value}"),
        tab_name=tab,
        card_position=position,
        booking_pseudonym_hmac=_sha256_text(f"pseudonym:{value}"),
        source_scope_status="target_2026_overlap",
    )


def snapshot(source_path: Path, bookings: tuple[SourceBooking, ...]) -> SourceSnapshot:
    source_path.write_bytes(b"canonical-source")
    ordered = _sha256_text(
        _canonical_json([item.membership_tuple() for item in bookings])
    )
    membership_set = _sha256_text(
        _canonical_json(sorted(item.membership_tuple() for item in bookings))
    )
    return SourceSnapshot(
        path=source_path,
        file_sha256=_file_sha256(source_path),
        source_run_id="source-run",
        source_capture_set_sha256="c" * 64,
        membership_ordered_sha256=ordered,
        membership_set_sha256=membership_set,
        bookings=bookings,
        page_manifest={},
        population_count=len(bookings),
        pseudonym_key_id="key",
        all_booking_semantics=tuple(
            (item.booking_pseudonym_hmac, item.list_card_sha256)
            for item in bookings
        ),
        tab_totals=tuple(
            (tab, sum(item.tab_name == tab for item in bookings))
            for tab in ("Upcoming", "Completed", "Cancelled")
        ),
        target_2026_count=len(bookings),
        competitor_count=0,
    )


def add_price_snapshot(
    connection: sqlite3.Connection,
    run_id: str,
    item: SourceBooking,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO booking_detail_snapshots(
            run_id,booking_id,booking_id_sha256,booking_pseudonym_hmac,
            tab_name,page_no,card_position,list_card_sha256,
            source_service_start_on,source_service_end_on,
            source_scope_status,source_reservation_status,
            detail_service_start_on,detail_service_end_on,detail_scope_status,
            room_count,nights,reservation_status,payment_status,
            collection_model,refund_status,payment_schedule_json,has_local_tax,
            card_type,card4,card4_sha256,card_role,semantic_detail_sha256,
            snapshot_version,captured_at_utc
        ) VALUES(
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,'completed','paid',
            'agoda_collect','none_displayed','[]',0,
            'MasterCard','3820',?,'charged',?,1,'now'
        )
        """,
        (
            run_id,
            item.booking_id,
            item.booking_id_sha256,
            item.booking_pseudonym_hmac,
            item.tab_name,
            item.page_no,
            item.card_position,
            item.list_card_sha256,
            item.service_start_on,
            item.service_end_on,
            item.source_scope_status,
            item.reservation_status,
            item.service_start_on,
            item.service_end_on,
            item.source_scope_status,
            _sha256_text("3820"),
            _sha256_text(f"detail:{item.booking_id}"),
        ),
    )
    snapshot_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO price_components(
            snapshot_id,ordinal,component_kind,label_normalized,currency,
            amount_decimal_text,amount_minor_units,currency_scale
        ) VALUES (?,1,'gross_total','Total Charge','JPY','86411',86411,0)
        """,
        (snapshot_id,),
    )
    connection.execute(
        """
        INSERT INTO payment_events(
            snapshot_id,event_kind,event_on,currency,amount_decimal_text,
            amount_minor_units,currency_scale,card4_sha256,evidence_label
        ) VALUES(?,'charge','2026-01-01','JPY','86411',86411,0,?,'Paid Today')
        """,
        (snapshot_id, _sha256_text("3820")),
    )
    return snapshot_id


def add_terminal_observation(
    connection: sqlite3.Connection,
    run_id: str,
    item: SourceBooking,
    *,
    detail_status: str = "unknown",
    observation_kind: str = "price_evidence_not_displayed",
) -> None:
    member_hash = _sha256_text(
        _canonical_json([item.booking_pseudonym_hmac])
    )
    cursor = connection.execute(
        """
        INSERT INTO page_attestations(
            run_id,tab_name,page_no,phase,expected_selected_page,
            observed_selected_page,ordered_membership_sha256,
            set_membership_sha256,source_page_set_sha256,observed_at_utc
        ) VALUES(?,'Cancelled',1,'before_click',1,1,?,?,?,'now')
        """,
        (run_id, member_hash, member_hash, "c" * 64),
    )
    attestation_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO page_attestation_members(
            attestation_id,ordinal,booking_pseudonym_hmac,list_card_sha256
        ) VALUES(?,1,?,?)
        """,
        (attestation_id, item.booking_pseudonym_hmac, item.list_card_sha256),
    )
    connection.execute(
        """
        INSERT INTO booking_detail_observations(
            run_id,booking_id_sha256,booking_pseudonym_hmac,
            tab_name,page_no,card_position,list_card_sha256,list_attestation_id,
            attested_ordered_membership_sha256,
            attested_set_membership_sha256,attested_source_page_set_sha256,
            source_service_start_on,source_service_end_on,
            source_scope_status,source_reservation_status,
            detail_service_start_on,detail_service_end_on,detail_scope_status,
            reservation_status,detail_reservation_status,payment_status,
            collection_model,refund_status,observation_kind,
            payment_information_present,gross_total_present,
            visible_money_value_count,card_type,card4,card4_sha256,card_role,
            amount_matching_eligible,unresolved_competitor,
            semantic_detail_sha256,observed_at_utc
        ) VALUES(
            ?,?,?,'Cancelled',1,1,?,?, ?,?,?, ?,?,?,'Cancelled',
            ?,?,?,'cancelled',?,'unknown','unknown','unknown',
            ?,0,0,0,NULL,NULL,NULL,'unavailable',
            0,1,?,'now'
        )
        """,
        (
            run_id,
            item.booking_id_sha256,
            item.booking_pseudonym_hmac,
            item.list_card_sha256,
            attestation_id,
            member_hash,
            member_hash,
            "c" * 64,
            item.service_start_on,
            item.service_end_on,
            item.source_scope_status,
            item.service_start_on,
            item.service_end_on,
            item.source_scope_status,
            detail_status,
            observation_kind,
            _sha256_text(f"terminal:{item.booking_id}"),
        ),
    )


def worker_db(
    path: Path,
    source_snapshot: SourceSnapshot,
    run_id: str,
    results: tuple[SourceBooking, ...],
) -> None:
    connection = _secure_create_work_db(
        path, source_snapshot, run_id, "msedge", 100
    )
    for item in results:
        if item.tab_name == "Cancelled":
            add_terminal_observation(connection, run_id, item)
        else:
            add_price_snapshot(connection, run_id, item)
    connection.commit()
    connection.close()
    os.chmod(path, 0o600)


def ten_booking_population(
    *, cancelled_indexes: frozenset[int] = frozenset()
) -> tuple[SourceBooking, ...]:
    return tuple(
        booking(
            str(1700000000 + index),
            tab="Cancelled" if index in cancelled_indexes else "Completed",
            position=index,
        )
        for index in range(1, 11)
    )


def ten_worker_inputs(
    root: Path,
    source_snapshot: SourceSnapshot,
    *,
    assignments: dict[str, tuple[SourceBooking, ...]] | None = None,
) -> tuple[WorkerInput, ...]:
    inputs: list[WorkerInput] = []
    for index, item in enumerate(source_snapshot.bookings, start=1):
        label = f"W{index:02d}"
        run_id = f"run-{label.lower()}"
        path = root / f"{label.lower()}.sqlite"
        results = (
            assignments[label]
            if assignments is not None and label in assignments
            else (item,)
        )
        worker_db(path, source_snapshot, run_id, results)
        inputs.append(WorkerInput(label, path, run_id))
    return tuple(inputs)


@unittest.skipIf(_IMPORT_ERROR is not None, f"retired tool missing: {_IMPORT_ERROR}")
class AgodaDetailParallelMergeTests(unittest.TestCase):
    def test_exact_disjoint_union_preserves_relational_graph(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            output = root / "merged.sqlite"

            result = merge_parallel_work_databases(
                snapshot=source_snapshot,
                inputs=inputs,
                output_work_db=output,
                run_id="merged",
                app="msedge",
                window_id=200,
            )
            self.assertEqual(result["merged_result_count"], 10)
            self.assertEqual(result["price_snapshot_count"], 10)
            if os.name != "nt":
                self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            with _connect(output) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM booking_detail_snapshots"
                    ).fetchone()[0],
                    10,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM price_components"
                    ).fetchone()[0],
                    10,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM payment_events"
                    ).fetchone()[0],
                    10,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM parallel_merge_manifest"
                    ).fetchone()[0],
                    "ready_for_final_revalidation",
                )

    def test_terminal_observation_attestation_ids_are_remapped(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite",
                ten_booking_population(cancelled_indexes=frozenset({2})),
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            output = root / "merged.sqlite"

            result = merge_parallel_work_databases(
                snapshot=source_snapshot,
                inputs=inputs,
                output_work_db=output,
                run_id="merged",
                app="msedge",
                window_id=200,
            )
            self.assertEqual(result["terminal_no_price_count"], 1)
            with _connect(output) as connection:
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM booking_detail_observations o
                        JOIN page_attestations a
                          ON a.attestation_id=o.list_attestation_id
                        JOIN page_attestation_members m
                          ON m.attestation_id=a.attestation_id
                         AND m.booking_pseudonym_hmac=o.booking_pseudonym_hmac
                         AND m.list_card_sha256=o.list_card_sha256
                        WHERE o.run_id='merged' AND a.run_id='merged'
                        """
                    ).fetchone()[0],
                    1,
                )

    def test_status_conflict_terminal_observation_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite",
                ten_booking_population(cancelled_indexes=frozenset({2})),
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            with _connect(inputs[1].path) as connection:
                connection.execute(
                    "UPDATE booking_detail_observations "
                    "SET observation_kind=?,detail_reservation_status='completed'",
                    ("cancelled_list_detail_status_conflict_no_price",),
                )
                connection.commit()
            output = root / "merged.sqlite"
            result = merge_parallel_work_databases(
                snapshot=source_snapshot,
                inputs=inputs,
                output_work_db=output,
                run_id="merged",
                app="msedge",
                window_id=200,
            )
            self.assertEqual(result["terminal_no_price_count"], 1)
            with _connect(output) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT observation_kind,detail_reservation_status "
                        "FROM booking_detail_observations"
                    ).fetchone(),
                    (
                        "cancelled_list_detail_status_conflict_no_price",
                        "completed",
                    ),
                )

    def test_duplicate_membership_fails_without_output(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            population = ten_booking_population()
            source_snapshot = snapshot(root / "source.sqlite", population)
            inputs = ten_worker_inputs(
                root,
                source_snapshot,
                assignments={"W02": (population[0], population[1])},
            )
            output = root / "merged.sqlite"
            with self.assertRaisesRegex(
                ParallelMergeError, "membership_overlaps"
            ):
                merge_parallel_work_databases(
                    snapshot=source_snapshot,
                    inputs=inputs,
                    output_work_db=output,
                    run_id="merged",
                    app="msedge",
                    window_id=200,
                )
            self.assertFalse(output.exists())

    def test_missing_canonical_member_fails_without_output(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(
                root, source_snapshot, assignments={"W10": ()}
            )
            output = root / "merged.sqlite"
            with self.assertRaisesRegex(
                ParallelMergeError, "membership_empty"
            ):
                merge_parallel_work_databases(
                    snapshot=source_snapshot,
                    inputs=inputs,
                    output_work_db=output,
                    run_id="merged",
                    app="msedge",
                    window_id=200,
                )
            self.assertFalse(output.exists())

    def test_orphan_child_fails_without_output(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            output = root / "merged.sqlite"
            with _connect(inputs[1].path) as connection:
                connection.execute(
                    """
                    INSERT INTO price_components(
                        snapshot_id,ordinal,component_kind,label_normalized,
                        currency,amount_decimal_text,amount_minor_units,currency_scale
                    ) VALUES(999,1,'gross_total','Total Charge','JPY','1',1,0)
                    """
                )
                connection.commit()
            with self.assertRaisesRegex(ParallelMergeError, "child_row_orphaned"):
                merge_parallel_work_databases(
                    snapshot=source_snapshot,
                    inputs=inputs,
                    output_work_db=output,
                    run_id="merged",
                    app="msedge",
                    window_id=200,
                )
            self.assertFalse(output.exists())

    def test_source_semantic_mismatch_fails_without_output(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            output = root / "merged.sqlite"
            with _connect(inputs[1].path) as connection:
                connection.execute(
                    "UPDATE booking_detail_snapshots SET list_card_sha256=?",
                    ("x" * 64,),
                )
                connection.commit()
            with self.assertRaisesRegex(
                ParallelMergeError, "snapshot_source_binding_invalid"
            ):
                merge_parallel_work_databases(
                    snapshot=source_snapshot,
                    inputs=inputs,
                    output_work_db=output,
                    run_id="merged",
                    app="msedge",
                    window_id=200,
                )
            self.assertFalse(output.exists())

    def test_requires_exact_ten_worker_labels(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            for invalid in (
                inputs[:-1],
                inputs + (WorkerInput("W11", root / "w11.sqlite", "run-w11"),),
            ):
                with self.subTest(input_count=len(invalid)):
                    output = root / f"merged-{len(invalid)}.sqlite"
                    with self.assertRaisesRegex(
                        ParallelMergeError, "exact_w01_w10"
                    ):
                        merge_parallel_work_databases(
                            snapshot=source_snapshot,
                            inputs=invalid,
                            output_work_db=output,
                            run_id="merged",
                            app="msedge",
                            window_id=200,
                        )
                    self.assertFalse(output.exists())

    def test_capture_sentinel_closes_writer_race_and_cleans_partial_locks(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            blocked = inputs[4]
            blocked_lock = _browser_lock_path(
                blocked.path.resolve(), blocked.run_id
            )
            descriptor = os.open(
                blocked_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            try:
                output = root / "merged.sqlite"
                with self.assertRaisesRegex(
                    ParallelMergeError, "active_or_stale_writer_lock"
                ):
                    merge_parallel_work_databases(
                        snapshot=source_snapshot,
                        inputs=inputs,
                        output_work_db=output,
                        run_id="merged",
                        app="msedge",
                        window_id=200,
                    )
                self.assertFalse(output.exists())
                self.assertTrue(blocked_lock.exists())
                for worker in inputs[:4]:
                    self.assertFalse(
                        _browser_lock_path(
                            worker.path.resolve(), worker.run_id
                        ).exists()
                    )
            finally:
                os.close(descriptor)
                blocked_lock.unlink(missing_ok=True)

    def test_manifest_fields_are_exactly_bound_to_source(self) -> None:
        mutations = (
            ("source_population_count", 999),
            ("pseudonym_key_id", "other-key"),
            ("app_name", "other-browser"),
        )
        for field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory(
                dir="/tmp"
            ) as directory:
                root = Path(directory)
                source_snapshot = snapshot(
                    root / "source.sqlite", ten_booking_population()
                )
                inputs = ten_worker_inputs(root, source_snapshot)
                with _connect(inputs[0].path) as connection:
                    connection.execute(
                        f"UPDATE capture_run_manifest SET {field}=?",
                        (value,),
                    )
                    connection.commit()
                output = root / "merged.sqlite"
                with self.assertRaisesRegex(
                    ParallelMergeError, "manifest_source_mismatch"
                ):
                    merge_parallel_work_databases(
                        snapshot=source_snapshot,
                        inputs=inputs,
                        output_work_db=output,
                        run_id="merged",
                        app="msedge",
                        window_id=200,
                    )
                self.assertFalse(output.exists())

    def test_foreign_run_snapshot_is_rejected_before_copy(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            with _connect(inputs[0].path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    "SELECT * FROM booking_detail_snapshots LIMIT 1"
                ).fetchone()
                columns = [
                    column for column in row.keys() if column != "snapshot_id"
                ]
                values = [row[column] for column in columns]
                values[columns.index("run_id")] = "foreign-run"
                values[columns.index("semantic_detail_sha256")] = "x" * 64
                values[columns.index("snapshot_version")] = 2
                connection.execute(
                    f"INSERT INTO booking_detail_snapshots({','.join(columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)})",
                    values,
                )
                connection.commit()
            output = root / "merged.sqlite"
            with self.assertRaisesRegex(
                ParallelMergeError, "foreign_run_rows"
            ):
                merge_parallel_work_databases(
                    snapshot=source_snapshot,
                    inputs=inputs,
                    output_work_db=output,
                    run_id="merged",
                    app="msedge",
                    window_id=200,
                )
            self.assertFalse(output.exists())

    def test_failure_after_hardlink_removes_owned_output(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            output = root / "merged.sqlite"
            original_fsync_directory = merge_module._fsync_directory
            calls = 0

            def fail_first_directory_sync(path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("injected_post_link_failure")
                original_fsync_directory(path)

            with patch.object(
                merge_module,
                "_fsync_directory",
                side_effect=fail_first_directory_sync,
            ):
                with self.assertRaisesRegex(
                    OSError, "injected_post_link_failure"
                ):
                    merge_parallel_work_databases(
                        snapshot=source_snapshot,
                        inputs=inputs,
                        output_work_db=output,
                        run_id="merged",
                        app="msedge",
                        window_id=200,
                    )
            self.assertFalse(output.exists())
            for worker in inputs:
                self.assertFalse(
                    _browser_lock_path(
                        worker.path.resolve(), worker.run_id
                    ).exists()
                )

    def test_mid_merge_failure_never_publishes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source_snapshot = snapshot(
                root / "source.sqlite", ten_booking_population()
            )
            inputs = ten_worker_inputs(root, source_snapshot)
            output = root / "merged.sqlite"
            original = merge_module._copy_worker
            call_count = 0

            def fail_second(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise ParallelMergeError("injected_mid_merge_failure")
                return original(*args, **kwargs)

            with patch.object(merge_module, "_copy_worker", side_effect=fail_second):
                with self.assertRaisesRegex(
                    ParallelMergeError, "injected_mid_merge_failure"
                ):
                    merge_parallel_work_databases(
                        snapshot=source_snapshot,
                        inputs=inputs,
                        output_work_db=output,
                        run_id="merged",
                        app="msedge",
                        window_id=200,
                    )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
