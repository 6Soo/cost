import json
import sqlite3
import unittest

from ledger.domain.direct_geographic_trip_context import (
    SCHEMA_VERSION,
    TARGET_CODE,
    context_keys,
    is_taiwan_marker,
    validate_geographic_trip_context_document,
)


class GeographicTripContextTest(unittest.TestCase):
    def _document(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "records": [{
                "tab": TARGET_CODE,
                "mm": 1,
                "dd": 7,
                "region": "대만",
                "window": 8,
                "current_card_geography_required": True,
                "payment_date_is_service_date": False,
                "transaction_evidence_allowed": False,
                "provenance": {
                    "kind": "historical_context_only",
                    "source_path": "ledger/data/retired_staff_ota_index.json",
                    "source_rows": ["2026:43", "2026:44"],
                    "note": "context only",
                },
            }],
        }

    def test_context_is_strict_and_keyed_by_target(self):
        raw = json.dumps(self._document(), ensure_ascii=False).encode("utf-8")
        self.assertEqual(context_keys(raw), [TARGET_CODE])
        self.assertEqual(
            validate_geographic_trip_context_document(self._document())[0]["window"],
            8,
        )

    def test_context_cannot_be_transaction_evidence(self):
        document = self._document()
        document["records"][0]["transaction_evidence_allowed"] = True
        with self.assertRaisesRegex(ValueError, "authority_invalid"):
            validate_geographic_trip_context_document(document)

    def test_marker_boundary_is_explicit(self):
        self.assertTrue(is_taiwan_marker("TAIPEI TW"))
        self.assertTrue(is_taiwan_marker("Cafe Taichung City"))
        self.assertTrue(is_taiwan_marker("HUALIEN STATION"))
        self.assertFalse(is_taiwan_marker("TAIYUAN HOTEL"))
        self.assertFalse(is_taiwan_marker("TWD 1,000"))
        self.assertFalse(is_taiwan_marker("TWIN NETWORK"))


if __name__ == "__main__":
    unittest.main()
