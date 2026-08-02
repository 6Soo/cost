import unittest

from ledger.domain import direct_all_period_scope_policy as scope


class AllPeriodScopePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scope.build_all_period_scope_policy()

    def test_every_event_is_in_all_period_scope(self):
        result = self.result
        self.assertEqual(result["event_count"], 5328)
        self.assertEqual(result["period_counts"], scope.EXPECTED_PERIOD_COUNTS)
        self.assertEqual(sum(result["period_counts"].values()), result["event_count"])
        self.assertEqual(result["excluded_by_period_count"], 0)

    def test_quarter_exclusion_and_deletion_are_forbidden(self):
        result = self.result
        self.assertFalse(result["quarter_filter_allowed"])
        self.assertFalse(result["delete_unclassified_allowed"])
        self.assertTrue(result["cross_period_relation_retention_required"])

    def test_current_candidate_counts_are_not_shrunk_to_a_quarter(self):
        self.assertEqual((self.result["accepted_union"], self.result["global_residual"]),
                         (1568, 3760))


if __name__ == "__main__":
    unittest.main()
