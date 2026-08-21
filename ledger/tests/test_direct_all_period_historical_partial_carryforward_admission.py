from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_historical_partial_carryforward_admission as admission


class HistoricalPartialCarryforwardAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_historical_partial_carryforward_admission()

    def test_only_concrete_replayed_axes_are_admitted(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["candidate_count"], manifest["legacy_candidate_axis_count"]),
                         (14, 28))
        self.assertEqual(manifest["axis_counts"], {
            "account": 14, "allocation_target": 14,
        })

    def test_placeholders_and_vat_proposals_are_withheld(self) -> None:
        for row in self.result["candidates"]:
            self.assertNotIn("확인", row["axes"].values())
            self.assertNotIn("공제후보", row["axes"].values())
        self.assertEqual(self.result["manifest"]["fully_concrete_payment_count"], 0)
        self.assertEqual(self.result["manifest"]["trip_allocation_eligible_count"], 0)
        self.assertTrue(all("vat_tag" not in row["axes"] for row in self.result["candidates"]))
        self.assertEqual((self.result["manifest"]["authority_status"],
                          self.result["manifest"]["gate5_credit"]), ("candidate_only", 0))

    def test_scope_is_disjoint_and_unpublished(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["full_carryforward_overlap_count"], 0)
        self.assertFalse(manifest["database_applied"])
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertTrue(manifest["all_source_events_retained"])


if __name__ == "__main__":
    unittest.main()
