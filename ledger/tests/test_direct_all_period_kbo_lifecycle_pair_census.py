import unittest

from ledger.domain import direct_all_period_kbo_lifecycle_pair_census as census


class AllPeriodKboLifecyclePairCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = census.build_all_period_kbo_lifecycle_pair_census()

    def test_exact_singleton_and_atomic_groups(self):
        result = self.result
        self.assertEqual(result["kbo_lifecycle_residual_count"], 135)
        self.assertEqual(result["exact_group_linked_event_count"], 62)
        self.assertEqual(result["exact_singleton_relation_count"], 44)
        self.assertEqual(result["unordered_atomic_group_count"], 5)
        self.assertEqual(result["unlinked_or_cardinality_conflict_count"], 73)
        self.assertEqual(result["unlinked_unique_event_hash_count"], 73)
        self.assertEqual(result["unlinked_unique_source_hash_count"], 73)
        self.assertTrue(result["unlinked_rows_preserved_not_collapsed"])

    def test_multi_event_groups_do_not_claim_bijection(self):
        result = self.result
        self.assertEqual(result["individual_bijection_count"], 44)
        self.assertFalse(result["multi_event_bijection_asserted"])

    def test_relation_only_authority_boundary(self):
        result = self.result
        self.assertTrue(result["relation_evidence_preserved"])
        self.assertEqual(result["full_classification_delta"], 0)
        self.assertFalse(result["database_applied"])
        self.assertEqual(result["posting_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
