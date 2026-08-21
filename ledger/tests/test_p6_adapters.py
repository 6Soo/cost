from __future__ import annotations

import tempfile
import unittest
import json
from collections import Counter
from pathlib import Path

import openpyxl

from ledger.domain.direct_sources import import_all
from ledger.domain.source_adapters import (
    adapt_pg_record,
    adapt_service_mail_record,
    forbidden_ota_fields,
)
from ledger.domain.ledger_db import (
    DEFAULT_BOOKINGS,
    DEFAULT_CSV,
    DEFAULT_TRIPS,
    LEDGER_DIR,
    apply_p1_confidence_rules,
    apply_p3_unassigned_review,
    apply_p4_provider_rules,
    apply_p5_quality_audit,
    connect,
    import_legacy,
    initialize,
    resolve_hana_split_cancellations,
    validation_report,
)
from ledger.domain.v2_workbook_adapter import (
    export_parallel_workbook,
    regression_report,
)


class P6AdapterIntegrationTest(unittest.TestCase):
    def test_pg_mail_allowlist_rejects_raw_mail_fields_and_keeps_typed_values(self) -> None:
        record = {
            "provider": "NICE",
            "message_id": "pg-test-1",
            "sender_domain": "nicepg.co.kr",
            "payment_date": "2026-06-19",
            "merchant": "의왕도시공사",
            "product": "백운산동 107호",
            "amount_krw": 140000,
            "approval_number": "30059131",
            "order_id": "2606190889522",
            "status": "purchase",
        }
        clean = adapt_pg_record(record)
        self.assertEqual(clean["redaction_version"], "pg-allowlist-v1")
        self.assertEqual(clean["amount_krw"], 140000)
        with self.assertRaisesRegex(ValueError, "pg_unknown_field"):
            adapt_pg_record({**record, "body": "raw MIME"})

    def test_service_mail_contract_requires_explicit_service_period(self) -> None:
        clean = adapt_service_mail_record({
            "provider": "FOREST_GO_KR",
            "message_id": "service-test-1",
            "sender_domain": "forest.go.kr",
            "property_name": "백운산동 107호",
            "service_start_on": "2026-07-19",
            "service_end_on": "2026-07-19",
            "status": "confirmed",
        })
        self.assertEqual(clean["service_start_on"], "2026-07-19")
        with self.assertRaisesRegex(ValueError, "service_mail_period_invalid"):
            adapt_service_mail_record({
                "provider": "FOREST_GO_KR",
                "message_id": "service-test-2",
                "sender_domain": "forest.go.kr",
                "status": "confirmed",
            })

    def test_real_ota_candidate_census_and_pnr_lengths(self) -> None:
        rows = json.loads((LEDGER_DIR / "data/ota_mail_index.json").read_text(encoding="utf-8"))["records"]
        self.assertEqual(len(rows), 1802)
        from ledger.domain.source_adapters import adapt_ota_record
        clean = [adapt_ota_record(row) for row in rows]
        self.assertTrue(all(set(("amount_candidates", "pnr_candidates", "booking_ref_candidates", "travel_date_candidates")) <= set(r) for r in clean))
        self.assertEqual(sum(bool(forbidden_ota_fields(r)) for r in clean), 0)
        self.assertEqual(sum(bool(r.get("amount_candidates")) for r in clean), 680)
        self.assertEqual(sum(len(r.get("amount_candidates", [])) for r in clean), 2178)
        pnrs = [x for r in clean for x in r.get("pnr_candidates", [])]
        self.assertEqual((sum(bool(r.get("pnr_candidates")) for r in clean), len(pnrs)), (160, 165))
        self.assertEqual(Counter(map(len, pnrs)), {6: 132, 7: 21, 8: 6, 10: 6})
        refs = [x for r in clean for x in r.get("booking_ref_candidates", [])]
        dates = [x for r in clean for x in r.get("travel_date_candidates", [])]
        self.assertEqual((sum(bool(r.get("booking_ref_candidates")) for r in clean), len(refs)), (465, 476))
        self.assertEqual((sum(bool(r.get("travel_date_candidates")) for r in clean), len(dates)), (1429, 3757))
        self.assertTrue(all("booking_number" not in r and "period_original" not in r for r in clean))
    def test_direct_sources_are_idempotent_and_workbook_has_no_unexplained_diff(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            db = connect(root / "p6.db")
            try:
                initialize(db)
                import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
                resolve_hana_split_cancellations(db)
                apply_p1_confidence_rules(db)
                apply_p3_unassigned_review(db)
                apply_p4_provider_rules(db)
                apply_p5_quality_audit(db)
                first = import_all(
                    db,
                    LEDGER_DIR,
                    LEDGER_DIR / "data" / "manual_v4.csv",
                    LEDGER_DIR / "data" / "ota_mail_index.json",
                    pg_mail_path=LEDGER_DIR / "data" / "pg_mail_index.json",
                    pg_mail_supplement_path=(
                        LEDGER_DIR / "data" / "pg_mail_supplemental_index.json"
                    ),
                    service_mail_path=LEDGER_DIR / "data" / "service_mail_index.json",
                )
                second = import_all(
                    db,
                    LEDGER_DIR,
                    LEDGER_DIR / "data" / "manual_v4.csv",
                    LEDGER_DIR / "data" / "ota_mail_index.json",
                    pg_mail_path=LEDGER_DIR / "data" / "pg_mail_index.json",
                    pg_mail_supplement_path=(
                        LEDGER_DIR / "data" / "pg_mail_supplemental_index.json"
                    ),
                    service_mail_path=LEDGER_DIR / "data" / "service_mail_index.json",
                )
                self.assertEqual(first["direct_records"], 10303)
                self.assertEqual(first["pg_mail"]["records"], 1864)
                self.assertEqual(first["pg_mail_supplement"]["records"], 19)
                self.assertEqual(first["service_mail"]["records"], 2)
                self.assertEqual(second["direct_records"], 10303)
                self.assertEqual(first["cards"]["identity_collisions"], 0)
                self.assertEqual(first["cards"]["normalized_payments"], 5328)
                self.assertEqual(
                    db.execute(
                        """SELECT COUNT(*) FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           WHERE s.source_kind='card_raw'
                             AND json_extract(s.payload_json, '$.status')='취소매출'
                             AND d.transaction_type='cancellation'
                             AND d.amount_krw<0"""
                    ).fetchone()[0],
                    149,
                )
                self.assertEqual(
                    db.execute(
                        """SELECT COUNT(*) FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           WHERE s.source_kind='card_raw'
                             AND json_extract(s.payload_json, '$.status')='취소또는할인'
                             AND d.transaction_type='cancellation'
                             AND d.amount_krw<0"""
                    ).fetchone()[0],
                    8,
                )
                self.assertEqual(
                    db.execute(
                        """SELECT ABS(SUM(d.amount_krw)) FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           WHERE json_extract(s.payload_json, '$.status')='취소매출'"""
                    ).fetchone()[0],
                    43490431,
                )
                self.assertEqual(
                    db.execute(
                        """SELECT ABS(SUM(d.amount_krw)) FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           WHERE json_extract(s.payload_json, '$.status')='취소또는할인'"""
                    ).fetchone()[0],
                    2925343,
                )
                self.assertEqual(
                    db.execute(
                        """SELECT COUNT(*) FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           WHERE json_extract(s.payload_json, '$.status') IN ('취소매출','취소또는할인')
                             AND d.amount_krw>=0"""
                    ).fetchone()[0],
                    0,
                )
                normalized_snapshot = db.execute(
                    """SELECT s.source_key, d.event_role, d.card_event_id,
                              d.amount_krw, d.transaction_type, d.normalization_version
                       FROM direct_normalized_payments d
                       JOIN direct_source_records s ON s.id=d.source_record_id
                       ORDER BY s.source_key, d.event_role"""
                ).fetchall()
                self.assertTrue(normalized_snapshot)
                self.assertTrue(
                    all(row[5] == "direct-card-v3" for row in normalized_snapshot)
                )
                identities = db.execute(
                    "SELECT card_event_id, identity_status FROM direct_card_events ORDER BY card_event_id"
                ).fetchall()
                self.assertTrue(identities)
                self.assertTrue(all(row[1] == "unique" for row in identities))
                first_identity_snapshot = [tuple(row) for row in identities]
                first_identity_count = len(first_identity_snapshot)
                self.assertEqual(second["cards"]["inserted"], 0)
                self.assertEqual(second["cards"]["identity_collisions"], 0)
                self.assertEqual(second["cards"]["normalized_payments"], 5328)
                self.assertEqual(second["manual"]["inserted"], 0)
                self.assertEqual(second["ota"]["inserted"], 0)
                second_identity_snapshot = [
                    tuple(row)
                    for row in db.execute(
                        "SELECT card_event_id, identity_status FROM direct_card_events ORDER BY card_event_id"
                    ).fetchall()
                ]
                self.assertEqual(second_identity_snapshot, first_identity_snapshot)
                self.assertEqual(len(second_identity_snapshot), first_identity_count)
                self.assertEqual(
                    db.execute(
                        """SELECT s.source_key, d.event_role, d.card_event_id,
                                  d.amount_krw, d.transaction_type, d.normalization_version
                           FROM direct_normalized_payments d
                           JOIN direct_source_records s ON s.id=d.source_record_id
                           ORDER BY s.source_key, d.event_role"""
                    ).fetchall(),
                    normalized_snapshot,
                )
                split_hana = db.execute(
                    """
                    SELECT
                        source_record_id,
                        SUM(CASE WHEN event_role='approval'
                                 AND amount_krw>0 THEN 1 ELSE 0 END) AS approvals,
                        SUM(CASE WHEN event_role='cancellation'
                                 AND amount_krw<0 THEN 1 ELSE 0 END) AS cancellations
                    FROM direct_normalized_payments
                    WHERE event_role<>'single'
                    GROUP BY source_record_id
                    """
                ).fetchall()
                self.assertGreater(len(split_hana), 0)
                self.assertTrue(
                    all(
                        int(row["approvals"]) == 1
                        and int(row["cancellations"]) == 1
                        for row in split_hana
                    )
                )

                output = root / "parallel.xlsx"
                workbook_result = export_parallel_workbook(db, output)
                self.assertEqual(workbook_result["rows"], 1833)
                self.assertEqual(workbook_result["amount_krw"], 320_752_342)
                workbook = openpyxl.load_workbook(output, read_only=True)
                self.assertEqual(
                    sum(max(0, sheet.max_row - 1) for sheet in workbook.worksheets),
                    1833,
                )
                workbook.close()
                report = regression_report(
                    db,
                    LEDGER_DIR / "baselines" / "p05_latest_20260725"
                    / "regression_totals.json",
                )
                self.assertEqual(report["unexplained_differences"], 0)
                self.assertTrue(validation_report(db)["valid"])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
