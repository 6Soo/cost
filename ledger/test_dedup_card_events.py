# -*- coding: utf-8 -*-
import csv
import unittest


class CardEventDedupRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("data/classified_v14.csv", encoding="utf-8") as f:
            cls.rows = list(csv.DictReader(f))

    def rows_for(self, bucket, amount):
        return [
            row
            for row in self.rows
            if row["bucket"] == bucket and round(float(row["krw"])) == amount
        ]

    def test_same_amount_distinct_card_approvals_are_preserved(self):
        cases = [
            ("0413_나가센도", 62496, 2),
            ("0616_레분토&리시리", 336292, 3),
            ("0625_아키타", 341394, 2),
        ]
        for bucket, amount, expected in cases:
            with self.subTest(bucket=bucket, amount=amount):
                rows = self.rows_for(bucket, amount)
                self.assertEqual(expected, len(rows))
                self.assertEqual(expected, len({row["appr"] for row in rows}))

    def test_komagane_split_payments_share_verified_booking(self):
        rows = [
            row
            for row in self.rows
            if row["bucket"] == "0413_나가센도"
            and "고마가네" in row["merchant"]
        ]
        self.assertEqual(7, len(rows))
        self.assertTrue(
            all("1400824130566434" in row["note"] for row in rows)
        )

    def test_refunds_are_never_deleted(self):
        expected = {
            "TRIP-0102": -310100,
            "TRIP-0107": -307139,
            "TRIP-0113": -378300,
            "TRIP-0126": -87100,
        }
        by_uid = {row["uid"]: row for row in self.rows}
        for uid, amount in expected.items():
            with self.subTest(uid=uid):
                self.assertIn(uid, by_uid)
                self.assertEqual(amount, round(float(by_uid[uid]["krw"])))

    def test_verified_refunds_move_from_pending_to_linked(self):
        by_uid = {row["uid"]: row for row in self.rows}
        links = {
            "TRIP-0102": "TRIP-0101",
            "TRIP-0107": "TRIP-0106",
            "TRIP-0113": "TRIP-0112",
        }
        for uid, original_uid in links.items():
            with self.subTest(uid=uid):
                self.assertIn(f"연결환불_{original_uid}", by_uid[uid]["note"])
                self.assertNotIn("연결대기 환불", by_uid[uid]["note"])
        self.assertIn("연결대기 환불", by_uid["TRIP-0126"]["note"])

    def test_near_amount_different_approval_is_not_merged(self):
        by_uid = {row["uid"]: row for row in self.rows}
        self.assertIn("TRIP-0122", by_uid)
        self.assertEqual(9492, round(float(by_uid["TRIP-0122"]["krw"])))
        self.assertEqual("00106433", by_uid["TRIP-0122"]["appr"])


if __name__ == "__main__":
    unittest.main()
