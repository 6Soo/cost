import unittest
from ledger.tests._platform import requires_staged_evidence

from ledger.domain import direct_all_period_manual_duplicate_collapse_admission as duplicate


@requires_staged_evidence()
class AllPeriodManualDuplicateCollapseAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = duplicate.build_all_period_manual_duplicate_collapse_admission()

    def test_two_card_events_not_four_manual_rows(self):
        manifest = self.result["manifest"]
        proposals = self.result["proposals"]
        self.assertEqual((manifest["manual_rows"], manifest["physical_card_events"],
                          manifest["manual_duplicate_rows_not_extra_events"]), (4, 2, 2))
        self.assertEqual((manifest["full_classification_delta"], manifest["accepted_union"],
                          manifest["global_residual"]), (2, 1556, 3772))
        self.assertEqual({row["account"] for row in proposals}, {"항공료", "기타비용"})
        self.assertEqual({row["trip_target"] for row in proposals},
                         {"0616_레분토&리시리", "0620_묘코"})

    def test_authority_boundary(self):
        manifest = self.result["manifest"]
        self.assertEqual((manifest["authority_status"], manifest["posting_status"],
                          manifest["database_applied"]), ("unattested", "blocked", False))


if __name__ == "__main__":
    unittest.main()
