from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledger.domain.ledger_db import connect, initialize
from ledger.domain.mail_evidence import mail_claim_strength, record_mail_search


class MailEvidenceTest(unittest.TestCase):
    def test_found_requires_message_id_and_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "mail.db")
            try:
                initialize(db)
                created = record_mail_search(
                    db,
                    "mail:KBD-0982:1",
                    "KBD-0982",
                    query='"강화리조트" "36,100"',
                    query_version="merchant-amount-v1",
                    account_scope="connected_gmail",
                    search_complete=True,
                    searched_at="2026-07-26T00:00:00+09:00",
                    result_status="found",
                    candidate_count=1,
                    message_id="19e736e6fd984415",
                    candidate_message_ids=["19e736e6fd984415"],
                    subject="강화리조트 : SmartroPay 결제",
                    observed_amount_krw=36100,
                    actor="terra",
                )
                self.assertTrue(created)
                self.assertFalse(
                    record_mail_search(
                        db,
                        "mail:KBD-0982:1",
                        "KBD-0982",
                        query='"강화리조트" "36,100"',
                        query_version="merchant-amount-v1",
                        account_scope="connected_gmail",
                        search_complete=True,
                        searched_at="2026-07-26T00:00:00+09:00",
                        result_status="found",
                        candidate_count=1,
                        message_id="19e736e6fd984415",
                        candidate_message_ids=["19e736e6fd984415"],
                        subject="강화리조트 : SmartroPay 결제",
                        observed_amount_krw=36100,
                        actor="terra",
                    )
                )
                row = db.execute(
                    "SELECT * FROM mail_search_evidence WHERE evidence_id=?",
                    ("mail:KBD-0982:1",),
                ).fetchone()
                self.assertEqual(mail_claim_strength(row), "strong")
            finally:
                db.close()

    def test_not_found_is_scoped_absence_not_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "mail.db")
            try:
                initialize(db)
                record_mail_search(
                    db,
                    "mail:KBD-0855:1",
                    "KBD-0855",
                    query='"가방나라" "50,000"',
                    query_version="merchant-amount-v1",
                    account_scope="connected_gmail",
                    search_complete=True,
                    searched_at="2026-07-26T00:00:00+09:00",
                    result_status="not_found",
                    candidate_count=0,
                    actor="terra",
                )
                row = db.execute(
                    "SELECT * FROM mail_search_evidence WHERE evidence_id=?",
                    ("mail:KBD-0855:1",),
                ).fetchone()
                self.assertEqual(mail_claim_strength(row), "absence_scoped")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
