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
    append_change_event,
    apply_p1_confidence_rules,
    apply_p3_unassigned_review,
    apply_p4_provider_rules,
    apply_p5_quality_audit,
    apply_change_log,
    build_review_snapshot,
    card_event_fingerprint,
    canonical_change_event,
    compare_review_snapshots,
    connect,
    import_legacy,
    replace_allocation_plan,
    review_details,
    review_report,
    regression_totals,
    rebuild_database,
    redact_sensitive_payload,
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
        self.assertEqual(report["transactions"], 1833)
        self.assertEqual(report["active_allocations"], 1833)
        self.assertEqual(report["transaction_total_krw"], 320_115_617)
        self.assertEqual(report["allocation_total_krw"], 320_115_617)
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
            1833,
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

    def test_card_event_fingerprint_is_stable_but_not_a_dedup_key(self) -> None:
        row = {
            "src": "KBD",
            "card4": "9800",
            "appr": "12345678",
            "use_date": "2026-07-25",
            "post_date": "2026-07-26",
            "merchant": "TRIP.COM",
            "currency": "KRW",
            "foreign": "0",
            "krw": "100000",
        }
        self.assertEqual(card_event_fingerprint(row), card_event_fingerprint(dict(row)))
        changed = dict(row, appr="12345679")
        self.assertNotEqual(card_event_fingerprint(row), card_event_fingerprint(changed))

    def test_sensitive_change_payload_is_redacted(self) -> None:
        redacted = redact_sensitive_payload({
            "pin": "2468",
            "email": "person@example.com",
            "note": "PIN번호: 1357 / 010-1234-5678",
            "booking_number": "1400111111111111",
        })
        serialized = json.dumps(redacted, ensure_ascii=False)
        self.assertNotIn("2468", serialized)
        self.assertNotIn("1357", serialized)
        self.assertNotIn("person@example.com", serialized)
        self.assertNotIn("010-1234-5678", serialized)
        self.assertIn("1400111111111111", serialized)

    def test_change_log_is_idempotent_and_rebuilds_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            first_db_path = root / "first.db"
            rebuilt_db_path = root / "rebuilt.db"
            change_log = root / "ledger_changes.jsonl"
            db = connect(first_db_path)
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                apply_p1_confidence_rules(db)
                apply_p3_unassigned_review(db)
                apply_p4_provider_rules(db)
                apply_p5_quality_audit(db)
                payment = db.execute(
                    """
                    SELECT external_key FROM payment_transactions
                    WHERE amount_krw > 0 ORDER BY id LIMIT 1
                    """
                ).fetchone()["external_key"]
                decision_event = {
                    "event_type": "classification_decision",
                    "target_type": "payment",
                    "target_key": payment,
                    "actor": "tester",
                    "payload": {
                        "dimension": "expense_type",
                        "value": "숙박비",
                        "confidence": 1.0,
                        "confidence_label": "상",
                        "status": "confirmed",
                        "rule_id": "manual_verified",
                        "rationale": "확정 person@example.com PIN번호: 2468",
                    },
                }
                booking_event = {
                    "event_type": "payment_booking_link",
                    "target_type": "payment",
                    "target_key": payment,
                    "actor": "tester",
                    "payload": {
                        "provider": "trip.com",
                        "booking_number": "1400999999999999",
                        "product_type": "lodging",
                        "status": "confirmed",
                    },
                }
                first_event = append_change_event(change_log, decision_event)
                first_recorded_at = first_event["recorded_at"]
                self.assertEqual(
                    first_event["event_id"],
                    append_change_event(change_log, decision_event)["event_id"],
                )
                self.assertEqual(
                    append_change_event(change_log, decision_event)["recorded_at"],
                    first_recorded_at,
                )
                append_change_event(change_log, booking_event)
                log_text = change_log.read_text(encoding="utf-8")
                self.assertNotIn("person@example.com", log_text)
                self.assertNotIn("2468", log_text)
                self.assertEqual(len(log_text.splitlines()), 2)

                self.assertEqual(apply_change_log(db, change_log), 2)
                self.assertEqual(apply_change_log(db, change_log), 0)
                first_hash = build_review_snapshot(db)["semantic_sha256"]
            finally:
                db.close()

            result = rebuild_database(
                rebuilt_db_path,
                DEFAULT_CSV,
                DEFAULT_TRIPS,
                DEFAULT_BOOKINGS,
                change_log,
            )
            self.assertEqual(result["applied_changes"], 2)
            rebuilt = connect(rebuilt_db_path)
            try:
                self.assertEqual(
                    build_review_snapshot(rebuilt)["semantic_sha256"],
                    first_hash,
                )
                decision = rebuilt.execute(
                    """
                    SELECT decision_status, rule_id
                    FROM current_classification_decisions d
                    JOIN payment_transactions p ON p.id=d.target_id
                    WHERE d.target_type='payment'
                      AND p.external_key=?
                      AND d.dimension='expense_type'
                    """,
                    (payment,),
                ).fetchone()
                self.assertEqual(tuple(decision), ("confirmed", "manual_verified"))
                link = rebuilt.execute(
                    """
                    SELECT pbl.link_status
                    FROM current_payment_booking_links pbl
                    JOIN payment_transactions p ON p.id=pbl.payment_id
                    JOIN bookings b ON b.id=pbl.booking_id
                    WHERE p.external_key=? AND b.booking_number='1400999999999999'
                    """,
                    (payment,),
                ).fetchone()
                self.assertEqual(link["link_status"], "confirmed")
            finally:
                rebuilt.close()

    def test_tampered_change_log_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            change_log = root / "ledger_changes.jsonl"
            db = connect(root / "ledger.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                payment = db.execute(
                    "SELECT external_key FROM payment_transactions ORDER BY id LIMIT 1"
                ).fetchone()["external_key"]
                append_change_event(change_log, {
                    "event_type": "classification_decision",
                    "target_type": "payment",
                    "target_key": payment,
                    "payload": {
                        "dimension": "expense_type",
                        "value": "숙박비",
                    },
                })
                tampered = change_log.read_text(encoding="utf-8").replace(
                    '"숙박비"', '"항공료"'
                )
                change_log.write_text(tampered, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "무결성 오류"):
                    apply_change_log(db, change_log)
            finally:
                db.close()

    def test_change_log_with_unsanitized_sensitive_data_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            change_log = root / "ledger_changes.jsonl"
            db = connect(root / "ledger.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                payment = db.execute(
                    "SELECT external_key FROM payment_transactions ORDER BY id LIMIT 1"
                ).fetchone()["external_key"]
                event = canonical_change_event({
                    "event_type": "classification_decision",
                    "target_type": "payment",
                    "target_key": payment,
                    "payload": {
                        "dimension": "expense_type",
                        "value": "숙박비",
                    },
                })
                event["payload"]["rationale"] = "PIN번호: 2468"
                change_log.write_text(
                    json.dumps(event, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "민감정보"):
                    apply_change_log(db, change_log)
            finally:
                db.close()

    def test_outdated_projection_db_requires_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "old.db")
            try:
                db.execute(
                    """
                    CREATE TABLE payment_transactions (
                        id INTEGER PRIMARY KEY,
                        external_key TEXT NOT NULL UNIQUE
                    )
                    """
                )
                db.commit()
                with self.assertRaisesRegex(RuntimeError, "rebuild"):
                    from ledger.domain.ledger_db import initialize
                    initialize(db)
            finally:
                db.close()

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

    def test_every_unlinked_refund_has_an_explicit_resolution_reason(self) -> None:
        report = validation_report(self.db)
        self.assertEqual(report["unexplained_transaction_relations"], 0)
        self.assertGreater(report["outside_window_transaction_relations"], 0)
        self.assertGreater(report["insufficient_evidence_transaction_relations"], 0)

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

    def test_p1_confidence_rules_version_conflicts_and_clear_the_queue(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "p1.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                result = apply_p1_confidence_rules(db)
                self.assertEqual(result["remaining_high_confidence_uncertain"], 0)
                self.assertEqual(
                    review_report(db)["high_confidence_with_uncertain_rationale"],
                    0,
                )
                self.assertTrue(validation_report(db)["valid"])
                self.assertGreater(
                    db.execute(
                        """
                        SELECT COUNT(*) FROM classification_decisions
                        WHERE superseded_by_id IS NOT NULL
                        """
                    ).fetchone()[0],
                    0,
                )
            finally:
                db.close()

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
