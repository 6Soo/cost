"""Phase 3 card import tests (synthetic profile only).

Covers WEB-A01..A03 style cases: mixed placement, same-file reuse,
overlapping file, cancel/refund separation, identifier collision,
interrupt resume, and source-row vs event counts.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp.card_import import CardImporter
from webapp.ledger_store import LedgerStore

HEADER = "occurred_on,merchant,amount_krw,currency,card_last4,approval_no,cancel_flag,suggested_tab,memo\n"


def make_importer():
    directory = tempfile.mkdtemp()
    store = LedgerStore(Path(directory) / "webledger.sqlite")
    conn = sqlite3.connect(str(Path(directory) / "imports.sqlite"), check_same_thread=False)
    return CardImporter(conn, store), store


GOOD_CSV = HEADER + (
    "2026-04-09,AGODA TEST,100000,KRW,1111,A1,,trip-demo-a,\n"
    "2026-04-10,AGODA TEST,-20000,KRW,1111,A2,,\n"
    "2026-04-11,UNKNOWN SHOP,30000,KRW,2222,A3,,,\n"
    "2026-04-12,BAD ROW,abc,KRW,3333,A4,,,\n"
)


class ImportBasicsTests(unittest.TestCase):
    def test_mixed_file_placement(self):
        importer, store = make_importer()
        try:
            received = importer.receive(GOOD_CSV.encode("utf-8"), "synthetic.csv")
            self.assertFalse(received["reused"])
            result = importer.process(received["batch_id"])
            self.assertEqual(result["status"], "completed_with_issues")
            self.assertEqual(result["source_rows"], 4)
            self.assertEqual(result["parsed_ok"], 3)
            self.assertEqual(result["parse_errors"], 1)
            self.assertEqual(result["new_events"], 3)
            self.assertEqual(result["placed_trips"], 1)
            self.assertEqual(result["placed_unclassified"], 2)
            # seed fixture A 지출 180000원에 가져온 100000원이 더해진다
            self.assertEqual(store.tab_totals("trip-demo-a")["expense"], 280000)
        finally:
            store.close()

    def test_cancel_row_separate_event(self):
        importer, store = make_importer()
        try:
            received = importer.receive(GOOD_CSV.encode("utf-8"), "synthetic.csv")
            importer.process(received["batch_id"])
            rows = store.conn.execute(
                "SELECT payload_json FROM board_rows WHERE row_id LIKE 'imp-%'"
            ).fetchall()
            amounts = sorted(__import__("json").loads(r[0])["amount_krw"] for r in rows)
            self.assertEqual(amounts, [-20000, 30000, 100000])
        finally:
            store.close()

    def test_same_file_reused(self):
        importer, store = make_importer()
        try:
            first = importer.receive(GOOD_CSV.encode("utf-8"), "synthetic.csv")
            importer.process(first["batch_id"])
            second = importer.receive(GOOD_CSV.encode("utf-8"), "synthetic.csv")
            self.assertTrue(second["reused"])
            count = store.conn.execute(
                "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'imp-%'"
            ).fetchone()[0]
            self.assertEqual(count, 3)
        finally:
            store.close()

    def test_overlapping_file_only_new(self):
        importer, store = make_importer()
        try:
            first = importer.receive(GOOD_CSV.encode("utf-8"), "a.csv")
            importer.process(first["batch_id"])
            extra = HEADER + (
                "2026-04-09,AGODA TEST,100000,KRW,1111,A1,,trip-demo-a,\n"
                "2026-04-13,NEW SHOP,50000,KRW,4444,A5,,trip-demo-b,\n"
            )
            second = importer.receive(extra.encode("utf-8"), "b.csv")
            result = importer.process(second["batch_id"])
            self.assertEqual(result["new_events"], 1)
            self.assertEqual(result["skipped_existing"], 1)
            self.assertEqual(store.tab_totals("trip-demo-b")["expense"], 50000)
        finally:
            store.close()

    def test_identifier_collision_preserved(self):
        importer, store = make_importer()
        try:
            first = importer.receive(GOOD_CSV.encode("utf-8"), "a.csv")
            importer.process(first["batch_id"])
            clash = HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,A1,,trip-demo-b,\n"
            second = importer.receive(clash.encode("utf-8"), "c.csv")
            result = importer.process(second["batch_id"])
            self.assertEqual(result["conflicts"], 1)
            self.assertEqual(result["new_events"], 0)
            # 충돌은 합치지 않으므로 첫 파일 배치 뒤 280000원 그대로
            self.assertEqual(store.tab_totals("trip-demo-a")["expense"], 280000)
        finally:
            store.close()

    def test_interrupt_resume_no_dupes(self):
        importer, store = make_importer()
        try:
            received = importer.receive(GOOD_CSV.encode("utf-8"), "a.csv")
            partial = importer.process(received["batch_id"], limit=1)
            self.assertEqual(partial["status"], "reconciling")
            done = importer.process(received["batch_id"])
            self.assertEqual(done["status"], "completed_with_issues")
            self.assertEqual(done["new_events"], 3)
            count = store.conn.execute(
                "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'imp-%'"
            ).fetchone()[0]
            self.assertEqual(count, 3)
        finally:
            store.close()

    def test_progress_counts(self):
        importer, store = make_importer()
        try:
            received = importer.receive(GOOD_CSV.encode("utf-8"), "a.csv")
            progress = importer.progress(received["batch_id"])
            self.assertEqual(progress["source_rows"], 4)
            self.assertEqual(progress["status"], "reconciling")
            importer.process(received["batch_id"])
            progress = importer.progress(received["batch_id"])
            self.assertEqual(progress["new_events"], 3)
            self.assertIsNone(importer.progress("imp-missing"))
        finally:
            store.close()


class SourceIdentityTests(unittest.TestCase):
    """R08: 안정 식별자는 승인번호 기준, 내용 변경·취소 구분은 충돌 보존."""

    def test_same_approval_different_amount_conflict(self):
        importer, store = make_importer()
        try:
            first = HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,ZZ1,,trip-demo-a,\n"
            second = HEADER + "2026-04-09,AGODA TEST,120000,KRW,1111,ZZ1,,trip-demo-a,\n"
            r1 = importer.receive(first.encode("utf-8"), "a.csv")
            importer.process(r1["batch_id"])
            r2 = importer.receive(second.encode("utf-8"), "b.csv")
            result = importer.process(r2["batch_id"])
            self.assertEqual(result["conflicts"], 1)
            self.assertEqual(result["new_events"], 0)
        finally:
            store.close()

    def test_same_approval_cancel_flag_conflict(self):
        importer, store = make_importer()
        try:
            first = HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,ZZ2,,trip-demo-a,\n"
            second = HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,ZZ2,1,trip-demo-a,\n"
            r1 = importer.receive(first.encode("utf-8"), "c.csv")
            importer.process(r1["batch_id"])
            r2 = importer.receive(second.encode("utf-8"), "d.csv")
            result = importer.process(r2["batch_id"])
            self.assertEqual(result["conflicts"], 1)
            self.assertEqual(result["new_events"], 0)
        finally:
            store.close()


class SourceBytesTests(unittest.TestCase):
    """8.2 R08: 원본 바이트 보관·해시·파일명 변경 재업로드."""

    def test_blob_and_renamed_reuse(self):
        from webapp.card_import import verify_source_bytes

        importer, store = make_importer()
        try:
            received = importer.receive(GOOD_CSV.encode("utf-8"), "synthetic.csv")
            importer.process(received["batch_id"])
            self.assertTrue(verify_source_bytes(importer.conn, received["batch_id"]))
            renamed = importer.receive(GOOD_CSV.encode("utf-8"), "other-name.csv")
            self.assertTrue(renamed["reused"])
            count = store.conn.execute(
                "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'imp-%'"
            ).fetchone()[0]
            self.assertEqual(count, 3)
        finally:
            store.close()

    def test_same_file_identical_rows_are_candidates(self):
        importer, store = make_importer()
        try:
            csv = HEADER + (
                "2026-04-09,SHOP,1000,KRW,1111,D1,,,\n"
                "2026-04-09,SHOP,1000,KRW,1111,D1,,,\n"
            )
            received = importer.receive(csv.encode("utf-8"), "dup.csv")
            result = importer.process(received["batch_id"])
            self.assertEqual(result["source_rows"], 2)
            self.assertEqual(result["new_events"], 1)
            self.assertEqual(result.get("duplicate_candidates"), 1)
        finally:
            store.close()


class WorkerResumeTests(unittest.TestCase):
    """8.2 R03: 재시작 뒤 재업로드 없이 이어간다."""

    def test_restart_resumes_without_reupload(self):
        import tempfile
        from pathlib import Path

        from webapp.card_import import CardImporter, CardWorker
        from webapp.ledger_store import LedgerStore

        directory = tempfile.mkdtemp()
        db_path = str(Path(directory) / "webledger.sqlite")
        store = LedgerStore(db_path)
        importer = CardImporter(store.conn, store)
        try:
            lines = "".join(
                f"2026-04-{(i % 28) + 1:02d},RSHOP{i},1000,KRW,1111,R{i},,,\n"
                for i in range(10)
            )
            body = HEADER + lines
            received = importer.receive(body.encode("utf-8"), "ten.csv")
            importer.process(received["batch_id"], limit=3)
            mid = importer.progress(received["batch_id"])
            self.assertEqual(mid["status"], "reconciling")
        finally:
            store.close()
        worker = CardWorker(db_path)
        try:
            store2 = LedgerStore(db_path)
            importer2 = CardImporter(store2.conn, store2)
            try:
                self.assertEqual(importer2.reset_stuck(), 0)
                done = importer2.process_to_completion(received["batch_id"])
                self.assertEqual(done["status"], "completed")
                self.assertEqual(done["new_events"], 10)
                count = store2.conn.execute(
                    "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'imp-%'"
                ).fetchone()[0]
                self.assertEqual(count, 10)
            finally:
                store2.close()
        finally:
            worker.stop(timeout=2)

    def test_worker_sweep_claims_and_completes(self):
        import tempfile
        from pathlib import Path

        from webapp.card_import import CardImporter, CardWorker
        from webapp.ledger_store import LedgerStore

        directory = tempfile.mkdtemp()
        db_path = str(Path(directory) / "webledger.sqlite")
        store = LedgerStore(db_path)
        importer = CardImporter(store.conn, store)
        try:
            received = importer.receive(GOOD_CSV.encode("utf-8"), "synthetic.csv")
            worker = CardWorker(db_path, idle_poll=0.05)
            try:
                self.assertTrue(worker.sweep_once(importer))
                progress = importer.progress(received["batch_id"])
                self.assertIn(progress["status"], ("completed", "completed_with_issues"))
            finally:
                worker.stop(timeout=2)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
