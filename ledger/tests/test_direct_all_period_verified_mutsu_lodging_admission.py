from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_verified_mutsu_lodging_admission as admission


class VerifiedMutsuLodgingAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_verified_mutsu_lodging_admission()

    def test_six_individual_verified_bookings(self) -> None:
        self.assertEqual(self.result["manifest"]["selected_count"], 6)
        self.assertEqual(len({row["booking_id"] for row in self.result["candidates"]}), 6)

    def test_three_axes_are_candidate_hints_only(self) -> None:
        for row in self.result["candidates"]:
            self.assertEqual((row["account"], row["cost_type"], row["trip_target"]),
                             ("숙박비", "여행원가", "0417_아오모리"))
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
