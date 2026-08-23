from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.ledger_db import initialize
from tools.import_agoda_mail_card_evidence import import_artifact


class AgodaMailCardEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "ledger.sqlite"
        db = sqlite3.connect(self.db_path)
        initialize(db)
        db.execute(
            """INSERT INTO bookings(provider,booking_number,product_type,label,
               service_start_on,service_end_on,status) VALUES(?,?,?,?,?,?,?)""",
            ("agoda", "1520497128", "lodging", "Hotel Route Inn Rifu",
             "2025-02-22", "2025-02-23", "completed"),
        )
        db.commit()
        db.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def artifact(self, **overrides: object) -> Path:
        record = {
            "booking_id": "1520497128",
            "gmail_message_id": "194c5a72c5281732",
            "attachment_filename": "Confirmation_for_Booking_ID_#_1520497128.pdf",
            "sent_at": "2025-02-02T07:54:15+00:00",
            "service_start_on": "2025-02-22",
            "service_end_on": "2025-02-23",
            "card_type": "MasterCard",
            "card_last4": "5855",
            "evidence_text_sha256": hashlib.sha256(b"exact redacted excerpt").hexdigest(),
            "scheduled_payment": {"currency": "JPY", "decimal_text": "29995", "due_on": "2025-02-19"},
        }
        record.update(overrides)
        path = self.root / "evidence.json"
        path.write_text(json.dumps({"artifact_type": "agoda-mail-card-evidence-v1", "records": [record]}), encoding="utf-8")
        return path

    def test_imports_mail_provenance_without_relabelling_as_portal(self) -> None:
        path = self.artifact()
        first = import_artifact(self.db_path, path, "run-1")
        second = import_artifact(self.db_path, path, "run-2")
        self.assertEqual(first["source_inserted"], 1)
        self.assertEqual(second["source_inserted"], 0)
        db = sqlite3.connect(self.db_path)
        rows = db.execute(
            """SELECT s.source_kind,s.payload_json,e.evidence_kind,e.evidence_role
               FROM direct_source_records s JOIN booking_source_evidence e
                 ON e.direct_source_record_id=s.id"""
        ).fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        db.close()
        self.assertEqual({row[0] for row in rows}, {"ota_mail_live"})
        self.assertEqual({row[2] for row in rows}, {"ota_mail_live"})
        self.assertEqual({row[3] for row in rows}, {"identity", "service_period", "lifecycle"})
        payload = json.loads(rows[0][1])
        self.assertEqual(payload["card_last4"], "5855")
        self.assertEqual(payload["evidence_origin"], "gmail_attachment_confirmation_pdf")
        self.assertEqual(integrity, "ok")
        self.assertEqual(foreign_keys, [])

    def test_period_conflict_rolls_back(self) -> None:
        path = self.artifact(service_start_on="2025-02-21")
        with self.assertRaisesRegex(ValueError, "mail_card_service_period_conflict"):
            import_artifact(self.db_path, path, "run-bad")
        db = sqlite3.connect(self.db_path)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM direct_source_records").fetchone()[0], 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
