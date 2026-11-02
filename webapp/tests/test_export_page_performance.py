"""Synthetic regression tests for export diagnostics read amplification."""

from __future__ import annotations

import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from webapp import board_export_helpers, ledger_board
from webapp.ledger_store import LedgerStore
from webapp.ledger_store_records import fetch_conflict_note, fetch_conflicting_row_ids


class ExportSummaryCallCountTests(unittest.TestCase):
    def test_bulk_conflict_ids_match_single_row_latest_event_semantics(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE board_revisions (
                id INTEGER PRIMARY KEY,
                row_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                new_json TEXT,
                actor TEXT,
                created_at TEXT,
                client_request_id TEXT,
                kind TEXT
            );
        """)
        events = [
            # A later save resolves an older conflict.
            (1, "source-resolved", 4, "conflict"),
            (2, "source-resolved", 5, "save"),
            # Equal revisions are resolved by the larger id, as in row_conflict.
            (3, "source-tie", 8, "conflict"),
            (4, "source-tie", 8, "save"),
            (5, "allocation:active-1", 2, "save"),
            (6, "allocation:active-1", 2, "conflict"),
            # A legacy/null kind is interpreted as save by the single-row API.
            (7, "source-null-kind", 1, "conflict"),
            (8, "source-null-kind", 2, None),
            (9, "source-current-conflict", 1, "save"),
            (10, "source-current-conflict", 3, "conflict"),
        ]
        conn.executemany(
            "INSERT INTO board_revisions"
            " (id,row_id,revision,new_json,actor,created_at,client_request_id,kind)"
            " VALUES (?,?,?, '{}','owner','synthetic','perf',?)",
            events,
        )
        try:
            bulk = fetch_conflicting_row_ids(conn)
            oracle = {
                row_id for row_id, in conn.execute(
                    "SELECT DISTINCT row_id FROM board_revisions")
                if fetch_conflict_note(conn, row_id) is not None
            }
            self.assertEqual(bulk, oracle)
            self.assertEqual(bulk, {"allocation:active-1", "source-current-conflict"})
        finally:
            conn.close()

    def test_each_tab_is_loaded_once_and_output_is_unchanged(self):
        trips = [
            {"tab_id": "t-a", "display_key": "합성 A", "archived": 0},
            {"tab_id": "t-b", "display_key": "합성 B", "archived": 1},
        ]
        rows = {
            "t-a": [
                {"row_kind": "income", "row_id": "r1"},
                {"row_kind": "expense", "row_id": "r2"},
            ],
            "t-b": [{"row_kind": "expense", "row_id": "r3"}],
            None: [
                {"row_kind": "income", "row_id": "r4"},
                {"row_kind": "refund", "row_id": "r5"},
            ],
        }
        calls = []

        def list_rows(tab_id):
            calls.append(tab_id)
            return rows[tab_id]

        counts, summary = board_export_helpers.collect_export_page_summaries(
            trips,
            list_tab_rows_fn=list_rows,
            row_needs_review_fn=lambda row: row["row_id"] in {"r2", "r4"},
            row_has_conflict_fn=lambda row: row["row_id"] in {"r3", "r5"},
        )

        self.assertEqual(calls, ["t-a", "t-b", None])
        self.assertEqual(counts, [
            {"tab_id": "t-a", "display_key": "합성 A", "archived": False,
             "income_count": 1, "expense_count": 1},
            {"tab_id": "t-b", "display_key": "합성 B", "archived": True,
             "income_count": 0, "expense_count": 1},
            {"tab_id": None, "display_key": "분류대기", "archived": False,
             "income_count": 1, "expense_count": 1},
        ])
        self.assertEqual(summary, {
            "review_total": 2,
            "conflict_total": 2,
            "per_tab": [
                {"tab_id": "t-a", "display_key": "합성 A",
                 "review_count": 1, "conflict_count": 0},
                {"tab_id": "t-b", "display_key": "합성 B",
                 "review_count": 0, "conflict_count": 1},
            ],
        })

    def test_export_page_uses_one_request_local_conflict_snapshot(self):
        store = LedgerStore(Path(tempfile.mkdtemp()) / "synthetic.sqlite",
                            seed_demo=False)
        store.create_trip(starts_on="2026-05-01", destination="합성 A",
                          client_request_id="perf-a")
        store.create_trip(starts_on="2026-06-01", destination="합성 B",
                          client_request_id="perf-b")
        previous_store = ledger_board._STORE
        list_calls = []
        original_list = store.list_tab_rows

        def counted_list(tab_id):
            list_calls.append(tab_id)
            return original_list(tab_id)

        try:
            ledger_board.bind_store(store)
            with (patch.object(store, "list_tab_rows", side_effect=counted_list),
                  patch.object(store, "conflicting_row_ids", wraps=store.conflicting_row_ids) as conflicts,
                  patch.object(store, "row_conflict", side_effect=AssertionError(
                      "export must use its request-local conflict snapshot"))):
                markup = ledger_board.export_page()

            trip_ids = [trip["tab_id"] for trip in store.list_trips(include_archived=True)]
            self.assertEqual(list_calls, trip_ids + [None])
            conflicts.assert_called_once_with()
            self.assertIn("합성 A", markup)
            self.assertIn("합성 B", markup)
            self.assertIn("검토필요 0행 · 충돌 0행", markup)
        finally:
            ledger_board.bind_store(previous_store)
            store.close()


if __name__ == "__main__":
    unittest.main()
