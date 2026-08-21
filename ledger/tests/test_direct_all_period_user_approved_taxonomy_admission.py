from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_user_approved_taxonomy_admission as admission


class UserApprovedTaxonomyAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_user_approved_taxonomy_admission()

    def test_exact_low_ambiguity_subset_only(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["selected_count"], 116)
        self.assertEqual(manifest["candidate_axis_count"], 232)
        self.assertEqual(manifest["excluded_ambiguous_count"], 125)
        self.assertEqual(len(self.result["candidates"]), 116)

    def test_no_trip_posting_or_data_loss_authority(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["trip_assignment_count"], 0)
        self.assertEqual(manifest["full_classification_delta"], 0)
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])
        self.assertTrue(all(row["trip_target"] is None for row in self.result["candidates"]))

    def test_every_decision_has_complete_taxonomy_axes(self) -> None:
        for row in self.result["candidates"]:
            self.assertTrue(row["account"])
            self.assertEqual(row["cost_type"], "여행원가")
            self.assertNotIn("vat_tag", row)
            self.assertEqual(row["candidate_status"],
                             "withheld_pending_independent_evidence")


if __name__ == "__main__":
    unittest.main()
