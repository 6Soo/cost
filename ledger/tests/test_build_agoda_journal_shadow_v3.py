import sqlite3
import unittest

from tools.build_agoda_journal_shadow_v3 import build_rows


class AgodaJournalShadowV3Tests(unittest.TestCase):
    def test_missing_authority_is_unresolved_and_balanced_inputs_are_two_lines(self):
        db = sqlite3.connect(":memory:")
        db.executescript(
            """
            CREATE TABLE direct_agoda_accounting_draft_v3_authorities(
              draft_id TEXT, payment_id INTEGER, booking_id INTEGER,
              booking_number TEXT, amount_krw INTEGER, payment_lane TEXT,
              payment_year INTEGER, service_year INTEGER, occurred_on TEXT,
              target_match_status TEXT, target_authority TEXT,
              allocation_target TEXT,
              authority_candidate_targets_json TEXT
            );
            """
        )
        db.execute(
            """INSERT INTO direct_agoda_accounting_draft_v3_authorities VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "a" * 64, 1, 2, "1700000001", 1234, "2026년 결제", 2026, 2026,
                "2026-01-01", "authority_missing", "none",
                "여행_미배정", "[]",
            ),
        )
        batches, lines = build_rows(db, "b" * 64)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(lines), 2)
        self.assertEqual(batches[0]["debit_account"], "미확정여행원가")
        self.assertEqual(batches[0]["shadow_cohort"], "target_unresolved")
        self.assertEqual(sum(line["amount_krw"] for line in lines if line["side"] == "debit"), 1234)
        self.assertEqual(sum(line["amount_krw"] for line in lines if line["side"] == "credit"), 1234)
        db.close()


if __name__ == "__main__":
    unittest.main()
