from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledger.domain.direct_sources import (
    DIRECT_CARD_NORMALIZATION_VERSION,
    _normalize_single_payment,
    import_cards,
    _insert_source,
)
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.source_adapters import stable_card_event_identity
from ledger.domain.han_normalizer import HAN_NORMALIZER_CONTRACT_SHA256, HAN_NORMALIZER_VERSION
from ledger.domain.direct_sources import import_manual, import_ota


class DirectSourceNormalizationTest(unittest.TestCase):
    def test_changed_content_same_source_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "direct.db")
            try:
                initialize(db)
                _insert_source(db, "card_raw", "KBO:E:1", {"krw": 100})
                with self.assertRaisesRegex(ValueError, "source_key_content_conflict:card_raw:KBO:E:1"):
                    _insert_source(db, "card_raw", "KBO:E:1", {"krw": 101})
                _, created = _insert_source(db, "card_raw", "KBO:E:1", {"krw": 100})
                self.assertFalse(created)
            finally:
                db.close()

    def test_payload_digest_tamper_fails_with_stable_error(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "direct.db"); initialize(db)
            _insert_source(db, "manual_ledger", "M:1", {"amount": "1"})
            db.execute("UPDATE direct_source_records SET payload_json='not-json'")
            with self.assertRaisesRegex(ValueError, "source_payload_digest_inconsistent:manual_ledger:M:1"):
                _insert_source(db, "manual_ledger", "M:1", {"amount": "1"})
            db.close()

    def test_actual_card_import_changed_content_preserves_source_and_children(self) -> None:
        cards = [{"src":"KBO", "raw_record_id":"E:1", "c4":"1234", "appr":"1", "orig":"", "use":"2026-06-01", "bill":"2026-06-02", "mer":"M", "uptype":"", "cur":"KRW", "fx":"", "krw":100, "approval_amount":0, "cancel_amount":0, "purchase_amount":0, "cancel":False, "status":""}]
        with tempfile.TemporaryDirectory() as dirname:
            db = connect(Path(dirname) / "direct.db"); initialize(db)
            with patch("ledger.domain.direct_sources.cardindex.build_cards", return_value=cards):
                import_cards(db, Path(dirname))
                before = tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("direct_source_records", "direct_card_events", "direct_normalized_payments"))
                cards[0]["krw"] = 101
                with self.assertRaisesRegex(ValueError, "source_key_content_conflict:card_raw:KBO:E:1"):
                    import_cards(db, Path(dirname))
                after = tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("direct_source_records", "direct_card_events", "direct_normalized_payments"))
                self.assertEqual(after, before)
            db.close()

    def test_manual_and_ota_changed_content_leave_source_and_children_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); db = connect(root / "direct.db"); initialize(db)
            manual = root / "manual.csv"; manual.write_text("tab,row,note\nA,1,one\n", encoding="utf-8")
            ota = root / "ota.json"; ota.write_text('{"records":[{"messageId":"m1"}]}', encoding="utf-8")
            import_manual(db, manual); import_ota(db, ota)
            before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("direct_source_records", "direct_card_events", "direct_normalized_payments")}
            manual.write_text("tab,row,note\nA,1,two\n", encoding="utf-8")
            ota.write_text('{"records":[{"messageId":"m1","messageHash":"changed"}]}', encoding="utf-8")
            with self.assertRaises(ValueError): import_manual(db, manual)
            with self.assertRaises(ValueError): import_ota(db, ota)
            after = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
            self.assertEqual(after, before); db.close()
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
                "krw": 100, "approval_amount": 100, "cancel_amount": 20,
                "purchase_amount": 100, "cancel": True, "status": "",
                "amount_selection_reason":"split_approval_amount",
                "han_components":(("approval",100,"purchase","split_approval_amount"),
                                  ("cancellation",-20,"cancellation","split_cancel_amount")),
                "han_normalizer_version":HAN_NORMALIZER_VERSION,
                "han_contract_sha256":HAN_NORMALIZER_CONTRACT_SHA256,
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

    def test_hana_normalizer_provenance_is_preserved_in_raw_payload(self) -> None:
        card = {"src":"HAN", "raw_record_id":"H:1", "c4":"9999", "appr":"456", "orig":"456",
            "use":"2026-06-05", "bill":"2026-06-06", "mer":"M", "uptype":"", "cur":"KRW",
            "fx":"", "krw":120, "approval_amount":100, "cancel_amount":0, "purchase_amount":120,
            "cancel":False, "status":"", "amount_selection_reason":"purchase_amount_nonzero",
            "han_components":(("single",120,"purchase","purchase_amount_nonzero"),),
            "han_normalizer_version":HAN_NORMALIZER_VERSION, "han_contract_sha256":HAN_NORMALIZER_CONTRACT_SHA256}
        with tempfile.TemporaryDirectory() as dirname:
            db=connect(Path(dirname)/"direct.db");initialize(db)
            with patch("ledger.domain.direct_sources.cardindex.build_cards",return_value=[card]): import_cards(db,Path(dirname))
            import json
            payload=json.loads(db.execute("SELECT payload_json FROM direct_source_records").fetchone()[0]);db.close()
        self.assertEqual((payload["approval_amount"],payload["purchase_amount"],payload["cancel_amount"]),(100,120,0))
        self.assertEqual((payload["amount_selection_reason"],payload["han_normalizer_version"],payload["han_contract_sha256"]),
                         ("purchase_amount_nonzero",HAN_NORMALIZER_VERSION,HAN_NORMALIZER_CONTRACT_SHA256))

    def test_hana_tampered_components_fail_before_database_mutation(self) -> None:
        card = {"src":"HAN", "raw_record_id":"H:1", "c4":"9999", "appr":"456", "orig":"456",
            "use":"2026-06-05", "bill":"2026-06-06", "mer":"M", "uptype":"", "cur":"KRW", "fx":"",
            "krw":80, "approval_amount":100, "cancel_amount":20, "purchase_amount":80, "cancel":True, "status":"",
            "amount_selection_reason":"split_approval_amount",
            "han_components":(("approval",80,"purchase","split_approval_amount"),
                              ("cancellation",-20,"cancellation","split_cancel_amount")),
            "han_normalizer_version":HAN_NORMALIZER_VERSION,"han_contract_sha256":HAN_NORMALIZER_CONTRACT_SHA256}
        with tempfile.TemporaryDirectory() as dirname:
            db=connect(Path(dirname)/"direct.db");initialize(db)
            with patch("ledger.domain.direct_sources.cardindex.build_cards",return_value=[card]), \
                 self.assertRaisesRegex(ValueError,"han_component_contract_mismatch"):
                import_cards(db,Path(dirname))
            self.assertEqual(tuple(db.execute("SELECT (SELECT COUNT(*) FROM direct_source_records),"
                "(SELECT COUNT(*) FROM direct_card_events),(SELECT COUNT(*) FROM direct_normalized_payments)").fetchone()),(0,0,0))
            db.close()

    def test_hana_envelope_and_component_exact_types_fail_prewrite(self) -> None:
        base={"src":"HAN","raw_record_id":"H:1","c4":"9999","appr":"456","orig":"456",
            "use":"2026-06-05","bill":"2026-06-06","mer":"M","uptype":"","cur":"KRW","fx":"",
            "krw":120,"approval_amount":100,"cancel_amount":0,"purchase_amount":120,"cancel":False,"status":"",
            "amount_selection_reason":"purchase_amount_nonzero",
            "han_components":(("single",120,"purchase","purchase_amount_nonzero"),),
            "han_normalizer_version":HAN_NORMALIZER_VERSION,"han_contract_sha256":HAN_NORMALIZER_CONTRACT_SHA256}
        cases=(("approval_amount",True),("purchase_amount","120"),("cancel_amount",0.5),("cancel",0),
               ("krw","120"),("han_components",(("single",True,"purchase","purchase_amount_nonzero"),)),
               ("han_components",(("single","120","purchase","purchase_amount_nonzero"),)),
               ("han_components",(("single",120.0,"purchase","purchase_amount_nonzero"),)))
        for field,value in cases:
            card={**base,field:value}
            with self.subTest(field=field,value=repr(value)),tempfile.TemporaryDirectory() as dirname:
                db=connect(Path(dirname)/"direct.db");initialize(db)
                with patch("ledger.domain.direct_sources.cardindex.build_cards",return_value=[card]), \
                     self.assertRaisesRegex(ValueError,"han_(envelope_type_invalid|component_contract_mismatch)"):
                    import_cards(db,Path(dirname))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM direct_source_records").fetchone()[0],0);db.close()


if __name__ == "__main__":
    unittest.main()
