from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_independent_evidence import materialize_current_card_evidence
from ledger.domain.direct_ota_reservation_authority import (
    project_ota_reservation_authority,
    validate_ota_reservation_authority,
)
from ledger.domain.direct_projection import (
    _apply_schema,
    project_card_payments,
    project_confirmed_full_axis_allocations,
)
from ledger.domain.direct_sources import (
    import_cards,
    import_ota_reservation_facts,
    import_trip_schedule,
)
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.transition_gates_v2 import _allocation_decision_gate


class DirectOtaReservationAuthorityTest(unittest.TestCase):
    def _fixture(self) -> tuple[sqlite3.Connection, str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        db = connect(Path(temporary.name) / "candidate.db")
        initialize(db)
        _apply_schema(db)
        run_id = "ota-authority-test"
        db.execute(
            """INSERT INTO direct_projection_runs(
                 run_id,status,schema_version,input_manifest_sha256,
                 code_commit,code_bundle_sha256)
               VALUES (?, 'building', 'p07-direct-v3', ?, ?, ?)""",
            (run_id, "a" * 64, "test", "b" * 64),
        )
        import_cards(db, Path("ledger"))
        import_trip_schedule(db, Path("ledger/data/trips.json"))
        import_ota_reservation_facts(
            db, Path("ledger/data/ota_event_links_verified.json")
        )
        project_card_payments(db, run_id)
        materialize_current_card_evidence(db, run_id)
        result = project_ota_reservation_authority(db, run_id)
        self.assertEqual(result["promoted_payment_count"], 5)
        project_confirmed_full_axis_allocations(db, run_id)
        self.assertTrue(
            validate_ota_reservation_authority(
                db, run_id, require_allocations=True
            )["passed"]
        )
        return db, run_id

    def test_gate5_rechecks_source_evidence_queue_decisions_and_allocations(self) -> None:
        db, run_id = self._fixture()

        def gate5_ota_passes() -> bool:
            result = _allocation_decision_gate(db, run_id)
            return bool(result["actual"]["ota_reservation_validation"]["passed"])

        self.assertTrue(gate5_ota_passes())

        source_row = db.execute(
            """SELECT payload_json FROM direct_source_records
               WHERE source_kind='ota_reservation_fact' AND source_key='KBO-2681'"""
        ).fetchone()
        original_payload = str(source_row[0])
        payload = json.loads(original_payload)
        payload["hotel"] = "tampered"
        db.execute(
            """UPDATE direct_source_records SET payload_json=?
               WHERE source_kind='ota_reservation_fact' AND source_key='KBO-2681'""",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True),),
        )
        self.assertFalse(gate5_ota_passes())
        db.execute(
            """UPDATE direct_source_records SET payload_json=?
               WHERE source_kind='ota_reservation_fact' AND source_key='KBO-2681'""",
            (original_payload,),
        )
        self.assertTrue(gate5_ota_passes())

        queue_row = db.execute(
            """SELECT detail_sha256 FROM direct_ota_reservation_queue
               WHERE run_id=? AND source_key='KBO-2701'""", (run_id,)
        ).fetchone()
        original_queue_hash = str(queue_row[0])
        db.execute(
            """UPDATE direct_ota_reservation_queue SET detail_sha256=?
               WHERE run_id=? AND source_key='KBO-2701'""",
            ("0" * 64, run_id),
        )
        self.assertFalse(gate5_ota_passes())
        db.execute(
            """UPDATE direct_ota_reservation_queue SET detail_sha256=?
               WHERE run_id=? AND source_key='KBO-2701'""",
            (original_queue_hash, run_id),
        )
        self.assertTrue(gate5_ota_passes())

        evidence_row = db.execute(
            """SELECT evidence_id,direct_event_key,source_key,source_sha256
               FROM direct_promotion_evidence
               WHERE run_id=? AND evidence_kind='verified_booking'
               ORDER BY evidence_id LIMIT 1""", (run_id,)
        ).fetchone()
        other_event = db.execute(
            """SELECT direct_event_key FROM direct_promotion_evidence
               WHERE run_id=? AND evidence_kind='current_card'
                 AND direct_event_key<>? ORDER BY direct_event_key LIMIT 1""",
            (run_id, str(evidence_row[1])),
        ).fetchone()
        current_binding = db.execute(
            """SELECT evidence_id,source_key,source_sha256
               FROM direct_promotion_evidence
               WHERE run_id=? AND evidence_kind='current_card'
                 AND direct_event_key=?""",
            (run_id, str(evidence_row[1])),
        ).fetchone()
        replacement_source = db.execute(
            """SELECT source_key,source_sha256
               FROM direct_promotion_evidence
               WHERE run_id=? AND evidence_kind='current_card'
                 AND source_key<>? ORDER BY source_key LIMIT 1""",
            (run_id, str(current_binding[1])),
        ).fetchone()
        original_current_source = (str(current_binding[1]), str(current_binding[2]))
        db.execute(
            """UPDATE direct_promotion_evidence
               SET source_key=?,source_sha256=?
               WHERE run_id=? AND evidence_id=?""",
            (
                str(replacement_source[0]), str(replacement_source[1]),
                run_id, str(current_binding[0]),
            ),
        )
        self.assertFalse(gate5_ota_passes())
        db.execute(
            """UPDATE direct_promotion_evidence
               SET source_key=?,source_sha256=?
               WHERE run_id=? AND evidence_id=?""",
            (
                original_current_source[0], original_current_source[1],
                run_id, str(current_binding[0]),
            ),
        )
        self.assertTrue(gate5_ota_passes())

        original_event = str(evidence_row[1])
        db.execute(
            """UPDATE direct_promotion_evidence SET direct_event_key=?
               WHERE run_id=? AND evidence_id=?""",
            (str(other_event[0]), run_id, str(evidence_row[0])),
        )
        self.assertFalse(gate5_ota_passes())
        db.execute(
            """UPDATE direct_promotion_evidence SET direct_event_key=?
               WHERE run_id=? AND evidence_id=?""",
            (original_event, run_id, str(evidence_row[0])),
        )
        self.assertTrue(gate5_ota_passes())

        decision_row = db.execute(
            """SELECT id,value FROM classification_decisions
               WHERE rule_id LIKE 'ota-reservation-current-card-unique-service-period-v1:%'
               ORDER BY id LIMIT 1"""
        ).fetchone()
        original_value = str(decision_row[1])
        db.execute(
            "UPDATE classification_decisions SET value=? WHERE id=?",
            (original_value + "_tampered", int(decision_row[0])),
        )
        self.assertFalse(gate5_ota_passes())
        db.execute(
            "UPDATE classification_decisions SET value=? WHERE id=?",
            (original_value, int(decision_row[0])),
        )
        self.assertTrue(gate5_ota_passes())

        allocation_row = db.execute(
            """SELECT a.id,a.amount_krw
               FROM current_cost_allocations a
               JOIN allocation_plans ap ON ap.id=a.plan_id
               JOIN classification_decisions d ON d.id=ap.source_decision_id
               WHERE d.rule_id LIKE 'ota-reservation-current-card-unique-service-period-v1:%'
               ORDER BY a.id LIMIT 1"""
        ).fetchone()
        original_amount = int(allocation_row[1])
        db.execute(
            "UPDATE cost_allocations SET amount_krw=? WHERE id=?",
            (original_amount + 1, int(allocation_row[0])),
        )
        self.assertFalse(gate5_ota_passes())
        db.execute(
            "UPDATE cost_allocations SET amount_krw=? WHERE id=?",
            (original_amount, int(allocation_row[0])),
        )
        self.assertTrue(gate5_ota_passes())
        db.close()


if __name__ == "__main__":
    unittest.main()
