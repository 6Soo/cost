from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_sources import (
    hana_lifecycle_component_amounts,
    import_manual,
    import_ota,
    signed_card_event_amount,
)
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.source_adapters import (
    confirmed_booking_service_start,
    forbidden_ota_fields,
    mark_identity_collisions,
    normalize_service_period,
    reconcile_amount,
    sanitize_ota_record,
    stable_card_event_identity,
)


class SourceAdapterTest(unittest.TestCase):
    def test_manual_special_row_is_a_stable_manual_source_not_a_card_claim(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            manual_path = root / "manual.csv"
            manual_path.write_text(
                "tab,row,date,item,desc,card,amount,book\n"
                "0630_OZE,49,26.01.15,Trip.com,refund,Trip.com,-519200,\n",
                encoding="utf-8",
            )
            special_path = root / "manual_special_rows.json"
            special_path.write_text(
                json.dumps(
                    [{
                        "uid": "MAN-OZE-LODGE-3472049", "src": "MAN",
                        "use_date": "2026-07-16", "krw": "3472049",
                        "merchant": "OZE LODGE",
                    }]
                ),
                encoding="utf-8",
            )
            db = connect(root / "ledger.db")
            try:
                initialize(db)
                result = import_manual(db, manual_path, special_path)
                self.assertEqual(result, {"records": 2, "inserted": 2})
                sources = {
                    tuple(row)
                    for row in db.execute(
                        "SELECT source_kind, source_key FROM direct_source_records"
                    )
                }
                self.assertEqual(
                    sources,
                    {
                        ("manual_ledger", "0630_OZE:49"),
                        ("manual_special", "MAN-OZE-LODGE-3472049"),
                    },
                )
                # Manual evidence belongs to the complete source inventory,
                # but it is not a card claim and must never enter automatic
                # card-event/payment projection tables.
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM direct_card_events"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM direct_normalized_payments"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM direct_payment_links"
                    ).fetchone()[0],
                    0,
                )
            finally:
                db.close()

    def test_initialize_adds_v5_service_end_to_existing_booking_schema(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "legacy-v4.db")
            try:
                db.execute(
                    """
                    CREATE TABLE bookings (
                        id INTEGER PRIMARY KEY,
                        provider TEXT NOT NULL DEFAULT 'unknown',
                        booking_number TEXT NOT NULL,
                        product_type TEXT NOT NULL DEFAULT 'unknown',
                        label TEXT,
                        service_start_on TEXT,
                        status TEXT NOT NULL DEFAULT 'unknown',
                        UNIQUE(provider, booking_number)
                    )
                    """
                )
                initialize(db)
                columns = {
                    row["name"]
                    for row in db.execute("PRAGMA table_info(bookings)").fetchall()
                }
                self.assertIn("service_end_on", columns)
            finally:
                db.close()

    def test_positive_card_refund_source_is_signed_in_event_projection(self) -> None:
        self.assertEqual(
            signed_card_event_amount(
                {"src": "KBO", "krw": 421101, "cancel": True}
            ),
            -421101,
        )
        self.assertEqual(
            signed_card_event_amount(
                {"src": "KBO", "krw": 421101, "cancel": False}
            ),
            421101,
        )

    def test_hana_cancelled_capture_uses_billed_amount_for_both_legs(self) -> None:
        self.assertEqual(
            hana_lifecycle_component_amounts(
                {
                    "approval_amount": 52102,
                    "purchase_amount": 0,
                    "cancel_amount": -52850,
                }
            ),
            (52850, -52850),
        )

    def test_approval_identity_ignores_enrichment_and_legacy_uid(self) -> None:
        base = {
            "src": "KBD",
            "card4": "8835",
            "appr": "12345678",
            "krw": "10000",
            "merchant": "A",
            "uid": "OLD-1",
        }
        changed = {**base, "merchant": "정규화된 A", "uid": "NEW-999"}
        self.assertEqual(
            stable_card_event_identity(base).card_event_id,
            stable_card_event_identity(changed).card_event_id,
        )

    def test_same_approval_different_exact_events_do_not_collapse(self) -> None:
        common = {"src": "HAN", "card4": "4595", "appr": "00407242"}
        first = stable_card_event_identity({**common, "raw_record_id": "H:270", "use_date": "2026-06-01", "krw": 227411})
        second = stable_card_event_identity({**common, "raw_record_id": "H:315", "use_date": "2026-05-23", "krw": 584193})
        self.assertNotEqual(first.card_event_id, second.card_event_id)

    def test_same_raw_lifecycle_keeps_approval_and_cancellation_event_ids_separate(self) -> None:
        common = {
            "src": "HAN",
            "card4": "6741",
            "appr": "00105433",
            "use_date": "2026-04-08",
            "merchant": "TRIP.COM",
        }
        approval = stable_card_event_identity(
            {**common, "raw_record_id": "H:116:approval", "krw": 90415}
        )
        cancellation = stable_card_event_identity(
            {**common, "raw_record_id": "H:116:cancellation", "krw": -90415}
        )
        self.assertNotEqual(approval.card_event_id, cancellation.card_event_id)

    def test_two_337406_lifecycles_keep_all_four_raw_event_ids(self) -> None:
        rows = [
            {
                "src": "KBD", "raw_record_id": "F:31",
                "appr": "30100002", "krw": 337406, "cancel": False,
            },
            {
                "src": "KBD", "raw_record_id": "F:426",
                "appr": "40138659", "orig_appr": "30100002",
                "krw": -337406, "cancel": True,
            },
            {
                "src": "KBD", "raw_record_id": "F:32",
                "appr": "30100024", "krw": 337406, "cancel": False,
            },
            {
                "src": "KBD", "raw_record_id": "F:427",
                "appr": "40138660", "orig_appr": "30100024",
                "krw": -337406, "cancel": True,
            },
        ]
        event_ids = [
            stable_card_event_identity(row).card_event_id for row in rows
        ]
        self.assertEqual(len(set(event_ids)), 4)
        self.assertEqual(
            [(rows[0]["appr"], rows[1]["orig_appr"]),
             (rows[2]["appr"], rows[3]["orig_appr"])],
            [("30100002", "30100002"), ("30100024", "30100024")],
        )

    def test_overseas_identity_preserves_same_amount_duplicate_rows(self) -> None:
        base = {
            "src": "KBO",
            "card4": "8835",
            "use_date": "2026-03-12",
            "post_date": "2026-03-14",
            "currency": "JPY",
            "foreign": "6500.00",
            "krw": "62496",
        }
        first = stable_card_event_identity({**base, "raw_record_id": "KBO:E:41"})
        second = stable_card_event_identity({**base, "raw_record_id": "KBO:E:42"})
        self.assertNotEqual(first.card_event_id, second.card_event_id)

    def test_structural_collision_is_reviewed_not_merged(self) -> None:
        row = {
            "src": "KBO",
            "card4": "8835",
            "use_date": "2026-03-12",
            "currency": "JPY",
            "foreign": "6500",
            "krw": "62496",
        }
        identities = mark_identity_collisions(
            [stable_card_event_identity(row), stable_card_event_identity(row)]
        )
        self.assertEqual([item.identity_status for item in identities], ["collision", "collision"])

    def test_ota_allowlist_drops_personal_and_authentication_data(self) -> None:
        record = {
            "provider": "trip.com",
            "booking_number": "1400823716285910",
            "service_start_on": "2026-07-02",
            "pin": "2647",
            "생년월일": "1956-08-02",
            "phone": "010-1234-5678",
            "email": "person@example.com",
            "passport_number": "M12345678",
        }
        self.assertTrue(forbidden_ota_fields(record))
        clean = sanitize_ota_record(record)
        self.assertEqual(clean["booking_number"], "1400823716285910")
        self.assertEqual(clean["redaction_version"], "ota-allowlist-v5")
        self.assertFalse(forbidden_ota_fields(clean))

    def test_ota_allowlist_preserves_nm_matching_arrays(self) -> None:
        clean = sanitize_ota_record(
            {
                "booking_numbers": ["1122-610-807"],
                "pnrs": ["ABC123"],
                "travel_dates": ["2026-06-25", "2026-07-09"],
                "booking_display_amounts": [163787.77, 163788],
            }
        )
        self.assertEqual(clean["booking_numbers"], ["1122-610-807"])
        self.assertEqual(clean["booking_display_amounts"][-1], 163788)

    def test_authenticated_portal_preserves_settlement_facts(self) -> None:
        clean = sanitize_ota_record(
            {
                "provider": "agoda",
                "source_channel": "authenticated_booking_portal",
                "message_id": "portal:agoda:1738849062:2026-07-26",
                "observed_at": "2026-07-26T01:35:00+09:00",
                "booking_number": "1738849062",
                "reference_code": "6875898319",
                "service_start_on": "2026-10-26",
                "service_end_on": "2026-10-28",
                "currency": "JPY",
                "foreign_amount": "162256",
                "booking_display_amount": "162256",
                "card_last4": "8835",
                "record_type": "payment_scheduled",
                "booking_confirmation_status": "confirmed",
                "extraction_sources": ["authenticated_portal_dom"],
            }
        )
        self.assertEqual(clean["source_channel"], "authenticated_booking_portal")
        self.assertEqual(clean["foreign_amount"], "162256")
        self.assertEqual(clean["record_type"], "payment_scheduled")
        self.assertEqual(clean["extraction_sources"], ["authenticated_portal_dom"])

    def test_authenticated_portal_preserves_group_and_list_card_identity(self) -> None:
        clean = sanitize_ota_record(
            {
                "provider": "booking",
                "source_channel": "authenticated_booking_portal",
                "message_id": "portal:booking:group-a:booking-card-b:2026-07-26",
                "booking_number": "booking-card-b",
                "portalGroupId": "group-a",
                "portalGroupStatus": "completed",
                "portalBookingStatus": "cancelled",
                "portalListName": "past_trips",
                "portalListPosition": 17,
                "booking_confirmation_status": "confirmed",
                "extraction_sources": ["authenticated_portal_dom"],
            }
        )
        self.assertEqual(clean["portal_group_id"], "group-a")
        self.assertEqual(clean["portal_group_status"], "completed")
        self.assertEqual(clean["portal_booking_status"], "cancelled")
        self.assertEqual(clean["portal_list_name"], "past_trips")
        self.assertEqual(clean["portal_list_position"], 17)

    def test_synthetic_gmail_facts_keep_safe_trip_structure_without_people(self) -> None:
        records = [
            {
                "source": "trip_flight",
                "messageId": "synthetic-flight-change",
                "type": "payment_confirmation",
                "bookingNo": "SYNTH-FLT-01",
                "pnr": "Q1W2E3",
                "passengerCount": 2,
                "serviceStartOn": "2026-06-20",
                "serviceEndOn": "2026-06-25",
                "bookingStatus": "confirmed",
                "cancellationCondition": "change_fee",
                "passengers": ["Synthetic Person One", "Synthetic Person Two"],
                "email": "synthetic-flight@example.com",
            },
            {
                "source": "trip_hotel",
                "messageId": "synthetic-hotel-prepay",
                "type": "charge",
                "bookingNo": "SYNTH-HTL-02",
                "roomCount": 3,
                "serviceStartOn": "2026-06-23",
                "serviceEndOn": "2026-06-24",
                "bookingStatus": "confirmed",
                "cancellationCondition": "nonrefundable",
                "guestName": "Synthetic Hotel Guest",
                "phone": "010-0000-0000",
            },
            {
                "source": "trip_flight",
                "messageId": "synthetic-flight-confirmed",
                "type": "charge",
                "bookingNo": "SYNTH-FLT-03",
                "pnr": "Z9Y8X7",
                "passengerCount": "1",
                "serviceStartOn": "2026-06-25",
                "serviceEndOn": "2026-07-09",
                "bookingStatus": "confirmed",
                "cancellationCondition": "no_show_charge",
            },
        ]
        clean = [sanitize_ota_record(record) for record in records]
        self.assertEqual(clean[0]["pnr"], "Q1W2E3")
        self.assertEqual(clean[0]["passenger_count"], 2)
        self.assertEqual(clean[1]["room_count"], 3)
        self.assertEqual(clean[2]["service_end_on"], "2026-07-09")
        self.assertEqual(clean[1]["cancellation_condition"], "nonrefundable")
        self.assertTrue(all("passengers" not in record for record in clean))
        self.assertTrue(all(not forbidden_ota_fields(record) for record in clean))
        invalid_pnr = sanitize_ota_record(
            {
                "pnr": "Synthetic Passenger Name",
                "pnrs": ["ABC123", "Passenger Name"],
            }
        )
        self.assertNotIn("pnr", invalid_pnr)
        self.assertEqual(invalid_pnr["pnrs"], ["ABC123"])

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "synthetic-gmail-facts.json"
            source.write_text(json.dumps({"records": records}), encoding="utf-8")
            db = connect(root / "ledger.db")
            try:
                initialize(db)
                self.assertEqual(import_ota(db, source)["confirmed_booking_periods"], 3)
                rows = db.execute(
                    """
                    SELECT booking_number, service_start_on, service_end_on
                    FROM bookings
                    ORDER BY booking_number
                    """
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in rows],
                    [
                        ("SYNTH-FLT-01", "2026-06-20", "2026-06-25"),
                        ("SYNTH-FLT-03", "2026-06-25", "2026-07-09"),
                        ("SYNTH-HTL-02", "2026-06-23", "2026-06-24"),
                    ],
                )
                payloads = [
                    json.loads(row[0])
                    for row in db.execute(
                        """
                        SELECT payload_json
                        FROM direct_source_records
                        WHERE source_kind='ota_mail'
                        ORDER BY source_key
                        """
                    ).fetchall()
                ]
                by_booking = {
                    payload["booking_number"]: payload for payload in payloads
                }
                self.assertEqual(by_booking["SYNTH-FLT-01"]["pnr"], "Q1W2E3")
                self.assertEqual(
                    by_booking["SYNTH-FLT-01"]["passenger_count"],
                    2,
                )
                self.assertEqual(by_booking["SYNTH-HTL-02"]["room_count"], 3)
                self.assertEqual(
                    by_booking["SYNTH-FLT-03"]["service_end_on"],
                    "2026-07-09",
                )
                self.assertEqual(
                    by_booking["SYNTH-HTL-02"]["cancellation_condition"],
                    "nonrefundable",
                )
                self.assertTrue(
                    all(not forbidden_ota_fields(payload) for payload in payloads)
                )
                self.assertTrue(
                    all("passengers" not in payload for payload in payloads)
                )
            finally:
                db.close()

    def test_confirmed_booking_period_requires_one_safe_reference_and_day(self) -> None:
        confirmed = sanitize_ota_record(
            {
                "source": "trip_hotel",
                "type": "charge",
                "bookingNo": "1400826669398170",
                "serviceStartOn": "2026-08-27",
                "bookingStatus": "confirmed",
                "email": "must-not-survive@example.com",
            }
        )
        self.assertEqual(
            confirmed_booking_service_start(confirmed),
            {
                "provider": "trip_hotel",
                "booking_number": "1400826669398170",
                "service_start_on": "2026-08-27",
            },
        )
        self.assertIsNone(
            confirmed_booking_service_start(
                sanitize_ota_record(
                    {
                        "source": "trip_hotel",
                        "type": "evidence_only",
                        "bookingNo": "1400826669398170",
                        "serviceStartOn": "2026-08-27",
                        "bookingStatus": "confirmed",
                    }
                )
            )
        )
        self.assertIsNone(
            confirmed_booking_service_start(
                sanitize_ota_record(
                    {
                        "source": "trip_hotel",
                        "type": "charge",
                        "bookingRefs": ["1400826669398170", "1400826831996226"],
                        "serviceStartOn": "2026-08-27",
                        "bookingStatus": "confirmed",
                    }
                )
            )
        )

    def test_ota_collector_aliases_preserve_safe_attachment_contract(self) -> None:
        clean = sanitize_ota_record(
            {
                "provider": "booking",
                "messageId": "mail-1",
                "bookingRefs": ["5895361455"],
                "travelDates": ["0920", "0922"],
                "amounts": [129002],
                "cardLast4": "4111 1111 1111 8835",
                "amountCandidates": [
                    {
                        "amount": "129,002",
                        "currency": "jpy",
                        "role": "pay_at_property_total",
                        "source": "forwarded_message",
                        "unsafe_note": "must not survive",
                    },
                    {
                        "amount": "20000",
                        "currency": "JPY",
                        "role": "deposit",
                        "source": "attachment_text",
                    },
                    {
                        "amount": "999",
                        "currency": "JPY",
                        "role": "unknown_role",
                    },
                ],
                "attachmentState": "text_extracted",
                "attachmentCount": "2",
                "attachmentMimeTypes": ["application/pdf", "message/rfc822"],
                "attachmentReceiptDetected": True,
                "forwardedContentDetected": True,
                "forwardedContentExtracted": True,
                "extractionSources": [
                    "message_body",
                    "forwarded_message",
                    "attachment_text",
                ],
                "attachment_filename": "person-name-receipt.pdf",
            }
        )
        self.assertEqual(clean["message_id"], "mail-1")
        self.assertEqual(clean["booking_numbers"], ["5895361455"])
        self.assertEqual(clean["booking_display_amounts"], [129002])
        self.assertEqual(clean["card_last4"], "8835")
        self.assertEqual(clean["attachment_state"], "text_extracted")
        self.assertEqual(clean["attachment_count"], 2)
        self.assertEqual(
            clean["attachment_mime_types"],
            ["application/pdf", "message/rfc822"],
        )
        self.assertEqual(len(clean["amount_candidates"]), 2)
        self.assertEqual(clean["amount_candidates"][0]["amount"], "129002")
        self.assertEqual(clean["amount_candidates"][0]["currency"], "JPY")
        self.assertNotIn("unsafe_note", clean["amount_candidates"][0])
        self.assertNotIn("attachment_filename", clean)

    def test_ota_attachment_state_and_last4_are_validated(self) -> None:
        clean = sanitize_ota_record(
            {
                "card_last4": "12",
                "attachment_state": "full_attachment_body",
                "attachment_count": "not-a-number",
            }
        )
        self.assertNotIn("card_last4", clean)
        self.assertNotIn("attachment_state", clean)
        self.assertNotIn("attachment_count", clean)

    def test_ota_gmail_attachment_metadata_derives_forwarded_state(self) -> None:
        clean = sanitize_ota_record(
            {
                "messageId": "forwarded-1",
                "has_attachment": True,
                "attachments": [
                    {
                        "filename": "private-name.eml",
                        "mime_type": "message/rfc822",
                    },
                    {
                        "filename": "receipt.pdf",
                        "mime_type": "application/pdf",
                    },
                ],
                "forwardedContentExtracted": "false",
            }
        )
        self.assertEqual(clean["attachment_state"], "present_unread")
        self.assertEqual(clean["attachment_count"], 2)
        self.assertEqual(
            clean["attachment_mime_types"],
            ["message/rfc822", "application/pdf"],
        )
        self.assertTrue(clean["forwarded_content_detected"])
        self.assertFalse(clean["forwarded_content_extracted"])
        self.assertNotIn("attachments", clean)

    def test_ota_import_does_not_drop_collector_aliases_after_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "ota.json"
            source.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "provider": "skyticket",
                                "messageId": "sky-1",
                                "bookingRefs": ["300584370"],
                                "travelDates": ["1127", "1130"],
                                "amounts": [84040],
                                "cardLast4": "8835",
                                "attachmentState": "present_unread",
                                "attachmentCount": 1,
                                "attachmentMimeTypes": ["application/pdf"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db = connect(root / "ledger.db")
            try:
                initialize(db)
                import_ota(db, source)
                row = db.execute(
                    """
                    SELECT payload_json FROM direct_source_records
                    WHERE source_kind='ota_mail' AND source_key='sky-1'
                    """
                ).fetchone()
                payload = json.loads(row[0])
                self.assertEqual(payload["booking_numbers"], ["300584370"])
                self.assertEqual(payload["travel_dates"], ["1127", "1130"])
                self.assertEqual(payload["booking_display_amounts"], [84040])
                self.assertEqual(payload["card_last4"], "8835")
                self.assertEqual(payload["attachment_state"], "present_unread")
            finally:
                db.close()

    def test_direct_ota_import_records_only_confirmed_booking_periods(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "confirmed-bookings.json"
            source.write_text(
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
                            },
                            {
                                "source": "trip_hotel",
                                "messageId": "kbd-1089-confirmed",
                                "type": "charge",
                                "bookingNo": "1400826831996226",
                                "serviceStartOn": "2026-10-31",
                                "bookingStatus": "confirmed",
                            },
                            {
                                "source": "trip_hotel",
                                "messageId": "kbd-1089-evidence-only",
                                "type": "evidence_only",
                                "bookingNo": "1400826831996226",
                                "serviceStartOn": "2026-10-31",
                                "bookingStatus": "confirmed",
                            },
                            {
                                "source": "booking",
                                "messageId": "deposit-pending",
                                "type": "charge",
                                "bookingNo": "5502442589",
                                "serviceStartOn": "2026-08-27",
                                "bookingStatus": "confirmed",
                                "settlementCondition": "refundable_deposit_pending",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db = connect(root / "ledger.db")
            try:
                initialize(db)
                result = import_ota(db, source)
                self.assertEqual(result["confirmed_booking_periods"], 3)
                rows = db.execute(
                    """
                    SELECT b.provider, b.booking_number, p.service_start_on,
                           COALESCE(p.settlement_condition, '') AS settlement_condition
                    FROM direct_booking_service_periods p
                    JOIN bookings b ON b.id=p.booking_id
                    ORDER BY b.booking_number
                    """
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in rows],
                [
                    ("trip.com", "1400826669398170", "2026-08-27", ""),
                    ("trip.com", "1400826831996226", "2026-10-31", ""),
                    ("booking.com", "5502442589", "2026-08-27", "refundable_deposit_pending"),
                ],
                )
                payload = json.loads(
                    db.execute(
                        "SELECT payload_json FROM direct_source_records WHERE source_key='kbd-1029-confirmed'"
                    ).fetchone()[0]
                )
                self.assertNotIn("email", payload)
            finally:
                db.close()

    def test_direct_ota_public_import_initializes_schema_without_trusting_notes(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "standalone-ota.json"
            source.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "source": "trip_hotel",
                                "messageId": "confirmed-period",
                                "type": "charge",
                                "bookingNo": "1400826669398170",
                                "serviceStartOn": "2026-08-27",
                                "bookingStatus": "confirmed",
                            },
                            {
                                "source": "trip_hotel",
                                "messageId": "note-only-period",
                                "type": "evidence_only",
                                "bookingNo": "1400829999999999",
                                "serviceStartOn": "2026-09-01",
                                "bookingStatus": "confirmed",
                                "note": "unverified note reference",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db = connect(root / "standalone.db")
            try:
                result = import_ota(db, source)
                self.assertEqual(result["confirmed_booking_periods"], 1)
                tables = {
                    row[0]
                    for row in db.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type='table'
                        """
                    ).fetchall()
                }
                self.assertIn("direct_source_records", tables)
                self.assertIn("direct_booking_service_periods", tables)
                self.assertEqual(
                    int(
                        db.execute(
                            "SELECT COUNT(*) FROM direct_booking_service_periods"
                        ).fetchone()[0]
                    ),
                    1,
                )
                self.assertEqual(
                    int(
                        db.execute(
                            """
                            SELECT COUNT(*)
                            FROM bookings
                            WHERE booking_number='1400829999999999'
                            """
                        ).fetchone()[0]
                    ),
                    0,
                )
            finally:
                db.close()

    def test_amount_reconciliation_distinguishes_supported_tolerance(self) -> None:
        self.assertEqual(reconcile_amount(100_000, 100_000)[0], "exact")
        self.assertEqual(
            reconcile_amount(996_000, 1_000_000, discount_krw=4_000)[0],
            "discount_adjusted",
        )
        self.assertEqual(
            reconcile_amount(1_015_000, 1_000_000, overseas_krw=True)[0],
            "within_2_percent",
        )
        self.assertEqual(
            reconcile_amount(1_015_000, 1_000_000, overseas_krw=False)[0],
            "mismatch",
        )

    def test_month_day_period_does_not_assume_a_year(self) -> None:
        self.assertEqual(
            normalize_service_period("0417", "0419"),
            ("0417", "0419", "month_day", "0417"),
        )
        self.assertEqual(
            normalize_service_period("2026-04-17", "2026-04-19")[:3],
            ("2026-04-17", "2026-04-19", "day"),
        )


if __name__ == "__main__":
    unittest.main()
