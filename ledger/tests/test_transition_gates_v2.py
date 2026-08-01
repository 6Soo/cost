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
    _direct_event_role_scope,
    _current_direct_event_hashes,
    _event_set_sha256,
    _decision_scope_sha256,
    _direct_event_semantic_hash,
)
from ledger.domain.p07_manifest import verify_run_artifacts
from ledger.domain.decision_integrity import decision_integrity


class DirectTransitionGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_decision_integrity_is_history_inclusive_and_allocation_unbound(self) -> None:
        db = connect(self.root / "integrity.db")
        initialize(db)
        db.execute("""INSERT INTO classification_decisions
            (target_type,target_id,dimension,value,confidence,decision_status)
            VALUES ('payment',999,'account','x',1,'superseded')""")
        db.execute("""INSERT INTO classification_decisions
            (target_type,target_id,dimension,value,confidence,decision_status)
            VALUES ('allocation',1,'allocation_target','x',1,'confirmed')""")
        result = decision_integrity(db)
        self.assertEqual(result["orphan_count"], 1)
        self.assertEqual(result["orphan_sample"], [[1, "payment", 999]])
        self.assertTrue(result["allocation_target_binding_unconfirmed"])
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute("""INSERT INTO classification_decisions
            (target_type,target_id,dimension,value,confidence,decision_status)
            VALUES ('mystery',7,'account','x',1,'confirmed')""")
        result = decision_integrity(db)
        self.assertEqual(result["invalid_target_type_count"], 1)
        db.close()

    def test_gate1_reports_deterministic_source_key_conflict(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute("INSERT INTO direct_source_records(source_kind,source_key,source_sha256,payload_json) VALUES ('card_raw','A:conflict','a','{}')")
        db.execute("INSERT INTO direct_source_records(source_kind,source_key,source_sha256,payload_json) VALUES ('card_raw','A:conflict','b','{}')")
        db.commit(); db.close()
        gate = self._report(database, run_id, expected)["gates"][0]
        self.assertFalse(gate["passed"])
        issue = next(item for item in gate["actual"]["issues"] if item["reason"] == "source_key_content_conflict")
        self.assertEqual(issue["sample"], [["card_raw", "A:conflict"]])

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
            event_id = "card:" + f"{card_number:064x}"
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

    def _valid_baseline(
        self,
        database: Path,
        run_id: str,
        expected: dict[str, object],
        root: Path,
    ) -> dict[str, object]:
        db = sqlite3.connect(database)
        event_hashes, event_set_hash, scope_hash = _current_direct_event_hashes(
            db, run_id
        )
        db.close()
        payload = {
            "format_version": 1,
            "event_scope": "direct-event-role-v1",
            "parser_version": PARSER_BUNDLE_VERSION,
            "source_run_id": run_id,
            "input_manifest_sha256": expected["input_manifest_sha256"],
            "decision_scope_sha256": scope_hash,
            "candidate_semantic_sha256": expected["candidate_semantic_sha256"],
            "event_set_sha256": _event_set_sha256(event_hashes.items()),
            "events": [
                {"direct_event_key": key, "event_sha256": event_hashes[key]}
                for key in sorted(event_hashes)
            ],
        }
        path = root / "ledger/baselines/direct.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        return {
            "relative_path": "ledger/baselines/direct.json",
            "role": "direct_semantic_baseline",
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }

    @staticmethod
    def _write_baseline(payload: dict[str, object], root: Path) -> dict[str, object]:
        path = root / "ledger/baselines/direct.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        return {
            "relative_path": "ledger/baselines/direct.json",
            "role": "direct_semantic_baseline",
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }

    def test_clean_first_slice_fixture_passes_gates_1_to_4_and_7(self) -> None:
        database, run_id, expected, _ = self._fixture()
        report = self._report(database, run_id, expected)
        passed = [bool(gate["passed"]) for gate in report["gates"]]
        self.assertEqual(passed, [True, True, True, False, False, False, True])
        self.assertEqual(report["gates"][3]["reason"],"han_equality_validation_missing_or_stale")
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

    def test_identity_fallback_alone_fails_gate_two(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute(
            """
            UPDATE direct_card_events
            SET identity_status='legacy_fallback'
            WHERE source_record_id=(
                SELECT MIN(source_record_id) FROM direct_card_events
            )
            """
        )
        db.commit()
        db.close()
        report = self._report(database, run_id, expected)
        gate = report["gates"][1]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["reason"], "identity_not_unique")
        self.assertEqual(gate["actual"]["collision_count"], 0)
        self.assertEqual(gate["actual"]["fallback_count"], 1)
        self.assertEqual(gate["actual"]["fallback_sample"][0][2], "legacy_fallback")

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
        self.assertEqual(gate["actual"]["decision_scope_format"], "direct-event-role-scope-v1")
        self.assertEqual(gate["actual"]["decision_scope_count"], 5)
        self.assertEqual(gate["actual"]["decision_scope_unique_count"], 5)
        self.assertEqual(gate["actual"]["decision_scope_invalid_count"], 0)
        self.assertEqual(gate["actual"]["decision_scope_duplicate_count"], 0)
        self.assertEqual(
            gate["actual"]["decision_scope_sha256"],
            "a856dd4fae44d27849aacaaeee910b7dfc50bf4413c68dfebc4976180b1002ef",
        )
        self.assertEqual(
            gate["actual"]["unresolved_direct_event_key_sample"],
            [f"card:{index:064x}#single" for index in range(1, 6)],
        )
        self.assertEqual(
            sum(gate["actual"]["counts_by_source_system"].values()), 5
        )
        self.assertEqual(
            sum(gate["actual"]["counts_by_event_role"].values()), 5
        )
        self.assertEqual(
            sum(gate["actual"]["counts_by_transaction_type"].values()), 5
        )
        self.assertEqual(gate["actual"]["requirements_status"], "direct_decision_contract_unavailable")

    def test_scope_fingerprint_is_order_invariant_and_role_sensitive(self) -> None:
        rows = [
            {
                "card_event_id": "card:" + "a" * 64,
                "event_role": "approval",
                "source_system": "HAN",
                "transaction_type": "purchase",
            },
            {
                "card_event_id": "card:" + "a" * 64,
                "event_role": "cancellation",
                "source_system": "HAN",
                "transaction_type": "cancellation",
            },
        ]
        first = _direct_event_role_scope(rows)
        reversed_scope = _direct_event_role_scope(list(reversed(rows)))
        changed = _direct_event_role_scope(
            [dict(rows[0]), {**rows[1], "event_role": "single"}]
        )
        self.assertEqual(first["decision_scope_sha256"], reversed_scope["decision_scope_sha256"])
        self.assertNotEqual(first["decision_scope_sha256"], changed["decision_scope_sha256"])
        self.assertEqual(first["counts_by_event_role"], {"approval": 1, "cancellation": 1})

    def test_scope_fingerprint_reports_invalid_and_duplicate_rows_without_dedup(self) -> None:
        rows = [
            {
                "card_event_id": "invalid",
                "event_role": "bogus",
                "source_system": "X",
                "transaction_type": "purchase",
            }
        ]
        scope = _direct_event_role_scope(rows + rows)
        one_row_scope = _direct_event_role_scope(rows)
        self.assertEqual(scope["decision_scope_count"], 2)
        self.assertEqual(scope["decision_scope_unique_count"], 1)
        self.assertEqual(scope["decision_scope_invalid_count"], 2)
        self.assertEqual(scope["decision_scope_duplicate_count"], 1)
        self.assertNotEqual(
            scope["decision_scope_sha256"], one_row_scope["decision_scope_sha256"]
        )
        self.assertEqual(scope["decision_scope_invalid_sample"], ["invalid#bogus", "invalid#bogus"])

    def test_new_gate5_field_tamper_is_rejected_by_artifact_verifier(self) -> None:
        from ledger.domain.direct_projection import build_direct_candidate

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            result = build_direct_candidate(
                root / "candidate.db",
                Path("ledger"),
                output_dir=root / "reports",
            )
            report_dir = Path(str(result["report_dir"]))
            report_path = report_dir / "gate_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["gates"][4]["actual"]["decision_scope_count"] += 1
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "gate_report_self_hash_mismatch"):
                verify_run_artifacts(report_dir, repository_root=Path("."))

    def test_new_gate6_diff_field_tamper_is_rejected_by_artifact_verifier(self) -> None:
        from ledger.domain.direct_projection import build_direct_candidate

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            result = build_direct_candidate(
                root / "candidate.db", Path("ledger"), output_dir=root / "reports"
            )
            report_dir = Path(str(result["report_dir"]))
            report_path = report_dir / "gate_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["gates"][5]["actual"]["current_event_set_sha256"] = "0" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "gate_report_self_hash_mismatch"):
                verify_run_artifacts(report_dir, repository_root=Path("."))

    def test_generic_confirmed_decision_and_exact_plan_do_not_resolve_gate5(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        payment_id = int(
            db.execute(
                "SELECT payment_id FROM direct_payment_projection_links WHERE run_id=? LIMIT 1",
                (run_id,),
            ).fetchone()[0]
        )
        db.execute(
            "INSERT INTO allocation_targets(id, target_type, code, name) VALUES (99, 'other', 'fake', 'Fake')"
        )
        db.execute(
            """INSERT INTO classification_decisions(
                   target_type, target_id, dimension, value, confidence,
                   confidence_label, decision_status
               ) VALUES ('payment', ?, 'allocation_target', 'fake', 1.0, 'high', 'confirmed')""",
            (payment_id,),
        )
        decision_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            """INSERT INTO allocation_plans(
                   payment_id, plan_version, plan_status, confidence, source_decision_id
               ) VALUES (?, 1, 'confirmed', 1.0, ?)""",
            (payment_id, decision_id),
        )
        plan_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO cost_allocations(plan_id, target_id, amount_krw) VALUES (?, 99, 100)" ,
            (plan_id,),
        )
        for status in ("legacy", "proposed", "needs_review", "rejected"):
            db.execute(
                """INSERT INTO classification_decisions(
                       target_type, target_id, dimension, value, confidence,
                       confidence_label, decision_status
                   ) VALUES ('payment', ?, ?, 'generic', 1.0, 'high', ?)""",
                (payment_id, f"generic_{status}", status),
            )
        db.commit()
        db.close()
        gate = self._report(database, run_id, expected)["gates"][4]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["actual"]["resolved_count"], 0)
        self.assertEqual(gate["actual"]["unresolved_count"], 5)
        self.assertEqual(gate["reason"], "direct_allocation_decision_unimplemented")

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

    @staticmethod
    def _valid_approval(**overrides: object) -> dict[str, object]:
        value = "a" * 64
        approval: dict[str, object] = {
            "transition_id": value,
            "rule_id": "rule-1",
            "direct_event_keys": [f"card:{value}#single"],
            "before_event_sha256": value,
            "after_event_sha256": value,
            "evidence_set_sha256": value,
            "before_semantic_sha256": value,
            "after_semantic_sha256": value,
            "approved_by": "owner",
            "approved_at": "2026-07-30T12:00:00+09:00",
            "approval_source": "approval-artifact",
            "approval_source_sha256": value,
            "source_run_id": "run-1",
        }
        approval.update(overrides)
        return approval

    def test_strict_approval_envelope_validates_and_binds_context(self) -> None:
        value = "a" * 64
        approval = {
            "transition_id": "a" * 64,
            "rule_id": "rule-1",
            "direct_event_keys": [f"card:{value}#single"],
            "before_event_sha256": value,
            "after_event_sha256": value,
            "evidence_set_sha256": value,
            "before_semantic_sha256": value,
            "after_semantic_sha256": value,
            "approved_by": "owner",
            "approved_at": "2026-07-30T12:00:00+09:00",
            "approval_source": "approval-artifact",
            "approval_source_sha256": value,
            "source_run_id": "run-1",
        }
        self.assertEqual(
            validate_approved_transitions(
                [approval],
                expected_source_run_id="run-1",
                expected_after_semantic_sha256=value,
            ),
            [approval],
        )

    def test_strict_approval_rejects_legacy_key_and_duplicate_consumption(self) -> None:
        value = "a" * 64
        approval = {
            "transition_id": "a" * 64,
            "rule_id": "rule-1",
            "direct_event_keys": ["KBD-1046"],
            "before_event_sha256": value,
            "after_event_sha256": value,
            "evidence_set_sha256": value,
            "before_semantic_sha256": value,
            "after_semantic_sha256": value,
            "approved_by": "owner",
            "approved_at": "2026-07-30T12:00:00Z",
            "approval_source": "artifact",
            "approval_source_sha256": value,
            "source_run_id": "run-1",
        }
        with self.assertRaisesRegex(ValueError, "approval_event_keys_invalid"):
            validate_approved_transitions([approval])
        approval["direct_event_keys"] = [f"card:{value}#approval"]
        with self.assertRaisesRegex(ValueError, "approval_duplicate_event"):
            validate_approved_transitions(
                [approval, dict(approval, transition_id="b" * 64)]
            )

    def test_strict_approval_rejects_draft_and_stale_context(self) -> None:
        value = "a" * 64
        approval = {
            "transition_id": "a" * 64, "rule_id": "rule-1",
            "direct_event_keys": [f"card:{value}#cancellation"],
            "before_event_sha256": value, "after_event_sha256": value,
            "evidence_set_sha256": value, "before_semantic_sha256": value,
            "after_semantic_sha256": value, "approved_by": "owner",
            "approved_at": "2026-07-30T12:00:00+09:00",
            "approval_source": "artifact", "approval_source_sha256": value,
            "source_run_id": "stale-run",
        }
        with self.assertRaisesRegex(ValueError, "approval_source_run_mismatch"):
            validate_approved_transitions(
                [approval], expected_source_run_id="current-run",
                expected_after_semantic_sha256=value,
            )

    def test_transition_id_and_all_hashes_require_lowercase_sha256(self) -> None:
        fields = (
            "transition_id", "before_event_sha256", "after_event_sha256",
            "evidence_set_sha256", "before_semantic_sha256",
            "after_semantic_sha256", "approval_source_sha256",
        )
        for field in fields:
            with self.subTest(field=field):
                for invalid in ("A" * 64, "a" * 63, "g" * 64):
                    value = self._valid_approval(**{field: invalid})
                    with self.assertRaisesRegex(
                        ValueError, "approval_hash_invalid"
                    ):
                        validate_approved_transitions([value])

    def test_approval_rejects_each_missing_and_blank_required_field(self) -> None:
        required = (
            "transition_id", "rule_id", "direct_event_keys",
            "before_event_sha256", "after_event_sha256",
            "evidence_set_sha256", "before_semantic_sha256",
            "after_semantic_sha256", "approved_by", "approved_at",
            "approval_source", "approval_source_sha256", "source_run_id",
        )
        for field in required:
            with self.subTest(field=field):
                missing = self._valid_approval()
                del missing[field]
                with self.assertRaises(ValueError):
                    validate_approved_transitions([missing])
                blank = self._valid_approval(**{field: ""})
                with self.assertRaises(ValueError):
                    validate_approved_transitions([blank])

    def test_approval_rejects_impossible_timestamp_and_supersession(self) -> None:
        for timestamp in (
            "2026-02-31T12:00:00Z", "2026-07-30T25:00:00Z",
            "2026-07-30T12:00:00+99:99", "2026-07-30T12:00:00",
        ):
            with self.assertRaisesRegex(ValueError, "approval_timestamp_invalid"):
                validate_approved_transitions(
                    [self._valid_approval(approved_at=timestamp)]
                )
        for field in ("supersedes_approval_id", "supersedes"):
            with self.assertRaisesRegex(ValueError, "approval_supers"):
                validate_approved_transitions(
                    [self._valid_approval(**{field: "old"})]
                )

    def test_approval_timestamp_offset_bounds_and_zero_policy(self) -> None:
        for timestamp in (
            "2026-07-30T12:00:00+09:60",
            "2026-07-30T12:00:00-23:60",
            "2026-07-30T12:00:00-00:00",
        ):
            with self.assertRaisesRegex(ValueError, "approval_timestamp_invalid"):
                validate_approved_transitions(
                    [self._valid_approval(approved_at=timestamp)]
                )
        for timestamp in (
            "2026-07-30T12:00:00+23:59",
            "2026-07-30T12:00:00-23:59",
            "2026-07-30T12:00:00Z",
            "2026-07-30T12:00:00+00:00",
        ):
            self.assertEqual(
                len(validate_approved_transitions(
                    [self._valid_approval(approved_at=timestamp)]
                )),
                1,
            )

    def test_approval_requires_exactly_one_direct_event(self) -> None:
        for event_keys in ([], ["card:" + "a" * 64 + "#single"] * 2):
            with self.assertRaisesRegex(ValueError, "approval_event_keys_invalid"):
                validate_approved_transitions(
                    [self._valid_approval(direct_event_keys=event_keys)]
                )

    def test_wrong_after_hash_and_duplicate_transition_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "approval_after_semantic_mismatch"):
            validate_approved_transitions(
                [self._valid_approval()],
                expected_source_run_id="run-1",
                expected_after_semantic_sha256="b" * 64,
            )
        approval = self._valid_approval()
        with self.assertRaisesRegex(ValueError, "approval_duplicate_transition"):
            validate_approved_transitions(
                [
                    approval,
                    dict(
                        approval,
                        direct_event_keys=["card:" + "b" * 64 + "#single"],
                    ),
                ]
            )

    def test_valid_envelope_with_matching_descriptor_still_fails_event_diff(
        self,
    ) -> None:
        database, run_id, expected, root = self._fixture()
        baseline = self._valid_baseline(database, run_id, expected, root)
        value = expected["candidate_semantic_sha256"]
        approval = self._valid_approval(
            source_run_id=run_id,
            after_semantic_sha256=value,
        )
        report = self._report(
            database, run_id, expected,
            approved_transitions=[approval], comparable_baseline=baseline,
        )
        gate = report["gates"][5]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["reason"], "direct_baseline_authority_unavailable")
        self.assertEqual(gate["actual"]["baseline_status"], "diff_computed_unapproved")
        self.assertEqual(gate["actual"]["unchanged_count"], 5)
        self.assertEqual(gate["actual"]["changed_count"], 0)
        self.assertEqual(gate["actual"]["added_count"], 0)
        self.assertEqual(gate["actual"]["removed_count"], 0)
        self.assertEqual(gate["actual"]["approvals_provided"], 1)
        self.assertEqual(gate["actual"]["approval_mode"], "event_level")

    def test_valid_envelope_without_baseline_still_fails_closed(self) -> None:
        database, run_id, expected, _ = self._fixture()
        approval = self._valid_approval(
            source_run_id=run_id,
            after_semantic_sha256=expected["candidate_semantic_sha256"],
        )
        report = self._report(
            database, run_id, expected, approved_transitions=[approval]
        )
        gate = report["gates"][5]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["reason"], "direct_baseline_unavailable")
        self.assertEqual(gate["actual"]["approvals_provided"], 1)
        self.assertEqual(gate["actual"]["approval_mode"], "event_level")

    def test_nonzero_event_diff_uses_baseline_owned_provenance_but_stays_unapproved(self) -> None:
        database, run_id, expected, root = self._fixture()
        db = sqlite3.connect(database)
        event_hashes, _, _ = _current_direct_event_hashes(db, run_id)
        db.close()
        keys = sorted(event_hashes)
        baseline_hashes = dict(event_hashes)
        baseline_hashes[keys[0]] = "b" * 64
        del baseline_hashes[keys[-1]]
        baseline_hashes["card:" + "f" * 64 + "#single"] = "c" * 64
        payload = {
            "format_version": 1,
            "event_scope": "direct-event-role-v1",
            "parser_version": PARSER_BUNDLE_VERSION,
            "source_run_id": "prior-approved-run",
            "input_manifest_sha256": "1" * 64,
            "decision_scope_sha256": _decision_scope_sha256(baseline_hashes),
            "candidate_semantic_sha256": "2" * 64,
            "event_set_sha256": _event_set_sha256(baseline_hashes.items()),
            "events": [
                {"direct_event_key": key, "event_sha256": baseline_hashes[key]}
                for key in sorted(baseline_hashes)
            ],
        }
        baseline = self._write_baseline(payload, root)
        gate = self._report(database, run_id, expected, comparable_baseline=baseline)["gates"][5]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["reason"], "direct_baseline_authority_unavailable")
        self.assertEqual(gate["actual"]["baseline_status"], "diff_computed_unapproved")
        self.assertEqual(gate["actual"]["changed_count"], 1)
        self.assertEqual(gate["actual"]["added_count"], 1)
        self.assertEqual(gate["actual"]["removed_count"], 1)
        self.assertEqual(gate["actual"]["changed_sample"], [keys[0]])
        self.assertEqual(gate["actual"]["added_sample"], [keys[-1]])
        self.assertEqual(
            gate["actual"]["removed_sample"], ["card:" + "f" * 64 + "#single"]
        )

    def test_integrity_and_invalid_approval_precedence_hold_with_baseline(self) -> None:
        database, run_id, expected, root = self._fixture()
        baseline = self._valid_baseline(database, run_id, expected, root)
        db = sqlite3.connect(database)
        db.execute(
            "UPDATE payment_transactions SET amount_krw=amount_krw+1 WHERE id=1"
        )
        db.commit()
        db.close()
        integrity = self._report(
            database, run_id, expected, comparable_baseline=baseline
        )["gates"][5]
        self.assertEqual(integrity["reason"], "candidate_semantic_hash_mismatch")

        invalid_approval = self._report(
            database, run_id, expected,
            approved_transitions=[{"transition_id": "bad"}],
            comparable_baseline=baseline,
        )["gates"][5]
        self.assertTrue(invalid_approval["reason"].startswith("approval_missing_event_lineage"))

    def test_baseline_scope_is_bound_to_its_own_event_keys(self) -> None:
        database, run_id, expected, root = self._fixture()
        descriptor = self._valid_baseline(database, run_id, expected, root)
        path = root / "ledger/baselines/direct.json"
        payload = json.loads(path.read_text())
        payload["events"] = payload["events"][:-1]
        payload["event_set_sha256"] = _event_set_sha256(
            (event["direct_event_key"], event["event_sha256"])
            for event in payload["events"]
        )
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        descriptor["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        gate = self._report(database, run_id, expected, comparable_baseline=descriptor)["gates"][5]
        self.assertEqual(gate["reason"], "baseline_decision_scope_hash_mismatch")

    def test_baseline_structure_matrix_rejects_invalid_format_scope_parser_hash_and_keys(self) -> None:
        database, run_id, expected, root = self._fixture()
        self._valid_baseline(database, run_id, expected, root)
        path = root / "ledger/baselines/direct.json"
        original = json.loads(path.read_text())
        cases = {
            "format": ("format_version", 2, "baseline_format_version_invalid"),
            "scope": ("event_scope", "direct-card-v2", "baseline_event_scope_invalid"),
            "parser": ("parser_version", "old-parser", "baseline_parser_version_invalid"),
            "manifest_hash": ("input_manifest_sha256", "A" * 64, "baseline_hash_invalid:input_manifest_sha256"),
            "semantic_hash": ("candidate_semantic_sha256", "g" * 64, "baseline_hash_invalid:candidate_semantic_sha256"),
        }
        for name, (field, value, reason) in cases.items():
            with self.subTest(name=name):
                payload = dict(original)
                payload[field] = value
                descriptor = self._write_baseline(payload, root)
                gate = self._report(database, run_id, expected, comparable_baseline=descriptor)["gates"][5]
                self.assertEqual(gate["reason"], reason)
        for name, field in (("source_blank", "source_run_id"), ("scope_blank", "decision_scope_sha256")):
            with self.subTest(name=name):
                payload = dict(original)
                payload[field] = ""
                descriptor = self._write_baseline(payload, root)
                gate = self._report(database, run_id, expected, comparable_baseline=descriptor)["gates"][5]
                self.assertTrue(gate["reason"].startswith("baseline_"))
        payload = dict(original)
        payload["events"] = list(original["events"])
        payload["events"][0] = dict(payload["events"][0], direct_event_key="bad-key")
        descriptor = self._write_baseline(payload, root)
        self.assertEqual(
            self._report(database, run_id, expected, comparable_baseline=descriptor)["gates"][5]["reason"],
            "baseline_event_key_invalid:0",
        )

    def test_baseline_adversarial_envelope_matrix_is_permanent(self) -> None:
        database, run_id, expected, root = self._fixture()
        self._valid_baseline(database, run_id, expected, root)
        path = root / "ledger/baselines/direct.json"
        original = json.loads(path.read_text())

        for field in (
            "format_version", "event_scope", "parser_version", "source_run_id",
            "input_manifest_sha256", "decision_scope_sha256",
            "candidate_semantic_sha256", "event_set_sha256", "events",
        ):
            with self.subTest(missing=field):
                payload = dict(original)
                payload.pop(field)
                descriptor = self._write_baseline(payload, root)
                reason = self._report(
                    database, run_id, expected, comparable_baseline=descriptor
                )["gates"][5]["reason"]
                self.assertTrue(reason.startswith("baseline_"))

        for field in (
            "source_run_id", "input_manifest_sha256", "decision_scope_sha256",
            "candidate_semantic_sha256", "event_set_sha256",
        ):
            with self.subTest(blank=field):
                payload = dict(original, **{field: ""})
                descriptor = self._write_baseline(payload, root)
                reason = self._report(
                    database, run_id, expected, comparable_baseline=descriptor
                )["gates"][5]["reason"]
                self.assertTrue(reason.startswith("baseline_"))

        for field in (
            "input_manifest_sha256", "decision_scope_sha256",
            "candidate_semantic_sha256", "event_set_sha256",
        ):
            for value in ("a" * 63, "A" * 64, "g" * 64):
                with self.subTest(hash_field=field, value=value[:4]):
                    payload = dict(original, **{field: value})
                    descriptor = self._write_baseline(payload, root)
                    reason = self._report(
                        database, run_id, expected, comparable_baseline=descriptor
                    )["gates"][5]["reason"]
                    self.assertEqual(reason, f"baseline_hash_invalid:{field}")

        for value in ("a" * 63, "A" * 64, "g" * 64):
            with self.subTest(event_hash=value[:4]):
                events = list(original["events"])
                events[0] = dict(events[0], event_sha256=value)
                descriptor = self._write_baseline(dict(original, events=events), root)
                reason = self._report(
                    database, run_id, expected, comparable_baseline=descriptor
                )["gates"][5]["reason"]
                self.assertEqual(reason, "baseline_event_hash_invalid:0")

        duplicate = list(original["events"]) + [dict(original["events"][0])]
        descriptor = self._write_baseline(dict(original, events=duplicate), root)
        self.assertEqual(
            self._report(database, run_id, expected, comparable_baseline=descriptor)
            ["gates"][5]["reason"],
            "baseline_event_key_duplicate",
        )

        mismatch = dict(original, event_set_sha256="0" * 64)
        descriptor = self._write_baseline(mismatch, root)
        self.assertEqual(
            self._report(database, run_id, expected, comparable_baseline=descriptor)
            ["gates"][5]["reason"],
            "baseline_event_set_hash_mismatch",
        )

        shaped = dict(original, event_scope="direct-card-v2")
        descriptor = self._write_baseline(shaped, root)
        self.assertEqual(
            self._report(database, run_id, expected, comparable_baseline=descriptor)
            ["gates"][5]["reason"],
            "baseline_event_scope_invalid",
        )

    def test_format_version_requires_exact_integer_one(self) -> None:
        database, run_id, expected, root = self._fixture()
        self._valid_baseline(database, run_id, expected, root)
        path = root / "ledger/baselines/direct.json"
        original = json.loads(path.read_text())
        for value in (True, 1.0, "1", None, 2):
            with self.subTest(value=value):
                payload = dict(original)
                payload["format_version"] = value
                descriptor = self._write_baseline(payload, root)
                gate = self._report(database, run_id, expected, comparable_baseline=descriptor)["gates"][5]
                self.assertEqual(gate["reason"], "baseline_format_version_invalid")

    def test_each_event_field_and_null_empty_change_semantic_hash(self) -> None:
        base = {
            "direct_event_key": "card:" + "a" * 64 + "#single",
            "external_key": "p1", "source_event_id": "s1",
            "identity_fingerprint": "i1", "source_system": "HAN",
            "occurred_on": "2026-07-30", "merchant": "merchant",
            "approval_number": "123", "amount_krw": 100,
            "transaction_type": "purchase", "card_event_id": "card:" + "a" * 64,
            "event_role": "single", "source_kind": "card_raw",
            "source_key": "HAN:1", "source_sha256": "b" * 64,
        }
        fields = tuple(base)
        original_hash = _direct_event_semantic_hash(base)
        for field in fields:
            changed = dict(base)
            changed[field] = (base[field] + "-changed") if isinstance(base[field], str) else 101
            self.assertNotEqual(original_hash, _direct_event_semantic_hash(changed))
        for field in fields:
            null_value = dict(base, **{field: None})
            empty_value = dict(base, **{field: ""})
            self.assertNotEqual(
                _direct_event_semantic_hash(null_value),
                _direct_event_semantic_hash(empty_value),
            )
        approval = dict(base, direct_event_key="card:" + "a" * 64 + "#approval", event_role="approval")
        cancellation = dict(base, direct_event_key="card:" + "a" * 64 + "#cancellation", event_role="cancellation")
        self.assertNotEqual(_direct_event_semantic_hash(approval), _direct_event_semantic_hash(cancellation))

    def test_duplicate_current_event_key_fails_gate6(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute("UPDATE direct_normalized_payments SET card_event_id=(SELECT card_event_id FROM direct_normalized_payments WHERE id=2) WHERE id=1")
        recomputed = candidate_semantic_sha256(db, run_id)
        db.execute("UPDATE direct_projection_runs SET candidate_semantic_sha256=? WHERE run_id=?", (recomputed, run_id))
        db.commit()
        db.close()
        expected["candidate_semantic_sha256"] = recomputed
        gate = self._report(database, run_id, expected)["gates"][5]
        self.assertEqual(gate["reason"], "baseline_current_event_key_duplicate")

    def test_baseline_event_order_and_sorted_nonzero_samples_are_stable(self) -> None:
        database, run_id, expected, root = self._fixture()
        descriptor = self._valid_baseline(database, run_id, expected, root)
        path = root / "ledger/baselines/direct.json"
        payload = json.loads(path.read_text())
        payload["events"] = list(reversed(payload["events"]))
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        descriptor["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        gate = self._report(database, run_id, expected, comparable_baseline=descriptor)["gates"][5]
        self.assertEqual(gate["actual"]["unchanged_count"], 5)
        self.assertEqual(gate["actual"]["changed_sample"], [])
        self.assertEqual(gate["actual"]["added_sample"], [])
        self.assertEqual(gate["actual"]["removed_sample"], [])

    def test_current_event_structure_error_precedes_baseline_unavailable(self) -> None:
        database, run_id, expected, _ = self._fixture()
        db = sqlite3.connect(database)
        db.execute(
            "UPDATE direct_normalized_payments SET card_event_id='not-a-card-key' WHERE id=1"
        )
        recomputed = candidate_semantic_sha256(db, run_id)
        db.execute(
            "UPDATE direct_projection_runs SET candidate_semantic_sha256=? WHERE run_id=?",
            (recomputed, run_id),
        )
        db.commit()
        db.close()
        expected["candidate_semantic_sha256"] = recomputed
        gate = self._report(database, run_id, expected)["gates"][5]
        self.assertEqual(gate["reason"], "baseline_current_event_key_invalid")

    def test_equal_amount_is_not_an_approval_identity(self) -> None:
        first = self._valid_approval(amount_krw=1234)
        second = self._valid_approval(
            transition_id="b" * 64,
            direct_event_keys=["card:" + "b" * 64 + "#single"],
            amount_krw=1234,
        )
        self.assertEqual(len(validate_approved_transitions([first, second])), 2)

    def test_verified_baseline_cannot_pass_without_event_diff(self) -> None:
        database, run_id, expected, root = self._fixture()
        baseline = self._valid_baseline(database, run_id, expected, root)
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
            "direct_baseline_authority_unavailable",
        )
        self.assertEqual(gate["actual"]["baseline_status"], "diff_computed_unapproved")

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
        self.assertEqual(int(db.execute("SELECT COUNT(*) FROM direct_candidate_payments").fetchone()[0]),0)
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
