from __future__ import annotations

import unittest
from ledger.tests._platform import allow_pin_drift

from ledger.domain import direct_all_period_verified_kamenoi_lodging_admission as admission


@allow_pin_drift()
class VerifiedKamenoiLodgingAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_verified_kamenoi_lodging_admission()

    def test_two_exact_booking_page_records(self) -> None:
        self.assertEqual(self.result["manifest"]["selected_count"], 2)
        self.assertEqual(len({row["booking_id"] for row in self.result["candidates"]}), 2)

    def test_three_axes_are_candidate_hints_only(self) -> None:
        for row in self.result["candidates"]:
            self.assertEqual((row["account"], row["cost_type"], row["trip_target"]),
                             ("숙박비", "여행원가", "0704_아키타"))
            self.assertNotIn("vat_tag", row)

    def test_candidate_only_and_sources_retained(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])
        self.assertEqual((manifest["authority_status"], manifest["gate5_credit"]),
                         ("candidate_only", 0))


if __name__ == "__main__":
    unittest.main()
