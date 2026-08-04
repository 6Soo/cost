from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_historical_carryforward_admission as admission


class HistoricalCarryforwardAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_historical_carryforward_admission()

    def test_all_611_rows_and_four_axes_replay_exactly(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["selected_count"], manifest["axis_decision_count"]),
                         (611, 2444))
        self.assertEqual((manifest["replay_missing_count"], manifest["replay_changed_count"]),
                         (0, 0))

    def test_trip_and_lifecycle_targets_are_separated(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["gate5_trip_eligible_count"],
                          manifest["lifecycle_nontrip_count"]), (608, 3))

    def test_replay_is_confirmed_but_posting_remains_blocked(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["authority_status"],
                         "confirmed_by_reproducible_code_replay")
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])


if __name__ == "__main__":
    unittest.main()
