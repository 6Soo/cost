from __future__ import annotations

import unittest

from tools.build_agoda_journal_draft import (
    build_journal_rows,
    build_resolution_rows,
    exact_booking_reference,
)


class AgodaJournalDraftTests(unittest.TestCase):
    def test_booking_reference_match_has_digit_boundaries(self) -> None:
        self.assertTrue(exact_booking_reference("예약 1234567890 확인", "1234567890"))
        self.assertFalse(exact_booking_reference("예약 912345678901 확인", "1234567890"))

    def test_historical_match_remains_candidate_only(self) -> None:
        unresolved = [
            {
                "source_draft_id": "a" * 64,
                "payment_id": 1,
                "booking_id": 2,
                "booking_number": "1234567890",
                "amount_krw": 100,
                "service_start_on": "2026-04-17",
                "service_end_on": "2026-04-18",
                "target_match_status": "service_target_ambiguous",
                "candidate_targets": ["0417_A", "0420_B"],
            }
        ]
        historical = {
            "1234567890": [
                {
                    "uid": "KBO-1",
                    "bucket": "0417_A",
                    "account": "숙박비",
                    "cost_type": "여행원가",
                    "krw": "100",
                    "cancel": "False",
                    "source_locator": "KBO-1",
                    "evidence_sha256": "b" * 64,
                }
            ]
        }
        resolutions, evidence = build_resolution_rows(
            unresolved,
            historical,
            {},
            historical_path="ledger/data/classified_v14.csv",
            historical_sha256="c" * 64,
            property_path="outputs/agoda-paseo-staging.json",
            property_sha256="d" * 64,
        )
        self.assertEqual(len(resolutions), 1)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(resolutions[0]["suggested_target"], "0417_A")
        self.assertEqual(
            resolutions[0]["resolution_status"],
            "historical_exact_booking_candidate",
        )
        self.assertEqual(resolutions[0]["authority_status"], "candidate_only")
        self.assertEqual(resolutions[0]["posting_status"], "blocked")
        self.assertFalse(resolutions[0]["posting_eligible"])

    def test_journal_only_consumes_unique_trip_target_and_balances(self) -> None:
        base = {
            "source_draft_id": "a" * 64,
            "payment_id": 1,
            "booking_id": 2,
            "booking_number": "1234567890",
            "allocation_target": "0404_A",
            "target_match_status": "unique_service_period",
            "candidate_targets": ["0404_A"],
            "service_start_on": "2026-04-05",
            "service_end_on": "2026-04-06",
            "external_key": "payment",
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
        unresolved = {
            **base,
            "source_draft_id": "b" * 64,
            "payment_id": 6,
            "booking_id": 7,
            "booking_number": "9876543210",
            "target_match_status": "service_target_missing",
            "allocation_target": "여행_미배정",
            "plan_confidence": 0.0,
            "allocation_id": 8,
            "target_id": 9,
            "target_type": "unassigned",
        }
        batches, lines = build_journal_rows([base, unresolved], "f" * 64)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(lines), 2)
        self.assertEqual({row["side"] for row in lines}, {"debit", "credit"})
        self.assertEqual(sum(row["amount_krw"] for row in lines), 200)
        self.assertEqual(batches[0]["posting_status"], "draft")
        self.assertFalse(batches[0]["posting_eligible"])


if __name__ == "__main__":
    unittest.main()
