from __future__ import annotations

import unittest

from ledger.domain.hana_events import (
    expand_hana_row,
    reconcile_hana_billing_projection,
)


def identity(value: object) -> str:
    return str(value)


class HanaEventsTest(unittest.TestCase):
    def test_captured_cancellation_becomes_two_equal_accounting_events(self) -> None:
        row = [""] * 20
        row[1] = "2026-06-23"
        row[3] = "4336-****-****-4595"
        row[4] = "00407274"
        row[5] = "52102"
        row[7] = "LOTTE ARAI RESORT"
        row[11] = "해외구매"
        row[15] = "52,850"
        row[17] = "매출취소"
        events = expand_hana_row("H:116", row, identity)
        self.assertEqual([event["amt"] for event in events], [52850, 52850])
        self.assertEqual([event["cx"] for event in events], [False, True])
        self.assertEqual(
            [event["raw_record_id"] for event in events],
            ["H:116:purchase", "H:116:refund"],
        )

    def test_normal_foreign_charge_uses_billed_not_approval_amount(self) -> None:
        row = [""] * 20
        row[1] = "2026-06-15"
        row[3] = "4336-****-****-4595"
        row[4] = "00202524"
        row[5] = "19330"
        row[7] = "TESHIKAGA"
        row[11] = "해외구매"
        row[14] = "19538"
        row[17] = "정상"
        events = expand_hana_row("H:174", row, identity)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["amt"], 19538)
        self.assertFalse(events[0]["cx"])

    def test_legacy_approval_amount_is_reconciled_to_billed_amount(self) -> None:
        classified = [
            {
                "uid": "HAN-3402",
                "src": "HAN",
                "use_date": "2026-06-15",
                "merchant": "TESHIKAGA HOKKAIDO JP",
                "krw": "19330",
                "appr": "00202524",
            }
        ]
        cards = [
            {
                "src": "HAN",
                "raw_record_id": "H:174:purchase",
                "use": "2026-06-15",
                "mer": "TESHIKAGA HOKKAIDO JP",
                "amt": 19538,
                "approved_amt": 19330,
                "appr": "00202524",
                "cx": False,
            }
        ]
        result = reconcile_hana_billing_projection(classified, cards)
        self.assertEqual(classified[0]["krw"], "19538")
        self.assertEqual(
            classified[0]["source_event_id"],
            "card:HAN:H:174:purchase",
        )
        self.assertEqual(
            result["consumed_card_keys"],
            {"HAN:H:174:purchase"},
        )
        self.assertEqual(len(result["updated"]), 1)

    def test_hana_approval_leading_zeroes_do_not_break_lineage(self) -> None:
        classified = [
            {
                "uid": "HAN-0492",
                "src": "HAN",
                "use_date": "2026-04-24",
                "merchant": "HANEYA GIFU JP",
                "krw": "11348",
                "appr": "370327",
            }
        ]
        cards = [
            {
                "src": "HAN",
                "raw_record_id": "G:22:purchase",
                "use": "2026-04-24",
                "mer": "HANEYA GIFU JP",
                "amt": 11348,
                "approved_amt": 11267,
                "appr": "00370327",
                "cx": False,
            }
        ]
        result = reconcile_hana_billing_projection(classified, cards)
        self.assertEqual(
            classified[0]["source_event_id"],
            "card:HAN:G:22:purchase",
        )
        self.assertEqual(
            result["consumed_card_keys"],
            {"HAN:G:22:purchase"},
        )

    def test_zero_net_cancelled_row_consumes_both_lifecycle_events(self) -> None:
        classified = [
            {
                "uid": "HAN-3444",
                "src": "HAN",
                "status": "매출취소",
                "merchant": "트립닷컴_이니시스",
                "krw": "0",
                "appr": "30106104",
            }
        ]
        cards = [
            {
                "src": "HAN",
                "raw_record_id": f"H:132:{kind}",
                "mer": "트립닷컴_이니시스",
                "amt": 152358,
                "appr": "30106104",
                "cx": kind == "refund",
            }
            for kind in ("purchase", "refund")
        ]
        result = reconcile_hana_billing_projection(classified, cards)
        self.assertEqual(
            result["consumed_card_keys"],
            {"HAN:H:132:purchase", "HAN:H:132:refund"},
        )
        self.assertFalse(result["conflicts"])


if __name__ == "__main__":
    unittest.main()
