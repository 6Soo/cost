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
from ledger.domain.source_loss_gate import (
    HISTORICAL_SOURCE_RECORD_FLOORS,
    source_inventory_gate,
)
from ledger.domain.v2_workbook_adapter import (
    export_parallel_workbook,
    regression_report,
)


class P6AdapterIntegrationTest(unittest.TestCase):
    def test_current_source_inventory_reconciles_without_lowering_projection_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            db = connect(root / "source-inventory.db")
            try:
                initialize(db)
                result = import_all(
                    db,
                    LEDGER_DIR,
                    LEDGER_DIR / "data" / "manual_v4.csv",
                    LEDGER_DIR / "data" / "ota_mail_index.json",
                )
                inventory = source_inventory_gate(
                    result,
                    direct_records=result["direct_records"],
                )
                self.assertTrue(inventory["passed"])
                self.assertTrue(inventory["direct_records_reconciled"])
                self.assertEqual(inventory["below_historical_floor"], {})
                self.assertGreater(
                    inventory["actual"]["manual"],
                    HISTORICAL_SOURCE_RECORD_FLOORS["manual"],
                )
            finally:
                db.close()

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
                inventory = source_inventory_gate(
                    first,
                    direct_records=first["direct_records"],
                )
                self.assertTrue(inventory["direct_records_reconciled"])
                self.assertEqual(inventory["below_historical_floor"], {})
                self.assertTrue(inventory["passed"])
                # Dynamic reconciliation proves the direct-source store is a
                # complete projection of today's source files.  Per-kind
                # historical floors independently catch source loss while
                # allowing append-only growth (currently manual_v4).
                for source_kind, floor in HISTORICAL_SOURCE_RECORD_FLOORS.items():
                    self.assertGreaterEqual(first[source_kind]["records"], floor)
                    self.assertEqual(
                        second[source_kind]["records"],
                        first[source_kind]["records"],
                    )
                self.assertEqual(second["direct_records"], first["direct_records"])
                self.assertEqual(second["cards"]["inserted"], 0)
                self.assertEqual(second["manual"]["inserted"], 0)
                self.assertEqual(second["ota"]["inserted"], 0)
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
