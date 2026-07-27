from __future__ import annotations

import unittest

from ledger.domain.master_linking import (
    balanced_ambiguous_master_keys,
    balanced_master_links,
)


class MasterLinkingTest(unittest.TestCase):
    def test_two_purchases_and_two_refunds_link_one_to_one_by_role(self) -> None:
        master = []
        for role, sign in (("정상", 1), ("취소", -1)):
            for number in (1, 2):
                master.append(
                    {
                        "거래키": f"raw-{role}-{number}",
                        "카드4": "8835",
                        "승인일": "2026-04-22",
                "원화금액": str(sign * 337406),
                "취소여부": role,
                "가맹점": "트립닷컴",
                    }
                )
        classified = [
            {
                "uid": uid,
                "card4": "8835",
                "use_date": "2026-04-22",
                "krw": amount,
                "status": status,
                "merchant": "트립닷컴",
            }
            for uid, amount, status in (
                ("KBD-0818", "337406", "정상"),
                ("KBD-0819", "337406", "정상"),
                ("KBD-0368", "-337406", "취소"),
                ("KBD-0369", "-337406", "취소"),
            )
        ]
        self.assertFalse(balanced_master_links(master, classified))
        self.assertEqual(
            balanced_ambiguous_master_keys(master, classified),
            {row["거래키"] for row in master},
        )

    def test_zero_net_hana_lifecycle_can_link_both_source_roles(self) -> None:
        master = [
            {
                "거래키": f"hana-{role}",
                "승인번호": "00105433",
                "원화금액": amount,
                "취소여부": role,
            }
            for role, amount in (("정상", "90415"), ("취소", "-90415"))
        ]
        classified = [
            {
                "uid": "HAN-3334",
                "appr": "00105433",
                "krw": "0",
                "status": "승인취소",
            }
        ]
        self.assertEqual(
            set(balanced_master_links(master, classified).values()),
            {"HAN-3334"},
        )

    def test_refund_prefers_explicit_original_approval(self) -> None:
        master = [
            {
                "거래키": "refund-two",
                "카드4": "8835",
                "승인일": "2026-04-22",
                "원화금액": "-337406",
                "승인번호": "40138660",
                "원승인번호": "30100024",
                "취소여부": "취소",
                "가맹점": "트립닷컴",
            }
        ]
        classified = [
            {
                "uid": "KBD-0368",
                "card4": "8835",
                "use_date": "2026-04-22",
                "merchant": "트립닷컴",
                "krw": "-337406",
                "orig_appr": "30100002",
            },
            {
                "uid": "KBD-0369",
                "card4": "8835",
                "use_date": "2026-04-22",
                "merchant": "트립닷컴",
                "krw": "-337406",
                "orig_appr": "30100024",
            },
        ]
        self.assertEqual(
            balanced_master_links(master, classified)["refund-two"],
            "KBD-0369",
        )

    def test_same_amount_different_merchants_link_uniquely(self) -> None:
        master = [
            {
                "거래키": merchant,
                "카드4": "3820",
                "승인일": "2026-06-05",
                "원화금액": "7000",
                "취소여부": "정상",
                "가맹점": merchant,
            }
            for merchant in ("다빈치", "아성다이소")
        ]
        classified = [
            {
                "uid": uid,
                "card4": "3820",
                "use_date": "2026-06-05",
                "krw": "7000",
                "status": "정상",
                "merchant": merchant,
            }
            for uid, merchant in (("KBD-0998", "다빈치"), ("KBD-0995", "아성다이소"))
        ]
        self.assertEqual(
            balanced_master_links(master, classified),
            {"다빈치": "KBD-0998", "아성다이소": "KBD-0995"},
        )

    def test_multiple_refund_legs_use_cancel_approval_not_shared_original(self) -> None:
        master = [
            {
                "거래키": f"refund-{approval}",
                "카드4": "8835",
                "승인일": "2026-05-04",
                "원화금액": "-1730400",
                "승인번호": approval,
                "원승인번호": "30101185",
                "취소여부": "취소",
                "가맹점": "트립닷컴",
            }
            for approval in ("43032904", "43032892")
        ]
        classified = [
            {
                "uid": uid,
                "card4": "8835",
                "use_date": "2026-05-04",
                "merchant": "트립닷컴",
                "krw": "-1730400",
                "appr": approval,
                "orig_appr": "30101185",
            }
            for uid, approval in (
                ("KBD-0862", "43032904"),
                ("KBD-0865", "43032892"),
            )
        ]
        self.assertEqual(
            balanced_master_links(master, classified),
            {
                "refund-43032904": "KBD-0862",
                "refund-43032892": "KBD-0865",
            },
        )


if __name__ == "__main__":
    unittest.main()
