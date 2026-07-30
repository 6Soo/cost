from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openpyxl

from ledger.domain.direct_sources import import_all
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
                )
                second = import_all(
                    db,
                    LEDGER_DIR,
                    LEDGER_DIR / "data" / "manual_v4.csv",
                    LEDGER_DIR / "data" / "ota_mail_index.json",
                )
                self.assertEqual(first["direct_records"], 8336)
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
