from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_historical_carryforward_admission as admission


class HistoricalCarryforwardAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_historical_carryforward_admission()

    def test_all_three_axis_rows_are_candidates_without_vat(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["candidate_count"], manifest["candidate_axis_count"]),
                         (750, 2250))
        self.assertEqual(manifest["gate5_credit"], 0)
        self.assertNotIn("decisions", self.result)
        self.assertEqual({row["candidate_status"] for row in self.result["candidates"]},
                         {"withheld_pending_independent_evidence"})
        self.assertEqual((manifest["replay_missing_count"], manifest["replay_changed_count"]),
                         (0, 0))

    def test_trip_and_lifecycle_targets_are_separated(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["legacy_trip_hint_count"],
                          manifest["legacy_nontrip_hint_count"]), (700, 50))

    def test_replay_is_candidate_only_and_posting_remains_blocked(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["authority_status"], "candidate_only")
        self.assertEqual(manifest["excluded_dimensions"], ["vat_tag"])
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])


if __name__ == "__main__":
    unittest.main()
