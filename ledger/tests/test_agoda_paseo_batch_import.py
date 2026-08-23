import json
import tempfile
import unittest
from pathlib import Path

from tools.agoda_paseo_batch_import import load_worker_batch, normalize_worker_record


class AgodaPaseoBatchImportTests(unittest.TestCase):
    def _record(self):
        return {
            "booking_id": "1719060820",
            "observed_booking_id": "1719060820",
            "detail_success": True,
            "panel_visible": False,
            "selector_count": 1,
            "status": "confirmed",
            "check_in": "2026-09-28",
            "check_out": "2026-09-29",
            "card_type": "MasterCard",
            "card4": "8835",
            "card_observation_status": "observed_card4",
            "price_components": [{
                "kind": "future_due",
                "currency": "JPY",
                "decimal_text": "8201",
                "minor_units": 8201,
                "scale": 0,
            }],
        }

    def test_normalizes_exact_safe_success(self):
        normalized = normalize_worker_record(self._record())
        self.assertEqual(normalized["booking_id"], "1719060820")
        self.assertEqual(normalized["card4"], "8835")
        self.assertEqual(normalized["price_components"][0]["minor_units"], 8201)

    def test_component_alias_and_scale_are_canonicalized(self):
        record = self._record()
        record["price_components"] = [
            {
                "component": "property_due",
                "currency": "TWD",
                "decimal_text": "2,337.75",
                "minor_units": 999,
            },
            {
                "label": "세금 및 봉사료",
                "currency": "TWD",
                "decimal_text": "362.25",
            },
        ]
        normalized = normalize_worker_record(record)
        self.assertEqual(
            normalized["price_components"],
            [
                {
                    "kind": "property_due",
                    "currency": "TWD",
                    "decimal_text": "2,337.75",
                    "minor_units": 233775,
                    "scale": 2,
                },
                {
                    "kind": "taxes_and_fees",
                    "currency": "TWD",
                    "decimal_text": "362.25",
                    "minor_units": 36225,
                    "scale": 2,
                    "label": "세금 및 봉사료",
                },
            ],
        )

    def test_surcharge_component_is_preserved_as_fee(self):
        record = self._record()
        record["price_components"] = [{
            "kind": "surcharge", "currency": "KRW", "decimal_text": "4,950"
        }]
        normalized = normalize_worker_record(record)
        self.assertEqual(normalized["price_components"][0]["kind"], "fee")
        self.assertEqual(normalized["price_components"][0]["minor_units"], 4950)

    def test_room_component_is_preserved_as_base(self):
        record = self._record()
        record["price_components"] = [{
            "kind": "room", "currency": "JPY", "decimal_text": "33,211"
        }]
        normalized = normalize_worker_record(record)
        self.assertEqual(normalized["price_components"][0]["kind"], "base")
        self.assertEqual(normalized["price_components"][0]["minor_units"], 33211)

    def test_rejects_identity_panel_and_selector_failures(self):
        for key, value, reason in (
            ("observed_booking_id", "1719060821", "worker_observed_booking_id_mismatch"),
            ("panel_visible", True, "worker_customer_center_panel_not_false"),
            ("selector_count", 2, "worker_selector_count_not_one"),
        ):
            record = self._record()
            record[key] = value
            with self.assertRaisesRegex(ValueError, reason):
                normalize_worker_record(record)

    def test_failed_detail_is_preserved_in_artifact_but_not_imported(self):
        record = self._record()
        record["detail_success"] = False
        self.assertIsNone(normalize_worker_record(record))

    def test_multi_room_reference_list_is_preserved_only_in_worker_artifact(self):
        record = self._record()
        record["reference_code"] = "2509160506,2509160508,2509160510"
        normalized = normalize_worker_record(record)
        self.assertNotIn("reference_code", normalized)
        record["reference_code"] = "not a valid reference"
        with self.assertRaisesRegex(ValueError, "worker_reference_code_invalid"):
            normalize_worker_record(record)

    def test_batch_requires_unique_in_scope_records(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "batch.json"
            batch = {"lane": "test", "targets": ["1719060820"], "records": [self._record()], "writes": 0}
            path.write_text(json.dumps(batch), encoding="utf-8")
            loaded, normalized = load_worker_batch(path)
            self.assertEqual(loaded["lane"], "test")
            self.assertEqual(len(normalized), 1)


if __name__ == "__main__":
    unittest.main()
