from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledger.domain.ledger_db import (
    AllocationItem,
    DEFAULT_BOOKINGS,
    DEFAULT_CSV,
    DEFAULT_TRIPS,
    connect,
    import_legacy,
    replace_allocation_plan,
    review_report,
    validation_report,
)


class DomainLedgerIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tempdir.name) / "ledger.db"
        cls.db = connect(cls.db_path)
        cls.first = import_legacy(cls.db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls.tempdir.cleanup()

    def test_legacy_snapshot_preserves_count_and_total(self) -> None:
        report = validation_report(self.db)
        self.assertTrue(report["valid"])
        self.assertEqual(report["transactions"], 1705)
        self.assertEqual(report["active_allocations"], 1705)
        self.assertEqual(report["transaction_total_krw"], 310_719_899)
        self.assertEqual(report["allocation_total_krw"], 310_719_899)
        self.assertEqual(report["allocation_mismatches"], 0)

    def test_import_is_idempotent_for_same_snapshot(self) -> None:
        again = import_legacy(self.db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
        self.assertTrue(again.repeated_snapshot)
        self.assertEqual(again.transactions, self.first.transactions)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0],
            1705,
        )

    def test_payment_fact_does_not_contain_classification_columns(self) -> None:
        columns = {
            row[1]
            for row in self.db.execute("PRAGMA table_info(payment_transactions)").fetchall()
        }
        self.assertFalse({"bucket", "account", "confidence", "note"} & columns)
        decision_dimensions = {
            row[0]
            for row in self.db.execute(
                "SELECT DISTINCT dimension FROM current_classification_decisions"
            )
        }
        self.assertEqual(
            decision_dimensions,
            {
                "allocation_target",
                "expense_type",
                "cost_nature",
                "vat_treatment",
                "legacy_status",
            },
        )

    def test_booking_and_cancellation_are_explicit_relations(self) -> None:
        report = validation_report(self.db)
        self.assertGreater(report["bookings"], 0)
        self.assertGreater(report["transaction_relations"], 0)
        self.assertGreater(report["resolved_transaction_relations"], 0)

    def test_review_report_exposes_quality_separately_from_balance(self) -> None:
        report = review_report(self.db)
        # 현재 미배정 전체는 과거 9건 + MISC 중 현재 미배정 10건이다.
        # 핸드오프의 11건/1,478,413원은 MISC 생성 집합(이후 1건은 취소환불 이동)이다.
        self.assertEqual(report["unassigned_payments"], 19)
        self.assertEqual(report["unassigned_amount_krw"], 2_734_540)
        self.assertEqual(report["engine_isolated_payments"], 11)
        self.assertEqual(report["engine_isolated_amount_krw"], 1_478_413)
        self.assertGreater(report["high_confidence_with_uncertain_rationale"], 0)

    def test_foreign_keys_are_clean(self) -> None:
        violations = self.db.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(violations, [])

    def test_one_payment_can_be_reallocated_to_multiple_targets_as_a_plan(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "split.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                payment = db.execute(
                    """
                    SELECT id, amount_krw
                    FROM payment_transactions
                    WHERE amount_krw > 1
                    ORDER BY id LIMIT 1
                    """
                ).fetchone()
                targets = db.execute(
                    "SELECT id FROM allocation_targets ORDER BY id LIMIT 2"
                ).fetchall()
                first = payment["amount_krw"] // 2
                replace_allocation_plan(
                    db,
                    payment["id"],
                    [
                        AllocationItem(target_id=targets[0]["id"], amount_krw=first),
                        AllocationItem(
                            target_id=targets[1]["id"],
                            amount_krw=payment["amount_krw"] - first,
                        ),
                    ],
                    status="proposed",
                    confidence=0.7,
                )
                rows = db.execute(
                    "SELECT * FROM current_cost_allocations WHERE payment_id=?",
                    (payment["id"],),
                ).fetchall()
                self.assertEqual(len(rows), 2)
                self.assertEqual(sum(row["amount_krw"] for row in rows), payment["amount_krw"])
                self.assertEqual(validation_report(db)["allocation_mismatches"], 0)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
