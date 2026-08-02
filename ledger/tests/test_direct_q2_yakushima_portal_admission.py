import unittest
from unittest import mock

from ledger.domain import direct_q2_yakushima_portal_admission as yakushima


class Q2YakushimaPortalAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = yakushima.build_q2_yakushima_portal_admission()

    def test_two_card_events_one_portal_booking_group(self):
        manifest = self.result["manifest"]
        proposals = self.result["proposals"]
        self.assertEqual((manifest["full_classification_delta"], manifest["accepted_union"],
                          manifest["global_residual"]), (2, 1558, 3770))
        self.assertEqual((manifest["card_event_count"], manifest["portal_booking_count"],
                          manifest["booking_bijection_asserted"]), (2, 1, False))
        self.assertEqual({row["trip_target"] for row in proposals}, {"1127_야쿠시마"})

    def test_portal_file_tamper_rejected(self):
        fake = mock.Mock(stdout=b'{}')
        with mock.patch.object(yakushima.subprocess, "run", return_value=fake), \
             self.assertRaisesRegex(ValueError, "file_pin"):
            yakushima._portal()

    def test_authority_boundary(self):
        manifest = self.result["manifest"]
        self.assertEqual((manifest["authority_status"], manifest["posting_status"],
                          manifest["database_applied"]), ("unattested", "blocked", False))


if __name__ == "__main__":
    unittest.main()
