from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from ledger.domain.direct_current_cancellation_settlement import (
    _canonical,
    _sha,
    finalize_cancellation_settlement_manifest,
    project_current_cancellation_settlements,
    validate_cancellation_settlement_authorities,
    validate_cancellation_settlement_manifest,
)
from ledger.domain.direct_independent_evidence import (
    materialize_current_card_evidence,
)
from ledger.domain.direct_projection import (
    _apply_schema,
    project_card_payments,
    project_confirmed_full_axis_allocations,
)
from ledger.domain.direct_sources import _insert_source
from ledger.domain.ledger_db import initialize
from ledger.domain.transition_gates_v2 import _allocation_decision_gate


class CurrentCancellationSettlementTest(unittest.TestCase):
    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        initialize(db)
        _apply_schema(db)
        db.execute(
            """INSERT INTO direct_projection_runs(
                 run_id,status,schema_version,input_manifest_sha256,
                 code_commit,code_bundle_sha256)
               VALUES ('run','building','p07-direct-v3',?,'commit',?)""",
            ("a" * 64, "b" * 64),
        )
        _insert_source(db, "trip_schedule", "0101_테스트", {
            "tab": "0101_테스트", "mm": 1, "dd": 1,
            "region": "테스트", "window": 1,
        })
        return db

    def _event(
        self,
        db: sqlite3.Connection,
        index: int,
        *,
        source: str,
        amount: int,
        transaction_type: str,
        occurred_on: str,
        payload: dict[str, object],
        approval_number: str | None = None,
        merchant: str = "merchant",
        identity_status: str = "unique",
    ) -> None:
        source_key = f"{source}:fixture:{index}"
        full_payload = {"src": source, **payload}
        source_id, _ = _insert_source(db, "card_raw", source_key, full_payload)
        card_event_id = "card:" + hashlib.sha256(
            f"fixture-event:{index}".encode("utf-8")
        ).hexdigest()
        db.execute(
            """INSERT INTO direct_card_events(
                 source_record_id,card_event_id,generator_version,
                 identity_status,source_system,amount_krw,approval_number,
                 occurred_on,merchant)
               VALUES (?,?,'fixture-v1',?,?,?,?,?,?)""",
            (
                source_id, card_event_id, identity_status, source, amount,
                approval_number, occurred_on, merchant,
            ),
        )
        db.execute(
            """INSERT INTO direct_normalized_payments(
                 source_record_id,event_role,card_event_id,amount_krw,
                 transaction_type,normalization_version)
               VALUES (?,'single',?,?,?,'fixture-v1')""",
            (source_id, card_event_id, amount, transaction_type),
        )

    def _materialize(self, db: sqlite3.Connection, count: int) -> None:
        self.assertEqual(project_card_payments(db, "run"), count)
        with patch(
            "ledger.domain.direct_independent_evidence.EXPECTED_CURRENT_EVENT_COUNT",
            count,
        ):
            result = materialize_current_card_evidence(db, "run")
        self.assertEqual(result["manifest"]["event_count"], count)

    def _kbd_pair(
        self,
        db: sqlite3.Connection,
        *,
        purchase_amount: int = 100,
        reversal_amount: int = -100,
        purchase_day: str = "2026-04-01",
        reversal_day: str = "2026-04-02",
    ) -> None:
        self._event(
            db, 1, source="KBD", amount=purchase_amount,
            transaction_type="purchase", occurred_on=purchase_day,
            payload={"card4": "1234", "appr": "77777777"},
            approval_number="77777777",
        )
        self._event(
            db, 2, source="KBD", amount=reversal_amount,
            transaction_type="cancellation", occurred_on=reversal_day,
            payload={"card4": "1234", "orig_appr": "77777777"},
            approval_number="99999999",
        )

    def test_exact_pair_becomes_three_axis_terminal_and_sealed_manifest(self) -> None:
        db = self._db()
        try:
            self._kbd_pair(db)
            self._materialize(db, 2)
            self.assertEqual(project_current_cancellation_settlements(db, "run"), {
                "scope_payments": 2,
                "authorities": 1,
                "set_authorities": 0,
                "payments": 2,
                "decisions": 6,
                "withheld_payments": 0,
            })
            allocation = project_confirmed_full_axis_allocations(db, "run")
            self.assertEqual(
                (allocation["full_axis_payments"],
                 allocation["nontrip_full_axis_payments"]),
                (2, 2),
            )
            self.assertEqual(tuple(db.execute(
                """SELECT account,cost_type,allocation_target,net_krw
                   FROM direct_cancellation_settlement_authorities"""
            ).fetchone()), ("비용제외", "비용제외", "취소환불", 0))
            self.assertTrue(validate_cancellation_settlement_authorities(
                db, "run", require_terminal=True,
            )["passed"])
            finalize_cancellation_settlement_manifest(db, "run")
            self.assertTrue(
                validate_cancellation_settlement_manifest(db, "run")["passed"]
            )
            gate = _allocation_decision_gate(db, "run")
            self.assertEqual(
                (
                    gate["actual"]["terminal_complete_count"],
                    gate["actual"]["resolved_count"],
                    gate["actual"]["unresolved_count"],
                ),
                (2, 2, 0),
            )
            self.assertTrue(gate["passed"])
            manifest_row = db.execute(
                """SELECT state_sha256,payload_json
                   FROM direct_cancellation_settlement_manifests
                   WHERE run_id='run'"""
            ).fetchone()
            payload = json.loads(str(manifest_row["payload_json"]))
            payload["run_id"] = "other-run"
            payload["input_manifest_sha256"] = "f" * 64
            manifest_sha256 = _sha(payload)
            run_sha256 = _sha({
                "state_sha256": manifest_row["state_sha256"],
                "manifest_sha256": manifest_sha256,
            })
            db.execute(
                """UPDATE direct_cancellation_settlement_manifests
                   SET manifest_sha256=?,run_sha256=?,payload_json=?
                   WHERE run_id='run'""",
                (
                    manifest_sha256,
                    run_sha256,
                    _canonical(payload).decode("utf-8"),
                ),
            )
            tampered = validate_cancellation_settlement_manifest(db, "run")
            self.assertFalse(tampered["passed"])
            self.assertIn(
                "settlement_manifest_run_binding_mismatch", tampered["issues"]
            )
        finally:
            db.close()

    def test_negative_trip_refund_allocation_is_signed_and_gate5_detects_tamper(self) -> None:
        db = self._db()
        try:
            self._event(
                db, 1, source="KBD", amount=100,
                transaction_type="purchase", occurred_on="2026-01-01",
                payload={"card4": "1234", "appr": "77777777"},
                approval_number="77777777", merchant="Airbnb",
            )
            self._event(
                db, 2, source="KBD", amount=-100,
                transaction_type="refund", occurred_on="2026-01-02",
                payload={"card4": "1234", "orig_appr": "77777777"},
                approval_number="88888888", merchant="Airbnb",
            )
            self.assertEqual(project_card_payments(db, "run"), 2)
            db.execute("DROP VIEW current_independently_promoted_decisions")
            db.execute(
                """CREATE VIEW current_independently_promoted_decisions AS
                   SELECT 'run' AS run_id,d.id,d.target_type,d.target_id,
                          d.dimension,d.value,d.confidence,d.confidence_label,
                          d.decision_status,d.rule_id,d.rationale,
                          NULL AS derivation_id,NULL AS current_evidence_id,
                          NULL AS independent_evidence_id
                   FROM classification_decisions d
                   WHERE d.target_type='payment'
                     AND d.decision_status='confirmed'"""
            )
            payment_ids = [
                int(row[0]) for row in db.execute(
                    """SELECT payment_id
                       FROM direct_payment_projection_links
                       WHERE run_id='run' ORDER BY payment_id"""
                ).fetchall()
            ]
            for payment_id in payment_ids:
                for dimension, value in (
                    ("account", "숙박비"),
                    ("cost_type", "여행원가"),
                    ("allocation_target", "0101_테스트"),
                ):
                    db.execute(
                        """INSERT INTO classification_decisions(
                             target_type,target_id,dimension,value,confidence,
                             confidence_label,decision_status,rule_id,rationale)
                           VALUES ('payment',?,?,?,?,?,'confirmed',?,?)""",
                        (
                            payment_id, dimension, value, 0.99, "test",
                            "negative-reversal-regression-v1",
                            "signed reversal allocation regression",
                        ),
                    )
            allocation = project_confirmed_full_axis_allocations(db, "run")
            self.assertEqual(allocation["allocations"], 2)
            amounts = [
                int(row[0]) for row in db.execute(
                    """SELECT a.amount_krw
                       FROM current_cost_allocations a
                       ORDER BY a.payment_id"""
                ).fetchall()
            ]
            self.assertEqual(amounts, [100, -100])
            self.assertEqual(
                [
                    tuple(row) for row in db.execute(
                        """SELECT difference_krw
                           FROM payment_allocation_summary
                           ORDER BY payment_id"""
                    ).fetchall()
                ],
                [(0,), (0,)],
            )
            gate = _allocation_decision_gate(db, "run")
            self.assertTrue(gate["passed"])
            self.assertEqual(gate["actual"]["unresolved_count"], 0)

            refund_id = payment_ids[1]
            db.execute(
                """UPDATE cost_allocations
                   SET amount_krw=-99
                   WHERE plan_id IN (
                       SELECT id FROM allocation_plans WHERE payment_id=?
                   )""",
                (refund_id,),
            )
            tampered_gate = _allocation_decision_gate(db, "run")
            self.assertFalse(tampered_gate["passed"])
            self.assertEqual(tampered_gate["actual"]["unresolved_count"], 1)
        finally:
            db.close()

    def test_reused_approval_is_withheld_as_one_open_component(self) -> None:
        db = self._db()
        try:
            self._kbd_pair(db)
            self._event(
                db, 3, source="KBD", amount=-100,
                transaction_type="cancellation", occurred_on="2026-04-03",
                payload={"card4": "1234", "orig_appr": "77777777"},
            )
            self._materialize(db, 3)
            result = project_current_cancellation_settlements(db, "run")
            self.assertEqual((result["payments"], result["withheld_payments"]), (0, 3))
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_cancellation_settlement_withheld
                   WHERE reason_code='component_cardinality_mismatch'"""
            ).fetchone()[0], 3)
        finally:
            db.close()

    def test_nonzero_and_reversed_date_components_are_withheld(self) -> None:
        for mode in ("nonzero", "date"):
            with self.subTest(mode=mode):
                db = self._db()
                try:
                    if mode == "nonzero":
                        self._kbd_pair(db, reversal_amount=-99)
                        expected = "component_net_nonzero"
                    else:
                        self._kbd_pair(
                            db, purchase_day="2026-04-03",
                            reversal_day="2026-04-02",
                        )
                        expected = "component_date_order_invalid"
                    self._materialize(db, 2)
                    result = project_current_cancellation_settlements(db, "run")
                    self.assertEqual(result["payments"], 0)
                    self.assertEqual(db.execute(
                        """SELECT COUNT(*)
                           FROM direct_cancellation_settlement_withheld
                           WHERE reason_code=?""",
                        (expected,),
                    ).fetchone()[0], 2)
                finally:
                    db.close()

    def test_kbo_equal_key_mn_is_set_authority_without_pair_claim(self) -> None:
        db = self._db()
        try:
            amounts = (100, 200, -150, -150)
            for index, amount in enumerate(amounts, start=1):
                self._event(
                    db, index, source="KBO", amount=amount,
                    transaction_type=("purchase" if amount > 0 else "refund"),
                    occurred_on=("2026-05-01" if amount > 0 else "2026-05-02"),
                    payload={
                        "card4": "4321", "currency": "JPY",
                        "foreign": "118800",
                    },
                    merchant="MINATOYA",
                )
            self._materialize(db, 4)
            result = project_current_cancellation_settlements(db, "run")
            self.assertEqual(
                (result["authorities"], result["set_authorities"],
                 result["payments"], result["decisions"]),
                (1, 1, 4, 12),
            )
            authority = db.execute(
                """SELECT authority_kind,individual_pair_asserted,
                          purchase_count,reversal_count,net_krw
                   FROM direct_cancellation_settlement_authorities"""
            ).fetchone()
            self.assertEqual(tuple(authority), ("kbo_exact_set", 0, 2, 2, 0))
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM transaction_relations").fetchone()[0],
                0,
            )
        finally:
            db.close()

    def test_kbo_one_to_one_still_does_not_claim_individual_pairing(self) -> None:
        db = self._db()
        try:
            for index, amount in enumerate((100, -100), start=1):
                self._event(
                    db, index, source="KBO", amount=amount,
                    transaction_type=("purchase" if amount > 0 else "refund"),
                    occurred_on=("2026-05-01" if amount > 0 else "2026-05-02"),
                    payload={
                        "card4": "4321", "currency": "JPY",
                        "foreign": "118800",
                    },
                    merchant="MINATOYA",
                )
            self._materialize(db, 2)
            result = project_current_cancellation_settlements(db, "run")
            self.assertEqual((result["set_authorities"], result["payments"]), (1, 2))
            self.assertEqual(db.execute(
                """SELECT individual_pair_asserted
                   FROM direct_cancellation_settlement_authorities"""
            ).fetchone()[0], 0)
        finally:
            db.close()

    def test_production_census_guard_includes_kbo_set_authority_count(self) -> None:
        db = self._db()
        try:
            self._kbd_pair(db)
            self._materialize(db, 2)
            with (
                patch(
                    "ledger.domain.direct_current_cancellation_settlement."
                    "PRODUCTION_SCOPE_COUNT", 2,
                ),
                patch(
                    "ledger.domain.direct_current_cancellation_settlement."
                    "PRODUCTION_AUTHORITY_COUNT", 1,
                ),
                patch(
                    "ledger.domain.direct_current_cancellation_settlement."
                    "PRODUCTION_SET_AUTHORITY_COUNT", 1,
                ),
                patch(
                    "ledger.domain.direct_current_cancellation_settlement."
                    "PRODUCTION_ACCEPTED_MEMBER_COUNT", 2,
                ),
                self.assertRaisesRegex(
                    ValueError, "settlement_production_census_drift",
                ),
            ):
                project_current_cancellation_settlements(db, "run")
        finally:
            db.close()

    def test_source_payload_tamper_and_axis_tamper_are_detected(self) -> None:
        db = self._db()
        try:
            self._kbd_pair(db)
            self._materialize(db, 2)
            project_current_cancellation_settlements(db, "run")
            project_confirmed_full_axis_allocations(db, "run")
            finalize_cancellation_settlement_manifest(db, "run")
            db.execute(
                """UPDATE classification_decisions SET value='접대비'
                   WHERE id=(SELECT MIN(id) FROM classification_decisions
                             WHERE dimension='account')"""
            )
            self.assertFalse(validate_cancellation_settlement_authorities(
                db, "run", require_terminal=True,
            )["passed"])
            self.assertFalse(
                validate_cancellation_settlement_manifest(db, "run")["passed"]
            )
            db.execute(
                """UPDATE direct_source_records SET payload_json='{}'
                   WHERE source_kind='card_raw' AND source_key='KBD:fixture:1'"""
            )
            with self.assertRaisesRegex(
                ValueError, "settlement_current_source_binding_invalid",
            ):
                validate_cancellation_settlement_authorities(db, "run")
        finally:
            db.close()

    def test_projection_failure_rolls_back_partial_authority_state(self) -> None:
        db = self._db()
        try:
            self._kbd_pair(db)
            self._materialize(db, 2)
            payment_id = int(db.execute(
                "SELECT payment_id FROM direct_payment_projection_links LIMIT 1"
            ).fetchone()[0])
            db.execute(
                """INSERT INTO classification_decisions(
                     target_type,target_id,dimension,value,confidence,
                     confidence_label,decision_status,rule_id,rationale)
                   VALUES ('payment',?,'account','기존값',1.0,'fixture',
                           'confirmed','fixture','fixture')""",
                (payment_id,),
            )
            with self.assertRaisesRegex(
                ValueError, "settlement_existing_decision_conflict",
            ):
                project_current_cancellation_settlements(db, "run")
            for table in (
                "direct_cancellation_settlement_authorities",
                "direct_cancellation_settlement_members",
                "direct_cancellation_settlement_derivations",
                "direct_cancellation_settlement_decision_bindings",
                "direct_cancellation_settlement_withheld",
            ):
                self.assertEqual(
                    db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM classification_decisions").fetchone()[0],
                1,
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
