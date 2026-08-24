from __future__ import annotations

import unittest
from ledger.tests._platform import allow_pin_drift

from ledger.domain import direct_all_period_historical_carryforward_census as census


@allow_pin_drift()
class HistoricalCarryforwardCensusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = census.build_historical_carryforward_census()

    def test_large_policy_scope_is_exact(self) -> None:
        self.assertEqual((self.result["strict_before_policy_count"],
                          self.result["classification_candidate_count"]), (764, 750))
        self.assertEqual(sum(self.result["account_counts"].values()), 750)
        self.assertEqual(self.result["cost_type_counts"], {"여행원가": 707, "판관비": 43})

    def test_trip_file_is_only_a_candidate_target_hint(self) -> None:
        self.assertEqual(self.result["trip_target_hint_count"], 700)
        self.assertEqual(self.result["nontrip_target_hint_count"], 50)
        self.assertEqual(self.result["nontrip_target_counts"], {"기타비용": 43, "취소환불": 7})
        self.assertFalse(self.result["trips_json_is_evidence"])

    def test_dry_run_does_not_apply_or_publish(self) -> None:
        self.assertEqual((self.result["authority_status"], self.result["gate5_credit"]),
                         ("candidate_only", 0))
        self.assertFalse(self.result["database_applied"])
        self.assertEqual(self.result["posting_status"], "blocked")
        self.assertTrue(self.result["all_source_events_retained"])

    def test_active_contract_excludes_vat(self) -> None:
        self.assertEqual(self.result["active_dimensions"],
                         ["account", "cost_type", "allocation_target"])
        self.assertEqual(self.result["excluded_dimensions"], ["vat_tag"])
        self.assertTrue(all("vat_tag" not in row for row in self.result["candidates"]))


if __name__ == "__main__":
    unittest.main()
