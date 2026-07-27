from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from ledger.domain.workbook_summary import (
    SUMMARY_EXTRA_BUCKETS,
    scoped_summary_total,
)


ROOT = Path(__file__).resolve().parents[2]


class WorkbookSummaryTest(unittest.TestCase):
    def test_prepaid_refunds_are_in_summary_scope(self) -> None:
        self.assertIn("전기예약_환불", SUMMARY_EXTRA_BUCKETS)

    def test_summary_scope_preserves_canonical_total_and_count(self) -> None:
        with (ROOT / "ledger/data/classified_v14.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            rows = list(csv.DictReader(stream))
        normalized = [
            dict(row, krw_f=float(row.get("krw") or 0))
            for row in rows
        ]
        trips = json.loads(
            (ROOT / "ledger/data/trips.json").read_text(encoding="utf-8")
        )
        buckets = {str(item["tab"]) for item in trips} | set(
            SUMMARY_EXTRA_BUCKETS
        )
        canonical_buckets = {str(row["bucket"]) for row in normalized}
        self.assertEqual(canonical_buckets - buckets, set())
        total, count = scoped_summary_total(normalized, buckets)
        self.assertEqual(total, 320_055_642)
        self.assertEqual(count, 1_835)

    def test_amount_and_count_use_identical_scope(self) -> None:
        rows = [
            {"bucket": "A", "krw_f": 100},
            {"bucket": "전기예약_환불", "krw_f": -40},
            {"bucket": "B", "krw_f": 999},
        ]
        self.assertEqual(
            scoped_summary_total(rows, {"A", "전기예약_환불"}),
            (60, 2),
        )


if __name__ == "__main__":
    unittest.main()
