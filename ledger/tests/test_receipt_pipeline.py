import copy
import json
import tempfile
import unittest
from pathlib import Path

from ledger.receipt_pipeline import ReceiptBatchError, load_and_validate, validate_batch


def make_batch():
    return {
        "batch_id": "synthetic-r8", "currency": "JPY",
        "conversion_policy": {"type": "fixed_convenience_rate",
                               "krw_per_jpy": 10,
                               "confirmed_by_user_on": "2026-07-29"},
        "images": [{"image_id": "img-1", "expected_physical_receipts": 2},
                   {"image_id": "img-2", "expected_physical_receipts": 1}],
        "receipts": [
            {"physical_id": "r-1", "image_id": "img-1", "date": "2026-07-01",
             "amount_jpy": {"status": "confirmed", "value": 7300},
             "trip_assignment": {"status": "auto_assigned", "header_match": True,
                                 "date_region_match": True}},
            {"physical_id": "r-2", "image_id": "img-1", "date": "2026-07-01",
             "amount_jpy": {"status": "confirmed", "value": 7300},
             "trip_assignment": {"status": "manual_confirmed"}},
            {"physical_id": "r-3", "image_id": "img-2", "date": None,
             "amount_jpy": {"status": "unreadable", "value": None},
             "trip_assignment": {"status": "review_required"}},
        ],
    }


class ReceiptPipelineTests(unittest.TestCase):
    def test_valid_summary_and_tuple_is_not_deduped(self):
        batch = make_batch()
        self.assertEqual(validate_batch(batch), {
            "physical_receipt_count": 3, "confirmed_amount_count": 2,
            "confirmed_total_jpy": 14600, "confirmed_total_krw": 146000})

    def test_missing_or_unknown_image(self):
        batch = make_batch(); batch["receipts"].pop()
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)

    def test_image_and_receipt_ids_must_be_nonblank_and_objects(self):
        for key in ("image_id", "physical_id"):
            batch = make_batch()
            if key == "image_id":
                batch["images"][0][key] = "  "
            else:
                batch["receipts"][0][key] = ""
            with self.assertRaises(ReceiptBatchError): validate_batch(batch)
        batch = make_batch(); batch["images"][0] = []
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)
        batch = make_batch(); batch["receipts"][0] = []
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)
        batch = make_batch(); batch["receipts"][0]["image_id"] = "nope"
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)

    def test_duplicate_ids_and_no_input_mutation(self):
        batch = make_batch(); original = copy.deepcopy(batch)
        batch["receipts"][1]["physical_id"] = "r-1"
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)
        self.assertEqual(batch, {**original, "receipts": [
            original["receipts"][0], batch["receipts"][1], original["receipts"][2]]})

    def test_invalid_count_bool_and_mismatch(self):
        for value in (True, 0, 1.0):
            batch = make_batch()
            batch["images"][0]["expected_physical_receipts"] = value
            with self.assertRaises(ReceiptBatchError): validate_batch(batch)
        batch = make_batch(); batch["images"][0]["expected_physical_receipts"] = 1
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)

    def test_invalid_amount_status_and_value(self):
        for amount in ({"status": "bad", "value": 1},
                       {"status": "confirmed", "value": None},
                       {"status": "confirmed", "value": True},
                       {"status": "estimated", "value": -1}):
            batch = make_batch(); batch["receipts"][0]["amount_jpy"] = amount
            with self.assertRaises(ReceiptBatchError): validate_batch(batch)

    def test_trip_status_must_be_known(self):
        for status in ("unknown", None):
            batch = make_batch()
            batch["receipts"][0]["trip_assignment"]["status"] = status
            with self.assertRaises(ReceiptBatchError): validate_batch(batch)

    def test_invalid_date_and_auto_signals(self):
        batch = make_batch(); batch["receipts"][0]["date"] = "2026-02-30"
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)
        batch = make_batch()
        batch["receipts"][0]["trip_assignment"]["header_match"] = 1
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)

    def test_batch_currency_policy_and_confirmation_date_scope(self):
        for path, value in ((["batch_id"], " "), (["currency"], "KRW"),
                            (["conversion_policy", "type"], "x"),
                            (["conversion_policy", "krw_per_jpy"], True),
                            (["conversion_policy", "confirmed_by_user_on"],
                             "2026-1-1")):
            batch = make_batch(); target = batch
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.assertRaises(ReceiptBatchError): validate_batch(batch)

    def test_eur_rejected_and_top_level_must_be_object(self):
        batch = make_batch(); batch["currency"] = "EUR"
        with self.assertRaises(ReceiptBatchError): validate_batch(batch)
        with self.assertRaises(ReceiptBatchError): validate_batch([])

    def test_temp_json_load_and_immutability(self):
        batch = make_batch(); before = copy.deepcopy(batch)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            path.write_text(json.dumps(batch), encoding="utf-8")
            self.assertEqual(load_and_validate(path)["physical_receipt_count"], 3)
        self.assertEqual(batch, before)


if __name__ == "__main__":
    unittest.main()
