import copy
import json
import unittest
from pathlib import Path

from ledger.receipt_pipeline import ReceiptBatchError, validate_batch


ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / "ledger" / "receipt_pipeline" / "receipt_batch_20260726.json"


def load_batch():
    return json.loads(BATCH_PATH.read_text(encoding="utf-8"))


class ReceiptPipelineTests(unittest.TestCase):
    def test_physical_bijection_and_total(self):
        summary = validate_batch(load_batch())
        self.assertEqual(summary["physical_receipt_count"], 19)
        self.assertEqual(summary["confirmed_amount_count"], 19)
        self.assertEqual(summary["confirmed_total_jpy"], 187_847)
        self.assertEqual(summary["confirmed_total_krw"], 1_878_470)

    def test_same_date_merchant_amount_are_not_deduplicated(self):
        batch = load_batch()
        receipts = {item["physical_id"]: item for item in batch["receipts"]}
        self.assertEqual(receipts["photo-3-r03"]["amount_jpy"]["value"], 7_300)
        self.assertEqual(receipts["photo-3-r04"]["amount_jpy"]["value"], 7_300)
        self.assertEqual(len(receipts), 19)
        validate_batch(batch)

    def test_urabandai_is_user_confirmed_travel_consumables(self):
        receipts = {
            item["physical_id"]: item for item in load_batch()["receipts"]
        }
        for physical_id, amount_krw in (
            ("photo-3-r01", 115_500),
            ("photo-3-r02", 66_000),
        ):
            classification = receipts[physical_id]["classification"]
            self.assertEqual(classification["target"], "여행원가")
            self.assertEqual(classification["account"], "여행 식재료·소모품")
            self.assertEqual(classification["status"], "user_confirmed")
            self.assertEqual(classification["amount_krw"], amount_krw)

    def test_missing_physical_receipt_fails(self):
        batch = load_batch()
        batch["receipts"].pop()
        with self.assertRaisesRegex(ReceiptBatchError, "expected 7"):
            validate_batch(batch)

    def test_duplicate_physical_id_fails(self):
        batch = load_batch()
        batch["receipts"][1]["physical_id"] = batch["receipts"][0]["physical_id"]
        with self.assertRaisesRegex(ReceiptBatchError, "duplicate physical_id"):
            validate_batch(batch)

    def test_p23_blocks_header_conflict_from_auto_assignment(self):
        batch = load_batch()
        family_mart = next(
            item for item in batch["receipts"]
            if item["physical_id"] == "photo-2-r03"
        )
        family_mart["trip_assignment"]["status"] = "auto_assigned"
        with self.assertRaisesRegex(ReceiptBatchError, "header match"):
            validate_batch(batch)

    def test_photo_two_can_split_across_trip_tabs_after_manual_confirmation(self):
        batch = load_batch()
        photo_two = [
            item for item in batch["receipts"] if item["image_id"] == "photo-2"
        ]
        self.assertEqual(
            [item["trip_assignment"]["trip_candidate"] for item in photo_two],
            ["0625_아키타", "0625_아키타", "0630_오제"],
        )
        self.assertEqual(
            photo_two[-1]["trip_assignment"]["status"], "manual_confirmed"
        )
        validate_batch(batch)


if __name__ == "__main__":
    unittest.main()
