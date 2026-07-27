from __future__ import annotations

import unittest
from pathlib import Path

from ledger.domain.legacy_card_review import review_legacy_card_claim
from ledger.domain.source_loss_gate import source_loss_gate


class LegacyCardReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.europe_row = {
            "uid": "TRIP-0233", "src": "HAN", "appr": "00324153",
            "krw": "472743", "use_date": "2026-05-28",
            "merchant": "PARK HOTEL GOLDEN", "cancel": "False",
        }
        self.unrelated_hana = {
            "src": "HAN", "raw_record_id": "H:907", "appr": "00324153",
            "krw": 472743, "use": "2026-01-20",
            "mer": "UNRELATED MERCHANT", "cancel": False,
        }

    def test_approval_amount_match_with_date_and_merchant_mismatch_is_conflict(self) -> None:
        result = review_legacy_card_claim(self.europe_row, [self.unrelated_hana])
        self.assertEqual(result["status"], "facts_conflict")
        self.assertEqual(result["mismatch_fields"], ["date", "merchant"])
        self.assertEqual(result["candidate_raw_ids"], ["HAN:H:907"])

    def test_missing_raw_material_is_not_reported_as_a_conflict(self) -> None:
        result = review_legacy_card_claim(self.europe_row, [])
        self.assertEqual(result, {"status": "raw_material_absent"})
        gate = source_loss_gate([self.europe_row], [])
        self.assertTrue(gate["closure_blocked"])
        self.assertEqual(
            gate["closure_blocking_queue"][0]["status"],
            "source_event_absent",
        )

    def test_exact_legacy_candidate_stays_manual_review_without_explicit_identity(self) -> None:
        raw = self.unrelated_hana | {
            "raw_record_id": "H:908", "use": "2026-05-28",
            "mer": "PARK HOTEL GOLDEN",
        }
        result = review_legacy_card_claim(self.europe_row, [raw])
        self.assertEqual(result["status"], "manual_review_required")
        self.assertEqual(result["reason"], "explicit_source_event_id_required")
        self.assertEqual(result["candidate_raw_ids"], ["HAN:H:908"])

    def test_same_approval_in_another_source_is_not_merged(self) -> None:
        other_source = self.unrelated_hana | {"src": "KBD", "raw_record_id": "F:990"}
        result = review_legacy_card_claim(self.europe_row, [other_source])
        self.assertEqual(result["status"], "source_conflict")
        self.assertEqual(result["candidate_raw_ids"], ["KBD:F:990"])

    def test_approval_and_cancellation_roles_are_independent(self) -> None:
        cancellation = self.unrelated_hana | {
            "raw_record_id": "H:907:refund", "use": "2026-05-28",
            "mer": "PARK HOTEL GOLDEN", "cancel": True,
        }
        result = review_legacy_card_claim(self.europe_row, [cancellation])
        self.assertEqual(result["status"], "cancellation_role_conflict")
        self.assertEqual(result["candidate_raw_ids"], ["HAN:H:907:refund"])

    def test_explicit_source_identity_is_not_replaced_by_a_lookup(self) -> None:
        row = self.europe_row | {"source_event_id": "card:HAN:H:908:purchase"}
        result = review_legacy_card_claim(row, [self.unrelated_hana])
        self.assertEqual(
            result,
            {
                "status": "explicit_source_event_present",
                "source_event_id": "card:HAN:H:908:purchase",
            },
        )

    def test_legacy_projection_script_has_no_approval_amount_lookup_fallback(self) -> None:
        ledger = Path(__file__).resolve().parents[1]
        for name in (
            "fix_v14.py",
            "build_v13_trip.py",
            "ingest.py",
            "link_workbook.py",
        ):
            with self.subTest(script=name):
                script = (ledger / name).read_text(encoding="utf-8")
                self.assertNotIn("def find_card(row):", script)
                self.assertNotIn("by_appr=", script)
                self.assertNotIn("_by_appr=", script)
                self.assertNotIn("existing_by_approval", script)


if __name__ == "__main__":
    unittest.main()
