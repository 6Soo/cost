from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_historical_carryforward_census as census


class HistoricalCarryforwardCensusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = census.build_historical_carryforward_census()

    def test_large_policy_scope_is_exact(self) -> None:
        self.assertEqual((self.result["strict_before_policy_count"],
                          self.result["classification_candidate_count"]), (764, 611))
        self.assertEqual(sum(self.result["account_counts"].values()), 611)

    def test_three_lifecycle_rows_are_not_trip_allocations(self) -> None:
        self.assertEqual(self.result["gate5_trip_eligible_count"], 608)
        self.assertEqual(self.result["lifecycle_nontrip_count"], 3)
        self.assertEqual(self.result["lifecycle_uids"], ["KBD-0779", "KBD-0781", "KBD-0783"])

    def test_dry_run_does_not_apply_or_publish(self) -> None:
        self.assertEqual(self.result["authority_status"], "awaiting_user_policy_decision")
        self.assertFalse(self.result["database_applied"])
        self.assertEqual(self.result["posting_status"], "blocked")
        self.assertTrue(self.result["all_source_events_retained"])

    def test_existing_projected_payments_do_not_overlap(self) -> None:
        self.assertEqual(self.result["already_projected_payment_count"], 139)
        self.assertEqual(self.result["already_projected_overlap_count"], 0)


if __name__ == "__main__":
    unittest.main()
