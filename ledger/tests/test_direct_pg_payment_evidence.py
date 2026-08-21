from __future__ import annotations

import unittest

from ledger.domain.direct_pg_payment_evidence import evidence_for_row


class PgPaymentEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schedule = {
            "0719_의왕": {
                "tab": "0719_의왕",
                "mm": 7,
                "dd": 19,
                "region": "의왕",
                "window": 1,
            }
        }
        self.service = {
            "forest-0719": {
                "source_key": "forest-0719",
                "source_sha256": "a" * 64,
                "payload": {
                    "service_start_on": "2026-07-19",
                    "service_end_on": "2026-07-19",
                },
            }
        }
        self.records = [
            {
                "source_key": "pg-purchase",
                "source_sha256": "b" * 64,
                "payload": {
                    "provider": "NICE",
                    "approval_number": "30059131",
                    "payment_date": "2026-06-19",
                    "merchant": "의왕도시공사",
                    "product": "백운산동 107호 외 1건",
                    "amount_krw": 140000,
                    "status": "purchase",
                    "service_evidence_key": "forest-0719",
                },
            },
            {
                "source_key": "pg-cancel",
                "source_sha256": "c" * 64,
                "payload": {
                    "provider": "NICE",
                    "approval_number": "30059131",
                    "payment_date": "2026-06-19",
                    "merchant": "의왕도시공사",
                    "product": "백운산동 107호 외 1건",
                    "amount_krw": 0,
                    "cancel_amount_krw": 49000,
                    "status": "partial_cancel",
                    "service_evidence_key": "forest-0719",
                },
            },
        ]

    def test_purchase_uses_service_mail_not_payment_date(self) -> None:
        result = evidence_for_row(
            {
                "approval": "30059131",
                "amount_krw": 140000,
                "merchant": "NICE_산림휴양시설_2-의왕도시공사",
                "occurred_on": "2026-06-19",
                "transaction_type": "purchase",
            },
            self.records,
            self.service,
            self.schedule,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["target_hint"], "0719_의왕")
        self.assertEqual(result["service_start"], "2026-07-19")
        self.assertNotEqual(result["service_start"], "2026-06-19")

    def test_partial_cancel_selects_cancel_mail_not_purchase_mail(self) -> None:
        result = evidence_for_row(
            {
                "approval": "45499121",
                "original_approval": "30059131",
                "amount_krw": -49000,
                "merchant": "NICE_산림휴양시설_2-의왕도시공사",
                "occurred_on": "2026-06-19",
                "transaction_type": "refund",
            },
            self.records,
            self.service,
            self.schedule,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["lifecycle"], "partial_cancellation")
        self.assertEqual(result["target_hint"], "0719_의왕")

    def test_ambiguous_amount_only_match_fails_closed(self) -> None:
        duplicate = {
            "source_key": "pg-purchase-duplicate",
            "source_sha256": "d" * 64,
            "payload": {
                **self.records[0]["payload"],
                "approval_number": "30059132",
            },
        }
        result = evidence_for_row(
            {
                "approval": "",
                "amount_krw": 140000,
                "merchant": "의왕도시공사",
                "occurred_on": "2026-06-19",
                "transaction_type": "purchase",
            },
            [*self.records, duplicate],
            self.service,
            self.schedule,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
