from __future__ import annotations

import unittest

from ledger.domain.candidate_selection import (
    select_bidirectionally_unique_candidates,
    select_unique_candidate,
)


class CandidateSelectionTest(unittest.TestCase):
    def test_single_candidate_is_selected(self) -> None:
        row, status = select_unique_candidate([{"id": 1}])
        self.assertEqual(row, {"id": 1})
        self.assertEqual(status, "unique")

    def test_multiple_candidates_are_never_selected_by_order(self) -> None:
        row, status = select_unique_candidate([{"id": 1}, {"id": 2}])
        self.assertIsNone(row)
        self.assertEqual(status, "ambiguous")

    def test_bidirectional_uniqueness_rejects_shared_candidate(self) -> None:
        items = [{"id": "refund-1"}, {"id": "refund-2"}]
        original = {"id": "original"}
        selected, statuses = select_bidirectionally_unique_candidates(
            items,
            lambda _: [original],
            item_key=lambda row: row["id"],
            candidate_key=lambda row: row["id"],
        )
        self.assertEqual(selected, {})
        self.assertEqual(
            statuses,
            {"refund-1": "ambiguous", "refund-2": "ambiguous"},
        )


if __name__ == "__main__":
    unittest.main()
