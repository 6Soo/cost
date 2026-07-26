import copy
import json
import tempfile
import unittest
from pathlib import Path

from ledger.domain.ledger_db import connect, initialize
from ledger.domain.receipt_projection import import_receipt_batch


ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / "ledger" / "receipt_pipeline" / "receipt_batch_20260726.json"


class ReceiptProjectionTests(unittest.TestCase):
    def _batch_file(self, root: Path, payload: dict) -> Path:
        path = root / "receipts.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_projection_preserves_each_receipt_and_only_posts_confirmed_cash(self):
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "ledger.db")
            try:
                initialize(db)
                result = import_receipt_batch(db, BATCH_PATH)
                self.assertEqual(result["physical_events_appended"], 19)
                self.assertEqual(result["manual_events_projected"], 2)
                self.assertEqual(result["physical_event_total"], 19)
                self.assertEqual(result["manual_event_total"], 2)
                duplicate_amount = db.execute(
                    "SELECT COUNT(*) FROM physical_receipt_events WHERE amount_jpy=7300"
                ).fetchone()[0]
                self.assertEqual(duplicate_amount, 2)
                methods = dict(db.execute(
                    "SELECT payment_method, COUNT(*) FROM physical_receipt_events GROUP BY payment_method"
                ).fetchall())
                self.assertGreater(methods["card"], 0)
                self.assertGreater(methods["unknown"], 0)
                posted = db.execute(
                    "SELECT amount_krw FROM manual_receipt_projections ORDER BY amount_krw"
                ).fetchall()
                self.assertEqual([row[0] for row in posted], [66_000, 115_500])
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM direct_normalized_payments").fetchone()[0],
                    0,
                )
            finally:
                db.close()

    def test_replay_is_idempotent_and_correction_appends_a_new_version(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            payload = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
            path = self._batch_file(root, payload)
            db = connect(root / "ledger.db")
            try:
                initialize(db)
                import_receipt_batch(db, path)
                replay = import_receipt_batch(db, path)
                self.assertEqual(replay["physical_events_appended"], 0)
                corrected = copy.deepcopy(payload)
                corrected["receipts"][0]["merchant"]["confidence"] = 0.95
                corrected_path = self._batch_file(root, corrected)
                changed = import_receipt_batch(db, corrected_path)
                self.assertEqual(changed["physical_events_appended"], 1)
                versions = db.execute(
                    """
                    SELECT event_version FROM physical_receipt_events
                    WHERE physical_id='photo-1-r01' ORDER BY event_version
                    """
                ).fetchall()
                self.assertEqual([row[0] for row in versions], [1, 2])
            finally:
                db.close()

    def test_sensitive_free_text_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            payload = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
            payload["images"][0]["header"]["raw"] = "SECRET-HEADER"
            payload["receipts"][0]["payment_method"]["detail"] = "SECRET-CARD-DETAIL"
            payload["receipts"][0]["notes"] = ["SECRET-NOTE"]
            path = self._batch_file(root, payload)
            db = connect(root / "ledger.db")
            try:
                initialize(db)
                import_receipt_batch(db, path)
                saved = "\n".join(row[0] for row in db.execute(
                    "SELECT payload_json FROM direct_source_records"
                ).fetchall())
                self.assertNotIn("SECRET-HEADER", saved)
                self.assertNotIn("SECRET-CARD-DETAIL", saved)
                self.assertNotIn("SECRET-NOTE", saved)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
