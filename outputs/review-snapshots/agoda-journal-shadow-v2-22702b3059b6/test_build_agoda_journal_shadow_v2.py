from __future__ import annotations

import unittest

from tools.build_agoda_journal_shadow_v2 import (
    BOUND_DEBIT_ACCOUNT,
    CREDIT_ACCOUNT,
    UNRESOLVED_DEBIT_ACCOUNT,
    build_shadow_rows,
)


class AgodaJournalShadowV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.bound = {
            "source_draft_id": "a" * 64,
            "payment_id": 1,
            "booking_id": 2,
            "booking_number": "1234567890",
            "allocation_target": "0404_A",
            "target_match_status": "unique_service_period",
            "candidate_targets": ["0404_A"],
            "service_start_on": "2026-04-05",
            "service_end_on": "2026-04-06",
            "external_key": "payment-1",
            "source_system": "KBO",
            "amount_krw": 100,
            "occurred_on": "2026-03-01",
            "merchant": "AGODA",
            "plan_id": 3,
            "plan_confidence": 1.0,
            "allocation_id": 4,
            "target_id": 5,
            "target_type": "trip",
        }
        self.unresolved = {
            **self.bound,
            "source_draft_id": "b" * 64,
            "payment_id": 6,
            "booking_id": 7,
            "booking_number": "9876543210",
            "allocation_target": "여행_미배정",
            "target_match_status": "service_target_ambiguous",
            "candidate_targets": ["0404_A", "0408_B"],
            "plan_confidence": 0.0,
            "allocation_id": 8,
            "target_id": 9,
            "target_type": "unassigned",
            "amount_krw": 250,
        }
        self.resolutions = {
            "b" * 64: {
                "resolution_id": "c" * 64,
                "source_draft_id": "b" * 64,
                "payment_id": 6,
                "booking_id": 7,
                "current_match_status": "service_target_ambiguous",
                "suggested_target": "0404_A",
                "resolution_status": "historical_exact_booking_candidate",
                "resolution_sha256": "d" * 64,
            }
        }

    def test_complete_scope_is_balanced_and_account_mapped(self) -> None:
        batches, lines = build_shadow_rows(
            [self.bound, self.unresolved], self.resolutions, "f" * 64
        )
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(lines), 4)
        by_payment = {row["payment_id"]: row for row in batches}
        self.assertEqual(by_payment[1]["debit_account"], BOUND_DEBIT_ACCOUNT)
        self.assertEqual(by_payment[6]["debit_account"], UNRESOLVED_DEBIT_ACCOUNT)
        self.assertEqual({row["credit_account"] for row in batches}, {CREDIT_ACCOUNT})
        self.assertEqual(
            sum(row["amount_krw"] for row in lines if row["side"] == "debit"),
            350,
        )
        self.assertEqual(
            sum(row["amount_krw"] for row in lines if row["side"] == "credit"),
            350,
        )

    def test_unresolved_candidate_remains_non_authoritative(self) -> None:
        batches, _ = build_shadow_rows(
            [self.unresolved], self.resolutions, "f" * 64
        )
        row = batches[0]
        self.assertEqual(row["shadow_cohort"], "target_unresolved")
        self.assertEqual(row["suggested_target"], "0404_A")
        self.assertEqual(row["target_authority"], "candidate_only")
        self.assertEqual(row["posting_status"], "shadow_only")
        self.assertFalse(row["posting_eligible"])
        self.assertFalse(row["authoritative_posting"])
        self.assertFalse(row["external_posting"])

    def test_unresolved_without_resolution_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "journal_shadow_unresolved_contract_invalid"
        ):
            build_shadow_rows([self.unresolved], {}, "f" * 64)


if __name__ == "__main__":
    unittest.main()
