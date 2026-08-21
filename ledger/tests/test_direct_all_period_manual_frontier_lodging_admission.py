from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_manual_frontier_lodging_admission as admission


class ManualFrontierLodgingAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_manual_frontier_lodging_admission()

    def test_exact_six_lodging_rows(self) -> None:
        self.assertEqual(self.result["manifest"]["selected_count"], 6)
        self.assertEqual(self.result["manifest"]["candidate_axis_count"], 18)
        self.assertEqual(len(self.result["candidates"]), 6)
        self.assertTrue(all(row["account"] == "숙박비" for row in self.result["candidates"]))

    def test_two_conflicting_agoda_airfare_rows_remain_deferred(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["deferred_ambiguous_count"], 2)
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])

    def test_trip_axes_are_exact_and_limited(self) -> None:
        counts = {}
        for row in self.result["candidates"]:
            counts[row["trip_target"]] = counts.get(row["trip_target"], 0) + 1
            self.assertEqual(row["cost_type"], "여행원가")
            self.assertNotIn("vat_tag", row)
        self.assertEqual(counts, {"0616_레분토&리시리": 4, "0924_야마구치": 2})


if __name__ == "__main__":
    unittest.main()
