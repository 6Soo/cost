from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_sources import (
    import_ota_records,
    reconcile_direct_ota_payment_evidence,
)
from ledger.domain.ledger_db import (
    AllocationItem,
    DEFAULT_CSV,
    LEDGER_DIR,
    connect,
    cli,
    initialize,
    replace_decision,
    replace_allocation_plan,
    resolve_hana_split_cancellations,
    validation_report,
)
from ledger.domain.reconciliation import (
    PeriodCloseBlocked,
    close_period,
    coverage_report,
    create_match_group,
    assess_insurance_trip_link,
    intersection_signals,
    project_direct_payments,
    reconcile_repeated_amount_ota_group,
    record_authorization_hold,
    record_match_decision,
    refund_balance,
    refund_case_disposition,
    refund_lifecycle_bundles,
    verification_dimensions,
    select_direct_receipt,
    resolve_authorization_hold,
    tax_assessment,
)


class ReconciliationInvariantTest(unittest.TestCase):
    def test_high_value_card_events_do_not_gain_travel_or_period_proof_from_titles_or_notes(self) -> None:
        # These five high-value cases have a card RAW event but fail the new
        # direct-receipt + three-axis OTA gate: KBD-1029 has no OTA record;
        # KBD-0388/0389/0390 are two distinct stay bundles; KBD-1021's note
        # conflicts; KBD-1058 has only Toss/manual equal amount; KBD-0741's
        # 312,100 OTA item is a different itinerary.
        weak_cases = {
            "KBD-1029": [],
            "KBD-0388-0390": [
                {
                    "name": "booking_number", "status": "match",
                    "left": "show-nai", "right": "show-nai",
                    "evidence": [{
                        "source_record_id": "booking-info:show-nai",
                        "source_type": "booking_info_only",
                        "attachment_state": "not_applicable",
                        "forwarded_state": "not_applicable",
                        "ota_field_loss_state": "not_applicable",
                        "extraction_source": "note",
                    }],
                },
            ],
            "KBD-1021": [{
                "name": "booking_number", "status": "mismatch",
                "left": "note-a", "right": "note-b", "evidence": [],
            }],
            "KBD-1058": [{
                "name": "amount", "status": "match", "left": "499200", "right": "499200",
                "evidence": [{"source_type": "manual_note", "source_record_id": "manual:trip", "attachment_state": "none", "forwarded_state": "not_forwarded", "ota_field_loss_state": "clear", "extraction_source": "note"}],
            }],
            "KBD-0741": [
                {
                    "name": "amount", "status": "mismatch",
                    "left": "1248400", "right": "312100",
                    "evidence": [{
                        "message_id": "different-itinerary", "source_type": "ota_mail",
                        "attachment_state": "none", "forwarded_state": "not_forwarded",
                        "ota_field_loss_state": "clear", "extraction_source": "gmail_body",
                    }],
                },
            ],
        }
        for label, signals in weak_cases.items():
            with self.subTest(label=label):
                dimensions = verification_dimensions(
                    card_source_event_ids=["card:KBO:E:900"], signal_rows=signals,
                )
                self.assertTrue(dimensions["card_verified"])
                self.assertFalse(dimensions["ota_verified"])
                self.assertFalse(dimensions["travel_verified"])
                self.assertFalse(dimensions["period_verified"])
                self.assertFalse(dimensions["strong_travel_classification_ready"])

    def test_trusted_ota_booking_and_service_boundaries_are_all_required_for_strong_travel(self) -> None:
        evidence = [{
            "message_id": "gmail-verified", "source_type": "ota_mail",
            "attachment_state": "present_read", "forwarded_state": "not_forwarded",
            "ota_field_loss_state": "clear", "extraction_source": "gmail_body",
        }]
        base = [
            {"name": "booking_number", "status": "match", "left": "B-1", "right": "B-1", "evidence": evidence},
            {"name": "amount", "status": "match", "left": "900000", "right": "900000", "evidence": evidence},
            {"name": "provider", "status": "match", "left": "trip.com", "right": "trip.com", "evidence": evidence},
            {"name": "product_type", "status": "match", "left": "lodging", "right": "lodging", "evidence": evidence},
            {"name": "service_start_on", "status": "match", "left": "2026-06-20", "right": "2026-06-20", "evidence": evidence},
            {"name": "service_end_on", "status": "match", "left": "2026-06-25", "right": "2026-06-25", "evidence": evidence},
        ]
        verified = verification_dimensions(
            card_source_event_ids=["card:KBD:F:10"], signal_rows=base,
        )
        self.assertEqual(
            verified,
            {
                "card_verified": True, "ota_verified": True,
                "travel_verified": True, "period_verified": True,
                "strong_travel_classification_ready": True,
            },
        )

    def test_payment_mail_and_separate_ticket_pnr_do_not_create_direct_lineage(self) -> None:
        def evidence(message_id: str) -> list[dict[str, str]]:
            return [{
                "message_id": message_id, "source_type": "ota_mail",
                "attachment_state": "none", "forwarded_state": "not_forwarded",
                "ota_field_loss_state": "clear", "extraction_source": "gmail_body",
            }]
        payment = evidence("payment-amount")
        ticket = evidence("ticket-pnr")
        rows = [
            {"name": "amount", "status": "match", "evidence": payment},
            {"name": "provider", "status": "match", "evidence": payment},
            {"name": "product_type", "status": "match", "evidence": payment},
            {"name": "pnr", "status": "match", "evidence": ticket},
            {"name": "service_start_on", "status": "match", "evidence": ticket},
            {"name": "service_end_on", "status": "match", "evidence": ticket},
        ]
        result = verification_dimensions(card_source_event_ids=["card:KBD:F:97"], signal_rows=rows)
        self.assertTrue(result["ota_verified"])
        self.assertTrue(result["travel_verified"])
        self.assertTrue(result["period_verified"])
        self.assertFalse(result["strong_travel_classification_ready"])
    def setUp(self) -> None:
        # Use a fresh in-memory database so schema and IDs are isolated per test.
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def _payment(self, key: str, amount: int, kind: str = "purchase") -> int:
        cur = self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint, source_system,
                amount_krw, transaction_type
            ) VALUES (?, ?, ?, 'TEST', ?, ?)
            """,
            (key, key, f"fp:{key}", amount, kind),
        )
        return int(cur.lastrowid)

    def _strong_signal(
        self,
        name: str,
        source_event_id: str,
        *,
        left: str = "REF-1",
        right: str = "REF-1",
        evidence: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "name": name,
            "status": "match",
            "left": left,
            "right": right,
            "source_event_id": source_event_id,
            "evidence": evidence
            if evidence is not None
            else [
                {
                    "source_record_id": "ota:test",
                    "attachment_state": "none",
                    "forwarded_state": "not_forwarded",
                    "amount_currency_state": "resolved",
                    "ota_field_loss_state": "clear",
                }
            ],
        }

    def _booking_payment_mail(
        self,
        message_id: str,
        booking_number: str,
        foreign_amount: str,
        *,
        card_last4: str = "8835",
    ) -> dict[str, object]:
        return {
            "provider": "booking.com",
            "source_channel": "mail",
            "message_id": message_id,
            "booking_number": booking_number,
            "product_type": "lodging",
            "merchant": "Test Hotel",
            "service_start_on": "2026-06-21",
            "service_end_on": "2026-06-22",
            "payment_date": "2026-06-20",
            "currency": "JPY",
            "foreign_amount": foreign_amount,
            "card_last4": card_last4,
            "record_type": "charge",
            "booking_confirmation_status": "confirmed",
            "status": "paid",
            "extraction_sources": ["message_body"],
        }

    def _booking_card_payment(
        self,
        key: str,
        foreign_amount: str,
        *,
        card_last4: str = "8835",
    ) -> int:
        method_id = self.db.execute(
            """
            INSERT INTO payment_methods(method_key, issuer, last4)
            VALUES (?, 'KBO', ?)
            """,
            (f"KBO:{card_last4}:{key}", card_last4),
        ).lastrowid
        return int(
            self.db.execute(
                """
                INSERT INTO payment_transactions(
                    external_key, source_event_id, identity_fingerprint,
                    payment_method_id, source_system, occurred_on, merchant,
                    currency, foreign_amount, amount_krw, transaction_type
                ) VALUES (?, ?, ?, ?, 'KBO', '2026-06-20',
                          'BKG*BOOKING.COM HOTEL', 'JPY', ?, 100000, 'purchase')
                """,
                (key, f"card:{key}", f"fp:{key}", method_id, foreign_amount),
            ).lastrowid
        )

    def test_direct_booking_payment_mail_confirms_only_unique_intersection(self) -> None:
        payment_id = self._booking_card_payment("KBO-UNIQUE", "63060")
        import_ota_records(
            self.db,
            [self._booking_payment_mail("mail-unique", "5838582477", "63060")],
        )
        result = reconcile_direct_ota_payment_evidence(self.db)
        self.assertEqual(result["confirmed_strong"], 1)
        self.assertEqual(result["conflict_records"], 0)
        row = self.db.execute(
            """
            SELECT g.status, pbl.link_status
            FROM current_match_group_projection g
            JOIN match_group_payments mgp ON mgp.group_id=g.group_id
            JOIN current_payment_booking_links pbl ON pbl.payment_id=mgp.payment_id
            WHERE mgp.payment_id=?
            """,
            (payment_id,),
        ).fetchone()
        self.assertEqual(dict(row), {
            "status": "confirmed_strong",
            "link_status": "confirmed",
        })

    def test_direct_booking_mail_accepts_confirmed_raw_link_for_legacy_payment(self) -> None:
        payment_id = self._booking_card_payment("KBO-LEGACY", "63060")
        self.db.execute(
            "UPDATE payment_transactions SET source_event_id='legacy:KBO-LEGACY' WHERE id=?",
            (payment_id,),
        )
        source_id = self.db.execute(
            """
            INSERT INTO direct_source_records(
                source_kind, source_key, source_sha256, payload_json
            ) VALUES ('card_raw', 'KBO:legacy', 'sha:kbo-legacy', '{}')
            """
        ).lastrowid
        direct_id = self.db.execute(
            """
            INSERT INTO direct_normalized_payments(
                source_record_id, event_role, card_event_id, amount_krw,
                transaction_type, normalization_version
            ) VALUES (?, 'single', 'card:KBO-LEGACY', 100000, 'purchase', 'v2')
            """,
            (source_id,),
        ).lastrowid
        self.db.execute(
            """
            INSERT INTO direct_payment_links(
                direct_payment_id, payment_id, link_status, reason_code
            ) VALUES (?, ?, 'confirmed', 'unique_exact_structure')
            """,
            (direct_id, payment_id),
        )
        import_ota_records(
            self.db,
            [self._booking_payment_mail("mail-legacy", "5838582477", "63060")],
        )
        result = reconcile_direct_ota_payment_evidence(self.db)
        self.assertEqual(result["confirmed_strong"], 1)
        self.assertEqual(
            self.db.execute(
                "SELECT link_status FROM current_payment_booking_links WHERE payment_id=?",
                (payment_id,),
            ).fetchone()[0],
            "confirmed",
        )

    def test_direct_booking_payment_mail_keeps_repeated_amount_as_nm_conflict(self) -> None:
        for index in range(2):
            self._booking_card_payment(f"KBO-REPEAT-{index}", "24000")
        import_ota_records(
            self.db,
            [
                self._booking_payment_mail("mail-repeat-1", "6474894255", "24000"),
                self._booking_payment_mail("mail-repeat-2", "5437691600", "24000"),
            ],
        )
        result = reconcile_direct_ota_payment_evidence(self.db)
        self.assertEqual(result["confirmed_strong"], 0)
        self.assertEqual(result["conflict_records"], 2)
        group = self.db.execute(
            """
            SELECT status,
                   (SELECT COUNT(*) FROM match_group_payments
                    WHERE group_id=g.group_id) AS payments,
                   (SELECT COUNT(*) FROM match_group_bookings
                    WHERE group_id=g.group_id) AS bookings
            FROM current_match_group_projection g
            WHERE group_key LIKE 'booking-direct-conflict:%'
            """
        ).fetchone()
        self.assertEqual(dict(group), {
            "status": "conflict",
            "payments": 2,
            "bookings": 2,
        })

    def test_card_coverage_is_lossless_only_after_final_allocation(self) -> None:
        payment_id = self._payment("CARD-1", 10000)
        target = self.db.execute(
            "INSERT INTO allocation_targets(target_type, code, name) VALUES ('trip', 'TRIP-1', '테스트여행')"
        ).lastrowid
        plan = self.db.execute(
            "INSERT INTO allocation_plans(payment_id, plan_version, plan_status, confidence) VALUES (?, 1, 'confirmed', 1.0)",
            (payment_id,),
        ).lastrowid
        self.db.execute(
            "INSERT INTO cost_allocations(plan_id, target_id, amount_krw) VALUES (?, ?, 10000)",
            (plan, target),
        )
        self.db.commit()
        report = coverage_report(self.db)
        self.assertTrue(report.lossless)
        self.assertEqual(report.pending_events, 0)

    def test_initialize_adds_match_signal_lineage_columns_without_rebuild(self) -> None:
        legacy = sqlite3.connect(":memory:")
        legacy.row_factory = sqlite3.Row
        legacy.executescript(
            """
            CREATE TABLE match_signal_results (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL,
                signal_name TEXT NOT NULL,
                signal_status TEXT NOT NULL,
                left_value TEXT,
                right_value TEXT,
                rule_id TEXT NOT NULL,
                UNIQUE(group_id, signal_name)
            );
            """
        )
        initialize(legacy)
        columns = {
            row["name"]
            for row in legacy.execute(
                "PRAGMA table_info(match_signal_results)"
            ).fetchall()
        }
        self.assertIn("source_event_id", columns)
        self.assertIn("evidence_json", columns)
        legacy.close()

    def test_match_group_cli_uses_same_strong_confirmation_rules(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db_path = Path(dirname) / "ledger.db"
            db = connect(db_path)
            initialize(db)
            payment_id = db.execute(
                """
                INSERT INTO payment_transactions(
                    external_key, source_event_id, identity_fingerprint,
                    source_system, amount_krw, transaction_type
                ) VALUES ('CLI-1', 'CLI-1', 'fp:CLI-1', 'TEST', 163788, 'purchase')
                """
            ).lastrowid
            db.commit()
            db.close()
            signal = self._strong_signal(
                "order_number",
                "CLI-1",
                left="1122-610-807 (1)",
                right="1122-610-807 (1)",
            )
            exit_code = cli(
                [
                    "--db",
                    str(db_path),
                    "upsert-match-group",
                    "--group-key",
                    "CLI-MYTRIP",
                    "--status",
                    "proposed",
                    "--payment-ids-json",
                    json.dumps([payment_id]),
                    "--signals-json",
                    json.dumps([signal], ensure_ascii=False),
                ]
            )
            self.assertEqual(exit_code, 0)
            staged = connect(db_path)
            group_id = int(
                staged.execute(
                    "SELECT id FROM match_groups WHERE group_key='CLI-MYTRIP'"
                ).fetchone()["id"]
            )
            staged.close()
            decision_exit = cli(
                [
                    "--db",
                    str(db_path),
                    "record-decision",
                    "--decision-id",
                    "CLI-MYTRIP-DECISION",
                    "--group-id",
                    str(group_id),
                    "--status",
                    "confirmed_strong",
                    "--actor",
                    "test",
                    "--reason-code",
                    "order_number_match",
                    "--rationale",
                    "원천 계보가 있는 주문번호 일치",
                ]
            )
            self.assertEqual(decision_exit, 0)
            verified = connect(db_path)
            row = verified.execute(
                "SELECT status FROM match_groups WHERE group_key='CLI-MYTRIP'"
            ).fetchone()
            self.assertEqual(row["status"], "confirmed_strong")
            verified.close()
            with self.assertRaises(ValueError):
                cli(
                    [
                        "--db",
                        str(db_path),
                        "upsert-match-group",
                        "--group-key",
                        "CLI-MYTRIP",
                        "--status",
                        "proposed",
                        "--signals-json",
                        "[]",
                    ]
                )
            successor_exit = cli(
                [
                    "--db",
                    str(db_path),
                    "record-decision",
                    "--decision-id",
                    "CLI-MYTRIP-CONFLICT",
                    "--group-id",
                    str(group_id),
                    "--status",
                    "conflict",
                    "--actor",
                    "test",
                    "--reason-code",
                    "new_conflict",
                    "--rationale",
                    "후속 충돌 발견",
                    "--supersedes",
                    "CLI-MYTRIP-DECISION",
                ]
            )
            self.assertEqual(successor_exit, 0)
            with self.assertRaises(ValueError):
                cli(
                    [
                        "--db",
                        str(db_path),
                        "upsert-match-group",
                        "--group-key",
                        "CLI-MANUAL-BYPASS",
                        "--status",
                        "confirmed_manual",
                    ]
                )

    def test_close_blocks_pending_event_and_persists_gate(self) -> None:
        self._payment("CARD-PENDING", 12000)
        with self.assertRaises(PeriodCloseBlocked):
            close_period(self.db, "run-pending", require_tax_evidence=False)
        row = self.db.execute(
            "SELECT passed FROM period_close_gates WHERE run_id='run-pending' AND gate_name='card_lossless'"
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_match_group_requires_no_conflicting_signal_for_strong_confirmation(self) -> None:
        payment_id = self._payment("CARD-MATCH", 15000)
        booking_id = self.db.execute(
            "INSERT INTO bookings(provider, booking_number) VALUES ('agoda', '1234567890')"
        ).lastrowid
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-CONFLICT",
                status="confirmed_strong",
                payment_ids=[payment_id],
                booking_ids=[booking_id],
                signals=[{"name": "amount", "status": "mismatch", "left": "15000", "right": "18000"}],
            )
        group_id = create_match_group(
            self.db,
            "GROUP-OK",
            status="confirmed_strong",
            confidence=1.0,
            payment_ids=[payment_id],
            booking_ids=[booking_id],
            signals=[
                self._strong_signal(
                    "booking_number",
                    "CARD-MATCH",
                    left="1234567890",
                    right="1234567890",
                )
            ],
        )
        self.assertTrue(record_match_decision(
            self.db, "DEC-1", group_id, status="confirmed_strong", actor="tester",
            reason_code="identifier_match", rationale="예약번호와 카드 관계 확인",
        ))
        self.assertFalse(record_match_decision(
            self.db, "DEC-1", group_id, status="confirmed_strong", actor="tester",
            reason_code="identifier_match", rationale="예약번호와 카드 관계 확인",
        ))
        with self.assertRaises(ValueError):
            record_match_decision(
                self.db,
                "DEC-1",
                group_id,
                status="confirmed_strong",
                actor="tester",
                reason_code="identifier_match",
                rationale="같은 ID의 다른 판정",
            )

    def test_intersection_signals_preserve_card_suffix_and_amount_conflicts(self) -> None:
        signals = intersection_signals(
            {
                "approval_number": "30057780",
                "card4": "4886",
                "amount_krw": 1404842,
            },
            {
                "approval_number": "30057780",
                "card4": "8059",
                "amount_krw": 1404842,
            },
        )
        status = {signal["name"]: signal["status"] for signal in signals}
        self.assertEqual(status["approval_number"], "match")
        self.assertEqual(status["amount"], "match")
        self.assertEqual(status["card_suffix"], "mismatch")

    def test_intersection_signals_do_not_hide_payment_delta(self) -> None:
        signals = intersection_signals(
            {"amount_krw": 1056200},
            {"amount_krw": 1060200},
        )
        amount = next(signal for signal in signals if signal["name"] == "amount")
        self.assertEqual(amount["status"], "mismatch")
        self.assertEqual(int(amount["right"]) - int(amount["left"]), 4000)

    def test_authenticated_agoda_portal_blocks_wrong_mail_cross_match(self) -> None:
        signals = intersection_signals(
            {
                "card4": "8835",
                "currency": "JPY",
                "foreign_amount": "21913",
                "occurred_on": "2026-06-18",
            },
            {
                "booking_number": "1738849062",
                "card4": "8835",
                "currency": "JPY",
                "foreign_amount": "162256",
                "payment_date": "2026-10-21",
                "service_start_on": "2026-10-26",
                "service_end_on": "2026-10-28",
            },
        )
        statuses = {signal["name"]: signal["status"] for signal in signals}
        self.assertEqual(statuses["card_suffix"], "match")
        self.assertEqual(statuses["currency"], "match")
        self.assertEqual(statuses["foreign_amount"], "mismatch")
        self.assertEqual(statuses["occurred_on"], "mismatch")

        payment_id = self._payment("KBO-2951", 215007)
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "AGODA-1738849062-WRONG-CROSS-MATCH",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[
                    self._strong_signal(
                        "booking_number",
                        "KBO-2951",
                        left="1738849062",
                        right="1738849062",
                        evidence=[
                            {
                                "source_record_id": "portal:agoda:1738849062:2026-07-26",
                                "source_type": "ota_authenticated_portal",
                                "source_channel": "authenticated_booking_portal",
                                "attachment_state": "not_applicable",
                                "forwarded_state": "not_applicable",
                                "amount_currency_state": "resolved",
                                "ota_field_loss_state": "clear",
                                "extraction_source": "authenticated_portal_dom",
                            }
                        ],
                    ),
                    *[
                        signal
                        for signal in signals
                        if signal["name"] in {"foreign_amount", "occurred_on"}
                    ],
                ],
            )

    def test_approval_amount_match_cannot_hide_date_and_merchant_conflicts(self) -> None:
        card = {
            "approval_number": "30101845",
            "amount_krw": 333727,
            "occurred_on": "2026-05-20",
            "merchant": "HERTZ INTERNATIONAL",
        }
        ota = {
            "approval_number": "30101845",
            "amount_krw": 333727,
            "payment_date": "2026-05-22",
            "merchant": "AVIS BUDGET",
        }
        signals = intersection_signals(card, ota)
        statuses = {
            signal["name"]: signal["status"] for signal in signals
        }
        self.assertEqual(statuses["approval_number"], "match")
        self.assertEqual(statuses["amount"], "match")
        self.assertEqual(statuses["occurred_on"], "mismatch")
        self.assertEqual(statuses["merchant"], "mismatch")

        payment_id = self._payment("CARD-STRUCTURAL-CONFLICT", 333727)
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-STRUCTURAL-CONFLICT",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[
                    self._strong_signal(
                        "approval_number",
                        "CARD-STRUCTURAL-CONFLICT",
                        left="30101845",
                        right="30101845",
                    ),
                    *[
                        signal
                        for signal in signals
                        if signal["name"] in {"occurred_on", "merchant"}
                    ],
                ],
            )

    def test_booking_only_candidate_keeps_merchant_amount_and_service_conflicts_visible(self) -> None:
        signals = intersection_signals(
            {
                "merchant": "Amsterdam Card Merchant",
                "foreign_amount": "549",
                "service_start_on": "2026-08-20",
            },
            {
                "merchant": "Hirakatakan",
                "foreign_amount": "582.18",
                "service_start_on": "2026-02-10",
            },
        )
        statuses = {signal["name"]: signal["status"] for signal in signals}
        self.assertEqual(statuses["merchant"], "mismatch")
        self.assertEqual(statuses["foreign_amount"], "mismatch")
        self.assertEqual(statuses["service_start_on"], "mismatch")

        payment_id = self._payment("KBO-2882", 0)
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "BOOKING-INFO-ONLY-CONFLICT",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=signals,
            )
        group_id = create_match_group(
            self.db,
            "BOOKING-INFO-ONLY-PROPOSED",
            status="proposed",
            payment_ids=[payment_id],
            signals=signals,
        )
        self.assertGreater(group_id, 0)

    def test_repeated_amount_payment_identity_is_separate_from_trip_allocation(self) -> None:
        cards = [
            {
                "card_id": "KBD-0972",
                "owner": "owner-a",
                "approval_number": "30058508",
                "amount_krw": 383700,
                "currency": "KRW",
                "approved_at": "2026-05-28T20:40:08+09:00",
            },
            {
                "card_id": "KBD-0973",
                "owner": "owner-b",
                "approval_number": "30058520",
                "amount_krw": 383700,
                "currency": "KRW",
                "approved_at": "2026-05-28T20:46:10+09:00",
            },
        ]
        ota = [
            {
                "booking_ref": "1400827190108091",
                "message_id": "mail-repeat-1",
                "amount_krw": 383700,
                "currency": "KRW",
                "mail_at": "2026-05-28T20:40:05+09:00",
                "trip_code": "0625_아키타",
            },
            {
                "booking_ref": "1400827189198011",
                "message_id": "mail-repeat-2",
                "amount_krw": 383700,
                "currency": "KRW",
                "mail_at": "2026-05-28T20:46:12+09:00",
                "trip_code": "0630_오제",
            },
        ]
        result = reconcile_repeated_amount_ota_group(
            cards,
            ota,
            {
                "KBD-0972": "0630_오제",
                "KBD-0973": "0625_아키타",
            },
        )
        self.assertEqual(result["payment_status"], "confirmed_strong")
        self.assertEqual(result["allocation_status"], "conflict")
        self.assertEqual(result["allocation_reason"], "reverse_assignment")
        identities = {
            item["card_id"]: item["booking_ref"]
            for item in result["payment_matches"]
        }
        self.assertEqual(
            identities,
            {
                "KBD-0972": "1400827190108091",
                "KBD-0973": "1400827189198011",
            },
        )
        self.assertEqual(
            {
                item["card_id"]: item["owner"]
                for item in result["payment_matches"]
            },
            {"KBD-0972": "owner-a", "KBD-0973": "owner-b"},
        )
        for item in result["payment_matches"]:
            self.assertEqual(
                item["intersection_signals"],
                [
                    "approval_number",
                    "booking_ref",
                    "amount_currency",
                    "mail_at",
                ],
            )

        corrected = reconcile_repeated_amount_ota_group(
            cards,
            ota,
            {
                "KBD-0972": "0625_아키타",
                "KBD-0973": "0630_오제",
            },
        )
        self.assertEqual(corrected["payment_status"], "confirmed_strong")
        self.assertEqual(corrected["allocation_status"], "confirmed")

    def test_repeated_amount_group_requires_booking_and_unique_time_intersection(self) -> None:
        cards = [
            {
                "card_id": "CARD-1",
                "approval_number": "111",
                "amount_krw": 10000,
                "approved_at": "2026-05-28T20:40:00+09:00",
            },
            {
                "card_id": "CARD-2",
                "approval_number": "222",
                "amount_krw": 10000,
                "approved_at": "2026-05-28T20:41:00+09:00",
            },
        ]
        missing_approval_cards = [dict(card) for card in cards]
        missing_approval_cards[0]["approval_number"] = ""
        missing_approval = reconcile_repeated_amount_ota_group(
            missing_approval_cards,
            [
                {
                    "booking_ref": "BOOK-1",
                    "message_id": "mail-missing-approval-1",
                    "amount_krw": 10000,
                    "mail_at": "2026-05-28T20:40:00+09:00",
                },
                {
                    "booking_ref": "BOOK-2",
                    "message_id": "mail-missing-approval-2",
                    "amount_krw": 10000,
                    "mail_at": "2026-05-28T20:41:00+09:00",
                },
            ],
        )
        self.assertEqual(missing_approval["payment_status"], "conflict")
        self.assertEqual(
            missing_approval["payment_reason"],
            "approval_identity_missing_or_duplicated",
        )

        missing_booking = reconcile_repeated_amount_ota_group(
            cards,
            [
                {
                    "booking_ref": "",
                    "amount_krw": 10000,
                    "mail_at": "2026-05-28T20:40:00+09:00",
                },
                {
                    "booking_ref": "BOOK-2",
                    "amount_krw": 10000,
                    "mail_at": "2026-05-28T20:41:00+09:00",
                },
            ],
        )
        self.assertEqual(missing_booking["payment_status"], "conflict")
        self.assertEqual(
            missing_booking["payment_reason"],
            "booking_reference_missing_or_duplicated",
        )

        ambiguous_time = reconcile_repeated_amount_ota_group(
            cards,
            [
                {
                    "booking_ref": "BOOK-1",
                    "message_id": "mail-ambiguous-1",
                    "amount_krw": 10000,
                    "mail_at": "2026-05-28T20:40:30+09:00",
                },
                {
                    "booking_ref": "BOOK-2",
                    "message_id": "mail-ambiguous-2",
                    "amount_krw": 10000,
                    "mail_at": "2026-05-28T20:40:30+09:00",
                },
            ],
        )
        self.assertEqual(ambiguous_time["payment_status"], "conflict")
        self.assertEqual(
            ambiguous_time["payment_reason"],
            "temporal_assignment_not_unique",
        )

    def test_five_observed_repeated_amount_groups_detect_reverse_assignment(self) -> None:
        # These are five non-Agoda repeated-amount groups observed in the
        # committed card CSV and OTA mail index.  The card time is aligned to
        # the corresponding direct-mail timestamp because the committed CSV
        # preserves the approval number/date but not the time-of-day.
        observed_groups = [
            (
                429031,
                [
                    ("TRIP-0156", "30050468", "2025-09-16T23:03:43+09:00"),
                    ("TRIP-0157", "30050479", "2025-09-16T23:04:38+09:00"),
                ],
                [
                    ("1087-639-436", "2025-09-16T23:03:43+09:00"),
                    ("1083-031-644", "2025-09-16T23:04:38+09:00"),
                ],
            ),
            (
                417040,
                [
                    ("TRIP-0389", "30057511", "2026-03-27T15:33:17+09:00"),
                    ("TRIP-0390", "30057487", "2026-03-27T15:34:19+09:00"),
                    ("TRIP-0391", "30057498", "2026-03-27T15:35:15+09:00"),
                    ("TRIP-0392", "30057500", "2026-03-27T15:42:13+09:00"),
                    ("TRIP-0393", "30057522", "2026-03-27T15:43:26+09:00"),
                ],
                [
                    ("1129-649-782", "2026-03-27T15:33:17+09:00"),
                    ("1125-634-382", "2026-03-27T15:34:19+09:00"),
                    ("1121-833-450", "2026-03-27T15:35:15+09:00"),
                    ("1129-746-782", "2026-03-27T15:42:13+09:00"),
                    ("1120-834-169", "2026-03-27T15:43:26+09:00"),
                ],
            ),
            (
                336292,
                [
                    ("TRIP-0373", "30092383", "2026-02-01T07:01:31+09:00"),
                    ("TRIP-0372", "30092406", "2026-02-01T07:02:14+09:00"),
                    ("TRIP-0371", "30092428", "2026-02-01T07:02:55+09:00"),
                ],
                [
                    ("1400823577012470", "2026-02-01T07:01:31+09:00"),
                    ("1400823577012863", "2026-02-01T07:02:14+09:00"),
                    ("1400823577013247", "2026-02-01T07:02:55+09:00"),
                ],
            ),
            (
                62496,
                [
                    ("TRIP-0097", "30096534", "2026-03-12T22:23:30+09:00"),
                    ("TRIP-0098", "30096556", "2026-03-12T22:24:43+09:00"),
                ],
                [
                    ("1400824415599919", "2026-03-12T22:23:30+09:00"),
                    ("1400824415604933", "2026-03-12T22:24:43+09:00"),
                ],
            ),
            (
                341394,
                [
                    ("TRIP-0423", "30050716", "2025-09-22T20:02:34+09:00"),
                    ("TRIP-0424", "30050727", "2025-09-22T20:03:52+09:00"),
                ],
                [
                    ("1080-502-429", "2025-09-22T20:02:34+09:00"),
                    ("1084-314-399", "2025-09-22T20:03:52+09:00"),
                ],
            ),
        ]
        for amount, card_rows, ota_rows in observed_groups:
            with self.subTest(amount=amount):
                cards = [
                    {
                        "card_id": card_id,
                        "approval_number": approval,
                        "amount_krw": amount,
                        "currency": "KRW",
                        "approved_at": approved_at,
                    }
                    for card_id, approval, approved_at in card_rows
                ]
                ota = [
                    {
                        "booking_ref": booking_ref,
                        "message_id": f"observed:{booking_ref}",
                        "amount_krw": amount,
                        "currency": "KRW",
                        "mail_at": mail_at,
                        "trip_code": "observed-group",
                        "allocation_key": f"booking:{booking_ref}",
                    }
                    for booking_ref, mail_at in ota_rows
                ]
                expected = {
                    card_id: f"booking:{ota_rows[index][0]}"
                    for index, (card_id, _, _) in enumerate(card_rows)
                }
                shifted_values = list(expected.values())[1:] + list(
                    expected.values()
                )[:1]
                reversed_allocation = dict(
                    zip(expected.keys(), shifted_values)
                )
                result = reconcile_repeated_amount_ota_group(
                    cards,
                    ota,
                    reversed_allocation,
                )
                self.assertEqual(result["payment_status"], "confirmed_strong")
                self.assertEqual(result["allocation_status"], "conflict")
                self.assertEqual(
                    result["allocation_reason"],
                    "reverse_assignment",
                )
                self.assertEqual(
                    {
                        row["card_id"]: row["booking_ref"]
                        for row in result["payment_matches"]
                    },
                    {
                        card_id: ota_rows[index][0]
                        for index, (card_id, _, _) in enumerate(card_rows)
                    },
                )

    def test_manual_allocation_override_is_append_only_and_becomes_current(self) -> None:
        first_payment = self._payment("TRIP-0097", 62496)
        second_payment = self._payment("TRIP-0098", 62496)
        first_target = int(
            self.db.execute(
                """
                INSERT INTO allocation_targets(target_type, code, name)
                VALUES ('trip', 'BOOK-1400824415599919', 'first booking')
                """
            ).lastrowid
        )
        second_target = int(
            self.db.execute(
                """
                INSERT INTO allocation_targets(target_type, code, name)
                VALUES ('trip', 'BOOK-1400824415604933', 'second booking')
                """
            ).lastrowid
        )
        wrong_first = replace_allocation_plan(
            self.db,
            first_payment,
            [AllocationItem(target_id=second_target, amount_krw=62496)],
            status="proposed",
            confidence=0.5,
        )
        wrong_second = replace_allocation_plan(
            self.db,
            second_payment,
            [AllocationItem(target_id=first_target, amount_krw=62496)],
            status="proposed",
            confidence=0.5,
        )
        corrected_first = replace_allocation_plan(
            self.db,
            first_payment,
            [AllocationItem(target_id=first_target, amount_krw=62496)],
            status="confirmed",
            confidence=1.0,
        )
        corrected_second = replace_allocation_plan(
            self.db,
            second_payment,
            [AllocationItem(target_id=second_target, amount_krw=62496)],
            status="confirmed",
            confidence=1.0,
        )
        supersedes = {
            row["id"]: row["supersedes_plan_id"]
            for row in self.db.execute(
                """
                SELECT id, supersedes_plan_id
                FROM allocation_plans
                WHERE id IN (?, ?)
                """,
                (corrected_first, corrected_second),
            ).fetchall()
        }
        self.assertEqual(supersedes[corrected_first], wrong_first)
        self.assertEqual(supersedes[corrected_second], wrong_second)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE allocation_plans SET plan_status='rejected' WHERE id=?",
                (corrected_first,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "DELETE FROM allocation_plans WHERE id=?",
                (corrected_first,),
            )
        self.assertEqual(
            int(self.db.execute("SELECT COUNT(*) FROM allocation_plans").fetchone()[0]),
            4,
        )
        current = {
            row["payment_id"]: (
                row["target_id"],
                row["allocation_status"],
                row["plan_version"],
            )
            for row in self.db.execute(
                """
                SELECT payment_id, target_id, allocation_status, plan_version
                FROM current_cost_allocations
                WHERE payment_id IN (?, ?)
                """,
                (first_payment, second_payment),
            ).fetchall()
        }
        self.assertEqual(
            current,
            {
                first_payment: (first_target, "confirmed", 2),
                second_payment: (second_target, "confirmed", 2),
            },
        )
        self.assertTrue(
            close_period(
                self.db,
                "manual-allocation-corrected",
                require_tax_evidence=False,
            )["passed"]
        )

        rejected_successor = replace_allocation_plan(
            self.db,
            first_payment,
            [AllocationItem(target_id=first_target, amount_krw=62496)],
            status="rejected",
            confidence=0.0,
        )
        rejected_row = self.db.execute(
            """
            SELECT supersedes_plan_id
            FROM allocation_plans
            WHERE id=?
            """,
            (rejected_successor,),
        ).fetchone()
        self.assertEqual(rejected_row["supersedes_plan_id"], corrected_first)
        # A rejected leaf means "no current allocation"; it must not uncover
        # the old reversed proposal underneath it.
        self.assertEqual(
            int(
                self.db.execute(
                    """
                    SELECT COUNT(*)
                    FROM current_cost_allocations
                    WHERE payment_id=?
                    """,
                    (first_payment,),
                ).fetchone()[0]
            ),
            0,
        )
        with self.assertRaises(PeriodCloseBlocked) as blocked:
            close_period(
                self.db,
                "manual-allocation-rejected",
                require_tax_evidence=False,
            )
        self.assertFalse(blocked.exception.gates["card_lossless"]["passed"])

        restored = replace_allocation_plan(
            self.db,
            first_payment,
            [AllocationItem(target_id=first_target, amount_krw=62496)],
            status="confirmed",
            confidence=1.0,
        )
        restored_row = self.db.execute(
            """
            SELECT plan_version, supersedes_plan_id
            FROM allocation_plans
            WHERE id=?
            """,
            (restored,),
        ).fetchone()
        self.assertEqual(restored_row["plan_version"], 4)
        self.assertEqual(
            restored_row["supersedes_plan_id"],
            rejected_successor,
        )
        restored_current = self.db.execute(
            """
            SELECT target_id, plan_version, allocation_status
            FROM current_cost_allocations
            WHERE payment_id=?
            """,
            (first_payment,),
        ).fetchone()
        self.assertEqual(
            tuple(restored_current),
            (first_target, 4, "confirmed"),
        )
        self.assertTrue(
            close_period(
                self.db,
                "manual-allocation-restored",
                require_tax_evidence=False,
            )["passed"]
        )

    def test_direct_receipt_outranks_unrelated_scored_candidate(self) -> None:
        result = select_direct_receipt(
            {
                "amount_krw": 499505,
                "occurred_at": "2026-06-11T11:21:25",
            },
            [
                {
                    "booking_number": "1400827517097737",
                    "amount_krw": 499505,
                    "occurred_at": "2026-06-11T11:21:00",
                    "document_role": "receipt",
                    "merchant": "Trip.com 서울-니가타",
                },
                {
                    "booking_number": "1400825754461766",
                    "amount_krw": 499505,
                    "occurred_at": "2026-05-01T00:00:00",
                    "document_role": "scored_candidate",
                    "merchant": "unrelated",
                },
            ],
        )
        self.assertEqual(result["status"], "confirmed_strong")
        self.assertEqual(
            result["candidate"]["booking_number"],
            "1400827517097737",
        )

    def test_insurance_payment_does_not_prove_trip_allocation(self) -> None:
        result = assess_insurance_trip_link(
            payment_identity_confirmed=True,
            trip_code="0620-MYOKO",
            policy_travel_dates_confirmed=False,
            policy_roster_confirmed=False,
            exact_manual_trip_row=False,
        )
        self.assertEqual(result["payment_identity_status"], "confirmed")
        self.assertEqual(result["trip_link_status"], "needs_review")
        self.assertEqual(result["trip_code"], "")

    def test_authorization_hold_is_not_recognized_as_travel_cost(self) -> None:
        hold = self._payment("CARD-HOLD", 416838)
        release = self._payment("CARD-HOLD-RELEASE", -416838, "refund")
        record_authorization_hold(
            self.db,
            hold,
            evidence=[
                {
                    "text": "card pre-authorization; returned after checkout",
                    "booking": "1400826972865451",
                }
            ],
        )
        disposition = self.db.execute(
            "SELECT disposition, finalized FROM card_event_dispositions WHERE payment_id=?",
            (hold,),
        ).fetchone()
        self.assertEqual(disposition["disposition"], "pending")
        self.assertEqual(disposition["finalized"], 0)
        resolve_authorization_hold(
            self.db,
            hold,
            release,
            resolution="released",
        )
        disposition = self.db.execute(
            "SELECT disposition, finalized FROM card_event_dispositions WHERE payment_id=?",
            (hold,),
        ).fetchone()
        self.assertEqual(disposition["disposition"], "cancellation_refund")
        self.assertEqual(disposition["finalized"], 1)
        report = coverage_report(self.db)
        self.assertTrue(report.lossless)
        validation = validation_report(self.db)
        self.assertEqual(validation["transactions"], 0)
        self.assertEqual(validation["allocation_total_krw"], 0)
        self.assertEqual(validation["allocation_mismatches"], 0)
        self.assertTrue(
            close_period(
                self.db,
                "hold-released",
                require_tax_evidence=False,
            )["passed"]
        )
        disposition = self.db.execute(
            "SELECT disposition, finalized FROM card_event_dispositions WHERE payment_id=?",
            (hold,),
        ).fetchone()
        self.assertEqual(disposition["disposition"], "cancellation_refund")
        self.assertEqual(disposition["finalized"], 1)
        with self.assertRaises(ValueError):
            resolve_authorization_hold(
                self.db,
                hold,
                release,
                resolution="released",
            )

    def test_captured_hold_allocates_only_the_capture_event(self) -> None:
        hold = self._payment("CARD-HOLD-CAPTURE", 318339)
        capture = self._payment("CARD-CAPTURE", 318339)
        record_authorization_hold(self.db, hold)
        with self.assertRaises(ValueError):
            replace_allocation_plan(
                self.db,
                hold,
                [AllocationItem(target_id=1, amount_krw=318339)],
                status="confirmed",
                confidence=1.0,
            )
        resolve_authorization_hold(
            self.db,
            hold,
            capture,
            resolution="captured",
        )
        target = int(
            self.db.execute(
                """
                INSERT INTO allocation_targets(target_type, code, name)
                VALUES ('trip', 'CAPTURE-TRIP', 'capture trip')
                """
            ).lastrowid
        )
        replace_allocation_plan(
            self.db,
            capture,
            [AllocationItem(target_id=target, amount_krw=318339)],
            status="confirmed",
            confidence=1.0,
        )
        report = coverage_report(self.db)
        self.assertTrue(report.lossless)
        allocated = self.db.execute(
            "SELECT SUM(amount_krw) FROM current_cost_allocations"
        ).fetchone()[0]
        self.assertEqual(allocated, 318339)
        validation = validation_report(self.db)
        self.assertEqual(validation["transactions"], 1)
        self.assertEqual(validation["allocation_total_krw"], 318339)
        self.assertEqual(validation["allocation_mismatches"], 0)

    def test_recorded_hold_hides_a_preexisting_allocation(self) -> None:
        hold = self._payment("CARD-HOLD-STALE-PLAN", 50000)
        target = int(
            self.db.execute(
                """
                INSERT INTO allocation_targets(target_type, code, name)
                VALUES ('trip', 'STALE-PLAN-TRIP', 'stale allocation')
                """
            ).lastrowid
        )
        plan = int(
            self.db.execute(
                """
                INSERT INTO allocation_plans(payment_id, plan_version, plan_status, confidence)
                VALUES (?, 1, 'confirmed', 1.0)
                """,
                (hold,),
            ).lastrowid
        )
        self.db.execute(
            "INSERT INTO cost_allocations(plan_id, target_id, amount_krw) VALUES (?, ?, 50000)",
            (plan, target),
        )
        self.db.commit()
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM current_cost_allocations").fetchone()[0],
            1,
        )
        record_authorization_hold(self.db, hold)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM current_cost_allocations").fetchone()[0],
            0,
        )
        report = coverage_report(self.db)
        self.assertEqual(report.pending_events, 1)

    def test_authorization_hold_cannot_reopen_or_reuse_related_event(self) -> None:
        hold = self._payment("CARD-HOLD-ONE", 10000)
        other_hold = self._payment("CARD-HOLD-TWO", 10000)
        release = self._payment("CARD-HOLD-RELEASE-ONE", -10000, "refund")
        record_authorization_hold(self.db, hold)
        record_authorization_hold(self.db, other_hold)
        with self.assertRaises(ValueError):
            resolve_authorization_hold(
                self.db,
                hold,
                other_hold,
                resolution="captured",
            )
        resolve_authorization_hold(
            self.db,
            hold,
            release,
            resolution="released",
        )
        with self.assertRaises(ValueError):
            record_authorization_hold(self.db, hold)
        with self.assertRaises(ValueError):
            resolve_authorization_hold(
                self.db,
                other_hold,
                release,
                resolution="released",
            )

    def test_trip_partial_refund_posts_only_4400_not_audit_refund_again(self) -> None:
        # KBD F:637 (+296,200) and F:633 (-291,800), original approval
        # 30057229.  The refund remains visible to audit but the travel cost
        # is the 4,400 residual only.
        original = self._payment("KBD-F637-30057229", 296200)
        refund = self._payment("KBD-F633-30057229", -291800, "refund")
        self.db.execute(
            """
            INSERT INTO transaction_relations(
                transaction_id, related_transaction_id, relation_type,
                reference_value, match_method, confidence, relation_status
            ) VALUES (?, ?, 'refunds', 'ORIG-1', 'approval_number', 1.0, 'confirmed')
            """,
            (refund, original),
        )
        self.db.commit()
        balance = refund_balance(self.db, original)
        self.assertEqual(balance["gross_krw"], 296200)
        self.assertEqual(balance["refunded_krw"], 291800)
        self.assertEqual(balance["remaining_krw"], 4400)
        self.assertEqual(balance["audit_refund_krw"], 291800)
        self.assertEqual(balance["travel_cost_posting_krw"], 4400)
        self.assertEqual(
            balance["travel_cost_posting_krw"] + balance["audit_refund_krw"],
            balance["gross_krw"],
        )
        self.assertFalse(balance["over_refunded"])

    def test_two_337406_raw_lifecycles_form_two_relations_and_two_zero_nets(self) -> None:
        originals = [
            self._payment("KBD:F:31", 337406),
            self._payment("KBD:F:32", 337406),
        ]
        refunds = [
            self._payment("KBD:F:426", -337406, "refund"),
            self._payment("KBD:F:427", -337406, "refund"),
        ]
        self.db.executemany(
            """
            INSERT INTO transaction_relations(
                transaction_id, related_transaction_id, relation_type,
                reference_value, match_method, confidence, relation_status
            ) VALUES (?, ?, 'cancels', ?, 'issuer+original_approval',
                      1.0, 'confirmed')
            """,
            [
                (refunds[0], originals[0], "30100002"),
                (refunds[1], originals[1], "30100024"),
            ],
        )
        self.db.commit()
        self.assertEqual(
            self.db.execute(
                """
                SELECT COUNT(*) FROM transaction_relations
                WHERE transaction_id IN (?, ?)
                  AND relation_status='confirmed'
                """,
                tuple(refunds),
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            [refund_balance(self.db, original)["remaining_krw"]
             for original in originals],
            [0, 0],
        )

    def test_trip_partial_refund_is_one_audit_relation_and_4400_net_cost(self) -> None:
        original = self._payment("KBD-TRIP-296200", 296200)
        refund = self._payment("KBD-TRIP-291800", -291800, "refund")
        target = int(
            self.db.execute(
                """
                INSERT INTO allocation_targets(target_type, code, name)
                VALUES ('trip', '0424_ALPEN', 'Alpen')
                """
            ).lastrowid
        )
        from ledger.domain.ledger_db import AllocationItem, replace_allocation_plan

        replace_allocation_plan(
            self.db,
            original,
            [AllocationItem(target_id=target, amount_krw=296200)],
            status="confirmed",
            confidence=1.0,
        )
        replace_allocation_plan(
            self.db,
            refund,
            [AllocationItem(target_id=target, amount_krw=-291800)],
            status="confirmed",
            confidence=1.0,
        )
        self.db.execute(
            """
            INSERT INTO transaction_relations(
                transaction_id, related_transaction_id, relation_type,
                reference_value, match_method, confidence, relation_status,
                resolution_code
            ) VALUES (?, ?, 'refunds', '30057229',
                      'issuer+original_approval', 1.0, 'confirmed',
                      'original_linked')
            """,
            (refund, original),
        )
        self.db.commit()

        self.assertNotEqual(original, refund)
        balance = refund_balance(self.db, original)
        self.assertEqual(
            balance,
            {
                "gross_krw": 296200,
                "refunded_krw": 291800,
                "remaining_krw": 4400,
                "audit_refund_krw": 291800,
                "travel_cost_posting_krw": 4400,
                "over_refunded": False,
            },
        )
        audit = self.db.execute(
            """
            SELECT COUNT(*) AS relation_count,
                   SUM(ABS(refund.amount_krw)) AS refund_evidence_krw
            FROM transaction_relations relation
            JOIN payment_transactions refund
              ON refund.id=relation.transaction_id
            WHERE relation.related_transaction_id=?
              AND relation.relation_type='refunds'
              AND relation.relation_status='confirmed'
            """,
            (original,),
        ).fetchone()
        self.assertEqual(int(audit["relation_count"]), 1)
        self.assertEqual(int(audit["refund_evidence_krw"]), 291800)
        # The relation is audit evidence, not a third posting.  Only the two
        # source events reach travel cost, yielding the true 4,400 won net.
        posting = self.db.execute(
            """
            SELECT COUNT(*) AS posting_count, SUM(amount_krw) AS net_cost_krw
            FROM current_cost_allocations
            WHERE payment_id IN (?, ?)
            """,
            (original, refund),
        ).fetchone()
        self.assertEqual(int(posting["posting_count"]), 2)
        self.assertEqual(int(posting["net_cost_krw"]), 4400)
        self.assertEqual(
            validation_report(self.db, [original, refund])["allocation_total_krw"],
            4400,
        )

    def test_five_reviewed_refund_cases_keep_audit_and_posting_separate(self) -> None:
        # The first two were legacy TRIP UID moves, whereas the MAN case has
        # no evidenced original/refund relation.  A residual alone is never a
        # permission to post travel cost.
        cases = {
            "TRIP-0140/0141": (632200, 311900, False, None, "original_relation_unconfirmed"),
            "TRIP-0145/0146": (296200, 291800, False, None, "original_relation_unconfirmed"),
            "TRIP-0430/0431": (699200, 519200, False, None, "original_relation_unconfirmed"),
            "KBD-0782/0783": (550080, 550080, True, 0, "confirmed_full_cancellation"),
            "KBD-0829/0830": (514700, 434700, True, 80000, "confirmed_partial_refund"),
        }
        for label, (gross, refund, evidenced, posting, status) in cases.items():
            with self.subTest(label=label):
                result = refund_case_disposition(
                    gross_krw=gross,
                    refund_krw=-refund,
                    original_relation_evidenced=evidenced,
                )
                self.assertEqual(result["audit_refund_krw"], refund)
                self.assertEqual(result["residual_krw"], gross - refund)
                self.assertEqual(result["travel_cost_posting_krw"], posting)
                self.assertEqual(result["status"], status)

    def test_same_amount_refunds_keep_approval_anchored_bundle_identity(self) -> None:
        # Both 125,398 won KBD pairs exist on the same day.  The master view
        # previously collapsed them to one UID; original approval is the
        # lifecycle identity, never amount/date/merchant alone.
        legs = [
            {
                "uid": uid, "src": "KBD", "krw": amount,
                "appr": approval, "orig_appr": original,
                "card_verified": True, "travel_verified": travel_verified,
            }
            for uid, amount, approval, original, travel_verified in (
                ("KBD-0779", 125398, "30099256", "", False),
                ("KBD-0778", -125398, "47662906", "30099256", False),
                ("KBD-0781", 125398, "30099278", "", False),
                ("KBD-0780", -125398, "47662917", "30099278", False),
                ("KBD-0799", 258700, "30099582", "", False),
                ("KBD-0797", -196500, "47942604", "30099582", False),
                ("KBD-0904", 333727, "30101845", "", True),
                ("KBD-0903", -333727, "41447552", "30101845", True),
                ("KBD-0906", 269354, "30101878", "", True),
                ("KBD-0905", -269354, "41447563", "30101878", True),
            )
        ]
        bundles = {bundle["pair_id"]: bundle for bundle in refund_lifecycle_bundles(legs)}
        self.assertEqual(set(bundles), {
            "refund-lifecycle:KBD:30099256",
            "refund-lifecycle:KBD:30099278",
            "refund-lifecycle:KBD:30099582",
            "refund-lifecycle:KBD:30101845",
            "refund-lifecycle:KBD:30101878",
        })
        self.assertEqual(
            bundles["refund-lifecycle:KBD:30099256"]["positive_leg_uids"],
            ["KBD-0779"],
        )
        self.assertEqual(
            bundles["refund-lifecycle:KBD:30099278"]["negative_leg_uids"],
            ["KBD-0780"],
        )
        self.assertEqual(bundles["refund-lifecycle:KBD:30099582"]["residual_krw"], 62200)
        self.assertEqual(bundles["refund-lifecycle:KBD:30101845"]["residual_krw"], 0)
        self.assertEqual(bundles["refund-lifecycle:KBD:30101878"]["residual_krw"], 0)
        # Card evidence and the travel-booking conclusion cannot promote each
        # other.  The first three have RAW confirmation but no trip proof.
        self.assertEqual(
            bundles["refund-lifecycle:KBD:30099256"]["card_evidence_status"],
            "card_verified",
        )
        self.assertEqual(
            bundles["refund-lifecycle:KBD:30099256"]["travel_evidence_status"],
            "travel_unverified",
        )

    def test_five_priority_real_refund_groups_follow_raw_period_and_pair_identity(self) -> None:
        with DEFAULT_CSV.open(encoding="utf-8-sig", newline="") as stream:
            by_uid = {row["uid"]: row for row in csv.DictReader(stream)}

        # Two same-day/same-amount originals exist. orig_appr selects only
        # 30101283 (KBD-0874), never the 30101205 sibling (KBD-0867).
        self.assertEqual(by_uid["KBD-0873"]["orig_appr"], "30101283")
        self.assertEqual(by_uid["KBD-0874"]["appr"], "30101283")
        self.assertEqual(by_uid["KBD-0867"]["appr"], "30101205")
        self.assertEqual(
            int(float(by_uid["KBD-0874"]["krw"])),
            int(float(by_uid["KBD-0867"]["krw"])),
        )

        # KBO-0346/0347 are two distinct outside-window refund events. With
        # no orig_appr, neither can be assigned an individual original pair.
        outside = [by_uid[uid] for uid in ("KBO-0346", "KBO-0347")]
        self.assertEqual({row["krw"] for row in outside}, {"-893170"})
        self.assertTrue(all(not row["orig_appr"] for row in outside))
        self.assertEqual(len({row["uid"] for row in outside}), 2)

        # These notes claim Q1/outside-window, but the source-event dates prove
        # both the purchases and refunds are Q2. Raw dates outrank note prose.
        for original_uid, refund_uid, pair_id in (
            ("KBO-2683", "KBO-2703", "KP0002"),
            ("KBO-2684", "KBO-2704", "KP0003"),
        ):
            with self.subTest(pair_id=pair_id):
                original = by_uid[original_uid]
                refund = by_uid[refund_uid]
                self.assertGreaterEqual(original["use_date"], "2026-04-01")
                self.assertLessEqual(refund["use_date"], "2026-06-30")
                self.assertEqual(original["appr"], pair_id)
                self.assertEqual(refund["orig_appr"], pair_id)
                self.assertEqual(
                    int(float(original["krw"])) + int(float(refund["krw"])),
                    0,
                )
                self.assertIn("당 분기 밖", refund["note"])

        # The later-discovered -68,720 leg remains a separate append-only leg.
        # Card evidence confirms the zero net; the note-only booking reference
        # still cannot promote travel evidence.
        late_bundle = refund_lifecycle_bundles([
            {
                "uid": "KBD-0963", "src": "KBD", "krw": 68720,
                "appr": "30102701", "orig_appr": "",
                "card_verified": True, "travel_verified": False,
            },
            {
                "uid": "KBD-1106", "src": "KBD", "krw": -68720,
                "appr": "43940664", "orig_appr": "30102701",
                "card_verified": True, "travel_verified": False,
            },
        ])[0]
        self.assertEqual(late_bundle["positive_leg_uids"], ["KBD-0963"])
        self.assertEqual(late_bundle["negative_leg_uids"], ["KBD-1106"])
        self.assertEqual(late_bundle["residual_krw"], 0)
        self.assertEqual(late_bundle["card_evidence_status"], "card_verified")
        self.assertEqual(
            late_bundle["travel_evidence_status"],
            "travel_unverified",
        )

    def test_new_refund_risk_bundles_preserve_multi_leg_and_outside_window_states(self) -> None:
        # KBD-0861 has four separately approved refund legs.  They sum to,
        # but never exceed, its 3,893,400 won original.
        multi_leg = [
            {"uid": "KBD-0861", "src": "KBD", "krw": 3893400, "appr": "30101185", "card_verified": True},
        ] + [
            {"uid": uid, "src": "KBD", "krw": amount, "appr": approval, "orig_appr": "30101185", "card_verified": True}
            for uid, amount, approval in (
                ("KBD-0862", -1730400, "43032904"),
                ("KBD-0863", -216300, "43032881"),
                ("KBD-0864", -216300, "43032870"),
                ("KBD-0865", -1730400, "43032892"),
            )
        ]
        bundle = refund_lifecycle_bundles(multi_leg)[0]
        self.assertEqual(bundle["negative_leg_uids"], ["KBD-0862", "KBD-0863", "KBD-0864", "KBD-0865"])
        self.assertEqual(bundle["refunded_krw"], 3893400)
        self.assertEqual(bundle["residual_krw"], 0)

        # KBO-0346/0347 are two RAW overseas cancellation events but have no
        # issuer original approval.  They stay as one approval-less event set
        # and cannot be promoted into a travel link.
        unresolved = refund_lifecycle_bundles([
            {"uid": uid, "src": "KBO", "use_date": "2026-04-07", "merchant": "TRIP.COM", "krw": -893170, "card_verified": True}
            for uid in ("KBO-0346", "KBO-0347")
        ])[0]
        self.assertEqual(unresolved["negative_leg_uids"], ["KBO-0346", "KBO-0347"])
        self.assertEqual(unresolved["original_relation_status"], "original_approval_missing")
        self.assertEqual(unresolved["travel_evidence_status"], "travel_unverified")

        # KBO-2703/2683 and KBO-2704/2684 were labelled as prior-period in a
        # legacy note, but their RAW originals are 4/13.  Q2 raw dates, not
        # that note, control period treatment.
        in_window = refund_case_disposition(
            gross_krw=716289, refund_krw=-716289,
            original_relation_evidenced=True, original_outside_window=True,
            original_occurred_on="2026-04-13",
            period_start_on="2026-04-01", period_end_on="2026-06-30",
        )
        self.assertEqual(in_window["status"], "confirmed_full_cancellation")
        self.assertEqual(in_window["travel_cost_posting_krw"], 0)
        self.assertEqual(in_window["period_treatment"], "same_period_netting")

        # KBD-0873/0874 is a real partial refund; KBD-0917/0916 is a full
        # one.  Their source confirmation still does not prove a trip.
        cases = {
            "KBD-0873/0874": (395506, 324912, 70594, "confirmed_partial_refund"),
            "KBD-0917/0916": (53200, 53200, 0, "confirmed_full_cancellation"),
        }
        for label, (gross, refund, residual, status) in cases.items():
            with self.subTest(label=label):
                result = refund_case_disposition(
                    gross_krw=gross, refund_krw=-refund,
                    original_relation_evidenced=True,
                )
                self.assertEqual(result["residual_krw"], residual)
                self.assertEqual(result["status"], status)

        # Same amount does not make KBD-0867 (approval 30101205) refundable:
        # KBD-0873 names original approval 30101283, i.e. KBD-0874 only.
        skyticket = refund_lifecycle_bundles([
            {"uid": "KBD-0867", "src": "KBD", "krw": 395506, "appr": "30101205", "card_verified": True},
            {"uid": "KBD-0874", "src": "KBD", "krw": 395506, "appr": "30101283", "card_verified": True},
            {"uid": "KBD-0873", "src": "KBD", "krw": -324912, "appr": "46499378", "orig_appr": "30101283", "card_verified": True},
        ])[0]
        self.assertEqual(skyticket["pair_id"], "refund-lifecycle:KBD:30101283")
        self.assertEqual(skyticket["positive_leg_uids"], ["KBD-0874"])
        self.assertEqual(skyticket["negative_leg_uids"], ["KBD-0873"])

        # KBD-1106 is an independently preserved RAW cancellation, paired
        # to KBD-0963 by original approval, not inferred from an OTA receipt.
        raw_discovered = refund_lifecycle_bundles([
            {"uid": "KBD-0963", "src": "KBD", "krw": 68720, "appr": "30102701", "card_verified": True},
            {"uid": "KBD-1106", "src": "KBD", "krw": -68720, "appr": "43940664", "orig_appr": "30102701", "card_verified": True},
        ])[0]
        self.assertEqual(raw_discovered["residual_krw"], 0)
        self.assertEqual(raw_discovered["card_evidence_status"], "card_verified")

    def test_refund_close_gate_blocks_cumulative_over_refund(self) -> None:
        original = self._payment("CARD-ORIGINAL", 100000)
        for key, amount in (("CARD-REFUND-1", -60000), ("CARD-REFUND-2", -50000)):
            refund = self._payment(key, amount, "refund")
            self.db.execute(
                """
                INSERT INTO transaction_relations(
                    transaction_id, related_transaction_id, relation_type,
                    reference_value, match_method, confidence, relation_status
                ) VALUES (?, ?, 'refunds', ?, 'approval_number', 1.0, 'confirmed')
                """,
                (refund, original, key),
            )
        self.db.commit()
        with self.assertRaises(PeriodCloseBlocked) as blocked:
            close_period(self.db, "over-refund", require_tax_evidence=False)
        self.assertFalse(blocked.exception.gates["refund_balance"]["passed"])
        self.assertEqual(
            blocked.exception.gates["refund_balance"]["actual"]["over_refunded_originals"],
            1,
        )

    def test_four_additional_non_agoda_refund_candidates_keep_one_net_posting(self) -> None:
        cases = {
            "KBD-0799/0797 TRIP.COM": (258700, 196500, 62200),
            "KBD-0834/0832 TRIP.COM": (146100, 58900, 87200),
            "KBD-0916/0917 KLOOK": (53200, 53200, 0),
            "KBD-0946/0947 KLOOK": (73900, 60424, 13476),
        }
        for label, (gross, refund, expected_net) in cases.items():
            with self.subTest(label=label):
                result = refund_case_disposition(
                    gross_krw=gross,
                    refund_krw=-refund,
                    original_relation_evidenced=True,
                )
                self.assertEqual(result["audit_refund_krw"], refund)
                self.assertEqual(result["residual_krw"], expected_net)
                self.assertEqual(
                    result["travel_cost_posting_krw"],
                    expected_net,
                )
                self.assertEqual(
                    result["status"],
                    "confirmed_full_cancellation"
                    if expected_net == 0
                    else "confirmed_partial_refund",
                )

    def test_strong_group_requires_identifier_or_unique_amount_evidence(self) -> None:
        payment_id = self._payment("CARD-WEAK", 10000)
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-WEAK",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[
                    {
                        "name": "merchant",
                        "status": "match",
                        "left": "TRIP",
                        "right": "TRIP",
                    }
                ],
            )

    def test_manual_confirmation_allows_missing_evidence_but_not_conflict(self) -> None:
        payment_id = self._payment("CARD-MANUAL", 10000)
        group_id = create_match_group(
            self.db,
            "GROUP-MANUAL-NO-EVIDENCE",
            status="confirmed_manual",
            payment_ids=[payment_id],
            signals=[
                {
                    "name": "booking_number",
                    "status": "unavailable",
                    "left": None,
                    "right": None,
                }
            ],
        )
        row = self.db.execute(
            "SELECT status FROM match_groups WHERE id=?",
            (group_id,),
        ).fetchone()
        self.assertEqual(row["status"], "confirmed_manual")
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-MANUAL-CONFLICT",
                status="confirmed_manual",
                payment_ids=[payment_id],
                signals=[
                    {
                        "name": "amount",
                        "status": "mismatch",
                        "left": "10000",
                        "right": "12000",
                    }
                ],
            )

    def test_confirmation_rejects_signal_status_that_contradicts_values(self) -> None:
        payment_id = self._payment("CARD-SIGNAL-LIE", 10000)
        for status in ("match", "unavailable"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                create_match_group(
                    self.db,
                    f"GROUP-SIGNAL-LIE-{status}",
                    status="confirmed_manual",
                    payment_ids=[payment_id],
                    signals=[
                        {
                            "name": "amount",
                            "status": status,
                            "left": "10000",
                            "right": "12000",
                        }
                    ],
                )

    def test_manual_decision_revalidates_persisted_group_conflicts(self) -> None:
        payment_id = self._payment("CARD-MANUAL-CONFLICT", 10000)
        group_id = create_match_group(
            self.db,
            "GROUP-PROPOSED-CONFLICT",
            status="proposed",
            payment_ids=[payment_id],
            signals=[
                {
                    "name": "amount",
                    "status": "mismatch",
                    "left": "10000",
                    "right": "12000",
                }
            ],
        )
        with self.assertRaises(ValueError):
            record_match_decision(
                self.db,
                "DEC-MANUAL-CONFLICT",
                group_id,
                status="confirmed_manual",
                actor="tester",
                reason_code="manual_review",
                rationale="증거 부족 수동검토",
                evidence=[],
            )

    def test_manual_decision_allows_empty_lineage_and_updates_projection(self) -> None:
        payment_id = self._payment("CARD-MANUAL-EMPTY", 10000)
        group_id = create_match_group(
            self.db,
            "GROUP-PROPOSED-MANUAL",
            status="proposed",
            payment_ids=[payment_id],
            signals=[],
        )
        self.assertTrue(
            record_match_decision(
                self.db,
                "DEC-MANUAL-EMPTY",
                group_id,
                status="confirmed_manual",
                actor="tester",
                reason_code="manual_review",
                rationale="원장 원문 육안확인",
                evidence=[],
            )
        )
        row = self.db.execute(
            "SELECT status FROM match_groups WHERE id=?",
            (group_id,),
        ).fetchone()
        self.assertEqual(row["status"], "confirmed_manual")

    def test_manual_decision_rejects_conflict_in_decision_evidence(self) -> None:
        payment_id = self._payment("CARD-MANUAL-EVIDENCE-CONFLICT", 10000)
        group_id = create_match_group(
            self.db,
            "GROUP-MANUAL-EVIDENCE-CONFLICT",
            status="proposed",
            payment_ids=[payment_id],
            signals=[],
        )
        with self.assertRaises(ValueError):
            record_match_decision(
                self.db,
                "DEC-MANUAL-EVIDENCE-CONFLICT",
                group_id,
                status="confirmed_manual",
                actor="tester",
                reason_code="manual_review",
                rationale="수동검토",
                evidence=[
                    {
                        "signal_name": "amount",
                        "signal_status": "mismatch",
                    }
                ],
            )

    def test_manual_append_only_chain_and_member_rematch_guard(self) -> None:
        payment_id = self._payment("CARD-MANUAL-CHAIN", 10000)
        booking_id = self.db.execute(
            """
            INSERT INTO bookings(provider, booking_number)
            VALUES ('mytrip', '1122-610-807')
            """
        ).lastrowid
        first_group = create_match_group(
            self.db,
            "GROUP-MANUAL-CHAIN-1",
            status="proposed",
            payment_ids=[payment_id],
            booking_ids=[booking_id],
            signals=[
                {
                    "name": "order_number",
                    "status": "unavailable",
                    "left": None,
                    "right": None,
                }
            ],
        )
        first_kwargs = {
            "status": "confirmed_manual",
            "actor": "tester",
            "reason_code": "manual_review",
            "rationale": "수기장부와 메일 원문 육안확인",
            "evidence": [],
        }
        self.assertTrue(
            record_match_decision(
                self.db,
                "MANUAL-CHAIN-1",
                first_group,
                **first_kwargs,
            )
        )
        self.assertFalse(
            record_match_decision(
                self.db,
                "MANUAL-CHAIN-1",
                first_group,
                **first_kwargs,
            )
        )
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-MANUAL-DIRECT-REMATCH",
                status="confirmed_manual",
                payment_ids=[payment_id],
                booking_ids=[booking_id],
                signals=[],
            )
        with self.assertRaises(ValueError):
            record_match_decision(
                self.db,
                "MANUAL-CHAIN-2",
                first_group,
                status="conflict",
                actor="tester",
                reason_code="new_conflict",
                rationale="추가 충돌 발견",
                evidence=[],
            )
        self.assertTrue(
            record_match_decision(
                self.db,
                "MANUAL-CHAIN-2",
                first_group,
                status="conflict",
                actor="tester",
                reason_code="new_conflict",
                rationale="추가 충돌 발견",
                evidence=[],
                supersedes="MANUAL-CHAIN-1",
            )
        )
        self.assertTrue(
            record_match_decision(
                self.db,
                "MANUAL-CHAIN-3",
                first_group,
                status="confirmed_manual",
                actor="tester",
                reason_code="conflict_resolved",
                rationale="충돌 원문 재확인 완료",
                evidence=[],
                supersedes="MANUAL-CHAIN-2",
            )
        )

        second_group = create_match_group(
            self.db,
            "GROUP-MANUAL-CHAIN-2",
            status="proposed",
            payment_ids=[payment_id],
            booking_ids=[booking_id],
            signals=[],
        )
        with self.assertRaises(ValueError):
            record_match_decision(
                self.db,
                "MANUAL-CROSS-GROUP-SUPERSEDES",
                second_group,
                status="confirmed_manual",
                actor="tester",
                reason_code="manual_review",
                rationale="다른 그룹 판정을 대체하려는 시도",
                evidence=[],
                supersedes="MANUAL-CHAIN-3",
            )
        with self.assertRaises(ValueError):
            record_match_decision(
                self.db,
                "MANUAL-REMATCH-BLOCKED",
                second_group,
                status="confirmed_manual",
                actor="tester",
                reason_code="manual_review",
                rationale="동일 카드·예약 중복 확정 시도",
                evidence=[],
            )
        self.assertTrue(
            record_match_decision(
                self.db,
                "MANUAL-CHAIN-4",
                first_group,
                status="unmatched",
                actor="tester",
                reason_code="released_for_rematch",
                rationale="기존 그룹 연결 해제",
                evidence=[],
                supersedes="MANUAL-CHAIN-3",
            )
        )
        self.db.execute(
            """
            UPDATE match_groups
            SET status='confirmed_manual'
            WHERE id=?
            """,
            (first_group,),
        )
        self.assertTrue(
            record_match_decision(
                self.db,
                "MANUAL-REMATCH-ALLOWED",
                second_group,
                status="confirmed_manual",
                actor="tester",
                reason_code="manual_review",
                rationale="기존 그룹 해제 후 재확정",
                evidence=[],
            )
        )
        current = {
            row["group_id"]: (row["decision_id"], row["status"])
            for row in self.db.execute(
                """
                SELECT group_id, decision_id, status
                FROM current_match_group_projection
                WHERE group_id IN (?, ?)
                """,
                (first_group, second_group),
            ).fetchall()
        }
        self.assertEqual(
            current[first_group],
            ("MANUAL-CHAIN-4", "unmatched"),
        )
        self.assertEqual(
            current[second_group],
            ("MANUAL-REMATCH-ALLOWED", "confirmed_manual"),
        )
        stale_denormalized = self.db.execute(
            "SELECT status FROM match_groups WHERE id=?",
            (first_group,),
        ).fetchone()
        self.assertEqual(
            stale_denormalized["status"],
            "confirmed_manual",
        )
        decision_count = int(
            self.db.execute(
                """
                SELECT COUNT(*)
                FROM match_decisions
                WHERE group_id IN (?, ?)
                """,
                (first_group, second_group),
            ).fetchone()[0]
        )
        self.assertEqual(decision_count, 5)

    def test_strong_decision_cannot_bypass_group_lineage_validation(self) -> None:
        payment_id = self._payment("CARD-STRONG-BYPASS", 10000)
        group_id = create_match_group(
            self.db,
            "GROUP-PROPOSED-NO-LINEAGE",
            status="proposed",
            payment_ids=[payment_id],
            signals=[
                {
                    "name": "booking_number",
                    "status": "match",
                    "left": "BOOK-1",
                    "right": "BOOK-1",
                }
            ],
        )
        with self.assertRaises(ValueError):
            record_match_decision(
                self.db,
                "DEC-STRONG-BYPASS",
                group_id,
                status="confirmed_strong",
                actor="tester",
                reason_code="identifier_match",
                rationale="예약번호 일치",
                evidence=[],
            )

    def test_superseded_match_invalidates_posting_and_close_rejects_stale_use(self) -> None:
        payment_id = self._payment("CARD-STALE-MATCH", 25000)
        group_id = create_match_group(
            self.db,
            "GROUP-STALE-MATCH",
            status="proposed",
            payment_ids=[payment_id],
            signals=[],
        )
        self.assertTrue(
            record_match_decision(
                self.db,
                "STALE-MATCH-1",
                group_id,
                status="confirmed_manual",
                actor="tester",
                reason_code="manual_review",
                rationale="최초 수동확정",
                evidence=[],
            )
        )
        self.db.execute(
            """
            INSERT INTO card_event_dispositions(
                payment_id, disposition, finalized, reason_code, decision_id
            ) VALUES (?, 'trip', 1, 'confirmed_match', 'STALE-MATCH-1')
            """,
            (payment_id,),
        )
        self.assertTrue(
            record_match_decision(
                self.db,
                "STALE-MATCH-2",
                group_id,
                status="unmatched",
                actor="tester",
                reason_code="manual_release",
                rationale="기존 연결 해제",
                evidence=[],
                supersedes="STALE-MATCH-1",
            )
        )
        invalidated = self.db.execute(
            """
            SELECT disposition, finalized, reason_code, decision_id
            FROM card_event_dispositions
            WHERE payment_id=?
            """,
            (payment_id,),
        ).fetchone()
        self.assertEqual(invalidated["disposition"], "pending")
        self.assertEqual(invalidated["finalized"], 0)
        self.assertEqual(
            invalidated["reason_code"],
            "match_decision_superseded",
        )
        self.assertEqual(invalidated["decision_id"], "STALE-MATCH-2")

        self.db.execute(
            """
            UPDATE card_event_dispositions
            SET disposition='trip', finalized=1,
                reason_code='legacy_stale_projection',
                decision_id='STALE-MATCH-1'
            WHERE payment_id=?
            """,
            (payment_id,),
        )
        with self.assertRaises(PeriodCloseBlocked) as blocked:
            close_period(
                self.db,
                "run-stale-match",
                require_tax_evidence=False,
            )
        gate = blocked.exception.gates["match_projection_current"]
        self.assertFalse(gate["passed"])
        self.assertEqual(
            gate["actual"]["stale_finalized_dispositions"],
            1,
        )

    def test_close_revalidates_legacy_current_strong_blockers(self) -> None:
        payment_id = self._payment("CARD-LEGACY-BLOCKER", 528297)
        group_id = create_match_group(
            self.db,
            "GROUP-LEGACY-BLOCKER",
            status="proposed",
            payment_ids=[payment_id],
            signals=[
                self._strong_signal(
                    "booking_number",
                    "CARD-LEGACY-BLOCKER",
                    left="40-894243710",
                    right="40-894243710",
                ),
                {
                    "name": "forwarded_unextracted",
                    "status": "unavailable",
                },
            ],
        )
        self.db.execute(
            """
            UPDATE match_groups
            SET status='confirmed_strong'
            WHERE id=?
            """,
            (group_id,),
        )
        with self.assertRaises(PeriodCloseBlocked) as blocked:
            close_period(
                self.db,
                "run-legacy-strong-blocker",
                require_tax_evidence=False,
            )
        gate = blocked.exception.gates["match_projection_current"]
        self.assertFalse(gate["passed"])
        self.assertEqual(
            gate["actual"]["invalid_current_strong_confirmations"],
            1,
        )

    def test_strong_group_rejects_ota_collection_blockers(self) -> None:
        payment_id = self._payment("CARD-BLOCKED", 163788)
        for blocker in (
            "ota_field_loss",
            "attachment_required",
            "forwarded_unextracted",
            "amount_currency_unresolved",
        ):
            with self.subTest(blocker=blocker), self.assertRaises(ValueError):
                create_match_group(
                    self.db,
                    f"GROUP-{blocker}",
                    status="confirmed_strong",
                    payment_ids=[payment_id],
                    signals=[
                        self._strong_signal("order_number", "CARD-BLOCKED"),
                        {"name": blocker, "status": "unavailable"},
                    ],
                )

    def test_strong_group_requires_payment_event_and_evidence_lineage(self) -> None:
        payment_id = self._payment("CARD-LINEAGE", 163788)
        missing_event = self._strong_signal("order_number", "")
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-NO-EVENT",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[missing_event],
            )
        missing_lineage = self._strong_signal(
            "order_number",
            "CARD-LINEAGE",
            evidence=[
                {
                    "attachment_state": "none",
                    "forwarded_state": "not_forwarded",
                }
            ],
        )
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-NO-LINEAGE",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[missing_lineage],
            )

    def test_note_only_identifier_cannot_confirm_strong_match(self) -> None:
        payment_id = self._payment("CARD-NOTE-ONLY", 163788)
        note_signal = self._strong_signal(
            "pnr",
            "CARD-NOTE-ONLY",
            left="ABC123",
            right="ABC123",
            evidence=[
                {
                    "source_record_id": "legacy-note:42",
                    "source_type": "manual_note",
                    "extraction_source": "note",
                    "attachment_state": "none",
                    "forwarded_state": "not_forwarded",
                    "amount_currency_state": "resolved",
                    "ota_field_loss_state": "clear",
                }
            ],
        )
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-NOTE-ONLY",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[note_signal],
            )

    def test_confirmed_card_relation_cannot_promote_booking_travel_or_period(self) -> None:
        original = self._payment("CARD-RELATION-ORIGINAL", 50000)
        refund = self._payment("CARD-RELATION-REFUND", -50000, "refund")
        booking_id = int(
            self.db.execute(
                """
                INSERT INTO bookings(
                    provider, booking_number, product_type, service_start_on
                ) VALUES ('trip.com', 'NOTE-ONLY-BOOKING', 'lodging',
                          '2026-08-01')
                """
            ).lastrowid
        )
        self.db.execute(
            """
            INSERT INTO transaction_relations(
                transaction_id, related_transaction_id, relation_type,
                reference_value, match_method, confidence, relation_status
            ) VALUES (?, ?, 'cancels', '30109999',
                      'issuer+original_approval', 1.0, 'confirmed')
            """,
            (refund, original),
        )
        approval_signal = self._strong_signal(
            "approval_number",
            "CARD-RELATION-ORIGINAL",
            left="30109999",
            right="30109999",
        )
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "CARD-RELATION-CANNOT-PROMOTE-BOOKING",
                status="confirmed_strong",
                payment_ids=[original],
                booking_ids=[booking_id],
                signals=[approval_signal],
            )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM current_cost_allocations "
                "WHERE payment_id=?",
                (original,),
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.execute(
                """
                SELECT COUNT(*) FROM current_classification_decisions
                WHERE target_type='payment' AND target_id=?
                  AND dimension IN (
                      'allocation_target', 'period_recognition',
                      'service_start_on'
                  )
                """,
                (original,),
            ).fetchone()[0],
            0,
        )

    def test_hana_relation_does_not_promote_needs_review_allocation(self) -> None:
        original = int(
            self.db.execute(
                """
                INSERT INTO payment_transactions(
                    external_key, source_event_id, identity_fingerprint,
                    source_system, amount_krw, approval_number,
                    transaction_type
                ) VALUES ('HAN-UNCERTAIN', 'HAN-UNCERTAIN',
                          'fp:hana-uncertain', 'HAN', 0, '00109999',
                          'adjustment')
                """
            ).lastrowid
        )
        self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint,
                source_system, amount_krw, approval_number,
                transaction_type
            ) VALUES ('MISC-HAN-UNCERTAIN', 'MISC-HAN-UNCERTAIN',
                      'fp:misc-hana-uncertain', 'HAN', -50000, '00109999',
                      'refund')
            """
        )
        target = int(
            self.db.execute(
                """
                INSERT INTO allocation_targets(target_type, code, name)
                VALUES ('trip', 'UNVERIFIED-TRIP', 'unverified trip')
                """
            ).lastrowid
        )
        decision_id = replace_decision(
            self.db,
            "payment",
            original,
            "allocation_target",
            "UNVERIFIED-TRIP",
            0.3,
            "하",
            "note/title/merchant-only allocation",
            None,
            decision_status="needs_review",
            rule_id="test:unverified-allocation",
        )
        replace_allocation_plan(
            self.db,
            original,
            [AllocationItem(target_id=target, amount_krw=0)],
            status="legacy",
            confidence=0.3,
            source_decision_id=decision_id,
        )
        result = resolve_hana_split_cancellations(self.db)
        self.assertEqual(result["resolved_pairs"], 0)
        self.assertEqual(
            self.db.execute(
                """
                SELECT COUNT(*) FROM current_cost_allocations allocation
                JOIN payment_transactions payment
                  ON payment.id=allocation.payment_id
                WHERE payment.external_key='MISC-HAN-UNCERTAIN'
                """
            ).fetchone()[0],
            0,
        )

    def test_title_amount_and_merchant_only_are_never_strong(self) -> None:
        payment_id = self._payment("CARD-WEAK-SOURCES", 89440)
        weak_signals = [
            self._strong_signal(
                "booking_number",
                "CARD-WEAK-SOURCES",
                left="TITLE-BOOKING",
                right="TITLE-BOOKING",
                evidence=[{
                    "message_id": "title-only-message",
                    "source_type": "title_only",
                    "extraction_source": "message_body",
                    "attachment_state": "none",
                    "forwarded_state": "not_forwarded",
                    "amount_currency_state": "resolved",
                    "ota_field_loss_state": "clear",
                }],
            ),
            self._strong_signal(
                "unique_amount_group",
                "CARD-WEAK-SOURCES",
                left="89440",
                right="89440",
            ),
            self._strong_signal(
                "merchant",
                "CARD-WEAK-SOURCES",
                left="TRIP.COM",
                right="TRIP.COM",
            ),
        ]
        for index, signal in enumerate(weak_signals):
            with self.subTest(signal=signal["name"]):
                with self.assertRaises(ValueError):
                    create_match_group(
                        self.db,
                        f"GROUP-WEAK-SOURCE-{index}",
                        status="confirmed_strong",
                        payment_ids=[payment_id],
                        signals=[signal],
                    )

    def test_five_reported_note_only_cases_have_no_direct_ota_lineage(self) -> None:
        with DEFAULT_CSV.open(encoding="utf-8-sig", newline="") as stream:
            by_uid = {row["uid"]: row for row in csv.DictReader(stream)}
        verified = json.loads(
            (LEDGER_DIR / "data" / "ota_event_links_verified.json").read_text(
                encoding="utf-8"
            )
        )

        def direct_lineage(record: dict[str, object]) -> bool:
            return bool(
                (
                    record.get("message_id")
                    and (
                        record.get("booking_ref")
                        or record.get("booking_id")
                        or record.get("pnr")
                    )
                )
                or (
                    record.get("document_role")
                    in {"receipt", "payment_confirmation"}
                    and record.get("source_record_id")
                )
            )

        for uid in ("KBD-1029", "KBD-1021", "KBD-1058", "KBD-0741"):
            with self.subTest(uid=uid):
                self.assertIn(uid, by_uid)
                self.assertFalse(direct_lineage(dict(verified.get(uid, {}))))

        # Three different charges plus unrelated KBD-0391 cannot be consumed
        # by one N:M total, especially with no direct message lineage.
        cards = [
            {
                "card_id": uid,
                "approval_number": by_uid[uid]["appr"],
                "amount_krw": int(float(by_uid[uid]["krw"])),
                "approved_at": by_uid[uid]["use_date"] + "T12:00:00+09:00",
            }
            for uid in ("KBD-0388", "KBD-0389", "KBD-0390", "KBD-0391")
        ]
        note_only_otas = [
            {
                "booking_ref": f"note-only-{uid}",
                "amount_krw": int(float(by_uid[uid]["krw"])),
                "mail_at": by_uid[uid]["use_date"] + "T12:00:00+09:00",
                "source_type": "manual_note",
            }
            for uid in ("KBD-0388", "KBD-0389", "KBD-0390")
        ]
        result = reconcile_repeated_amount_ota_group(cards, note_only_otas)
        self.assertEqual(result["payment_status"], "conflict")
        self.assertEqual(
            result["payment_reason"],
            "repeated_group_cardinality_mismatch",
        )

    def test_booking_info_only_and_existing_ota_fact_conflicts_block_confirmation(self) -> None:
        payment_id = self._payment("CARD-BOOKING-INFO-ONLY", 900000)
        booking_info_signal = self._strong_signal(
            "booking_number",
            "CARD-BOOKING-INFO-ONLY",
            left="BOOK-ONLY-1",
            right="BOOK-ONLY-1",
            evidence=[
                {
                    "source_record_id": "booking-info:BOOK-ONLY-1",
                    "source_type": "booking_info_only",
                    "attachment_state": "not_applicable",
                    "forwarded_state": "not_applicable",
                    "amount_currency_state": "resolved",
                    "ota_field_loss_state": "clear",
                }
            ],
        )
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-BOOKING-INFO-ONLY",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[booking_info_signal],
            )

        observed = {
            "service_start_on": "2026-05-10",
            "service_end_on": "2026-05-12",
            "currency": "EUR",
            "foreign_amount": "549",
        }
        ota = {
            "service_start_on": "2026-05-11",
            "service_end_on": "2026-05-13",
            "currency": "EUR",
            "foreign_amount": "582.18",
        }
        conflicts = intersection_signals(observed, ota)
        conflict_status = {
            signal["name"]: signal["status"] for signal in conflicts
        }
        self.assertEqual(conflict_status["service_start_on"], "mismatch")
        self.assertEqual(conflict_status["service_end_on"], "mismatch")
        self.assertEqual(conflict_status["currency"], "match")
        self.assertEqual(conflict_status["foreign_amount"], "mismatch")
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-OTA-EXISTING-FACT-CONFLICT",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[
                    self._strong_signal(
                        "booking_number",
                        "CARD-BOOKING-INFO-ONLY",
                        left="OTA-BOOK-1",
                        right="OTA-BOOK-1",
                    ),
                    *[
                        signal
                        for signal in conflicts
                        if signal["name"]
                        in {
                            "service_start_on",
                            "service_end_on",
                            "foreign_amount",
                        }
                    ],
                ],
            )

    def test_strong_group_persists_only_safe_lineage_fields(self) -> None:
        payment_id = self._payment("CARD-MYTRIP", 163788)
        group_id = create_match_group(
            self.db,
            "GROUP-MYTRIP",
            status="confirmed_strong",
            payment_ids=[payment_id],
            signals=[
                self._strong_signal(
                    "order_number",
                    "CARD-MYTRIP",
                    left="1122-610-807 (1)",
                    right="1122-610-807 (1)",
                    evidence=[
                        {
                            "message_id": "19ef821c940442e5",
                            "provider": "mytrip",
                            "attachment_state": "present_read",
                            "forwarded_state": "not_forwarded",
                            "amount_currency_state": "resolved",
                            "ota_field_loss_state": "clear",
                            "extraction_source": "gmail_body",
                            "raw_body": "must not persist",
                        }
                    ],
                )
            ],
        )
        row = self.db.execute(
            """
            SELECT source_event_id, evidence_json
            FROM match_signal_results
            WHERE group_id=? AND signal_name='order_number'
            """,
            (group_id,),
        ).fetchone()
        self.assertEqual(row["source_event_id"], "CARD-MYTRIP")
        evidence = json.loads(row["evidence_json"])
        self.assertEqual(evidence[0]["message_id"], "19ef821c940442e5")
        self.assertNotIn("raw_body", evidence[0])

    def test_unique_amount_strong_match_requires_resolved_currency(self) -> None:
        payment_id = self._payment("CARD-AMOUNT", 89440)
        unresolved = self._strong_signal(
            "unique_amount_group",
            "CARD-AMOUNT",
            left="89440",
            right="89440",
            evidence=[
                {
                    "message_id": "198cbf61975abcd6",
                    "attachment_state": "none",
                    "forwarded_state": "not_forwarded",
                    "amount_currency_state": "unresolved",
                    "ota_field_loss_state": "clear",
                }
            ],
        )
        with self.assertRaises(ValueError):
            create_match_group(
                self.db,
                "GROUP-AMOUNT-NO-CURRENCY",
                status="confirmed_strong",
                payment_ids=[payment_id],
                signals=[unresolved],
            )

    def test_match_group_preserves_charge_and_refund_roles(self) -> None:
        charge = self._payment("CARD-LIFE-P", 333727)
        refund = self._payment("CARD-LIFE-R", -333727, "refund")
        create_match_group(
            self.db,
            "GROUP-LIFECYCLE",
            status="confirmed_strong",
            payment_ids=[charge, refund],
            signals=[
                self._strong_signal(
                    "approval_number",
                    "CARD-LIFE-P",
                    left="30101845",
                    right="30101845",
                )
            ],
        )
        roles = {
            row["payment_id"]: row["role"]
            for row in self.db.execute(
                "SELECT payment_id, role FROM match_group_payments"
            ).fetchall()
        }
        self.assertEqual(roles[charge], "charge")
        self.assertEqual(roles[refund], "refund")

    def test_direct_legacy_link_uses_unique_exact_structure_not_approval_alone(self) -> None:
        wanted = self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint, source_system,
                occurred_on, merchant, amount_krw, approval_number, transaction_type
            ) VALUES ('HAN-WANTED','legacy:wanted','fp:wanted','HAN',
                      '2026-05-20','HERTZ INTERNATIONAL',543947,'00305072','purchase')
            """
        ).lastrowid
        self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint, source_system,
                occurred_on, merchant, amount_krw, approval_number, transaction_type
            ) VALUES ('HAN-OTHER','legacy:other','fp:other','HAN',
                      '2026-05-22','HERTZ INTERNATIONAL',422687,'00305072','purchase')
            """
        )
        source = self.db.execute(
            """
            INSERT INTO direct_source_records(
                source_kind, source_key, source_sha256, payload_json
            ) VALUES ('card_raw','HAN:H:331','sha:h331','{}')
            """
        ).lastrowid
        self.db.execute(
            """
            INSERT INTO direct_card_events(
                source_record_id, card_event_id, generator_version, identity_status,
                source_system, amount_krw, approval_number, occurred_on, merchant
            ) VALUES (?, 'card:raw-h331', 'v2', 'unique', 'HAN', 543947,
                      '00305072', '2026-05-20', 'HERTZ INTERNATIONAL')
            """,
            (source,),
        )
        self.db.execute(
            """
            INSERT INTO direct_normalized_payments(
                source_record_id, event_role, card_event_id, amount_krw,
                transaction_type, normalization_version
            ) VALUES (?, 'single', 'card:raw-h331', 543947, 'purchase', 'v2')
            """,
            (source,),
        )
        result = project_direct_payments(self.db)
        self.assertEqual(result["confirmed"], 1)
        link = self.db.execute(
            "SELECT payment_id, reason_code FROM direct_payment_links"
        ).fetchone()
        self.assertEqual(int(link["payment_id"]), int(wanted))
        self.assertEqual(link["reason_code"], "unique_exact_structure")

    def test_direct_projection_blocks_same_approval_amount_with_known_conflicts(self) -> None:
        canonical = self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint, source_system,
                occurred_on, merchant, amount_krw, approval_number, transaction_type
            ) VALUES ('HAN-CONFLICT','legacy:conflict','fp:conflict','HAN',
                      '2026-05-22','AVIS BUDGET',543947,'00305072','purchase')
            """
        ).lastrowid
        source = self.db.execute(
            """
            INSERT INTO direct_source_records(
                source_kind, source_key, source_sha256, payload_json
            ) VALUES ('card_raw','HAN:H:conflict','sha:h-conflict','{}')
            """
        ).lastrowid
        self.db.execute(
            """
            INSERT INTO direct_card_events(
                source_record_id, card_event_id, generator_version, identity_status,
                source_system, amount_krw, approval_number, occurred_on, merchant
            ) VALUES (?, 'card:raw-conflict', 'v2', 'unique', 'HAN', 543947,
                      '00305072', '2026-05-20', 'HERTZ INTERNATIONAL')
            """,
            (source,),
        )
        self.db.execute(
            """
            INSERT INTO direct_normalized_payments(
                source_record_id, event_role, card_event_id, amount_krw,
                transaction_type, normalization_version
            ) VALUES (?, 'single', 'card:raw-conflict', 543947, 'purchase', 'v2')
            """,
            (source,),
        )
        result = project_direct_payments(self.db)
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["conflict"], 1)
        link = self.db.execute(
            """
            SELECT payment_id, link_status, reason_code
            FROM direct_payment_links
            """
        ).fetchone()
        self.assertIsNone(link["payment_id"])
        self.assertEqual(link["link_status"], "conflict")
        self.assertEqual(
            link["reason_code"],
            "approval_amount_structural_conflict",
        )

        self.db.execute(
            """
            INSERT INTO card_event_identities(
                transaction_id, card_event_id, generator_version,
                identity_status, structural_payload_json
            ) VALUES (?, 'card:raw-conflict', 'v2', 'unique', '{}')
            """,
            (canonical,),
        )
        second = project_direct_payments(self.db)
        self.assertEqual(second["confirmed"], 0)
        self.assertEqual(second["conflict"], 1)
        stable_link = self.db.execute(
            """
            SELECT payment_id, link_status, reason_code
            FROM direct_payment_links
            """
        ).fetchone()
        self.assertIsNone(stable_link["payment_id"])
        self.assertEqual(
            stable_link["reason_code"],
            "stable_identity_structural_conflict",
        )

    def test_direct_projection_treats_missing_merchant_as_unmatched_not_conflict(self) -> None:
        self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint, source_system,
                occurred_on, merchant, amount_krw, approval_number, transaction_type
            ) VALUES ('HAN-MISSING','legacy:missing','fp:missing','HAN',
                      '2026-05-20','HERTZ INTERNATIONAL',543947,'00305072','purchase')
            """
        )
        source = self.db.execute(
            """
            INSERT INTO direct_source_records(
                source_kind, source_key, source_sha256, payload_json
            ) VALUES ('card_raw','HAN:H:missing','sha:h-missing','{}')
            """
        ).lastrowid
        self.db.execute(
            """
            INSERT INTO direct_card_events(
                source_record_id, card_event_id, generator_version, identity_status,
                source_system, amount_krw, approval_number, occurred_on, merchant
            ) VALUES (?, 'card:raw-missing', 'v2', 'unique', 'HAN', 543947,
                      '00305072', '2026-05-20', '')
            """,
            (source,),
        )
        self.db.execute(
            """
            INSERT INTO direct_normalized_payments(
                source_record_id, event_role, card_event_id, amount_krw,
                transaction_type, normalization_version
            ) VALUES (?, 'single', 'card:raw-missing', 543947, 'purchase', 'v2')
            """,
            (source,),
        )
        result = project_direct_payments(self.db)
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["conflict"], 0)
        self.assertEqual(result["unmatched"], 1)

    def test_tax_assessment_blocks_close_until_evidence_is_confirmed(self) -> None:
        trip = self.db.execute(
            "INSERT INTO trips(code, name) VALUES ('TAX-1', '세무 테스트')"
        ).lastrowid
        result = tax_assessment(
            self.db, trip, customer_receipts_krw=300000,
            entrusted_costs_krw=200000, refunds_krw=20000,
            evidence_confirmed=False,
        )
        self.assertEqual(result["net_travel_cost_krw"], 180000)
        self.assertEqual(result["commission_krw"], 120000)
        with self.assertRaises(PeriodCloseBlocked):
            close_period(self.db, "run-tax")


if __name__ == "__main__":
    unittest.main()
