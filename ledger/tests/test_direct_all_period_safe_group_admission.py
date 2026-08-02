import unittest
from unittest import mock

from ledger.domain import direct_all_period_safe_group_admission as base


class AllPeriodSafeGroupAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = base.build_all_period_safe_group_admission()

    def test_live_five_and_axes(self):
        manifest = self.result["manifest"]
        proposals = self.result["proposals"]
        self.assertEqual((manifest["full_classification_delta"], manifest["accepted_union"],
                          manifest["global_residual"]), (5, 1547, 3781))
        self.assertEqual(manifest["selected_event_set_sha256"], base.SELECTED_SET_SHA256)
        self.assertEqual(len(proposals), 5)
        self.assertEqual({row["account"] for row in proposals}, {"숙박비"})
        self.assertEqual({row["cost_type"] for row in proposals}, {"여행원가"})
        self.assertEqual({row["vat_tag"] for row in proposals}, {"불공제_해외"})
        self.assertEqual({row["trip_target"] for row in proposals},
                         {"0413_나가센도", "0408_교토"})

    def test_authority_boundary(self):
        manifest = self.result["manifest"]
        self.assertEqual((manifest["authority_status"], manifest["posting_status"],
                          manifest["database_applied"]), ("unattested", "blocked", False))

    def test_manual_cardinality_fails_closed(self):
        changed = list(base.GROUPS)
        row = list(changed[0]); row[5] = 4; changed[0] = tuple(row)
        with mock.patch.object(base, "GROUPS", tuple(changed)), \
             self.assertRaisesRegex(ValueError, "manual_group_cardinality"):
            base._manual_groups()

    def test_current_member_exchange_fails_closed(self):
        with mock.patch.object(base, "SELECTED_SET_SHA256", "f" * 64), \
             self.assertRaisesRegex(ValueError, "selected_set"):
            base._live()


if __name__ == "__main__":
    unittest.main()
