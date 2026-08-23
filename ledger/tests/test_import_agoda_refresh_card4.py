import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.ledger_db import initialize
from tools.import_agoda_refresh_card4 import import_bundle, validate_bundle


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ImportAgodaRefreshCard4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline.sqlite"
        self.current = self.root / "current.sqlite"
        for path in (self.baseline, self.current):
            db = sqlite3.connect(path)
            initialize(db)
            db.execute(
                "INSERT INTO bookings(provider, booking_number, product_type, status) VALUES ('agoda','12345678','lodging','completed')"
            )
            db.commit()
            db.close()
        self.refresh_path = self.root / "refresh.json"
        self.card_path = self.root / "card.json"
        self._write_bundle()

    def tearDown(self):
        self.temp.cleanup()

    def _write_bundle(self):
        old = {
            "source_id": "12345678", "status": "Completed", "detail_id": "old",
            "hotel": "Old", "dates": [], "payment_lines": [], "total_line": None,
            "id_exact_match": True,
        }
        new = {
            "source_id": "87654321", "status": "Upcoming",
            "detail_id": "M/+NFhbs2LOsd8vxlkqTXg==", "hotel": "New",
            "dates": ["2026년 10월 26일 월요일 - 2026년 10월 28일 수요일", "체크인", "2026년 10월 26일 월요일", "체크아웃", "2026년 10월 28일 수요일"],
            "payment_lines": ["JPY 100", "JPY 10", "JPY 110", "JPY 110"],
            "total_line": ["총 금액", "JPY 110"], "id_exact_match": True,
            "support_visible_count": 1,
        }
        records = [old, new]
        refresh = {
            "source": "test", "cancelled_excluded": True, "records": records,
            "integrity": {
                "record_count": 2, "unique_source_ids": 2, "duplicate_source_ids": 0,
                "records_sha256": hashlib.sha256(canonical(records).encode()).hexdigest(),
            },
            "refresh_manifest": {
                "captured_at_utc": "2026-08-21T00:00:00Z", "record_count": 1,
                "unique_source_ids": 1, "source_ids_sha256": hashlib.sha256(canonical(["87654321"]).encode()).hexdigest(),
                "customer_center_click_count": 0, "customer_center_route_count": 0,
            },
        }
        self.refresh_path.write_text(json.dumps(refresh, ensure_ascii=False), encoding="utf-8")
        refresh_hash = hashlib.sha256(self.refresh_path.read_bytes()).hexdigest()
        detail = {key: new[key] for key in ("source_id", "status", "detail_id", "hotel", "dates", "payment_lines", "total_line")}
        detail.update({
            "detail_capture_route": True, "support_clicks": 0, "card4": "8835",
            "card_line": "•••• •••• •••• 8835", "payment_state": "scheduled",
            "payment_amount": "", "total_amount": "JPY 110",
        })
        card = {
            "schema": "agoda-paseo-staging-refresh-card4-v1", "captured_at": "2026-08-21",
            "source_staging_sha256": refresh_hash, "customer_center_clicks": 0,
            "summary": {
                "record_count": 1, "detail_captured": 1, "card4_present": 1,
                "distinct_card4": ["8835"], "payment_states": {"scheduled": 1},
            },
            "records": [detail],
        }
        self.card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    def test_validates_and_imports_exact_delta(self):
        metadata, records = validate_bundle(self.refresh_path, self.card_path, self.baseline)
        self.assertEqual(metadata["delta_count"], 1)
        self.assertEqual(records[0]["card4"], "8835")
        self.assertEqual([x["kind"] for x in records[0]["price_components"]], [
            "base", "taxes_and_fees", "future_due", "gross_total"
        ])
        report = import_bundle(
            self.current, self.refresh_path, self.card_path, self.baseline, "test-refresh"
        )
        self.assertEqual(report["bookings_added"], 1)
        self.assertEqual(report["integrity_check"], "ok")
        db = sqlite3.connect(self.current)
        payload = json.loads(db.execute(
            "SELECT payload_json FROM direct_source_records WHERE source_kind='agoda_portal_detail'"
        ).fetchone()[0])
        self.assertEqual(payload["card_last4"], "8835")
        db.close()

    def test_rejects_digest_safety_delta_and_money_tampering(self):
        original = json.loads(self.card_path.read_text(encoding="utf-8"))
        mutations = []
        bad = copy.deepcopy(original); bad["source_staging_sha256"] = "0" * 64; mutations.append((bad, "digest"))
        bad = copy.deepcopy(original); bad["customer_center_clicks"] = 1; mutations.append((bad, "customer"))
        bad = copy.deepcopy(original); bad["records"][0]["source_id"] = "99999999"; mutations.append((bad, "delta"))
        bad = copy.deepcopy(original); bad["records"][0]["payment_lines"][3] = "JPY 111"; mutations.append((bad, "payment"))
        for value, label in mutations:
            with self.subTest(label=label):
                self.card_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_bundle(self.refresh_path, self.card_path, self.baseline)
        self.card_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
