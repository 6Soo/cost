import unittest
from unittest import mock

from ledger.domain import direct_q2_minatoya_portal_admission as minatoya


class Q2MinatoyaPortalAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = minatoya.build_q2_minatoya_portal_admission()

    def test_two_card_events_one_portal_booking_with_tolerance(self):
        manifest = self.result["manifest"]
        proposals = self.result["proposals"]
        self.assertEqual((manifest["full_classification_delta"], manifest["accepted_union"],
                          manifest["global_residual"]), (2, 1560, 3768))
        self.assertEqual((manifest["card_event_count"], manifest["portal_booking_count"],
                          manifest["booking_bijection_asserted"]), (2, 1, False))
        self.assertLessEqual(manifest["jpy_difference_bps"], manifest["jpy_tolerance_bps"])
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
                          manifest["database_applied"]), ("unattested", "blocked", False))


if __name__ == "__main__":
    unittest.main()
