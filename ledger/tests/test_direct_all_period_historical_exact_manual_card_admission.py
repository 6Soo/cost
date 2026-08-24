from __future__ import annotations

import unittest
from ledger.tests._platform import allow_pin_drift

from ledger.domain import direct_all_period_historical_exact_manual_card_admission as admission


@allow_pin_drift()
class HistoricalExactManualCardAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = admission.build_historical_exact_manual_card_admission()

    def test_frozen_replay_and_manual_card_group_counts(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(
            (manifest["candidate_count"], manifest["legacy_candidate_axis_count"]),
            (42, 126),
        )
        self.assertEqual(
            manifest["axis_counts"],
            {"account": 42, "allocation_target": 42, "cost_type": 42},
        )
        self.assertEqual(
            {row["manual_group_cardinality"] for row in self.result["candidates"]},
            {1},
        )
        self.assertTrue(all(row["legacy_trip_target_hint"] for row in self.result["candidates"]))
        self.assertTrue(all("vat_tag" not in row["axes"] for row in self.result["candidates"]))
        self.assertEqual((manifest["authority_status"], manifest["gate5_credit"]),
                         ("candidate_only", 0))

    def test_service_evidence_rows_are_withheld_and_posting_is_blocked(self) -> None:
        manifest = self.result["manifest"]
        admitted_uids = {row["historical_uid"] for row in self.result["candidates"]}
        self.assertEqual(manifest["service_evidence_withheld_count"], 4)
        self.assertTrue(
            set(manifest["service_evidence_withheld_uids"]).isdisjoint(admitted_uids)
        )
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["all_source_events_retained"])


if __name__ == "__main__":
    unittest.main()
