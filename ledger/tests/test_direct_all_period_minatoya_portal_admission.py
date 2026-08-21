import unittest
from unittest import mock

from ledger.domain import direct_all_period_minatoya_portal_admission as minatoya


class AllPeriodMinatoyaPortalAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = minatoya.build_all_period_minatoya_portal_admission()

    def test_two_card_events_remain_unresolved_without_exact_amount(self):
        manifest = self.result["manifest"]
        proposals = self.result["proposals"]
        self.assertEqual((manifest["full_classification_delta"], manifest["gate5_credit"],
                          manifest["accepted_union"], manifest["global_residual"]),
                         (0, 0, 1558, 3770))
        self.assertEqual((manifest["card_event_count"], manifest["portal_booking_count"],
                          manifest["booking_bijection_asserted"]), (2, 1, False))
        self.assertEqual(manifest["observed_jpy_difference_bps"], 152)
        self.assertFalse(manifest["generic_tolerance_allowed"])
        self.assertEqual({row["candidate_status"] for row in proposals}, {"unresolved"})
        self.assertEqual({row["trip_target"] for row in proposals}, {"1010_도쿠시마"})

    def test_portal_fact_tamper_rejected(self):
        good = minatoya._portal()
        bad = dict(good); bad["foreign_amount"] = "10000"
        raw = json_bytes = minatoya.json.dumps({"records": [bad]}).encode()
        fake = mock.Mock(stdout=raw)
        with mock.patch.object(minatoya.subprocess, "run", return_value=fake), \
             mock.patch.object(minatoya.yakushima, "PORTAL_FILE_SHA256", minatoya.yakushima._sha(raw)), \
             self.assertRaisesRegex(ValueError, "portal_fact"):
            minatoya._portal()

    def test_authority_boundary(self):
        manifest = self.result["manifest"]
        self.assertEqual((manifest["authority_status"], manifest["posting_status"],
                          manifest["database_applied"]), ("candidate_only", "blocked", False))


if __name__ == "__main__":
    unittest.main()
