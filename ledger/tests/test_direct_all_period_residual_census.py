import unittest

from ledger.domain import direct_all_period_residual_census as census


class AllPeriodResidualCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = census.build_all_period_residual_census()

    def test_current_residual_is_exact_and_lossless(self):
        result = self.result
        self.assertEqual(result["event_count"], 5328)
        self.assertEqual(result["accepted_count"], 1568)
        self.assertEqual(result["residual_count"], 3760)
        self.assertEqual(result["residual_set_sha256"], census.EXPECTED_RESIDUAL_SET_SHA256)
        self.assertEqual(result["excluded_by_period_count"], 0)

    def test_evidence_partitions_are_disjoint_and_complete(self):
        result = self.result
        self.assertEqual(result["partition_counts"], census.EXPECTED_COUNTS)
        self.assertEqual(sum(part["count"] for part in result["partitions"].values()), 3760)

    def test_remaining_mass_taxonomy_partition_stays_posting_blocked(self):
        result = self.result
        self.assertEqual(result["merchant_taxonomy_bucket_missing_count"], 241)
        self.assertFalse(result["database_applied"])
        self.assertEqual(result["posting_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
