from __future__ import annotations

import unittest

from ledger.domain import direct_all_period_verified_partial_booking_admission as admission


class VerifiedPartialBookingAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_verified_partial_booking_admission()

    def test_seven_exact_payment_records_and_seventeen_axes(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["selected_count"], manifest["axis_decision_count"]), (7, 17))
        self.assertEqual(sum(len(row["axes"]) for row in self.result["decisions"]), 17)

    def test_vat_is_explicitly_unresolved_and_gate5_gets_no_credit(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["vat_unresolved_count"], 7)
        self.assertEqual(manifest["gate5_credit"], 0)
        self.assertTrue(all("vat_tag" not in row["axes"] for row in self.result["decisions"]))

    def test_candidate_only_and_sources_retained(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])


if __name__ == "__main__":
    unittest.main()
