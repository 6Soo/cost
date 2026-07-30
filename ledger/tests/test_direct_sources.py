from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledger.domain.direct_sources import (
    DIRECT_CARD_NORMALIZATION_VERSION,
    _normalize_single_payment,
    import_cards,
)
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.source_adapters import stable_card_event_identity


class DirectSourceNormalizationTest(unittest.TestCase):
    def test_issuer_cancel_matrix_is_label_first_and_idempotent(self) -> None:
        for source in ("KBO", "CORP"):
            for raw in (100, -100, 0):
                self.assertEqual(
                    _normalize_single_payment({"src": source, "krw": raw, "cancel": True}),
                    (-abs(raw), "cancellation"),
                )

    def test_non_cancel_refund_adjustment_and_malformed_kbd_cancel_are_unchanged(self) -> None:
        self.assertEqual(
            _normalize_single_payment({"src": "KBO", "krw": 100, "cancel": False}),
            (100, "purchase"),
        )
        self.assertEqual(
            _normalize_single_payment({"src": "KBD", "krw": -100, "cancel": True}),
            (-100, "refund"),
        )
        self.assertEqual(
            _normalize_single_payment({"src": "KBD", "krw": 100, "cancel": True}),
            (100, "cancellation"),
        )
        self.assertEqual(
            _normalize_single_payment({"src": "KBO", "krw": 0, "cancel": False}),
            (0, "adjustment"),
        )

    def test_import_preserves_raw_event_identity_and_hana_split(self) -> None:
        cards = [
            {
                "src": "KBO", "raw_record_id": "E:1", "c4": "1234", "appr": "",
                "orig": "", "use": "2026-06-01", "bill": "2026-06-02",
                "mer": "KBO MERCHANT", "uptype": "", "cur": "KRW", "fx": "",
                "krw": 100, "approval_amount": 0, "cancel_amount": 0,
                "purchase_amount": 0, "cancel": True, "status": "취소매출",
            },
            {
                "src": "CORP", "raw_record_id": "A:1", "c4": "5678", "appr": "123",
                "orig": "", "use": "2026-06-03", "bill": "2026-06-04",
                "mer": "CORP MERCHANT", "uptype": "", "cur": "KRW", "fx": "",
                "krw": 200, "approval_amount": 0, "cancel_amount": 0,
                "purchase_amount": 0, "cancel": True, "status": "취소또는할인",
            },
            {
                "src": "HAN", "raw_record_id": "H:1", "c4": "9999", "appr": "456",
                "orig": "", "use": "2026-06-05", "bill": "2026-06-06",
                "mer": "HAN MERCHANT", "uptype": "", "cur": "KRW", "fx": "",
                "krw": 80, "approval_amount": 100, "cancel_amount": 20,
                "purchase_amount": 100, "cancel": False, "status": "",
            },
        ]
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "direct.db")
            try:
                initialize(db)
                with patch("ledger.domain.direct_sources.cardindex.build_cards", return_value=cards):
                    relation_tables = (
                        "transaction_relations",
                        "classification_decisions",
                        "allocation_plans",
                        "cost_allocations",
                    )
                    before_counts = {
                        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in relation_tables
                    }
                    self.assertEqual(before_counts, {table: 0 for table in relation_tables})
                    first = import_cards(db, Path(dirname))
                    first_snapshot = db.execute(
                        """SELECT s.source_key, d.event_role, d.card_event_id,
                                  d.amount_krw, d.transaction_type, d.normalization_version
                           FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           ORDER BY s.source_key, d.event_role"""
                    ).fetchall()
                    raw = db.execute(
                        """SELECT s.source_key,
                                  json_extract(s.payload_json, '$.krw') AS raw_krw,
                                  e.amount_krw, e.card_event_id,
                                  e.occurred_on, e.merchant
                           FROM direct_card_events e
                           JOIN direct_source_records s ON s.id=e.source_record_id
                           ORDER BY s.source_key"""
                    ).fetchall()
                    self.assertEqual(first["normalized_payments"], 4)
                    raw_by_key = {row[0]: row for row in raw}
                    self.assertEqual(raw_by_key["KBO:E:1"][1:3], (100, 100))
                    self.assertEqual(raw_by_key["CORP:A:1"][1:3], (200, 200))
                    expected_ids = {
                        f"{card['src']}:{card['raw_record_id']}": stable_card_event_identity(
                            {
                                "src": card["src"],
                                "card4": card["c4"],
                                "appr": card["appr"],
                                "orig_appr": card["orig"],
                                "use_date": card["use"],
                                "post_date": card["bill"],
                                "currency": card["cur"],
                                "foreign": card["fx"],
                                "krw": card["krw"],
                                "cancel": card["cancel"],
                                "raw_record_id": card["raw_record_id"],
                            }
                        ).card_event_id
                        for card in cards
                    }
                    self.assertEqual(
                        raw_by_key["KBO:E:1"][3], expected_ids["KBO:E:1"]
                    )
                    self.assertEqual(
                        raw_by_key["CORP:A:1"][3], expected_ids["CORP:A:1"]
                    )
                    by_key = {(row[0], row[1]): row for row in first_snapshot}
                    self.assertEqual(
                        by_key[("CORP:A:1", "single")][3:6],
                        (-200, "cancellation", DIRECT_CARD_NORMALIZATION_VERSION),
                    )
                    self.assertEqual(
                        by_key[("KBO:E:1", "single")][3:6],
                        (-100, "cancellation", DIRECT_CARD_NORMALIZATION_VERSION),
                    )
                    self.assertEqual(
                        by_key[("HAN:H:1", "approval")][3:6],
                        (100, "purchase", DIRECT_CARD_NORMALIZATION_VERSION),
                    )
                    self.assertEqual(
                        by_key[("HAN:H:1", "cancellation")][3:6],
                        (-20, "cancellation", DIRECT_CARD_NORMALIZATION_VERSION),
                    )
                    self.assertEqual(
                        {
                            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                            for table in relation_tables
                        },
                        {table: 0 for table in relation_tables},
                    )
                    second = import_cards(db, Path(dirname))
                    second_snapshot = db.execute(
                        """SELECT s.source_key, d.event_role, d.card_event_id,
                                  d.amount_krw, d.transaction_type, d.normalization_version
                           FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           ORDER BY s.source_key, d.event_role"""
                    ).fetchall()
                    self.assertEqual(second["inserted"], 0)
                    self.assertEqual(second_snapshot, first_snapshot)
                    self.assertEqual(
                        {table: 0 for table in relation_tables},
                        {
                            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                            for table in relation_tables
                        },
                    )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
