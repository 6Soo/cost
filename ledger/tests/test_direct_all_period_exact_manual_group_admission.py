from __future__ import annotations

import unittest
from ledger.tests._platform import requires_staged_evidence

from ledger.domain import direct_all_period_exact_manual_group_admission as admission


@requires_staged_evidence()
class ExactManualGroupAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_exact_manual_group_admission()

    def test_exact_group_is_three_axis_candidate_only(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual((manifest["selected_count"], manifest["candidate_axis_count"]), (5, 15))
        self.assertEqual((manifest["authority_status"], manifest["gate5_credit"]),
                         ("candidate_only", 0))
        self.assertEqual(
            {row["trip_target"] for row in self.result["proposals"]},
            {"0413_나가센도", "0408_교토"},
        )
        self.assertEqual({row["account"] for row in self.result["proposals"]}, {"숙박비"})
        self.assertEqual({row["cost_type"] for row in self.result["proposals"]}, {"여행원가"})
        self.assertTrue(all("vat_tag" not in row for row in self.result["proposals"]))

    def test_candidate_remains_blocked_and_sources_are_retained(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])


if __name__ == "__main__":
    unittest.main()
