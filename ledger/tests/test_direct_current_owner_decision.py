import json
import unittest

from ledger.domain.direct_current_owner_decision import (
    CONTRACT,
    assert_single_use,
    decision_for_row,
    parse_owner_decision_document,
)
from ledger.domain.direct_gmail_payment_evidence import evidence_for_row


class CurrentOwnerDecisionTests(unittest.TestCase):
    def _document(self, decisions):
        return json.dumps({
            "format_version": 1,
            "contract": CONTRACT,
            "decisions": decisions,
        }, ensure_ascii=False).encode()

    def _row(self):
        return {
            "source": "HAN",
            "occurred_on": "2026-01-15",
            "approval_number": "10328907",
            "amount_krw": 27000,
            "merchant": "전화결제_TOSS",
            "biz": "PG일반(비인증)",
        }

    def _decision(self):
        return {
            "decision_id": "d-1",
            "source_system": "HAN",
            "occurred_on": "2026-01-15",
            "approval_number": "10328907",
            "amount_krw": 27000,
            "merchant_tokens": ["전화결제_TOSS"],
            "account": "기타비용",
            "cost_type": "판관비",
            "allocation_target": "기타비용",
            "decision_status": "confirmed",
            "scope_status": "included_q1_other_cost",
            "rationale": "Q1 기타비용",
        }

    def test_exact_match_requires_all_identity_fields(self):
        decisions = parse_owner_decision_document(self._document([self._decision()]))
        self.assertEqual(decision_for_row(self._row(), decisions)["decision_id"], "d-1")
        wrong_amount = {**self._row(), "amount_krw": 27001}
        self.assertIsNone(decision_for_row(wrong_amount, decisions))

    def test_duplicate_payment_key_is_rejected(self):
        duplicate = {**self._decision(), "decision_id": "d-2"}
        with self.assertRaisesRegex(ValueError, "duplicate_payment_key"):
            parse_owner_decision_document(self._document([self._decision(), duplicate]))

    def test_reuse_is_rejected(self):
        decision = {**self._decision()}
        parsed = parse_owner_decision_document(self._document([decision]))
        match = decision_for_row(self._row(), parsed)
        with self.assertRaisesRegex(ValueError, "reused"):
            assert_single_use([match, match])

    def test_gmail_exact_match_also_checks_date_and_raw_gateway_token(self):
        tea = evidence_for_row({
            "source": "KBD", "occurred_on": "2026-04-10",
            "approval_number": "30098985", "amount_krw": 205800,
            "merchant": "NICE 결제대행-나이스정보통신(주)",
        })
        self.assertEqual(tea["classification"], "travel")
        self.assertIsNone(evidence_for_row({
            "source": "KBD", "occurred_on": "2026-04-11",
            "approval_number": "30098985", "amount_krw": 205800,
            "merchant": "NICE 결제대행-나이스정보통신(주)",
        }))
        solapi = evidence_for_row({
            "source": "KBD", "occurred_on": "2026-07-04",
            "approval_number": "30059587", "amount_krw": 10000,
            "merchant": "NICE 결제대행-나이스정보통신(주)",
        })
        self.assertEqual((solapi["classification"], solapi["account"]), ("overhead", "기타비용"))


if __name__ == "__main__":
    unittest.main()
