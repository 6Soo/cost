from __future__ import annotations

import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from ledger.domain.ledger_db import (
    AllocationItem,
    DEFAULT_BOOKINGS,
    DEFAULT_CSV,
    DEFAULT_DB,
    DEFAULT_TRIPS,
    LEDGER_DIR,
    REVIEW_QUEUE_METRICS,
    build_review_snapshot,
    compare_review_snapshots,
    connect,
    import_legacy,
    replace_allocation_plan,
    review_details,
    review_report,
    regression_totals,
    validation_report,
    write_review_snapshot,
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
        versions_before = self.db.execute(
            "SELECT COUNT(*) FROM payment_transaction_versions"
        ).fetchone()[0]
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
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM payment_transaction_versions"
            ).fetchone()[0],
            versions_before,
        )

    def test_default_runtime_db_is_outside_repository_data(self) -> None:
        self.assertNotEqual(DEFAULT_DB, LEDGER_DIR / "data" / "ledger_v2.db")

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

    def test_negative_events_distinguish_full_cancellation_and_partial_refund(self) -> None:
        full = self.db.execute(
            """
            SELECT COUNT(*)
            FROM transaction_relations r
            JOIN payment_transactions p ON p.id=r.transaction_id
            WHERE r.relation_type='cancels'
              AND r.relation_status NOT IN ('rejected', 'superseded')
              AND p.transaction_type='cancellation'
            """
        ).fetchone()[0]
        partial = self.db.execute(
            """
            SELECT COUNT(*)
            FROM transaction_relations r
            JOIN payment_transactions p ON p.id=r.transaction_id
            WHERE r.relation_type='refunds'
              AND r.relation_status NOT IN ('rejected', 'superseded')
              AND p.transaction_type='refund'
            """
        ).fetchone()[0]
        self.assertGreater(full, 0)
        self.assertGreater(partial, 0)
        missing_reference = self.db.execute(
            """
            SELECT COUNT(*)
            FROM transaction_relations
            WHERE match_method='missing_original_reference'
              AND related_transaction_id IS NULL
              AND relation_status NOT IN ('rejected', 'superseded')
            """
        ).fetchone()[0]
        self.assertGreater(missing_reference, 0)

    def test_changed_snapshot_versions_facts_and_supersedes_removed_booking_link(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            db = connect(root / "versioned.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                with DEFAULT_CSV.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                    fieldnames = list(rows[0])

                changed = next(
                    row for row in rows
                    if re.search(r"(?<!\d)1400\d{12}(?!\d)", row.get("note", ""))
                    and int(round(float(row.get("krw") or 0))) > 0
                )
                uid = changed["uid"]
                booking_number = re.search(
                    r"(?<!\d)(1400\d{12})(?!\d)",
                    changed["note"],
                ).group(1)
                original_amount = int(round(float(changed["krw"])))
                changed["krw"] = str(original_amount + 1)
                changed["note"] = changed["note"].replace(booking_number, "")

                second_csv = root / "classified_v14_changed.csv"
                with second_csv.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                import_legacy(db, second_csv, DEFAULT_TRIPS, DEFAULT_BOOKINGS)

                payment = db.execute(
                    """
                    SELECT id, amount_krw, record_version
                    FROM payment_transactions WHERE external_key=?
                    """,
                    (uid,),
                ).fetchone()
                versions = db.execute(
                    """
                    SELECT amount_krw
                    FROM payment_transaction_versions
                    WHERE transaction_id=?
                    ORDER BY record_version
                    """,
                    (payment["id"],),
                ).fetchall()
                self.assertEqual(payment["amount_krw"], original_amount + 1)
                self.assertGreaterEqual(payment["record_version"], 2)
                self.assertEqual(
                    [row["amount_krw"] for row in versions][-2:],
                    [original_amount, original_amount + 1],
                )

                stale_link = db.execute(
                    """
                    SELECT pbl.link_status
                    FROM payment_booking_links pbl
                    JOIN bookings b ON b.id=pbl.booking_id
                    WHERE pbl.payment_id=? AND b.booking_number=?
                    """,
                    (payment["id"], booking_number),
                ).fetchone()
                self.assertIsNotNone(stale_link)
                self.assertEqual(stale_link["link_status"], "superseded")
            finally:
                db.close()

    def test_review_report_exposes_quality_separately_from_balance(self) -> None:
        report = review_report(self.db)
        # 현재 미배정 전체는 과거 9건 + MISC 중 현재 미배정 10건이다.
        # 핸드오프의 11건/1,478,413원은 MISC 생성 집합(이후 1건은 취소환불 이동)이다.
        self.assertEqual(report["unassigned_payments"], 19)
        self.assertEqual(report["unassigned_amount_krw"], 2_734_540)
        self.assertEqual(report["engine_isolated_payments"], 11)
        self.assertEqual(report["engine_isolated_amount_krw"], 1_478_413)
        self.assertGreater(report["high_confidence_with_uncertain_rationale"], 0)

    def test_review_details_reproduce_every_queue_count_and_amount(self) -> None:
        report = review_report(self.db)
        queues = review_details(self.db)
        self.assertEqual(set(queues), set(REVIEW_QUEUE_METRICS))
        for queue_name, metric_name in REVIEW_QUEUE_METRICS.items():
            self.assertEqual(
                len(queues[queue_name]),
                report[metric_name],
                queue_name,
            )
            entity_keys = [row["entity_key"] for row in queues[queue_name]]
            self.assertEqual(len(entity_keys), len(set(entity_keys)), queue_name)

        self.assertEqual(
            sum(row["review_amount_krw"] for row in queues["unassigned"]),
            report["unassigned_amount_krw"],
        )
        self.assertEqual(
            sum(row["review_amount_krw"] for row in queues["engine_isolated"]),
            report["engine_isolated_amount_krw"],
        )
        sample = queues["high_confidence_uncertain_rationale"][0]
        self.assertTrue(sample["payment_external_key"])
        self.assertTrue(sample["decision_values"])
        self.assertTrue(sample["decision_rule_ids"])
        self.assertTrue(sample["allocation_targets"])
        booking_sample = queues["unknown_booking_providers"][0]
        self.assertTrue(booking_sample["payment_external_key"])
        self.assertTrue(booking_sample["decision_values"])
        self.assertTrue(booking_sample["decision_rationales"])
        self.assertTrue(booking_sample["booking_numbers"])

    def test_regression_totals_preserve_target_and_account_totals(self) -> None:
        totals = regression_totals(self.db)
        transaction_total = validation_report(self.db)["transaction_total_krw"]
        self.assertEqual(
            sum(row["amount_krw"] for row in totals["allocation_targets"]),
            transaction_total,
        )
        self.assertEqual(
            sum(row["amount_krw"] for row in totals["accounts"]),
            transaction_total,
        )
        self.assertGreater(len(totals["trips"]), 0)

    def test_review_snapshot_is_repeatable_and_writes_diffable_artifacts(self) -> None:
        first = build_review_snapshot(self.db)
        repeated = build_review_snapshot(self.db)
        self.assertEqual(first["semantic_sha256"], repeated["semantic_sha256"])
        diff = compare_review_snapshots(repeated, first)
        self.assertTrue(diff["unchanged"])
        for values in diff["queues"].values():
            self.assertEqual(values["added_count"], 0)
            self.assertEqual(values["resolved_count"], 0)

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            first_dir = root / "first"
            repeated_dir = root / "repeated"
            write_review_snapshot(self.db, first_dir)
            result = write_review_snapshot(self.db, repeated_dir, first_dir)
            self.assertTrue(result["diff"]["unchanged"])
            manifest = json.loads(
                (first_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["semantic_sha256"], first["semantic_sha256"])
            self.assertTrue(manifest["inputs"][0]["sha256"])
            with (first_dir / "queues" / "unassigned.csv").open(
                encoding="utf-8-sig",
                newline="",
            ) as stream:
                self.assertEqual(
                    len(list(csv.DictReader(stream))),
                    review_report(self.db)["unassigned_payments"],
                )

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
