import unittest

from ledger.domain import direct_all_period_remaining_cancellation_admission as cancellations


class AllPeriodRemainingCancellationAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = cancellations.build_all_period_remaining_cancellation_admission()

    def test_three_resolutions_and_totals(self):
        manifest = self.result["manifest"]
        rows = self.result["resolutions"]
        self.assertEqual((manifest["resolved_event_delta"], manifest["full_classification_delta"],
                          manifest["accepted_union"], manifest["global_residual"]),
                         (3, 2, 1554, 3774))
        self.assertEqual((manifest["han_pair_net_krw"], manifest["kbo_refund_total_krw"]),
                         (0, -418996))
        self.assertEqual({row["disposition"] for row in rows},
                         {"approval_cancellation_pair", "prior_period_lodging_refund"})
        self.assertEqual(sum(row["disposition"] == "prior_period_lodging_refund" for row in rows), 2)

    def test_refunds_are_group_only_and_authority_is_not_escalated(self):
        manifest = self.result["manifest"]
        self.assertFalse(manifest["refund_bijection_asserted"])
        self.assertEqual((manifest["authority_status"], manifest["posting_status"],
                          manifest["database_applied"]), ("unattested", "blocked", False))


if __name__ == "__main__":
    unittest.main()
