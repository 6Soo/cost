from __future__ import annotations

import unittest

from tools.build_agoda_accounting_draft import (
    UNASSIGNED_TARGET,
    build_draft_rows,
    matching_trip_codes,
)


class AgodaAccountingDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schedule = {
            "0404_A": {
                "starts_on": "2026-04-04",
                "ends_on": "2026-04-10",
                "region": "A",
            },
            "0408_B": {
                "starts_on": "2026-04-08",
                "ends_on": "2026-04-14",
                "region": "B",
            },
        }

    def test_service_period_match_is_unique_ambiguous_or_missing(self) -> None:
        self.assertEqual(
            matching_trip_codes("2026-04-05", "2026-04-07", self.schedule),
            ["0404_A"],
        )
        self.assertEqual(
            matching_trip_codes("2026-04-08", "2026-04-10", self.schedule),
            ["0404_A", "0408_B"],
        )
        self.assertEqual(
            matching_trip_codes("2026-03-01", "2026-03-02", self.schedule),
            [],
        )

    def test_unresolved_target_fails_closed_without_posting_authority(self) -> None:
        base = {
            "link_authority_id": "a" * 64,
            "reconciliation_run_id": "run",
            "candidate_report_sha256": "b" * 64,
            "payment_id": 1,
            "booking_id": 2,
            "booking_number": "1234567890",
            "service_start_on": "2026-04-08",
            "service_end_on": "2026-04-10",
            "external_key": "payment",
            "source_system": "KBO",
            "transaction_type": "purchase",
            "amount_krw": 100,
            "merchant": "AGODA",
            "booking_evidence_set_sha256": "c" * 64,
            "input_database_sha256": "d" * 64,
            "input_audit_sha256": "e" * 64,
        }
        row = build_draft_rows([base], self.schedule, "f" * 64)[0]
        self.assertEqual(row["account"], "숙박비")
        self.assertEqual(row["cost_type"], "여행원가")
        self.assertEqual(row["allocation_target"], UNASSIGNED_TARGET)
        self.assertEqual(row["target_match_status"], "service_target_ambiguous")
        self.assertEqual(row["allocation_confidence"], 0.0)
        self.assertEqual(row["decision_status"], "proposed")
        self.assertEqual(row["plan_status"], "proposed")
        self.assertFalse(row["posting_eligible"])


if __name__ == "__main__":
    unittest.main()
