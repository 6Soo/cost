from __future__ import annotations

import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledger.domain.direct_projection import (
    PARSER_BUNDLE_VERSION,
    REPOSITORY_ROOT,
    _apply_schema,
    _key_set_sha256,
    _manual_keys,
    _ota_keys,
    build_direct_candidate,
    build_source_inventory,
    candidate_semantic_snapshot,
    code_bundle_descriptor,
    project_card_payments,
)
from ledger.domain.ledger_db import initialize
from ledger.domain.p07_manifest import verify_run_artifacts
from ledger.domain.transition_gates_v2 import GATE_NAMES


class DirectProjectionTest(unittest.TestCase):
    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        initialize(db)
        _apply_schema(db)
        db.execute(
            """
            INSERT INTO direct_projection_runs(
                run_id, status, schema_version, input_manifest_sha256,
                code_commit, code_bundle_sha256
            ) VALUES ('run', 'building', 'p07-direct-v2', 'input', 'commit', 'bundle')
            """
        )
        return db

    def _insert_card(
        self,
        db: sqlite3.Connection,
        *,
        source_key: str = "HAN:G:7",
        event_id: str = "event-1",
        event_role: str = "single",
        amount: int = 100,
        transaction_type: str = "purchase",
    ) -> int:
        db.execute(
            """
            INSERT INTO direct_source_records(
                source_kind, source_key, source_sha256, payload_json
            ) VALUES ('card_raw', ?, 'source-hash', '{}')
            """,
            (source_key,),
        )
        source_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            """
            INSERT INTO direct_card_events(
                source_record_id, card_event_id, generator_version,
                identity_status, source_system, amount_krw,
                approval_number, occurred_on, merchant
            ) VALUES (?, ?, 'test-v1', 'unique', 'HAN', ?, '1234',
                      '2026-04-01', 'merchant')
            """,
            (source_id, event_id, amount),
        )
        db.execute(
            """
            INSERT INTO direct_normalized_payments(
                source_record_id, event_role, card_event_id, amount_krw,
                transaction_type, normalization_version
            ) VALUES (?, ?, ?, ?, ?, 'test-v1')
            """,
            (
                source_id,
                event_role,
                event_id,
                amount,
                transaction_type,
            ),
        )
        return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

    def test_source_inventory_covers_seven_physical_inputs_and_real_keys(self) -> None:
        inventory = build_source_inventory(Path("ledger"))
        self.assertEqual(len(inventory), 7)
        counts = {
            str(item["source_kind"]): int(item["record_count"])
            for item in inventory
        }
        self.assertEqual(
            counts,
            {
                "card_raw:A_20260720": 174,
                "card_raw:E": 1679,
                "card_raw:F": 1287,
                "card_raw:G": 221,
                "card_raw:H": 1876,
                "manual_ledger": 1379,
                "ota_mail": 1720,
            },
        )
        self.assertTrue(
            all(
                item["lf_sha256"] is None
                for item in inventory
                if str(item["relative_path"]).endswith(".xlsx")
            )
        )
        self.assertTrue(
            all(item["parser_version"] == PARSER_BUNDLE_VERSION for item in inventory)
        )

    def test_empty_manual_and_ota_inputs_fail_semantic_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            manual = root / "manual.csv"
            manual.write_text("tab,row\n", encoding="utf-8")
            ota = root / "ota.json"
            ota.write_text('{"records":[]}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manual_source_empty"):
                _manual_keys(manual)
            with self.assertRaisesRegex(ValueError, "ota_source_empty"):
                _ota_keys(ota)

    def test_equal_count_source_loss_changes_key_set_hash(self) -> None:
        before = _key_set_sha256(["a", "b"])
        after = _key_set_sha256(["a", "c"])
        self.assertNotEqual(before, after)

    def test_projection_preserves_business_fields_and_excludes_run_id(self) -> None:
        external_keys: list[str] = []
        semantics: list[str] = []
        for run_id in ("run-a", "run-b"):
            db = sqlite3.connect(":memory:")
            db.row_factory = sqlite3.Row
            initialize(db)
            _apply_schema(db)
            db.execute(
                """
                INSERT INTO direct_projection_runs(
                    run_id, status, schema_version, input_manifest_sha256,
                    code_commit, code_bundle_sha256
                ) VALUES (?, 'building', 'p07-direct-v2', 'i', 'c', 'b')
                """,
                (run_id,),
            )
            self._insert_card(db)
            self.assertEqual(project_card_payments(db, run_id), 1)
            row = db.execute(
                """
                SELECT external_key, source_system, occurred_on, merchant,
                       approval_number
                FROM payment_transactions
                """
            ).fetchone()
            external_keys.append(str(row["external_key"]))
            semantics.append(candidate_semantic_snapshot(db, run_id))
            self.assertEqual(
                tuple(row)[1:],
                ("HAN", "2026-04-01", "merchant", "1234"),
            )
            db.close()
        self.assertEqual(external_keys[0], external_keys[1])
        self.assertEqual(semantics[0], semantics[1])
        self.assertNotIn("run-a", external_keys[0])

    def test_manual_and_ota_sources_never_create_candidate_payments(self) -> None:
        db = self._db()
        for kind in ("manual_ledger", "ota_mail"):
            db.execute(
                """
                INSERT INTO direct_source_records(
                    source_kind, source_key, source_sha256, payload_json
                ) VALUES (?, ?, 'hash', '{}')
                """,
                (kind, f"{kind}:1"),
            )
        self._insert_card(db)
        self.assertEqual(project_card_payments(db, "run"), 1)
        self.assertEqual(
            int(db.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0]),
            1,
        )
        db.close()

    def test_projection_links_reject_one_to_many_and_many_to_one(self) -> None:
        db = self._db()
        direct_one = self._insert_card(db, source_key="HAN:G:1", event_id="e1")
        direct_two = self._insert_card(db, source_key="HAN:G:2", event_id="e2")
        for key in ("p1", "p2"):
            db.execute(
                """
                INSERT INTO payment_transactions(
                    external_key, source_event_id, identity_fingerprint,
                    source_system, amount_krw, transaction_type
                ) VALUES (?, ?, ?, 'HAN', 1, 'purchase')
                """,
                (key, key, key),
            )
        payment_one, payment_two = [
            int(row[0])
            for row in db.execute("SELECT id FROM payment_transactions ORDER BY id")
        ]
        db.execute(
            """
            INSERT INTO direct_payment_projection_links
            VALUES ('run', ?, ?)
            """,
            (direct_one, payment_one),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO direct_payment_projection_links
                VALUES ('run', ?, ?)
                """,
                (direct_one, payment_two),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO direct_payment_projection_links
                VALUES ('run', ?, ?)
                """,
                (direct_two, payment_one),
            )
        db.close()

    def test_business_mutation_changes_candidate_semantic_hash(self) -> None:
        db = self._db()
        self._insert_card(db)
        project_card_payments(db, "run")
        before = candidate_semantic_snapshot(db, "run")
        db.execute("UPDATE payment_transactions SET amount_krw=amount_krw+1")
        after = candidate_semantic_snapshot(db, "run")
        self.assertNotEqual(before, after)
        db.close()

    def test_existing_destination_and_output_directory_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            destination = root / "candidate.db"
            destination.write_bytes(b"keep")
            with self.assertRaisesRegex(FileExistsError, "destination_exists"):
                build_direct_candidate(
                    destination,
                    Path("ledger"),
                    output_dir=root / "reports",
                )
            self.assertEqual(destination.read_bytes(), b"keep")

    def test_candidate_outputs_inside_repository_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "candidate_output_inside_repository"):
            build_direct_candidate(
                REPOSITORY_ROOT / ".p07-forbidden-candidate.db",
                Path("ledger"),
                output_dir=Path(tempfile.gettempdir()) / "unused-p07-reports",
            )

    def test_mid_import_exception_never_publishes_partial_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            destination = root / "candidate.db"
            reports = root / "reports"
            with patch(
                "ledger.domain.direct_projection.import_all",
                side_effect=RuntimeError("manual_parser_failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "manual_parser_failure"):
                    build_direct_candidate(
                        destination,
                        Path("ledger"),
                        output_dir=reports,
                    )
            self.assertFalse(destination.exists())
            self.assertFalse(reports.exists())
            self.assertEqual(list(root.glob(".*-candidate-*.db*")), [])

    def test_pass_path_report_failure_rolls_back_building_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            destination = root / "candidate.db"
            reports = root / "reports"
            passing_report = {
                "format_version": 2,
                "run_id": "mocked",
                "passed": True,
                "gates": [
                    {
                        "gate": number,
                        "name": f"gate-{number}",
                        "passed": True,
                        "reason": "ok",
                        "actual": {},
                    }
                    for number in range(1, 8)
                ],
                "cutover_policy": "candidate_ready_for_shadow",
            }
            with (
                patch(
                    "ledger.domain.direct_projection.build_gate_report",
                    return_value=passing_report,
                ),
                patch(
                    "ledger.domain.direct_projection._write_artifact_directory",
                    side_effect=OSError("report_publish_failure"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "report_publish_failure"):
                    build_direct_candidate(
                        destination,
                        Path("ledger"),
                        output_dir=reports,
                    )
            self.assertFalse(destination.exists())
            self.assertFalse(reports.exists())

    def test_pass_path_activates_candidate_after_report_publication(self) -> None:
        from ledger.domain import direct_projection as module

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            destination = root / "candidate.db"
            reports = root / "reports"
            passing_report = {
                "format_version": 2,
                "run_id": "mocked",
                "passed": True,
                "gates": [
                    {
                        "gate": number,
                        "name": f"gate-{number}",
                        "passed": True,
                        "reason": "ok",
                        "actual": {},
                    }
                    for number in range(1, 8)
                ],
                "cutover_policy": "candidate_ready_for_shadow",
            }
            original_publish = module._write_artifact_directory
            observed_status: list[str] = []

            def inspect_then_publish(*args: object, **kwargs: object) -> Path:
                check = sqlite3.connect(destination)
                observed_status.append(
                    str(
                        check.execute(
                            "SELECT status FROM direct_projection_runs"
                        ).fetchone()[0]
                    )
                )
                check.close()
                return original_publish(*args, **kwargs)

            with (
                patch(
                    "ledger.domain.direct_projection.build_gate_report",
                    return_value=passing_report,
                ),
                patch(
                    "ledger.domain.direct_projection._write_artifact_directory",
                    side_effect=inspect_then_publish,
                ),
            ):
                result = build_direct_candidate(
                    destination,
                    Path("ledger"),
                    output_dir=reports,
                )
            self.assertTrue(result["passed"])
            self.assertEqual(observed_status, ["building"])
            check = sqlite3.connect(destination)
            self.assertEqual(
                check.execute(
                    "SELECT status FROM direct_projection_runs"
                ).fetchone()[0],
                "passed",
            )
            self.assertEqual(
                check.execute(
                    "SELECT COUNT(*) FROM direct_candidate_payments"
                ).fetchone()[0],
                5328,
            )
            check.close()
            manifest_path = next(
                reports.glob("*/blocker_manifest.json")
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["artifact_state"],
                "candidate_ready_for_shadow",
            )

    def test_passed_candidate_business_mutation_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            destination = root / "candidate.db"
            reports = root / "reports"

            def passing_report(
                _database: Path,
                run_id: str,
                **kwargs: object,
            ) -> dict[str, object]:
                expected = dict(kwargs["expected_provenance"])
                comparators = list(kwargs["historical_comparators"])
                gates = []
                for number, name in enumerate(GATE_NAMES, start=1):
                    actual: dict[str, object] = {}
                    if name == "allocation_and_decision_completeness":
                        actual["candidate_payment_count"] = 5328
                    elif name == "semantic_regression":
                        actual = {
                            "approvals_provided": 0,
                            "approval_mode": "none",
                            "diagnostic_comparators": comparators,
                        }
                    gates.append(
                        {
                            "gate": number,
                            "name": name,
                            "passed": True,
                            "reason": "ok",
                            "actual": actual,
                        }
                    )
                return {
                    "format_version": 2,
                    "run_id": run_id,
                    **expected,
                    "passed": True,
                    "gates": gates,
                    "cutover_policy": "candidate_ready_for_shadow",
                }

            with patch(
                "ledger.domain.direct_projection.build_gate_report",
                side_effect=passing_report,
            ):
                result = build_direct_candidate(
                    destination,
                    Path("ledger"),
                    output_dir=reports,
                )
            report_dir = Path(str(result["report_dir"]))
            verify_run_artifacts(
                report_dir,
                repository_root=REPOSITORY_ROOT,
            )
            candidate = sqlite3.connect(destination)
            candidate.execute(
                """
                UPDATE payment_transactions
                SET amount_krw=amount_krw+999999
                WHERE id=(SELECT MIN(id) FROM payment_transactions)
                """
            )
            candidate.commit()
            candidate.close()
            with self.assertRaisesRegex(
                ValueError,
                "candidate_db_semantic_content_mismatch",
            ):
                verify_run_artifacts(
                    report_dir,
                    repository_root=REPOSITORY_ROOT,
                )

    def test_legacy_import_spy_is_never_called_by_real_direct_build(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            with patch(
                "ledger.domain.ledger_db.import_legacy",
                side_effect=AssertionError("legacy_import_called"),
            ):
                result = build_direct_candidate(
                    root / "candidate.db",
                    Path("ledger"),
                    output_dir=root / "reports",
                )
            self.assertFalse(result["passed"])
            self.assertFalse((root / "candidate.db").exists())

    def test_artifact_verifier_rejects_manifest_inventory_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            result = build_direct_candidate(
                root / "candidate.db",
                Path("ledger"),
                output_dir=root / "reports",
            )
            report_dir = Path(str(result["report_dir"]))
            manifest_path = report_dir / "blocker_manifest.json"
            original = json.loads(manifest_path.read_text(encoding="utf-8"))
            verify_run_artifacts(
                report_dir,
                repository_root=REPOSITORY_ROOT,
            )

            tampered_input = json.loads(json.dumps(original))
            tampered_input["inputs"][0]["record_count"] += 1
            manifest_path.write_text(
                json.dumps(tampered_input),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "manifest_input_hash_mismatch",
            ):
                verify_run_artifacts(
                    report_dir,
                    repository_root=REPOSITORY_ROOT,
                )

            tampered_bundle = json.loads(json.dumps(original))
            tampered_bundle["code_bundle"][0]["raw_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(tampered_bundle),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "manifest_code_file_hash_mismatch",
            ):
                verify_run_artifacts(
                    report_dir,
                    repository_root=REPOSITORY_ROOT,
                )

            tampered_state = json.loads(json.dumps(original))
            tampered_state["artifact_state"] = "candidate_ready_for_shadow"
            tampered_state["approved_transitions"] = {
                "provided": 999,
                "mode": "event_level",
            }
            manifest_path.write_text(
                json.dumps(tampered_state),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "manifest_artifact_state_mismatch",
            ):
                verify_run_artifacts(
                    report_dir,
                    repository_root=REPOSITORY_ROOT,
                )

            tampered_approvals = json.loads(json.dumps(original))
            tampered_approvals["approved_transitions"] = {
                "provided": 999,
                "mode": "event_level",
            }
            manifest_path.write_text(
                json.dumps(tampered_approvals),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "manifest_approval_summary_mismatch",
            ):
                verify_run_artifacts(
                    report_dir,
                    repository_root=REPOSITORY_ROOT,
                )

    def test_bogus_commit_fails_before_database_creation(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            with self.assertRaisesRegex(ValueError, "code_commit_mismatch"):
                build_direct_candidate(
                    root / "candidate.db",
                    Path("ledger"),
                    output_dir=root / "reports",
                    code_commit="0" * 40,
                )
            self.assertFalse((root / "candidate.db").exists())
            self.assertFalse((root / "reports").exists())

    def test_code_bundle_records_runtime_dependencies(self) -> None:
        descriptor = code_bundle_descriptor(REPOSITORY_ROOT)
        paths = {
            str(item["relative_path"]) for item in descriptor["files"]
        }
        self.assertIn("ledger/domain/direct_sources.py", paths)
        self.assertIn("ledger/domain/schema.sql", paths)
        self.assertIn("ledger/domain/p07_manifest.py", paths)
        self.assertEqual(len(str(descriptor["code_bundle_sha256"])), 64)


if __name__ == "__main__":
    unittest.main()
