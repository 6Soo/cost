from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_manual_frontier_agoda_airfare_admission as admission


class ManualFrontierAgodaAirfareAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_manual_frontier_agoda_airfare_admission()

    def test_exact_two_airfare_rows(self) -> None:
        self.assertEqual(self.result["manifest"]["selected_count"], 2)
        self.assertEqual(self.result["manifest"]["candidate_axis_count"], 6)
        self.assertTrue(all(row["account"] == "항공료" for row in self.result["candidates"]))

    def test_atomic_group_does_not_claim_individual_bijection(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["card_event_count"], manifest["ota_message_count"]), (2, 2))
        self.assertFalse(manifest["individual_card_to_passenger_bijection_asserted"])
        self.assertEqual(manifest["posting_status"], "blocked")

    def test_all_axes_and_sources_are_retained(self) -> None:
        self.assertTrue(self.result["manifest"]["all_source_events_retained"])
        for row in self.result["candidates"]:
            self.assertEqual((row["cost_type"], row["trip_target"]),
                             ("여행원가", "0924_야마구치"))
            self.assertNotIn("vat_tag", row)


if __name__ == "__main__":
    unittest.main()
