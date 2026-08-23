from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.agoda_booking_evidence import (
    import_agoda_portal_details,
    import_agoda_portal_staging,
    materialize_agoda_mail_bookings,
)
from ledger.domain.direct_sources import import_ota
from ledger.domain.direct_sources import import_all
from ledger.domain.ledger_db import connect, initialize


class AgodaBookingEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / "evidence.db")
        initialize(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def _mail(self, message_id: str, *, source_kind: str = "ota_mail") -> None:
        path = self.root / f"{message_id}.json"
        path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "messageId": message_id,
                            "provider": "Agoda",
                            "bookingRefs": ["123456789"],
                            "travelDates": ["2026-08-15", "2026-08-16"],
                            "subject": "Agoda booking confirmation",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        import_ota(self.db, path, source_kind=source_kind)

    @staticmethod
    def _portal(*, status: str = "투숙 완료", end: str = "2026-08-16") -> dict[str, object]:
        return {
            "booking_id": "123456789",
            "status": status,
            "reservation_status": status,
            "detail_service_start_on": "2026-08-15",
            "detail_service_end_on": end,
            "payment_status": "paid",
            "collection_model": "agoda_collect",
            "card_type": "MasterCard",
            "card4": "8835",
            "card_role": "payment_or_guarantee_unresolved",
            "price_components": [
                {"kind": "base", "currency": "JPY", "decimal_text": "11532", "minor_units": 11532, "scale": 0},
                {"kind": "taxes_and_fees", "currency": "JPY", "decimal_text": "2421", "minor_units": 2421, "scale": 0},
                {"kind": "paid_today", "currency": "JPY", "decimal_text": "13953", "minor_units": 13953, "scale": 0},
                {"kind": "gross_total", "currency": "JPY", "decimal_text": "13953", "minor_units": 13953, "scale": 0},
            ],
            "payment_events": [],
            "captured_at": "2026-08-21T10:00:00Z",
        }

    def test_mail_and_portal_share_one_booking_and_keep_lineage(self) -> None:
        self._mail("mail-1")
        self.assertEqual(materialize_agoda_mail_bookings(self.db)["materialized"], 1)
        self._mail("mail-2", source_kind="ota_mail_live")
        materialize_agoda_mail_bookings(self.db)

        first = import_agoda_portal_details(
            self.db,
            [self._portal()],
            run_id="capture-1",
            staging_sha256="a" * 64,
        )
        self.assertEqual(first["source_inserted"], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM bookings WHERE provider='agoda'").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM direct_source_lineage").fetchone()[0],
            3,
        )
        roles = {
            row[0]
            for row in self.db.execute(
                "SELECT DISTINCT evidence_role FROM booking_source_evidence"
            )
        }
        self.assertEqual(
            roles,
            {"identity", "service_period", "lifecycle", "portal_payment_claim", "portal_card_observation"},
        )
        payload = json.loads(
            self.db.execute(
                "SELECT payload_json FROM direct_source_records "
                "WHERE source_kind='agoda_portal_detail'"
            ).fetchone()[0]
        )
        self.assertEqual(payload["portal_payment_state"], "paid_today")
        self.assertEqual(payload["card_last4"], "8835")
        self.assertEqual(payload["price_components"][2]["kind"], "paid_today")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM payment_booking_links").fetchone()[0],
            0,
        )

    def test_portal_recapture_is_idempotent_and_conflict_is_preserved(self) -> None:
        self._mail("mail-1")
        materialize_agoda_mail_bookings(self.db)
        record = self._portal()
        import_agoda_portal_details(self.db, [record], run_id="capture-1")
        before = self.db.execute(
            "SELECT COUNT(*) FROM booking_source_evidence"
        ).fetchone()[0]
        repeated = import_agoda_portal_details(self.db, [record], run_id="capture-1")
        self.assertEqual(repeated["source_inserted"], 0)
        self.assertEqual(repeated["evidence_inserted"], 0)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM booking_source_evidence").fetchone()[0],
            before,
        )

        conflict = self._portal(status="취소됨", end="2026-08-17")
        import_agoda_portal_details(self.db, [conflict], run_id="capture-2")
        booking = self.db.execute(
            "SELECT service_end_on, status FROM bookings WHERE provider='agoda'"
        ).fetchone()
        self.assertEqual(tuple(booking), ("2026-08-16", "confirmed"))
        self.assertGreater(
            self.db.execute(
                "SELECT MAX(conflict_count) FROM booking_source_evidence"
            ).fetchone()[0],
            0,
        )

    def test_card_observation_status_is_explicit_and_validated(self) -> None:
        record = self._portal()
        record["card4"] = None
        record["card_observation_status"] = "confirmed_non_card"
        result = import_agoda_portal_details(self.db, [record], run_id="capture-status")
        self.assertEqual(result["source_inserted"], 1)
        payload = json.loads(
            self.db.execute(
                "SELECT payload_json FROM direct_source_records "
                "WHERE source_kind='agoda_portal_detail'"
            ).fetchone()[0]
        )
        self.assertEqual(payload["card_observation_status"], "confirmed_non_card")
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM booking_source_evidence "
                "WHERE evidence_role='portal_card_observation'"
            ).fetchone()[0],
            1,
        )
        invalid = self._portal()
        invalid["card_observation_status"] = "maybe"
        with self.assertRaisesRegex(ValueError, "card_observation_status_invalid"):
            import_agoda_portal_details(self.db, [invalid], run_id="capture-invalid-status")

    def test_ambiguous_mail_reference_is_unresolved_not_a_guessed_booking(self) -> None:
        path = self.root / "ambiguous.json"
        path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "messageId": "ambiguous",
                            "provider": "Agoda",
                            "bookingRefs": ["123456789", "987654321"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        import_ota(self.db, path)
        stats = materialize_agoda_mail_bookings(self.db)
        self.assertEqual(stats["unresolved"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0], 0)

    def test_staging_adapter_reads_structured_rows_only(self) -> None:
        stage_path = self.root / "capture.sqlite"
        stage = sqlite3.connect(stage_path)
        try:
            stage.execute("PRAGMA journal_mode=WAL")
            stage.execute("PRAGMA wal_autocheckpoint=0")
            stage.executescript(
                """
                CREATE TABLE booking_detail_snapshots(
                    snapshot_id INTEGER PRIMARY KEY, run_id TEXT, booking_id TEXT,
                    reference_code TEXT, booking_id_sha256 TEXT,
                    detail_service_start_on TEXT, detail_service_end_on TEXT,
                    reservation_status TEXT, payment_status TEXT,
                    collection_model TEXT, refund_status TEXT, card_type TEXT,
                    card4 TEXT, card4_sha256 TEXT, card_role TEXT,
                    semantic_detail_sha256 TEXT, captured_at_utc TEXT
                );
                CREATE TABLE price_components(
                    snapshot_id INTEGER, ordinal INTEGER, component_kind TEXT,
                    currency TEXT, amount_decimal_text TEXT,
                    amount_minor_units INTEGER, currency_scale INTEGER
                );
                CREATE TABLE payment_events(
                    event_id INTEGER, snapshot_id INTEGER, event_kind TEXT,
                    event_on TEXT, currency TEXT, amount_decimal_text TEXT,
                    amount_minor_units INTEGER, currency_scale INTEGER,
                    card4_sha256 TEXT, evidence_label TEXT
                );
                """
            )
            stage.execute(
                """
                INSERT INTO booking_detail_snapshots VALUES(
                    1,'run-stage','123456789','REF-1',?,
                    '2026-08-15','2026-08-16','투숙 완료','paid',
                    'agoda_collect','none','MasterCard','8835',?,
                    'payment_or_guarantee_unresolved',?, '2026-08-21T10:00:00Z'
                )
                """,
                (
                    "15e2b0d3c33891ebb0f1ef609ec419420c20e320ce94c65fbc8c3312448eb225",
                    "e7681ff01626eca8ae89f31aa37d90564271ac32e252ede68f445a9fe0c1af8c",
                    "c" * 64,
                ),
            )
            stage.execute(
                "INSERT INTO price_components VALUES(1,1,'paid_today','JPY','13953',13953,0)"
            )
            stage.commit()
        finally:
            stage.close()
        source = sqlite3.connect(
            f"file:{stage_path.resolve().as_posix()}?mode=ro", uri=True
        )
        frozen = sqlite3.connect(":memory:")
        try:
            source.backup(frozen)
            stage_digest = hashlib.sha256(frozen.serialize()).hexdigest()
        finally:
            frozen.close()
            source.close()
        with self.assertRaisesRegex(ValueError, "agoda_staging_sha256_mismatch"):
            import_agoda_portal_staging(
                self.db,
                stage_path,
                staging_sha256="0" * 64,
            )
        stats = import_agoda_portal_staging(
            self.db, stage_path, staging_sha256=stage_digest
        )
        self.assertEqual(stats["records"], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0],
            0,
        )
        payload = json.loads(
            self.db.execute(
                "SELECT payload_json FROM direct_source_records "
                "WHERE source_kind='agoda_portal_detail'"
            ).fetchone()[0]
        )
        self.assertEqual(payload["portal_payment_state"], "paid_today")
        self.assertEqual(payload["observed_at"], "2026-08-21T10:00:00Z")
        self.assertEqual(payload["observed_semantic_detail_sha256"], "c" * 64)
        self.assertNotEqual(payload["semantic_detail_sha256"], "c" * 64)

    def test_source_payload_hash_and_lineage_are_exact(self) -> None:
        self._mail("mail-hash")
        materialize_agoda_mail_bookings(self.db)
        row = self.db.execute(
            """
            SELECT d.source_sha256, sd.sha256, sr.raw_payload
            FROM direct_source_records d
            JOIN direct_source_lineage l ON l.direct_source_record_id=d.id
            JOIN source_records sr ON sr.id=l.source_record_id
            JOIN source_documents sd ON sd.id=sr.document_id
            WHERE d.source_kind='ota_mail'
            """
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], row[1])
        import hashlib
        self.assertEqual(
            hashlib.sha256(str(row[2]).encode("utf-8")).hexdigest(), row[0]
        )

    def test_mismatched_evidence_source_tuple_is_rejected_by_composite_fk(self) -> None:
        self._mail("mail-fk-1")
        self._mail("mail-fk-2")
        rows = self.db.execute(
            "SELECT id, source_kind, source_key, source_sha256 FROM direct_source_records "
            "WHERE source_kind='ota_mail' ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        first, second = rows
        booking = self.db.execute(
            "INSERT INTO bookings(provider, booking_number) VALUES('agoda','123456789')"
        )
        booking_id = int(booking.lastrowid)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """
                INSERT INTO booking_source_evidence(
                    booking_id, direct_source_record_id, source_kind,
                    source_key, source_sha256, evidence_kind, evidence_role
                ) VALUES(?,?,?,?,?,'ota_mail','identity')
                """,
                (booking_id, first[0], second[1], second[2], second[3]),
            )

    def test_portal_hash_and_staging_hash_mismatch_fail_closed(self) -> None:
        record = self._portal()
        record["booking_id_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "booking_id_sha256_mismatch"):
            import_agoda_portal_details(self.db, [record], run_id="bad-hash")
        record = self._portal()
        record["payment_events"] = [{
            "event_kind": "charge",
            "currency": "JPY",
            "decimal_text": "1",
            "evidence_label": "card 4111111111111111",
        }]
        with self.assertRaisesRegex(ValueError, "evidence_label_value_invalid"):
            import_agoda_portal_details(self.db, [record], run_id="bad-label")

    def test_money_representations_must_agree(self) -> None:
        record = self._portal()
        record["price_components"] = [
            dict(record["price_components"][0], minor_units=1),
            *record["price_components"][1:],
        ]
        with self.assertRaisesRegex(ValueError, "component_representation_mismatch"):
            import_agoda_portal_details(self.db, [record], run_id="bad-money")
        record = self._portal()
        record["payment_events"] = [{
            "event_kind": "charge",
            "currency": "JPY",
            "decimal_text": "1",
            "minor_units": 1,
            "scale": 10,
        }]
        with self.assertRaisesRegex(ValueError, "payment_event_scale_invalid"):
            import_agoda_portal_details(self.db, [record], run_id="bad-scale")
        record = self._portal()
        record["price_components"] = [
            dict(record["price_components"][0], minor_units=1 << 63),
            *record["price_components"][1:],
        ]
        with self.assertRaisesRegex(ValueError, "component_minor_units_out_of_range"):
            import_agoda_portal_details(self.db, [record], run_id="bad-minor-units")

    def test_default_import_rolls_back_if_a_later_import_fails(self) -> None:
        ota = self.root / "ota.json"
        ota.write_text(
            json.dumps({
                "records": [{
                    "messageId": "rollback-mail",
                    "provider": "Agoda",
                    "bookingRefs": ["123456789"],
                }]
            }),
            encoding="utf-8",
        )
        manual = self.root / "manual.csv"
        manual.write_text("tab,row\n", encoding="utf-8")
        bad_trip = self.root / "bad-trips.json"
        bad_trip.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "trip_schedule_root_invalid"):
            import_all(
                self.db,
                self.root,
                manual,
                ota,
                cards=[],
                trip_path=bad_trip,
            )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM direct_source_records").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
