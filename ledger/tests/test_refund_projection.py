from __future__ import annotations

import unittest

from ledger.domain.refund_projection import (
    exact_full_refund_pairs,
    repair_standalone_cancellation_signs,
)


class RefundProjectionTest(unittest.TestCase):
    def test_unique_same_lifecycle_refund_is_paired(self) -> None:
        payment = {
            "uid": "HAN-3460",
            "src": "HAN",
            "use_date": "2026-06-23",
            "merchant": "LOTTE ARAI RESORT",
            "krw": "52850",
            "appr": "00407274",
        }
        refund = {
            "src": "HAN",
            "raw_record_id": "H:116:refund",
            "use": "2026-06-23",
            "mer": "LOTTE ARAI RESORT",
            "amt": 52850,
            "appr": "00407274",
            "cx": True,
        }
        self.assertEqual(
            exact_full_refund_pairs([payment], [refund], set()),
            [(payment, refund)],
        )

    def test_ambiguous_originals_are_not_arbitrarily_paired(self) -> None:
        payments = [
            {
                "uid": f"HAN-{number}",
                "src": "HAN",
                "use_date": "2026-06-23",
                "merchant": "SAME",
                "krw": "52850",
                "appr": "00407274",
            }
            for number in (1, 2)
        ]
        refund = {
            "src": "HAN",
            "raw_record_id": "H:116:refund",
            "use": "2026-06-23",
            "mer": "SAME",
            "amt": 52850,
            "appr": "00407274",
            "cx": True,
        }
        self.assertFalse(exact_full_refund_pairs(payments, [refund], set()))

    def test_standalone_corp_cancellation_repairs_sign_without_new_purchase(self) -> None:
        payment = {
            "uid": "CORP-2006",
            "src": "CORP",
            "use_date": "2026-04-20",
            "merchant": "트립닷컴",
            "krw": "356158",
            "appr": "51671053",
            "cancel": "False",
            "status": "정상",
            "bucket": "여행",
            "note": "",
        }
        card = {
            "src": "CORP",
            "raw_record_id": "A_20260720:62",
            "use": "2026-04-20",
            "mer": "트립닷컴",
            "amt": 356158,
            "appr": "51671053",
            "cx": True,
        }
        updates = repair_standalone_cancellation_signs([payment], [card])
        self.assertEqual(payment["krw"], "-356158")
        self.assertEqual(payment["bucket"], "취소환불")
        self.assertEqual(len(updates), 1)


if __name__ == "__main__":
    unittest.main()
