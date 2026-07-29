from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_projection import (
    _apply_schema,
    project_card_payments,
)
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.transition_gates_v2 import (
    PARSER_BUNDLE_VERSION,
    REQUIRED_INPUTS,
    SCHEMA_VERSION,
    _key_set_sha256,
    build_gate_report,
    candidate_semantic_sha256,
    gate_report_sha256,
    input_manifest_sha256,
    validate_approved_transitions,
)


class DirectTransitionGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def _raw_sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _fixture(
        self,
    ) -> tuple[Path, str, dict[str, object], Path]:
        database = self.root / "candidate.db"
        db = connect(database)
        initialize(db)
        _apply_schema(db)

        inventory: list[dict[str, object]] = []
        source_rows: list[tuple[dict[str, object], str]] = []
        for index, spec in enumerate(REQUIRED_INPUTS):
            relative = Path(str(spec["relative_path"]))
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = f"fixture-{spec['source_kind']}\n".encode()
            path.write_bytes(raw)
            prefix = spec["record_prefix"]
            source_key = (
                f"{prefix}1"
                if prefix is not None
                else "manual:1"
                if spec["db_source_kind"] == "manual_ledger"
                else "ota:1"
            )
            lf_hash = None
            if path.suffix.lower() != ".xlsx":
                lf_hash = self._raw_sha(raw)
            inventory.append(
                {
                    "source_kind": spec["source_kind"],
                    "relative_path": relative.as_posix(),
                    "raw_sha256": self._raw_sha(raw),
                    "lf_sha256": lf_hash,
                    "byte_count": len(raw),
                    "key_set_sha256": _key_set_sha256([source_key]),
                    "record_count": 1,
                    "parser_version": PARSER_BUNDLE_VERSION,
                }
            )
            source_rows.append((spec, source_key))
        input_hash = input_manifest_sha256(inventory)
        run_id = "test-run"
        expected = {
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_BUNDLE_VERSION,
            "input_manifest_sha256": input_hash,
            "candidate_semantic_sha256": None,
            "code_commit": "c" * 40,
            "code_bundle_sha256": "b" * 64,
        }
        db.execute(
            """
            INSERT INTO direct_projection_runs(
                run_id, status, schema_version, input_manifest_sha256,
                code_commit, code_bundle_sha256
            ) VALUES (?, 'building', ?, ?, ?, ?)
            """,
            (
                run_id,
                SCHEMA_VERSION,
                input_hash,
                expected["code_commit"],
                expected["code_bundle_sha256"],
            ),
        )
        for item in inventory:
            db.execute(
                """
                INSERT INTO direct_projection_inputs(
                    run_id, source_kind, relative_path, raw_sha256,
                    lf_sha256, byte_count, key_set_sha256, record_count,
                    parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["source_kind"],
                    item["relative_path"],
                    item["raw_sha256"],
                    item["lf_sha256"],
                    item["byte_count"],
                    item["key_set_sha256"],
                    item["record_count"],
                    item["parser_version"],
                ),
            )
        card_number = 0
        for spec, source_key in source_rows:
            db.execute(
                """
                INSERT INTO direct_source_records(
                    source_kind, source_key, source_sha256, payload_json
                ) VALUES (?, ?, ?, '{}')
                """,
                (
                    spec["db_source_kind"],
                    source_key,
                    f"source-hash-{source_key}",
                ),
            )
            source_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
            if spec["db_source_kind"] != "card_raw":
                continue
            card_number += 1
            event_id = f"event-{card_number}"
            db.execute(
                """
                INSERT INTO direct_card_events(
                    source_record_id, card_event_id, generator_version,
                    identity_status, source_system, amount_krw,
                    approval_number, occurred_on, merchant
                ) VALUES (?, ?, 'fixture-v1', 'unique', 'HAN', 100,
                          ?, '2026-04-01', ?)
                """,
                (source_id, event_id, f"a-{card_number}", f"m-{card_number}"),
            )
            db.execute(
                """
                INSERT INTO direct_normalized_payments(
                    source_record_id, event_role, card_event_id,
                    amount_krw, transaction_type, normalization_version
                ) VALUES (?, 'single', ?, 100, 'purchase', 'fixture-v1')
                """,
                (source_id, event_id),
            )
        project_card_payments(db, run_id)
        semantic_hash = candidate_semantic_sha256(db, run_id)
        db.execute(
            """
            UPDATE direct_projection_runs
            SET candidate_semantic_sha256=?
            WHERE run_id=?
            """,
            (semantic_hash, run_id),
        )
        db.commit()
        db.close()
        expected["candidate_semantic_sha256"] = semantic_hash
        return database, run_id, expected, self.root

    def _report(
        self,
        database: Path,
        run_id: str,
        expected: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        return build_gate_report(
            database,
            run_id,
            repository_root=self.root,
            expected_provenance=expected,
            **kwargs,
        )

    def test_clean_first_slice_fixture_passes_gates_1_to_4_and_7(self) -> None:
        database, run_id, expected, _ = self._fixture()
        report = self._report(database, run_id, expected)
        passed = [bool(gate["passed"]) for gate in report["gates"]]
        self.assertEqual(passed, [True, True, True, True, False, False, True])
        self.assertEqual(
            report["gates"][4]["reason"],
            "direct_allocation_decision_unimplemented",
        )
        self.assertEqual(
            report["gates"][5]["reason"],
            "direct_baseline_unavailable",
        )

    def test_missing_run_fails_all_seven_gates_with_stable_reason(self) -> None:
        database, _, expected, _ = self._fixture()
        report = self._report(database, "missing", expected)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["gates"]), 7)
        self.assertTrue(
            all(gate["reason"] == "run_id_not_found" for gate in report["gates"])
        )

    def test_raw_source_mutation_fails_source_provenance(self) -> None:
        database, run_id, expected, root = self._fixture()
        (root / "ledger/newcard/conv/E.xlsx").write_bytes(b"changed")
        report = self._report(database, run_id, expected)
        gate = report["gates"][0]
        self.assertFalse(gate["passed"])
        reasons = {
            issue["reason"] for issue in gate["actual"]["issues"]
        }
        self.assertIn("source_raw_sha256_mismatch", reasons)

    def test_equal_count_key_swap_fails_key_set_hash(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute(
            """
            UPDATE direct_source_records
            SET source_key='KBO:E:replacement'
            WHERE source_key='KBO:E:1'
            """
        )
        db.commit()
        db.close()
        report = self._report(database, run_id, expected)
        reasons = {
            issue["reason"]
            for issue in report["gates"][0]["actual"]["issues"]
        }
        self.assertIn("source_key_set_sha256_mismatch", reasons)

    def test_missing_projection_link_fails_bijection(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute(
            """
            DELETE FROM direct_payment_projection_links
            WHERE direct_payment_id=(
                SELECT MIN(direct_payment_id)
                FROM direct_payment_projection_links
            )
            """
        )
        db.commit()
        db.close()
        report = self._report(database, run_id, expected)
        gate = report["gates"][1]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["reason"], "unmatched_direct_payment")
        self.assertEqual(gate["actual"]["unmatched_count"], 1)

    def test_identity_collision_fails_with_stable_source_sample(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute(
            """
            UPDATE direct_card_events
            SET identity_status='collision'
            WHERE source_record_id=(
                SELECT MIN(source_record_id) FROM direct_card_events
            )
            """
        )
        db.commit()
        db.close()
        report = self._report(database, run_id, expected)
        gate = report["gates"][1]
        self.assertEqual(gate["reason"], "identity_collision")
        self.assertEqual(gate["actual"]["collision_count"], 1)
        self.assertTrue(gate["actual"]["collision_sample"][0][1])

    def test_seeded_legacy_payment_fails_leakage_gate(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint,
                source_system, amount_krw, transaction_type
            ) VALUES ('legacy-only', 'legacy', 'legacy', 'LEGACY', 1, 'purchase')
            """
        )
        db.commit()
        db.close()
        report = self._report(database, run_id, expected)
        gate = report["gates"][2]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["reason"], "unlinked_legacy_payment")
        self.assertIn("legacy-only", gate["actual"]["unlinked_payment_sample"])

    def test_positive_cancellation_remains_an_explicit_blocker(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = connect(database)
        direct_id = int(
            db.execute(
                "SELECT MIN(id) FROM direct_normalized_payments"
            ).fetchone()[0]
        )
        payment_id = int(
            db.execute(
                """
                SELECT payment_id
                FROM direct_payment_projection_links
                WHERE run_id=? AND direct_payment_id=?
                """,
                (run_id, direct_id),
            ).fetchone()[0]
        )
        db.execute(
            """
            UPDATE direct_normalized_payments
            SET transaction_type='cancellation', amount_krw=100
            WHERE id=?
            """,
            (direct_id,),
        )
        db.execute(
            """
            UPDATE payment_transactions
            SET transaction_type='cancellation', amount_krw=100
            WHERE id=?
            """,
            (payment_id,),
        )
        semantic_hash = candidate_semantic_sha256(db, run_id)
        db.execute(
            """
            UPDATE direct_projection_runs
            SET candidate_semantic_sha256=?
            WHERE run_id=?
            """,
            (semantic_hash, run_id),
        )
        db.commit()
        db.close()
        expected["candidate_semantic_sha256"] = semantic_hash
        report = self._report(database, run_id, expected)
        gate = report["gates"][3]
        self.assertFalse(gate["passed"])
        self.assertEqual(
            gate["reason"],
            "positive_cancellation_or_invalid_sign",
        )
        self.assertEqual(gate["actual"]["sign_issue_count"], 1)

    def test_gate5_reports_every_unresolved_candidate_key(self) -> None:
        database, run_id, expected, _ = self._fixture()
        report = self._report(database, run_id, expected)
        gate = report["gates"][4]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["actual"]["candidate_payment_count"], 5)
        self.assertEqual(gate["actual"]["unresolved_count"], 5)
        self.assertTrue(gate["actual"]["unresolved_event_key_sample"])

    def test_gate6_integrity_pass_without_baseline_still_fails(self) -> None:
        database, run_id, expected, _ = self._fixture()
        report = self._report(database, run_id, expected)
        gate = report["gates"][5]
        self.assertFalse(gate["passed"])
        self.assertTrue(gate["actual"]["integrity_ok"])
        self.assertEqual(gate["reason"], "direct_baseline_unavailable")
        self.assertEqual(gate["actual"]["approvals_provided"], 0)

    def test_gate6_business_mutation_is_detected(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute("UPDATE payment_transactions SET amount_krw=amount_krw+1")
        db.commit()
        db.close()
        report = self._report(database, run_id, expected)
        gate = report["gates"][5]
        self.assertEqual(
            gate["reason"],
            "candidate_semantic_hash_mismatch",
        )
        self.assertFalse(gate["actual"]["integrity_ok"])

    def test_aggregate_only_approval_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "approval_missing_event_lineage",
        ):
            validate_approved_transitions(
                [{"rule_id": "magic", "amount_krw": 18755}]
            )

    def test_verified_baseline_cannot_pass_without_event_diff(self) -> None:
        database, run_id, expected, root = self._fixture()
        payload = {
            "event_scope": "direct-card-v2",
            "parser_version": PARSER_BUNDLE_VERSION,
            "candidate_semantic_sha256": expected[
                "candidate_semantic_sha256"
            ],
        }
        baseline_path = root / "ledger/baselines/direct.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        baseline_path.write_bytes(raw)
        baseline = {
            "relative_path": "ledger/baselines/direct.json",
            "role": "direct_semantic_baseline",
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }
        report = self._report(
            database,
            run_id,
            expected,
            comparable_baseline=baseline,
        )
        gate = report["gates"][5]
        self.assertFalse(gate["passed"])
        self.assertEqual(
            gate["reason"],
            "direct_baseline_event_diff_unimplemented",
        )
        self.assertEqual(gate["actual"]["baseline_status"], "unverified")

    def test_unverified_three_field_baseline_cannot_satisfy_gate6(self) -> None:
        database, run_id, expected, _ = self._fixture()
        fabricated = {
            "event_scope": "direct-card-v2",
            "parser_version": PARSER_BUNDLE_VERSION,
            "candidate_semantic_sha256": expected[
                "candidate_semantic_sha256"
            ],
        }
        report = self._report(
            database,
            run_id,
            expected,
            comparable_baseline=fabricated,
        )
        gate = report["gates"][5]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["actual"]["baseline_status"], "invalid")
        self.assertIn("baseline_missing_provenance", gate["reason"])

    def test_gate7_rejects_stale_code_bundle(self) -> None:
        database, run_id, expected, _ = self._fixture()
        expected["code_bundle_sha256"] = "stale"
        report = self._report(database, run_id, expected)
        gate = report["gates"][6]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["reason"], "run_provenance_stale")
        self.assertIn(
            "code_bundle_sha256",
            gate["actual"]["mismatches"],
        )

    def test_consumer_view_exposes_passed_run_only(self) -> None:
        database, run_id, _, _ = self._fixture()
        db = sqlite3.connect(database)
        self.assertEqual(
            int(
                db.execute(
                    "SELECT COUNT(*) FROM direct_candidate_payments"
                ).fetchone()[0]
            ),
            0,
        )
        db.execute(
            """
            UPDATE direct_projection_runs SET status='passed' WHERE run_id=?
            """,
            (run_id,),
        )
        db.commit()
        self.assertEqual(
            int(
                db.execute(
                    "SELECT COUNT(*) FROM direct_candidate_payments"
                ).fetchone()[0]
            ),
            5,
        )
        db.execute(
            """
            UPDATE direct_projection_runs SET status='failed' WHERE run_id=?
            """,
            (run_id,),
        )
        db.commit()
        self.assertEqual(
            int(
                db.execute(
                    "SELECT COUNT(*) FROM direct_candidate_payments"
                ).fetchone()[0]
            ),
            0,
        )
        db.close()

    def test_gate_report_hash_excludes_its_own_hash_field(self) -> None:
        database, run_id, expected, _ = self._fixture()
        report = self._report(database, run_id, expected)
        digest = gate_report_sha256(report)
        report["gate_report_sha256"] = digest
        self.assertEqual(gate_report_sha256(report), digest)


if __name__ == "__main__":
    unittest.main()
