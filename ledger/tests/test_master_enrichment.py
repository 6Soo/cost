from __future__ import annotations

import unittest

from ledger.domain.master_enrichment import enrich_from_master


class MasterEnrichmentTest(unittest.TestCase):
    def test_unique_reference_date_and_amount_restores_detailed_merchant(self) -> None:
        classified = [
            {
                "uid": "KBD-0982",
                "use_date": "2026-05-29",
                "krw": "36100",
                "merchant": "(주)스마트로",
            }
        ]
        master = [
            {
                "워크북참조": "KBD-0982",
                "기록여부": "Y",
                "승인일": "2026-05-29",
                "원화금액": "36100",
                "가맹점": "(주)스마트로-해강개발 주식회사 강화리조트",
                "거래키": "card-event-1",
            }
        ]
        result = enrich_from_master(classified, master)
        self.assertEqual(
            classified[0]["merchant"],
            "(주)스마트로-해강개발 주식회사 강화리조트",
        )
        self.assertEqual(len(result["updated"]), 1)
        self.assertFalse(result["conflicts"])

    def test_reference_is_rejected_when_amount_does_not_agree(self) -> None:
        classified = [
            {
                "uid": "KBD-0982",
                "use_date": "2026-05-29",
                "krw": "36000",
                "merchant": "(주)스마트로",
            }
        ]
        master = [
            {
                "워크북참조": "KBD-0982",
                "기록여부": "Y",
                "승인일": "2026-05-29",
                "원화금액": "36100",
                "가맹점": "강화리조트",
                "거래키": "card-event-1",
            }
        ]
        result = enrich_from_master(classified, master)
        self.assertEqual(classified[0]["merchant"], "(주)스마트로")
        self.assertFalse(result["conflicts"])
        self.assertEqual(len(result["unresolved"]), 1)

    def test_kbo_uses_posting_date_when_approval_date_is_absent(self) -> None:
        classified = [
            {
                "uid": "KBO-2643",
                "src": "KBO",
                "use_date": "2026-04-01",
                "post_date": "2026-04-07",
                "card4": "8835",
                "currency": "JPY",
                "foreign": "19456",
                "krw": "188808",
                "merchant": "generic",
                "cancel": "False",
            }
        ]
        master = [
            {
                "워크북참조": "KBO-2643",
                "기록여부": "Y",
                "승인일": "",
                "매입일": "2026-04-07",
                "카드4": "8835",
                "통화": "JPY",
                "현지금액": "19456",
                "원화금액": "188808",
                "가맹점": "DETAILED MERCHANT",
                "취소여부": "정상",
                "거래키": "card-event-2",
            }
        ]
        result = enrich_from_master(classified, master)
        self.assertEqual(classified[0]["merchant"], "DETAILED MERCHANT")
        self.assertEqual(len(result["updated"]), 1)


if __name__ == "__main__":
    unittest.main()
