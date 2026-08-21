from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

from ledger.domain.direct_independent_evidence import (
    ACTIVE_DIMENSIONS,
    build_legacy_candidate_audit,
    materialize_current_card_evidence,
    project_independent_promotion,
    validate_promotion_candidate,
)
from ledger.domain.direct_projection import _apply_schema, project_card_payments
from ledger.domain.direct_sources import import_all
from ledger.domain.ledger_db import connect, initialize


class DirectIndependentEvidenceTests(unittest.TestCase):
    @staticmethod
    def _promotion() -> tuple[
            dict[str, object], dict[str, dict[str, object]],
            dict[str, dict[str, object]]]:
        evidence_id = "current-card:" + "a" * 64
        event_key = "card:" + "b" * 64 + "#single"
        index = {event_key: {
            "current_evidence_id": evidence_id,
            "current_event_sha256": "a" * 64,
        }}
        registry = {evidence_id: {
            "evidence_kind": "current_card", "authority_status": "current_raw",
            "direct_event_key": event_key, "source_kind": "card_raw",
            "source_key": "card:source", "source_sha256": "c" * 64,
            "fact_sha256": "a" * 64,
        }}
        derivations = {}
        values = {
            "account": "숙박비",
            "cost_type": "여행원가",
            "allocation_target": "0417_아오모리",
        }
        for number, dimension in enumerate(ACTIVE_DIMENSIONS, start=1):
            fact_sha256 = f"{number + 10:064x}"
            external_id = f"verified_booking:{fact_sha256}"
            derivations[dimension] = {
                "value": values[dimension],
                "status": "pass",
                "derivation_id": f"axis-derivation-{number}",
                "rule_id": f"independent-rule-{number}",
                "evidence_ids": [evidence_id, external_id],
            }
            registry[external_id] = {
                "evidence_kind": "verified_booking",
                "authority_status": "verified_external",
                "direct_event_key": event_key,
                "source_kind": "booking_raw",
                "source_key": f"booking:{number}",
                "source_sha256": f"{number:064x}",
                "fact_sha256": fact_sha256,
            }
        return ({
            "direct_event_key": event_key,
            "current_evidence_id": evidence_id,
            "conflict_count": 0,
            "derivations": derivations,
        }, index, registry)

    def test_promotion_requires_three_distinct_independent_derivations(self) -> None:
        candidate, index, registry = self._promotion()
        self.assertEqual(
            set(validate_promotion_candidate(candidate, index, registry)),
            set(ACTIVE_DIMENSIONS),
        )
        candidate["derivations"]["cost_type"]["derivation_id"] = \
            candidate["derivations"]["account"]["derivation_id"]
        with self.assertRaisesRegex(ValueError, "promotion_derivation_alias"):
            validate_promotion_candidate(candidate, index, registry)

    def test_promotion_rejects_manual_legacy_tolerance_vat_and_missing_axis(self) -> None:
        for forbidden in ("manual-rule", "legacy-replay", "within_2_percent", "trips.json-only"):
            candidate, index, registry = self._promotion()
            candidate["derivations"]["account"]["rule_id"] = forbidden
            with self.assertRaisesRegex(ValueError, "promotion_derivation_invalid"):
                validate_promotion_candidate(candidate, index, registry)
        candidate, index, registry = self._promotion()
        candidate["derivations"]["vat_tag"] = candidate["derivations"]["account"]
        with self.assertRaisesRegex(ValueError, "promotion_dimensions_invalid"):
            validate_promotion_candidate(candidate, index, registry)
        candidate, index, registry = self._promotion()
        del candidate["derivations"]["allocation_target"]
        with self.assertRaisesRegex(ValueError, "promotion_dimensions_invalid"):
            validate_promotion_candidate(candidate, index, registry)

    def test_fabricated_external_evidence_id_is_rejected(self) -> None:
        candidate, index, registry = self._promotion()
        fabricated = candidate["derivations"]["account"]["evidence_ids"][1]
        del registry[fabricated]
        with self.assertRaisesRegex(
                ValueError, "promotion_independent_evidence_unregistered"):
            validate_promotion_candidate(candidate, index, registry)

    def test_registered_evidence_cannot_be_reused_for_another_event(self) -> None:
        candidate, index, registry = self._promotion()
        external_id = candidate["derivations"]["account"]["evidence_ids"][1]
        registry[external_id]["direct_event_key"] = "card:" + "f" * 64 + "#single"
        with self.assertRaisesRegex(
                ValueError, "promotion_independent_evidence_unregistered"):
            validate_promotion_candidate(candidate, index, registry)

    def test_external_registry_row_requires_a_real_ingested_source(self) -> None:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            initialize(db); _apply_schema(db)
            db.execute(
                """INSERT INTO direct_projection_runs(
                     run_id,status,schema_version,input_manifest_sha256,
                     code_commit,code_bundle_sha256)
                   VALUES ('run','building','p07-direct-v3','i','c','b')"""
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO direct_promotion_evidence(
                         evidence_id,run_id,evidence_kind,authority_status,
                         direct_event_key,source_kind,source_key,source_sha256,
                         fact_sha256)
                       VALUES (?,'run','verified_booking','verified_external',
                               'card:event#single','booking_raw','missing',?,?)""",
                    ("verified_booking:" + "b" * 64, "a" * 64, "b" * 64),
                )
        finally:
            db.close()

    def test_legacy_cohorts_are_diagnostic_candidates_with_zero_credit(self) -> None:
        audit = build_legacy_candidate_audit()
        self.assertEqual(audit["previous_gate5_credit"], 676)
        self.assertEqual(audit["current_gate5_credit"], 0)
        self.assertTrue(audit["counts_are_diagnostic_not_a_set_union"])
        self.assertTrue(all(row["current_gate5_credit"] == 0 for row in audit["cohorts"]))
        counts = {
            row["cohort"]: row["reported_candidate_count"]
            for row in audit["cohorts"]
        }
        self.assertEqual(counts["legacy_replay_three_active_axes"], 750)
        self.assertEqual(counts["legacy_replay_missing_cost_type"], 14)

    def test_registry_schema_rejects_manual_external_authority(self) -> None:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            initialize(db); _apply_schema(db)
            db.execute(
                """INSERT INTO direct_projection_runs(
                     run_id,status,schema_version,input_manifest_sha256,
                     code_commit,code_bundle_sha256)
                   VALUES ('run','building','p07-direct-v3','i','c','b')"""
            )
            db.execute(
                """INSERT INTO direct_source_records(
                     source_kind,source_key,source_sha256,payload_json)
                   VALUES ('manual_ledger','M:1',?,'{}')""",
                ("a" * 64,),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO direct_promotion_evidence(
                         evidence_id,run_id,evidence_kind,authority_status,
                         direct_event_key,source_kind,source_key,source_sha256,
                         fact_sha256)
                       VALUES (?,'run','verified_booking','verified_external',
                               'card:event#single','manual_ledger','M:1',?,?)""",
                    ("verified_booking:" + "b" * 64, "a" * 64, "b" * 64),
                )
        finally:
            db.close()

    def test_projector_resolves_registered_sources_and_exposes_bound_axes(self) -> None:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            initialize(db); _apply_schema(db)
            db.execute(
                """INSERT INTO direct_projection_runs(
                     run_id,status,schema_version,input_manifest_sha256,
                     code_commit,code_bundle_sha256)
                   VALUES ('run','building','p07-direct-v3','i','c','b')"""
            )
            event_key = "card:" + "b" * 64 + "#single"
            card_sha = "c" * 64
            db.execute(
                """INSERT INTO direct_source_records(
                     source_kind,source_key,source_sha256,payload_json)
                   VALUES ('card_raw','card:source',?,'{}')""",
                (card_sha,),
            )
            source_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            db.execute(
                """INSERT INTO direct_card_events(
                     source_record_id,card_event_id,generator_version,
                     identity_status,source_system,amount_krw,merchant)
                   VALUES (?,?,'fixture-v1','unique','HAN',100,'hotel')""",
                (source_id, event_key.removesuffix("#single")),
            )
            db.execute(
                """INSERT INTO direct_normalized_payments(
                     source_record_id,event_role,card_event_id,amount_krw,
                     transaction_type,normalization_version)
                   VALUES (?,'single',?,100,'purchase','fixture-v1')""",
                (source_id, event_key.removesuffix("#single")),
            )
            project_card_payments(db, "run")
            candidate, index, registry = self._promotion()
            for evidence_id, record in registry.items():
                if record["evidence_kind"] != "current_card":
                    db.execute(
                        """INSERT INTO direct_source_records(
                             source_kind,source_key,source_sha256,payload_json)
                           VALUES (?,?,?,'{}')""",
                        (record["source_kind"], record["source_key"],
                         record["source_sha256"]),
                    )
                db.execute(
                    """INSERT INTO direct_promotion_evidence(
                         evidence_id,run_id,evidence_kind,authority_status,
                         direct_event_key,source_kind,source_key,source_sha256,
                         fact_sha256)
                       VALUES (?,'run',?,?,?,?,?,?,?)""",
                    (evidence_id, record["evidence_kind"],
                     record["authority_status"], record["direct_event_key"],
                     record["source_kind"], record["source_key"],
                     record["source_sha256"], record["fact_sha256"]),
                )
            self.assertEqual(
                project_independent_promotion(db, "run", candidate, index),
                {"payments": 1, "decisions": 3},
            )
            self.assertEqual(int(db.execute(
                "SELECT COUNT(*) FROM current_independently_promoted_decisions"
            ).fetchone()[0]), 3)
            db.execute("DELETE FROM direct_decision_promotion_bindings")
            db.execute("DELETE FROM direct_axis_derivations")
            db.execute("DELETE FROM classification_decisions")
            payment_id = int(db.execute(
                "SELECT payment_id FROM direct_payment_projection_links"
            ).fetchone()[0])
            blocked = candidate["derivations"]["cost_type"]
            blocked_external = next(
                evidence_id for evidence_id in blocked["evidence_ids"]
                if evidence_id != candidate["current_evidence_id"]
            )
            db.execute(
                """INSERT INTO direct_axis_derivations(
                     derivation_id,run_id,payment_id,dimension,value,rule_id,
                     current_evidence_id,independent_evidence_id,
                     derivation_status,conflict_count)
                   VALUES (?,'run',?,'cost_type','blocker','blocker-rule',
                           ?,?,'pass',0)""",
                (blocked["derivation_id"], payment_id,
                 candidate["current_evidence_id"], blocked_external),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                project_independent_promotion(db, "run", candidate, index)
            self.assertEqual(int(db.execute(
                "SELECT COUNT(*) FROM classification_decisions"
            ).fetchone()[0]), 0)
            self.assertEqual(int(db.execute(
                "SELECT COUNT(*) FROM direct_decision_promotion_bindings"
            ).fetchone()[0]), 0)
            self.assertEqual(int(db.execute(
                "SELECT COUNT(*) FROM direct_axis_derivations"
            ).fetchone()[0]), 1)
        finally:
            db.close()

    def test_current_card_evidence_covers_5328_events_once_without_manual(self) -> None:
        with tempfile.TemporaryDirectory(prefix="current-evidence-test-") as dirname:
            db = connect(Path(dirname) / "evidence.db")
            try:
                initialize(db)
                _apply_schema(db)
                db.execute(
                    """INSERT INTO direct_projection_runs(
                         run_id,status,schema_version,input_manifest_sha256,
                         code_commit,code_bundle_sha256)
                       VALUES ('run','building','p07-direct-v3','i','c','b')"""
                )
                import_all(
                    db, Path("ledger"), Path("ledger/data/manual_v4.csv"),
                    Path("ledger/data/ota_mail_index.json"),
                )
                self.assertEqual(project_card_payments(db, "run"), 5328)
                package = materialize_current_card_evidence(db, "run")
                registry_count = int(db.execute(
                    "SELECT COUNT(*) FROM direct_promotion_evidence WHERE run_id='run'"
                ).fetchone()[0])
            finally:
                db.close()
        manifest = package["manifest"]
        self.assertEqual((manifest["event_count"], manifest["unique_event_count"]),
                         (5328, 5328))
        self.assertEqual(manifest["materialization_count"], 1)
        self.assertEqual(manifest["manual_evidence_count"], 0)
        self.assertEqual(manifest["historical_evidence_count"], 0)
        self.assertEqual(len(package["by_key"]), 5328)
        self.assertEqual(registry_count, 5328)


if __name__ == "__main__":
    unittest.main()
