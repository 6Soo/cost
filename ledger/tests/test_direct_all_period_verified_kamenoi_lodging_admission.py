from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_verified_kamenoi_lodging_admission as admission


class VerifiedKamenoiLodgingAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_verified_kamenoi_lodging_admission()

    def test_two_exact_booking_page_records(self) -> None:
        self.assertEqual(self.result["manifest"]["selected_count"], 2)
        self.assertEqual(len({row["booking_id"] for row in self.result["decisions"]}), 2)

    def test_all_four_axes_are_confirmed(self) -> None:
        for row in self.result["decisions"]:
            self.assertEqual((row["account"], row["cost_type"], row["vat_tag"],
                              row["trip_target"], row["decision_status"]),
                             ("숙박비", "여행원가", "불공제_해외",
                              "0704_아키타", "confirmed"))

    def test_candidate_only_and_sources_retained(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])


if __name__ == "__main__":
    unittest.main()
