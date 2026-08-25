from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.agoda_booking_evidence import import_agoda_portal_details
from ledger.domain.agoda_mail_import import import_agoda_mail_index
from ledger.domain.ledger_db import initialize


class AgodaMailImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "ledger.sqlite"
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        initialize(db)
        import_agoda_portal_details(
            db,
            [{
                "booking_id": "1234567890",
                "status": "confirmation",
                "reservation_status": "completed",
                "detail_service_start_on": "2026-08-01",
                "detail_service_end_on": "2026-08-02",
                "payment_status": "paid",
                "collection_model": "agoda_collect",
                "price_components": [{
                    "kind": "paid_today",
                    "currency": "JPY",
                    "decimal_text": "86411",
                    "minor_units": 86411,
                    "scale": 0,
                }],
                "captured_at": "2026-08-21T00:00:00Z",
            }],
            run_id="portal-run",
            staging_sha256="a" * 64,
        )
        db.commit()
        db.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_index(self, records: list[dict[str, object]]) -> Path:
        path = self.root / "mail-index.json"
        path.write_text(json.dumps({"records": records}), encoding="utf-8")
        return path

    @staticmethod
    def mail_record(
        message_id: str,
        provider: str = "agoda",
        booking_ref: str = "1234567890",
    ) -> dict[str, object]:
        return {
            "messageId": message_id,
            "subject": "Agoda booking confirmation 2026",
            "sentAt": "2026-07-01T00:00:00+00:00",
            "provider": provider,
            "bookingRefs": [booking_ref] if booking_ref else [],
            "travelDates": ["2026-08-01", "2026-08-02"],
            "amounts": [86411],
            "messageHash": message_id + ("0" * (64 - len(message_id))),
        }

    def test_filters_provider_and_is_idempotent_without_touching_portal(self) -> None:
        index = self.write_index([
            self.mail_record("a" * 16),
            self.mail_record("b" * 16, provider="trip", booking_ref="9999999999"),
            self.mail_record("c" * 16, booking_ref="9876543210"),
        ])
        before = sqlite3.connect(self.db_path)
        before_portal = before.execute(
            "SELECT COUNT(*), MIN(source_sha256) FROM direct_source_records "
            "WHERE source_kind='agoda_portal_detail'"
        ).fetchone()
        before.close()

        first = import_agoda_mail_index(self.db_path, index, "mail-run-1")
        second = import_agoda_mail_index(self.db_path, index, "mail-run-2")

        self.assertEqual(first["input_records"], 3)
        self.assertEqual(first["agoda_records"], 2)
        self.assertEqual(first["skipped_non_agoda"], 1)
        self.assertEqual(first["source_inserted"], 2)
        self.assertEqual(first["bookings_created"], 1)
        self.assertEqual(first["conflicts"], 0)
        self.assertEqual(second["source_inserted"], 0)
        self.assertEqual(second["bookings_created"], 0)
        self.assertEqual(second["evidence_inserted"], 0)

        db = sqlite3.connect(self.db_path)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM bookings WHERE provider='agoda'").fetchone()[0],
            2,
        )
        self.assertEqual(
            db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='ota_mail_live'"
            ).fetchone()[0],
            2,
        )
        after_portal = db.execute(
            "SELECT COUNT(*), MIN(source_sha256) FROM direct_source_records "
            "WHERE source_kind='agoda_portal_detail'"
        ).fetchone()
        self.assertEqual(tuple(after_portal), tuple(before_portal))
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])
        db.close()

    def test_rejects_malformed_row_and_rolls_back_prior_rows(self) -> None:
        index = self.write_index([
            self.mail_record("d" * 16),
            {"provider": "agoda", "messageId": "f" * 16, "email": "must-not-be-stored"},
        ])
        with self.assertRaises(ValueError):
            import_agoda_mail_index(self.db_path, index, "mail-run-bad")
        db = sqlite3.connect(self.db_path)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM direct_source_records WHERE source_kind LIKE 'ota_mail%'").fetchone()[0],
            0,
        )
        db.close()

    def test_rejects_unknown_source_kind_before_opening_database(self) -> None:
        index = self.write_index([self.mail_record("e" * 16)])
        with self.assertRaisesRegex(ValueError, "source_kind_invalid"):
            import_agoda_mail_index(self.db_path, index, "mail-run", source_kind="browser")

    def test_conflicting_mail_batch_rolls_back(self) -> None:
        conflicting = self.mail_record("e" * 16)
        conflicting["status"] = "cancelled"
        index = self.write_index([conflicting])
        with self.assertRaisesRegex(ValueError, "materialization_conflict"):
            import_agoda_mail_index(self.db_path, index, "mail-run-conflict")
        db = sqlite3.connect(self.db_path)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM direct_source_records WHERE source_kind LIKE 'ota_mail%'").fetchone()[0],
            0,
        )
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM bookings WHERE provider='agoda'").fetchone()[0],
            1,
        )
        db.close()


if __name__ == "__main__":
    unittest.main()
