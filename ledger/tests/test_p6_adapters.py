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
                # 기대값 갱신 2026-07-29: 8,336 → 8,337.
                #   구성 실측 = cards 5,237 + manual 1,380 + ota 1,720 = 8,337.
                #   +1은 origin/main 병합 시 채택한 manual_v4 한 행(0404_에히메 커피빈 10,500원)이다.
                #   HEAD의 수기장부 재파싱본은 1,380행, origin/main은 1,379행이었고, 원장 최신본
                #   (ledger_current.xlsx 48시트)에 근거해 HEAD를 채택했다. APA 정정과는 무관하다
                #   (APA 행은 classified_v14 소속이라 direct_source_records에 들어오지 않는다).
                self.assertEqual(first["direct_records"], 8337)
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
                # 기대값 갱신 2026-07-29: rows 1,833 → 1,838 · amount_krw 320,752,342 → 320,120,405.
                #   근거 — classified_v14 가 1,833행/320,115,617 → 1,838행/319,483,680 으로
                #     이동했다(APA 합산청구 분해 +3행·-571,962, 하나카드 취소 2건).
                #   어댑터 총액과 CSV 총액의 차이는 갱신 전후 모두 636,725 로 동일하다
                #     (320,752,342-320,115,617 = 320,120,405-319,483,680) — 어댑터 집계 규칙은 불변.
                workbook_result = export_parallel_workbook(db, output)
                self.assertEqual(workbook_result["rows"], 1838)
                self.assertEqual(workbook_result["amount_krw"], 320_120_405)
                workbook = openpyxl.load_workbook(output, read_only=True)
                self.assertEqual(
                    sum(max(0, sheet.max_row - 1) for sheet in workbook.worksheets),
                    1838,
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
