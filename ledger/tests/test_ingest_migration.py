from __future__ import annotations

import unittest

from ledger.domain.ingest_migration import balanced_legacy_enrichment_pairs


class IngestMigrationTest(unittest.TestCase):
    def test_two_old_rows_receive_two_new_approvals_without_duplication(self) -> None:
        existing = [
            {
                "거래키": f"legacy#{number}",
                "출처": "국민국내매입",
                "카드4": "8835",
                "승인일": "2026-06-11",
                "가맹점": "트립닷컴(구)_NICE",
                "원화금액": "422424",
                "승인번호": "",
                "취소여부": "정상",
            }
            for number in (1, 2)
        ]
        incoming = [
            {
                **existing[0],
                "거래키": f"approval-{number}",
                "승인번호": approval,
            }
            for number, approval in ((1, "30103612"), (2, "30103634"))
        ]
        self.assertEqual(
            balanced_legacy_enrichment_pairs(existing, incoming),
            {"approval-1": "legacy#1", "approval-2": "legacy#2"},
        )

    def test_count_mismatch_does_not_guess(self) -> None:
        existing = [
            {
                "거래키": "legacy#1",
                "출처": "국민국내매입",
                "카드4": "8835",
                "승인일": "2026-06-11",
                "가맹점": "same",
                "원화금액": "100",
                "승인번호": "",
                "취소여부": "정상",
            }
        ]
        incoming = [
            {**existing[0], "거래키": f"new-{number}", "승인번호": str(number)}
            for number in (1, 2)
        ]
        self.assertFalse(balanced_legacy_enrichment_pairs(existing, incoming))


if __name__ == "__main__":
    unittest.main()
