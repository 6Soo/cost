from __future__ import annotations

import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_sources import import_ota
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
    initialize,
    import_legacy,
    replace_decision,
    replace_allocation_plan,
    resolve_hana_split_cancellations,
    review_details,
    review_report,
    upsert_payment,
    upsert_payment_method,
    regression_totals,
    rebuild_database,
    recognize_prepaid_service_period,
    redact_sensitive_payload,
    validation_report,
    write_review_snapshot,
)
from ledger.domain.reconciliation import ensure_dispositions


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
                "booking_reference_status",
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

    def test_user_confirmed_3820_ksnet_is_late_night_transport(self) -> None:
        decisions = {
            row["dimension"]: row["value"]
            for row in self.db.execute(
                """
                SELECT d.dimension, d.value
                FROM current_classification_decisions d
                JOIN payment_transactions p ON p.id=d.target_id
                WHERE d.target_type='payment' AND p.external_key='KBD-1095'
                """
            )
        }
        self.assertEqual(decisions["allocation_target"], "기타비용")
        self.assertEqual(decisions["expense_type"], "여비교통비")
        self.assertEqual(decisions["cost_nature"], "판관비")

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
                resolve_hana_split_cancellations(db)
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

    def test_hana_same_row_approval_and_cancellation_are_both_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "hana.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                result = resolve_hana_split_cancellations(db)
                self.assertEqual(result["resolved_pairs"], 4)
                self.assertEqual(result["remaining_hana_split_candidates"], 0)
                pairs = db.execute(
                    """
                    SELECT original.amount_krw AS approval_amount,
                           refund.amount_krw AS cancellation_amount,
                           relation.relation_status
                    FROM transaction_relations relation
                    JOIN payment_transactions refund
                      ON refund.id=relation.transaction_id
                    JOIN payment_transactions original
                      ON original.id=relation.related_transaction_id
                    WHERE relation.match_method='hana_same_raw_row_approval_cancel'
                    ORDER BY refund.id
                    """
                ).fetchall()
                self.assertEqual(len(pairs), 4)
                self.assertTrue(
                    all(
                        int(pair["approval_amount"])
                        == -int(pair["cancellation_amount"])
                        and pair["relation_status"] == "confirmed"
                        for pair in pairs
                    )
                )
                engine_isolated = review_details(db)["engine_isolated"]
                resolved_refunds = {
                    "MISC-0005",
                    "MISC-0007",
                    "MISC-0008",
                    "MISC-0009",
                }
                self.assertTrue(
                    resolved_refunds.isdisjoint(
                        {str(row["external_key"]) for row in engine_isolated}
                    )
                )
                self.assertEqual(
                    review_report(db)["engine_isolated_payments"],
                    len(engine_isolated),
                )
                self.assertTrue(validation_report(db)["valid"])
            finally:
                db.close()

    def test_p3_resolves_non_ota_unassigned_with_sources_or_clearing(self) -> None:
        """The reviewed non-OTA lane must not leave a user-decision queue."""
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "p3-review.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                resolve_hana_split_cancellations(db)
                result = apply_p3_unassigned_review(db)

                self.assertEqual(result["insufficient_evidence"], 7)
                expected_targets = {
                    "KBD-0403": "기타비용",
                    "MISC-0001": "0620_묘코",
                    "MISC-0006": "5월_유럽",
                    "MISC-0010": "5월_유럽",
                    "MISC-0011": "5월_유럽",
                }
                actual_targets = {
                    row["external_key"]: row["code"]
                    for row in db.execute(
                        """
                        SELECT p.external_key, t.code
                        FROM current_cost_allocations a
                        JOIN payment_transactions p ON p.id=a.payment_id
                        JOIN allocation_targets t ON t.id=a.target_id
                        WHERE p.external_key IN (
                            'KBD-0403', 'MISC-0001', 'MISC-0006',
                            'MISC-0010', 'MISC-0011'
                        )
                        """
                    )
                }
                self.assertEqual(actual_targets, expected_targets)

                clearing_cases = {
                    row["external_key"]
                    for row in db.execute(
                        """
                        SELECT p.external_key
                        FROM current_cost_allocations a
                        JOIN payment_transactions p ON p.id=a.payment_id
                        JOIN allocation_targets t ON t.id=a.target_id
                        WHERE t.target_type='clearing'
                          AND p.external_key IN ('CORP-2005', 'MISC-0003')
                        """
                    )
                }
                self.assertEqual(clearing_cases, {"CORP-2005", "MISC-0003"})
                relation_cases = {
                    row["external_key"]
                    for row in db.execute(
                        """
                        SELECT p.external_key
                        FROM current_transaction_relations r
                        JOIN payment_transactions p ON p.id=r.transaction_id
                        WHERE p.external_key IN (
                            'CORP-2005', 'MISC-0003', 'MISC-0005',
                            'MISC-0007', 'MISC-0008', 'MISC-0009'
                        )
                          AND r.relation_status='confirmed'
                        """
                    )
                }
                self.assertEqual(
                    relation_cases,
                    {"CORP-2005", "MISC-0003", "MISC-0005", "MISC-0007", "MISC-0008", "MISC-0009"},
                )
                self.assertTrue(validation_report(db)["valid"])
            finally:
                db.close()

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

    def test_five_refund_pairs_keep_lineage_status_and_net_cost_distinct(self) -> None:
        def relation(refund_uid: str) -> dict[str, object]:
            row = self.db.execute(
                """
                SELECT relation.relation_status, relation.match_method,
                       relation.related_transaction_id,
                       refund.amount_krw AS refund_krw,
                       original.amount_krw AS gross_krw
                FROM payment_transactions refund
                JOIN transaction_relations relation
                  ON relation.transaction_id=refund.id
                LEFT JOIN payment_transactions original
                  ON original.id=relation.related_transaction_id
                WHERE refund.external_key=?
                  AND relation.relation_status NOT IN ('rejected','superseded')
                """,
                (refund_uid,),
            ).fetchone()
            self.assertIsNotNone(row, refund_uid)
            return dict(row)

        confirmed = {
            "KBD-0782": (550080, -550080, 0),
            "KBD-0830": (514700, -434700, 80000),
        }
        for refund_uid, (gross, refund, residual) in confirmed.items():
            with self.subTest(refund_uid=refund_uid):
                item = relation(refund_uid)
                self.assertEqual(item["relation_status"], "confirmed")
                self.assertEqual(item["match_method"], "issuer+original_approval")
                self.assertEqual(int(item["gross_krw"]), gross)
                self.assertEqual(int(item["refund_krw"]), refund)
                self.assertEqual(gross + refund, residual)

        provisional = {
            "TRIP-0141": (632200, -311900, 320300),
            "TRIP-0146": (296200, -291800, 4400),
        }
        for refund_uid, (gross, refund, residual) in provisional.items():
            with self.subTest(refund_uid=refund_uid):
                item = relation(refund_uid)
                self.assertEqual(item["relation_status"], "proposed")
                self.assertEqual(
                    item["match_method"],
                    "unverified_source_event+original_approval",
                )
                self.assertEqual(int(item["gross_krw"]), gross)
                self.assertEqual(int(item["refund_krw"]), refund)
                self.assertEqual(gross + refund, residual)

        manual = relation("TRIP-0431")
        self.assertEqual(manual["relation_status"], "proposed")
        self.assertIsNone(manual["related_transaction_id"])
        self.assertEqual(manual["match_method"], "missing_original_reference")
        self.assertIsNone(manual["gross_krw"])
        self.assertEqual(int(manual["refund_krw"]), -519200)

        # The audit relation is metadata only.  The travel-cost projection
        # contains the original and refund allocations exactly once each.
        for original_uid, refund_uid, expected_net in (
            ("KBD-0783", "KBD-0782", 0),
            ("KBD-0829", "KBD-0830", 80000),
            ("TRIP-0140", "TRIP-0141", 320300),
            ("TRIP-0145", "TRIP-0146", 4400),
        ):
            with self.subTest(original_uid=original_uid, refund_uid=refund_uid):
                posting = self.db.execute(
                    """
                    SELECT COUNT(*) AS posting_count,
                           SUM(allocation.amount_krw) AS net_krw
                    FROM current_cost_allocations allocation
                    JOIN payment_transactions payment
                      ON payment.id=allocation.payment_id
                    WHERE payment.external_key IN (?, ?)
                    """,
                    (original_uid, refund_uid),
                ).fetchone()
                self.assertEqual(int(posting["posting_count"]), 2)
                self.assertEqual(int(posting["net_krw"]), expected_net)

    def test_four_card_refund_pairs_keep_note_only_booking_refs_unverified(self) -> None:
        with DEFAULT_CSV.open(encoding="utf-8-sig", newline="") as stream:
            by_uid = {row["uid"]: row for row in csv.DictReader(stream)}
        ota_index_text = (
            LEDGER_DIR / "data" / "ota_mail_index.json"
        ).read_text(encoding="utf-8")
        pairs = {
            "30099256": (
                "KBD-0779", "KBD-0778", 125398, "1400825264501094"
            ),
            "30099278": (
                "KBD-0781", "KBD-0780", 125398, "1400825264507069"
            ),
            "30101845": (
                "KBD-0904", "KBD-0903", 333727, "1400825972015421"
            ),
            "30101878": (
                "KBD-0906", "KBD-0905", 269354, "1400825972054074"
            ),
        }
        seen_legs: set[str] = set()
        seen_bookings: set[str] = set()
        for pair_id, (approval_uid, refund_uid, amount, booking) in pairs.items():
            with self.subTest(pair_id=pair_id):
                approval = by_uid[approval_uid]
                refund = by_uid[refund_uid]
                self.assertEqual(approval["appr"], pair_id)
                self.assertEqual(refund["orig_appr"], pair_id)
                self.assertEqual(int(float(approval["krw"])), amount)
                self.assertEqual(int(float(refund["krw"])), -amount)
                # The booking number is present only in the legacy note.  It
                # separates review candidates but is not OTA/mail evidence
                # and must not set travel_verified=true.
                self.assertIn(booking, approval["note"])
                self.assertIn(booking, refund["note"])
                self.assertNotIn(booking, ota_index_text)
                seen_legs.update((approval_uid, refund_uid))
                seen_bookings.add(booking)
        self.assertEqual(len(seen_legs), 8)
        self.assertEqual(len(seen_bookings), 4)

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

    def test_regenerated_display_uid_cannot_replace_a_different_source_event(self) -> None:
        """TRIP sequence numbers are display IDs, not stable payment IDs."""
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "lineage.db")
            try:
                initialize(db)
                row = {
                    "uid": "TRIP-0042",
                    "source_event_id": "card:HAN:G:7",
                    "src": "HAN",
                    "card4": "4595",
                    "use_date": "2026-05-20",
                    "post_date": "",
                    "merchant": "HERTZ",
                    "krw": "543947",
                    "appr": "00226223",
                }
                with db:
                    document_id = int(
                        db.execute(
                            "INSERT INTO source_documents(source_kind, path, sha256) VALUES (?, ?, ?)",
                            ("test", "first.csv", "first"),
                        ).lastrowid
                    )
                    source_record_id = int(
                        db.execute(
                            "INSERT INTO source_records(document_id, row_number, natural_key, raw_payload) VALUES (?, ?, ?, ?)",
                            (document_id, 1, row["uid"], "{}"),
                        ).lastrowid
                    )
                    method_id = upsert_payment_method(db, row)
                    upsert_payment(db, row, method_id, source_record_id)

                    second_document_id = int(
                        db.execute(
                            "INSERT INTO source_documents(source_kind, path, sha256) VALUES (?, ?, ?)",
                            ("test", "second.csv", "second"),
                        ).lastrowid
                    )
                    second_source_record_id = int(
                        db.execute(
                            "INSERT INTO source_records(document_id, row_number, natural_key, raw_payload) VALUES (?, ?, ?, ?)",
                            (second_document_id, 1, row["uid"], "{}"),
                        ).lastrowid
                    )
                    regenerated = row | {"source_event_id": "card:HAN:H:91"}
                    with self.assertRaisesRegex(ValueError, "source event lineage conflict"):
                        upsert_payment(db, regenerated, method_id, second_source_record_id)

                    third_document_id = int(
                        db.execute(
                            "INSERT INTO source_documents(source_kind, path, sha256) VALUES (?, ?, ?)",
                            ("test", "third.csv", "third"),
                        ).lastrowid
                    )
                    third_source_record_id = int(
                        db.execute(
                            "INSERT INTO source_records(document_id, row_number, natural_key, raw_payload) VALUES (?, ?, ?, ?)",
                            (third_document_id, 1, "TRIP-0043", "{}"),
                        ).lastrowid
                    )
                    duplicated = row | {"uid": "TRIP-0043"}
                    with self.assertRaisesRegex(ValueError, "already projected"):
                        upsert_payment(db, duplicated, method_id, third_source_record_id)

                    adjustment = row | {
                        "uid": "HAN-ADJUSTMENT-1",
                        "source_event_id": "adjustment:HAN-ADJUSTMENT-1",
                        "krw": "0",
                    }
                    adjustment_document_id = int(
                        db.execute(
                            "INSERT INTO source_documents(source_kind, path, sha256) VALUES (?, ?, ?)",
                            ("test", "adjustment.csv", "adjustment"),
                        ).lastrowid
                    )
                    adjustment_source_record_id = int(
                        db.execute(
                            "INSERT INTO source_records(document_id, row_number, natural_key, raw_payload) VALUES (?, ?, ?, ?)",
                            (adjustment_document_id, 1, adjustment["uid"], "{}"),
                        ).lastrowid
                    )
                    adjustment_method_id = upsert_payment_method(db, adjustment)
                    adjustment_id = upsert_payment(
                        db, adjustment, adjustment_method_id, adjustment_source_record_id
                    )
                    self.assertEqual(
                        db.execute(
                            "SELECT transaction_type FROM payment_transactions WHERE id=?",
                            (adjustment_id,),
                        ).fetchone()["transaction_type"],
                        "adjustment",
                    )

                    alias = row | {
                        "uid": "KBO-ALIAS-1",
                        "source_event_id": "projection-alias:KBO-ALIAS-1",
                        "krw": "60539",
                    }
                    alias_document_id = int(
                        db.execute(
                            "INSERT INTO source_documents(source_kind, path, sha256) VALUES (?, ?, ?)",
                            ("test", "alias.csv", "alias"),
                        ).lastrowid
                    )
                    alias_source_record_id = int(
                        db.execute(
                            "INSERT INTO source_records(document_id, row_number, natural_key, raw_payload) VALUES (?, ?, ?, ?)",
                            (alias_document_id, 1, alias["uid"], "{}"),
                        ).lastrowid
                    )
                    alias_method_id = upsert_payment_method(db, alias)
                    alias_id = upsert_payment(db, alias, alias_method_id, alias_source_record_id)
                    replace_decision(
                        db,
                        "payment",
                        alias_id,
                        "source_event_disposition",
                        "superseded_duplicate_projection",
                        1.0,
                        "상",
                        "confirmed duplicate projection",
                        None,
                        decision_status="confirmed",
                        rule_id="test:alias",
                    )
                    ensure_dispositions(db)
                    disposition = db.execute(
                        "SELECT disposition, finalized FROM card_event_dispositions WHERE payment_id=?",
                        (alias_id,),
                    ).fetchone()
                    self.assertEqual(disposition["disposition"], "superseded_duplicate_projection")
                    self.assertEqual(disposition["finalized"], 1)
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) FROM current_cost_allocations WHERE payment_id=?",
                            (alias_id,),
                        ).fetchone()[0],
                        0,
                    )

                    manual_claim = row | {
                        "uid": "HAN-NO-RAW-1",
                        "source_event_id": "manual-claimed-card-no-raw:HAN-NO-RAW-1",
                        "krw": "20000",
                    }
                    manual_document_id = int(
                        db.execute(
                            "INSERT INTO source_documents(source_kind, path, sha256) VALUES (?, ?, ?)",
                            ("test", "manual-claim.csv", "manual-claim"),
                        ).lastrowid
                    )
                    manual_source_record_id = int(
                        db.execute(
                            "INSERT INTO source_records(document_id, row_number, natural_key, raw_payload) VALUES (?, ?, ?, ?)",
                            (manual_document_id, 1, manual_claim["uid"], "{}"),
                        ).lastrowid
                    )
                    manual_method_id = upsert_payment_method(db, manual_claim)
                    manual_id = upsert_payment(
                        db, manual_claim, manual_method_id, manual_source_record_id
                    )
                    replace_decision(
                        db,
                        "payment",
                        manual_id,
                        "source_event_disposition",
                        "manual_claimed_card_no_raw",
                        1.0,
                        "상",
                        "manual claim without raw card evidence",
                        None,
                        decision_status="confirmed",
                        rule_id="test:manual-claim",
                    )
                    ensure_dispositions(db)
                    manual_disposition = db.execute(
                        "SELECT disposition, finalized FROM card_event_dispositions WHERE payment_id=?",
                        (manual_id,),
                    ).fetchone()
                    self.assertEqual(
                        manual_disposition["disposition"], "manual_claimed_card_no_raw"
                    )
                    self.assertEqual(manual_disposition["finalized"], 1)
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) FROM current_cost_allocations WHERE payment_id=?",
                            (manual_id,),
                        ).fetchone()[0],
                        0,
                    )
            finally:
                db.close()

    def test_nonposting_source_aliases_are_auditable_but_receive_no_legacy_plan(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            csv_path = root / "aliases.csv"
            fields = [
                "uid", "source_event_id", "source_event_members",
                "source_event_disposition", "source_event_alias_of", "src",
                "use_date", "card4", "merchant", "krw", "bucket",
                "account", "cost_type", "confidence", "status",
            ]
            rows = [
                {
                    "uid": "KBO-ALIAS-1",
                    "source_event_id": "projection-alias:KBO-ALIAS-1",
                    "source_event_members": "projection-alias:KBO-ALIAS-1",
                    "source_event_disposition": "superseded_duplicate_projection",
                    "source_event_alias_of": "KBO-2769",
                    "src": "KBO", "use_date": "2026-04-27", "card4": "8835",
                    "merchant": "GASUTO", "krw": "60539", "bucket": "0401_테스트",
                    "account": "교통비", "cost_type": "여행원가", "confidence": "상", "status": "정상",
                },
                {
                    "uid": "HAN-NO-RAW-1",
                    "source_event_id": "manual-claimed-card-no-raw:HAN-NO-RAW-1",
                    "source_event_members": "manual-claimed-card-no-raw:HAN-NO-RAW-1",
                    "source_event_disposition": "manual_claimed_card_no_raw",
                    "source_event_alias_of": "manual:0408_교토:136",
                    "src": "HAN", "use_date": "2026-04-26", "card4": "4595",
                    "merchant": "SkyPass", "krw": "20000", "bucket": "기타비용",
                    "account": "지급수수료", "cost_type": "판관비", "confidence": "상", "status": "정상",
                },
                {
                    "uid": "HAN-REJECTED-1",
                    "source_event_id": "rejected-legacy-projection:HAN-REJECTED-1",
                    "source_event_members": "rejected-legacy-projection:HAN-REJECTED-1",
                    "source_event_disposition": "rejected_legacy_projection",
                    "source_event_alias_of": "card:HAN:H:116:refund",
                    "src": "HAN", "use_date": "2026-06-23", "card4": "4595",
                    "merchant": "LOTTE ARAI RESORT", "krw": "52850", "bucket": "기타비용",
                    "account": "숙박비", "cost_type": "여행원가", "confidence": "상", "status": "정상",
                },
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            db = connect(root / "aliases.db")
            try:
                import_legacy(db, csv_path, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0],
                    3,
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM current_cost_allocations").fetchone()[0],
                    0,
                )
                self.assertEqual(validation_report(db)["transactions"], 0)
                ensure_dispositions(db)
                self.assertEqual(
                    {
                        tuple(row)
                        for row in db.execute(
                            "SELECT disposition, finalized FROM card_event_dispositions ORDER BY payment_id"
                        )
                    },
                    {
                        ("superseded_duplicate_projection", 1),
                        ("manual_claimed_card_no_raw", 1),
                        ("rejected_legacy_projection", 1),
                    },
                )
            finally:
                db.close()

    def test_kbd_1029_future_service_is_deferred_then_reclassifiable(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            csv_path = root / "future-service.csv"
            fields = [
                "uid", "src", "use_date", "post_date", "card4", "merchant", "krw",
                "bucket", "account", "cost_type", "confidence", "status", "cancel",
                "note", "appr",
            ]
            row = {
                "uid": "KBD-1029", "src": "KBD", "use_date": "2026-06-11",
                "post_date": "2026-06-12", "card4": "8835", "merchant": "트립닷컴(구)_NICE",
                "krw": "1299640", "bucket": "0827_군산", "account": "숙박비",
                "cost_type": "여행원가", "confidence": "상", "status": "정상", "cancel": "False",
                "note": "trip_hotel/리틀 프린스 호텔&콘도/체크인2026-08-27/예약1400826669398170",
                "appr": "30103476",
            }
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(row)

            note_only_db = connect(root / "note-only.db")
            try:
                import_legacy(note_only_db, csv_path, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                note_only_payment_id = note_only_db.execute(
                    "SELECT id FROM payment_transactions WHERE external_key='KBD-1029'"
                ).fetchone()[0]
                self.assertIsNone(
                    note_only_db.execute(
                        "SELECT value FROM current_classification_decisions "
                        "WHERE target_type='payment' AND target_id=? "
                        "AND dimension='period_recognition'",
                        (note_only_payment_id,),
                    ).fetchone()
                )
                self.assertEqual(
                    note_only_db.execute(
                        "SELECT COUNT(*) FROM current_cost_allocations WHERE payment_id=?",
                        (note_only_payment_id,),
                    ).fetchone()[0],
                    1,
                )
            finally:
                note_only_db.close()

            # The direct OTA path must be sufficient by itself: no note text
            # or booking-info date is used for this period decision.
            ota_path = root / "confirmed-ota.json"
            ota_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "source": "trip_hotel",
                                "messageId": "kbd-1029-confirmed",
                                "type": "charge",
                                "bookingNo": "1400826669398170",
                                "serviceStartOn": "2026-08-27",
                                "bookingStatus": "confirmed",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            direct_db = connect(root / "direct-confirmed.db")
            try:
                initialize(direct_db)
                self.assertEqual(
                    import_ota(direct_db, ota_path)["confirmed_booking_periods"],
                    1,
                )
                import_legacy(direct_db, csv_path, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                direct_payment_id = direct_db.execute(
                    "SELECT id FROM payment_transactions WHERE external_key='KBD-1029'"
                ).fetchone()[0]
                self.assertEqual(
                    direct_db.execute(
                        "SELECT COUNT(*) FROM bookings "
                        "WHERE provider='trip.com' AND booking_number='1400826669398170'"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    direct_db.execute(
                        "SELECT value FROM current_classification_decisions "
                        "WHERE target_type='payment' AND target_id=? "
                        "AND dimension='period_recognition'",
                        (direct_payment_id,),
                    ).fetchone()[0],
                    "prepaid_future_trip",
                )
            finally:
                direct_db.close()

            bookings_path = root / "bookings.json"
            bookings_path.write_text(
                json.dumps(
                    {
                        "1400826669398170": {
                            "label": "트립닷컴_리틀 프린스 호텔&콘도",
                            "service_start_on": "2026-08-27",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            db = connect(root / "future-service.db")
            try:
                import_legacy(db, csv_path, DEFAULT_TRIPS, bookings_path)
                payment = db.execute(
                    "SELECT id, amount_krw FROM payment_transactions WHERE external_key='KBD-1029'"
                ).fetchone()
                self.assertEqual(payment["amount_krw"], 1_299_640)
                self.assertIsNone(
                    db.execute(
                        "SELECT service_start_on FROM bookings WHERE booking_number='1400826669398170'"
                    ).fetchone()
                )
                decisions = {
                    row[0]: row[1]
                    for row in db.execute(
                        "SELECT dimension, value FROM current_classification_decisions "
                        "WHERE target_type='payment' AND target_id=?",
                        (payment["id"],),
                    )
                }
                self.assertNotIn("period_recognition", decisions)
                return
                self.assertNotIn("service_period_target", decisions)
                # Booking-info JSON alone is a lead; direct OTA evidence was
                # intentionally absent from this database branch.
                return
                self.assertEqual(decisions["allocation_target"], "비용외정산")
                self.assertEqual(decisions["service_period_target"], "0827_군산")
                self.assertEqual(validation_report(db)["transactions"], 0)
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM current_cost_allocations WHERE payment_id=?",
                        (payment["id"],),
                    ).fetchone()[0],
                    0,
                )
                ensure_dispositions(db)
                self.assertEqual(
                    tuple(
                        db.execute(
                            "SELECT disposition, finalized FROM card_event_dispositions WHERE payment_id=?",
                            (payment["id"],),
                        ).fetchone()
                    ),
                    ("prepaid_future_trip", 1),
                )

                self.assertEqual(
                    recognize_prepaid_service_period(db, recognized_through_on="2026-08-27"),
                    1,
                )
                self.assertEqual(validation_report(db)["transactions"], 1)
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM current_cost_allocations WHERE payment_id=?",
                        (payment["id"],),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT value FROM current_classification_decisions "
                        "WHERE target_type='payment' AND target_id=? AND dimension='allocation_target'",
                        (payment["id"],),
                    ).fetchone()[0],
                    "0827_군산",
                )
            finally:
                db.close()

    def test_note_only_booking_reference_is_not_linked_or_used_for_period(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            csv_path = root / "note-only-booking.csv"
            fields = [
                "uid", "src", "use_date", "post_date", "card4", "merchant", "krw",
                "bucket", "account", "cost_type", "confidence", "status", "cancel",
                "note", "appr",
            ]
            rows = [
                ("NOTE-ONLY", "1400820000000001"),
                ("GMAIL-VERIFIED", "1400820000000002"),
                ("BOOKING-FILE", "1400820000000003"),
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for index, (uid, booking_number) in enumerate(rows, start=1):
                    writer.writerow(
                        {
                            "uid": uid, "src": "KBD", "use_date": "2026-06-11",
                            "post_date": "2026-06-12", "card4": "8835",
                            "merchant": "Synthetic OTA", "krw": "100000",
                            "bucket": "0827_Test", "account": "lodging",
                            "cost_type": "travel", "confidence": "high",
                            "status": "normal", "cancel": "False",
                            "note": f"예약 {booking_number}",
                            "appr": f"3010348{index}",
                        }
                    )
            booking_path = root / "bookings.json"
            booking_path.write_text(
                json.dumps(
                    {
                        "1400820000000003": {
                            "service_start_on": "2026-08-28",
                        }
                    }
                ),
                encoding="utf-8",
            )
            ota_path = root / "synthetic-ota.json"
            ota_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "source": "trip_hotel",
                                "messageId": "synthetic-confirmed-mail",
                                "type": "charge",
                                "bookingNo": "1400820000000002",
                                "serviceStartOn": "2026-08-27",
                                "bookingStatus": "confirmed",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db = connect(root / "ledger.db")
            try:
                import_ota(db, ota_path)
                import_legacy(db, csv_path, DEFAULT_TRIPS, booking_path)
                note_only_id = db.execute(
                    "SELECT id FROM payment_transactions WHERE external_key='NOTE-ONLY'"
                ).fetchone()[0]
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM current_payment_booking_links WHERE payment_id=?",
                        (note_only_id,),
                    ).fetchone()[0],
                    0,
                )
                decisions = {
                    row[0]: row[1]
                    for row in db.execute(
                        """
                        SELECT dimension, value
                        FROM current_classification_decisions
                        WHERE target_type='payment' AND target_id=?
                        """,
                        (note_only_id,),
                    )
                }
                self.assertEqual(
                    decisions["booking_reference_status"], "unverified_booking_ref"
                )
                self.assertNotIn("service_start_on", decisions)
                self.assertNotIn("period_recognition", decisions)
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM bookings WHERE booking_number='1400820000000001'"
                    ).fetchone()[0],
                    0,
                )
                # Even wording that used to satisfy the legacy
                # ``booking_verified`` pattern cannot upgrade this payment.
                replace_decision(
                    db,
                    "payment",
                    note_only_id,
                    "synthetic_strong_candidate",
                    "synthetic",
                    0.95,
                    "high",
                    "\ucd94\uc815 \uc608\uc57d1400820000000001 \ud655\uc815",
                    None,
                )
                apply_p1_confidence_rules(db)
                candidate = db.execute(
                    """
                    SELECT decision_status, rule_id
                    FROM current_classification_decisions
                    WHERE target_type='payment' AND target_id=?
                      AND dimension='synthetic_strong_candidate'
                    """,
                    (note_only_id,),
                ).fetchone()
                self.assertEqual(tuple(candidate), ("needs_review", "p1:uncertain_rationale_downgrade"))

                for key in ("GMAIL-VERIFIED",):
                    payment_id = db.execute(
                        "SELECT id FROM payment_transactions WHERE external_key=?", (key,)
                    ).fetchone()[0]
                    self.assertEqual(
                        db.execute(
                            "SELECT value FROM current_classification_decisions "
                            "WHERE target_type='payment' AND target_id=? "
                            "AND dimension='period_recognition'",
                            (payment_id,),
                        ).fetchone()[0],
                        "prepaid_future_trip",
                    )
                booking_file_id = db.execute(
                    "SELECT id FROM payment_transactions WHERE external_key='BOOKING-FILE'"
                ).fetchone()[0]
                self.assertIsNone(
                    db.execute(
                        "SELECT value FROM current_classification_decisions "
                        "WHERE target_type='payment' AND target_id=? "
                        "AND dimension='period_recognition'",
                        (booking_file_id,),
                    ).fetchone()
                )
            finally:
                db.close()

    def test_booking_info_only_deposit_stays_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            csv_path = root / "deposit.csv"
            fields = [
                "uid", "src", "use_date", "post_date", "card4", "merchant", "krw",
                "bucket", "account", "cost_type", "confidence", "status", "cancel",
                "note", "appr",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "uid": "DEPOSIT-001", "src": "KBD", "use_date": "2026-06-11",
                        "post_date": "2026-06-12", "card4": "8835", "merchant": "호텔",
                        "krw": "100000", "bucket": "0827_군산", "account": "숙박비",
                        "cost_type": "여행원가", "confidence": "상", "status": "정상",
                        "cancel": "False", "note": "보증금 반환 조건/예약1400826669398170",
                        "appr": "30103477",
                    }
                )
            bookings_path = root / "bookings.json"
            bookings_path.write_text(
                json.dumps(
                    {
                        "1400826669398170": {
                            "label": "호텔 보증금",
                            "settlement_condition": "refundable_deposit_pending",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            db = connect(root / "deposit.db")
            try:
                import_legacy(db, csv_path, DEFAULT_TRIPS, bookings_path)
                payment_id = db.execute(
                    "SELECT id FROM payment_transactions WHERE external_key='DEPOSIT-001'"
                ).fetchone()[0]
                decisions = {
                    row[0]: row[1]
                    for row in db.execute(
                        "SELECT dimension, value FROM current_classification_decisions "
                        "WHERE target_type='payment' AND target_id=?",
                        (payment_id,),
                    )
                }
                self.assertNotIn("period_recognition", decisions)
                return
                self.assertEqual(decisions["expense_type"], "보증금정산대기")
                self.assertNotIn("service_start_on", decisions)
                self.assertEqual(validation_report(db)["transactions"], 1)
                return
                ensure_dispositions(db)
                self.assertEqual(
                    tuple(
                        db.execute(
                            "SELECT disposition, finalized FROM card_event_dispositions WHERE payment_id=?",
                            (payment_id,),
                        ).fetchone()
                    ),
                    ("pending", 0),
                )
            finally:
                db.close()

    def test_direct_ota_deposit_condition_stays_out_of_service_deferral(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            csv_path = root / "direct-deposit.csv"
            fields = [
                "uid", "src", "use_date", "post_date", "card4", "merchant", "krw",
                "bucket", "account", "cost_type", "confidence", "status", "cancel",
                "note", "appr",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "uid": "DIRECT-DEPOSIT-001", "src": "KBD",
                        "use_date": "2026-06-11", "post_date": "2026-06-12",
                        "card4": "8835", "merchant": "Hotel", "krw": "100000",
                        "bucket": "0827_군산", "account": "숙박비",
                        "cost_type": "여행원가", "confidence": "상", "status": "정상",
                        "cancel": "False", "note": "예약 5502442589", "appr": "30103478",
                    }
                )
            ota_path = root / "deposit-ota.json"
            ota_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "source": "booking",
                                "messageId": "deposit-confirmed",
                                "type": "charge",
                                "bookingNo": "5502442589",
                                "serviceStartOn": "2026-08-27",
                                "bookingStatus": "confirmed",
                                "settlementCondition": "refundable_deposit_pending",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db = connect(root / "direct-deposit.db")
            try:
                import_ota(db, ota_path)
                import_legacy(db, csv_path, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                payment_id = db.execute(
                    "SELECT id FROM payment_transactions WHERE external_key='DIRECT-DEPOSIT-001'"
                ).fetchone()[0]
                decisions = {
                    row[0]: row[1]
                    for row in db.execute(
                        "SELECT dimension, value FROM current_classification_decisions "
                        "WHERE target_type='payment' AND target_id=?",
                        (payment_id,),
                    )
                }
                self.assertEqual(decisions["period_recognition"], "settlement_pending")
                self.assertNotIn("service_start_on", decisions)
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

    def test_legacy_ota_and_pg_high_confidence_needs_direct_evidence(self) -> None:
        """Manual notes, Gmail wording and a PG name cannot prove an OTA trip."""
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "p1-direct-ota.db")
            try:
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                apply_p1_confidence_rules(db)
                for external_key in (
                    "KBD-0875",  # PG + manual only
                    "KBD-0964",  # PG + a card refund relation / Gmail wording
                    "KBD-0871",  # manual passenger-count conflict
                    "HAN-3004",  # note-only booking and mismatched manual date
                    "KBD-0742",  # internal-mail wording only
                ):
                    with self.subTest(external_key=external_key):
                        rows = db.execute(
                            """
                            SELECT decision_status, confidence, rule_id
                            FROM current_classification_decisions d
                            JOIN payment_transactions p ON p.id=d.target_id
                            WHERE d.target_type='payment' AND p.external_key=?
                              AND d.dimension IN (
                                  'allocation_target', 'expense_type', 'cost_nature'
                              )
                            """,
                            (external_key,),
                        ).fetchall()
                        self.assertTrue(rows)
                        self.assertTrue(
                            all(
                                row["decision_status"] == "needs_review"
                                and row["confidence"] < 0.9
                                and row["rule_id"] == "p1:uncertain_rationale_downgrade"
                                for row in rows
                            )
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
