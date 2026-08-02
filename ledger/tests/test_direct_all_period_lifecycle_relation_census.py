import unittest

from ledger.domain import direct_all_period_lifecycle_relation_census as census


class AllPeriodLifecycleRelationCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = census.build_all_period_lifecycle_relation_census()

    def test_exact_relations_are_rebased_to_current_residual(self):
        result = self.result
        self.assertEqual(result["lifecycle_residual_count"], 377)
        self.assertEqual(result["exact_original_approval_linked_count"], 209)
        self.assertEqual(result["linked_target_status_counts"],
                         {"accepted": 22, "residual": 187})
        self.assertEqual(result["linked_event_set_sha256"], census.EXPECTED_LINKED_SET_SHA256)

    def test_unlinked_lifecycle_events_remain_explicit(self):
        result = self.result
        self.assertEqual(result["unlinked_count"], 168)
        self.assertEqual(result["unlinked_source_counts"],
                         {"CORP": 4, "KBD": 29, "KBO": 135})
        self.assertEqual(result["unlinked_transaction_type_counts"],
                         {"cancellation": 139, "refund": 29})

    def test_relation_does_not_claim_classification_or_posting(self):
        result = self.result
        self.assertTrue(result["relation_evidence_preserved"])
        self.assertEqual(result["full_classification_delta"], 0)
        self.assertFalse(result["database_applied"])
        self.assertEqual(result["posting_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
