"""R08/R02: 은행 원천 동일성과 연결 경계 보존 테스트.

- batch_id는 내용 bytes의 sha256만 사용한다 (파일명 포함 금지)
- 같은 bytes에 다른 파일명 → reused=True, source/event/candidate 증가 0
- 계좌/거래 ID 없는 파일 간 같은 날짜·입금자·금액 → 확정 중복이 아니라 후보 보존
- 강한 식별(account_ref+transaction_id) 파일 간 재사용은 서로 다른 bytes 파일로 검증
- 같은 강한 식별자에 다른 금액 → 충돌 보존
- 별도 :memory: 연결은 같은 DB로 취급하지 않고, 외부 트랜잭션은 커밋하지 않는다
"""

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Local webapp package: income_ledger.py lives in this worktree.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import webapp
import webapp.income_ledger as income_ledger
from webapp.income_ledger import (BankImporter, BankImportError,
                                  _main_db_file, verify_source_bytes)
from webapp.ledger_store import LedgerStore

HEADER = "occurred_on,payer_name,amount_krw,direction,account_ref,transaction_id,memo\n"
WEAK_A = "2026-04-02,김예시,100000,credit,,,\n"
WEAK_B = "2026-04-03,박예시,200000,credit,,,\n"
STRONG_A = "2026-04-02,김예시,500000,credit,ACC1,TX9,\n"
STRONG_B = "2026-04-03,이예시,200000,credit,ACC1,TX10,\n"


def make_store():
    directory = tempfile.mkdtemp()
    return LedgerStore(Path(directory) / "webledger.sqlite")


def counts(store):
    queries = {
        "batches": "SELECT COUNT(*) FROM bank_import_batches",
        "blobs": "SELECT COUNT(*) FROM source_blobs",
        "import_rows": "SELECT COUNT(*) FROM bank_import_rows",
        "income_rows": "SELECT COUNT(*) FROM board_rows WHERE row_kind='income'"
                       " AND row_id LIKE 'bnk-%'",
        "candidates": "SELECT COUNT(*) FROM bank_import_rows"
                      " WHERE status='duplicate-candidate'",
    }
    return {name: store.conn.execute(sql).fetchone()[0]
            for name, sql in queries.items()}


class IsolationTests(unittest.TestCase):
    """격리 폴더의 코드가 실제로 import 되는지 확인한다."""

    def test_imports_resolve_to_isolated_worktree(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(Path(webapp.__file__).resolve().parent, root / "webapp")
        self.assertEqual(Path(income_ledger.__file__).resolve(),
                         root / "webapp" / "income_ledger.py")
        self.assertEqual(Path(sys.modules["webapp.ledger_store"].__file__).resolve(),
                         root / "webapp" / "ledger_store.py")


class BatchIdentityTests(unittest.TestCase):
    """batch_id는 내용 bytes만으로 만든다."""

    def test_batch_id_is_content_bytes_only(self):
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)
            content = (HEADER + WEAK_A).encode("utf-8")
            received = importer.receive(content, "bank1.csv")
            expected = "bnk-" + hashlib.sha256(content).hexdigest()[:16]
            self.assertEqual(received["batch_id"], expected)
            stored = store.conn.execute(
                "SELECT file_sha256, file_name FROM bank_import_batches"
                " WHERE batch_id=?", (received["batch_id"],)
            ).fetchone()
            self.assertEqual(stored[0], hashlib.sha256(content).hexdigest())
            self.assertEqual(stored[1], "bank1.csv")
            self.assertTrue(verify_source_bytes(store.conn, received["batch_id"]))
            # 파일명이 batch_id에 섞이지 않았다.
            self.assertNotIn("bank1.csv", received["batch_id"])
        finally:
            store.close()

    def test_same_bytes_renamed_file_is_reused_weak(self):
        """같은 bytes, 다른 파일명 (무식별 행) → 재사용, 증분 0."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)
            content = (HEADER + WEAK_A + WEAK_B).encode("utf-8")
            first = importer.receive(content, "bank.csv")
            self.assertFalse(first["reused"])
            before = counts(store)

            second = importer.receive(content, "renamed-copy.csv")
            self.assertTrue(second["reused"])
            self.assertEqual(second["batch_id"], first["batch_id"])
            self.assertEqual(second["result"], first["result"])
            self.assertEqual(counts(store), before)
        finally:
            store.close()

    def test_same_bytes_renamed_file_is_reused_strong(self):
        """같은 bytes, 다른 파일명 (강한 식별 행) → 재사용, 증분 0."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)
            content = (HEADER + STRONG_A).encode("utf-8")
            first = importer.receive(content, "strong.csv")
            self.assertFalse(first["reused"])
            before = counts(store)

            second = importer.receive(content, "2026년4월강한식별.csv")
            self.assertTrue(second["reused"])
            self.assertEqual(second["batch_id"], first["batch_id"])
            self.assertEqual(counts(store), before)
        finally:
            store.close()


class BankSourceIdentityTests(unittest.TestCase):
    """R08: 원천 식별자 기반 중복 처리 (파일 간 경계 포함)"""

    def test_no_id_same_payer_date_amount_preserved_as_candidate(self):
        """파일1 무식별 A행 1개, 파일2 A행+別の入金 B행 → 후보 1, 새 사건 1."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)

            csv1 = HEADER + WEAK_A
            csv2 = HEADER + WEAK_A + WEAK_B
            content1 = csv1.encode("utf-8")
            content2 = csv2.encode("utf-8")
            self.assertNotEqual(content1, content2)

            received1 = importer.receive(content1, "bank1.csv")
            self.assertFalse(received1["reused"])
            self.assertEqual(received1["result"]["new_events"], 1)
            self.assertEqual(received1["result"]["skipped_existing"], 0)

            received2 = importer.receive(content2, "bank2.csv")
            self.assertFalse(received2["reused"])
            self.assertNotEqual(received1["batch_id"], received2["batch_id"])
            result2 = received2["result"]

            self.assertEqual(result2["source_rows"], 2)
            self.assertEqual(result2["new_events"], 1)
            self.assertEqual(result2["skipped_existing"], 0)
            self.assertEqual(result2["duplicate_candidates"], 1)

            bnk_rows = store.conn.execute(
                "SELECT row_id FROM board_rows WHERE row_kind='income'"
                " AND row_id LIKE 'bnk-%'"
            ).fetchall()
            self.assertEqual(len(bnk_rows), 2)

            statuses = [r[0] for r in store.conn.execute(
                "SELECT status FROM bank_import_rows ORDER BY batch_id, row_index"
            ).fetchall()]
            self.assertEqual(statuses.count("placed"), 2)
            self.assertEqual(statuses.count("duplicate-candidate"), 1)
        finally:
            store.close()

    def test_no_id_same_payer_date_amount_different_memo_is_conflict(self):
        """무식별 행이지만 메모가 다르면 충돌로 보존한다."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)

            csv1 = HEADER + "2026-04-02,김예시,100000,credit,,,memo1\n"
            csv2 = HEADER + "2026-04-02,김예시,100000,credit,,,memo2\n"
            importer.receive(csv1.encode("utf-8"), "bank1.csv")
            received2 = importer.receive(csv2.encode("utf-8"), "bank2.csv")
            result2 = received2["result"]

            self.assertEqual(result2["new_events"], 0)
            self.assertEqual(result2["excluded_rows"], 1)
            self.assertEqual(result2["duplicate_candidates"], 0)
        finally:
            store.close()

    def test_cross_file_with_id_different_bytes_is_skipped(self):
        """강한 식별자의 파일 간 재사용은 bytes가 다른 두 파일로 검증한다."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)

            csv1 = HEADER + STRONG_A + WEAK_B
            csv2 = HEADER + STRONG_A
            content1 = csv1.encode("utf-8")
            content2 = csv2.encode("utf-8")
            self.assertNotEqual(content1, content2)

            received1 = importer.receive(content1, "bank1.csv")
            self.assertEqual(received1["result"]["new_events"], 2)

            received2 = importer.receive(content2, "bank2.csv")
            self.assertFalse(received2["reused"])
            self.assertNotEqual(received1["batch_id"], received2["batch_id"])
            result2 = received2["result"]

            self.assertEqual(result2["source_rows"], 1)
            self.assertEqual(result2["new_events"], 0)
            self.assertEqual(result2["skipped_existing"], 1)
            self.assertEqual(result2["duplicate_candidates"], 0)
            self.assertEqual(result2["excluded_rows"], 0)

            bnk_count = store.conn.execute(
                "SELECT COUNT(*) FROM board_rows WHERE row_kind='income'"
                " AND row_id LIKE 'bnk-%'"
            ).fetchone()[0]
            self.assertEqual(bnk_count, 2)
        finally:
            store.close()

    def test_cross_file_with_id_reordered_bytes_is_skipped(self):
        """행 순서만 바꿔도 bytes는 다르고, 강한 식별자는 재사용으로 잡힌다."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)

            csv1 = HEADER + STRONG_A + STRONG_B
            csv2 = HEADER + STRONG_B + STRONG_A
            content1 = csv1.encode("utf-8")
            content2 = csv2.encode("utf-8")
            self.assertNotEqual(content1, content2)

            received1 = importer.receive(content1, "bank1.csv")
            self.assertEqual(received1["result"]["new_events"], 2)

            received2 = importer.receive(content2, "bank2.csv")
            result2 = received2["result"]
            self.assertEqual(result2["new_events"], 0)
            self.assertEqual(result2["skipped_existing"], 2)
            self.assertEqual(result2["duplicate_candidates"], 0)
            self.assertEqual(result2["excluded_rows"], 0)
        finally:
            store.close()

    def test_cross_file_with_id_same_content_same_bytes_is_reused(self):
        """강한 식별 행이 담긴 bytes가 같으면 새 배치 자체를 만들지 않는다."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)
            content = (HEADER + STRONG_A).encode("utf-8")
            first = importer.receive(content, "bank1.csv")
            before = counts(store)
            second = importer.receive(content, "bank2.csv")
            self.assertTrue(second["reused"])
            self.assertEqual(counts(store), before)
            self.assertEqual(second["result"]["new_events"],
                             first["result"]["new_events"])
        finally:
            store.close()

    def test_cross_file_with_id_different_amount_is_conflict(self):
        """같은 거래 ID인데 금액이 다르면 충돌로 보존한다."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)

            csv1 = HEADER + "2026-04-02,김예시,100000,credit,ACC1,TX9,\n"
            csv2 = HEADER + "2026-04-02,김예시,150000,credit,ACC1,TX9,\n"
            importer.receive(csv1.encode("utf-8"), "bank1.csv")
            received2 = importer.receive(csv2.encode("utf-8"), "bank2.csv")
            result2 = received2["result"]

            self.assertEqual(result2["new_events"], 0)
            self.assertEqual(result2["excluded_rows"], 1)
            self.assertEqual(result2["duplicate_candidates"], 0)
        finally:
            store.close()

    def test_same_file_reupload_is_reused(self):
        """같은 파일을 다시 올리면 배치 단위로 재사용한다."""
        store = make_store()
        try:
            importer = BankImporter(store.conn, store)
            content = (HEADER + WEAK_A + WEAK_B).encode("utf-8")

            first = importer.receive(content, "bank.csv")
            self.assertFalse(first["reused"])
            self.assertEqual(first["result"]["new_events"], 2)

            before = counts(store)
            second = importer.receive(content, "bank.csv")
            self.assertTrue(second["reused"])
            self.assertEqual(second["result"]["new_events"], 2)
            self.assertEqual(counts(store), before)
        finally:
            store.close()


class ConnectionBoundaryTests(unittest.TestCase):
    """R02: 같은 DB 연결만 받아들이고 외부 트랜잭션은 커밋하지 않는다."""

    def test_separate_connection_to_same_file_is_accepted(self):
        store = make_store()
        caller = sqlite3.connect(str(store.path), check_same_thread=False)
        try:
            importer = BankImporter(caller, store)
            self.assertIs(importer.conn, store.conn)
            received = importer.receive((HEADER + WEAK_A).encode("utf-8"),
                                        "bank.csv")
            self.assertFalse(received["reused"])
            self.assertEqual(received["result"]["new_events"], 1)
        finally:
            caller.close()
            store.close()

    def test_separate_connection_to_other_file_is_rejected(self):
        store = make_store()
        other = make_store()
        try:
            with self.assertRaises(BankImportError) as ctx:
                BankImporter(other.conn, store)
            self.assertEqual(ctx.exception.code, "BANK_DB_MISMATCH")
        finally:
            other.close()
            store.close()

    def test_memory_connection_is_not_accepted_as_same_db(self):
        """PRAGMA database_list의 file이 빈 메모리 연결은 같은 DB로 증명되지 않는다."""
        store = make_store()
        caller = sqlite3.connect(":memory:")
        try:
            with self.assertRaises(BankImportError) as ctx:
                BankImporter(caller, store)
            self.assertEqual(ctx.exception.code, "BANK_DB_MISMATCH")
        finally:
            caller.close()
            store.close()

    def test_two_distinct_memory_connections_have_no_db_identity(self):
        """서로 다른 두 :memory: 연결은 둘 다 경로가 비어 있어 동일 판정이 불가능하다."""
        first = sqlite3.connect(":memory:")
        second = sqlite3.connect(":memory:")
        store = make_store()
        try:
            self.assertIsNone(_main_db_file(first))
            self.assertIsNone(_main_db_file(second))
            self.assertIsNotNone(_main_db_file(store.conn))
            # 경로가 비어 있으면 절대 같다고 판정하지 않는다.
            keeper = _main_db_file(store.conn)
            self.assertFalse(
                _main_db_file(first) is not None
                and keeper is not None
                and _main_db_file(first) == keeper
            )
        finally:
            first.close()
            second.close()
            store.close()

    def test_construction_keeps_caller_transaction_open(self):
        """schema executescript의 암시적 COMMIT은 외부 트랜잭션에 미치지 않는다."""
        store = make_store()
        caller = sqlite3.connect(str(store.path), check_same_thread=False)
        try:
            caller.execute("BEGIN")
            self.assertTrue(caller.in_transaction)
            BankImporter(caller, store)
            self.assertTrue(caller.in_transaction)
            caller.execute("ROLLBACK")
            self.assertFalse(caller.in_transaction)
        finally:
            caller.close()
            store.close()

    def test_receive_keeps_caller_transaction_open(self):
        """receive의 BEGIN/COMMIT 경계는 store.conn 밖의 트랜잭션을 건드리지 않는다."""
        store = make_store()
        caller = sqlite3.connect(str(store.path), check_same_thread=False)
        try:
            importer = BankImporter(caller, store)
            caller.execute("BEGIN")
            self.assertTrue(caller.in_transaction)

            received = importer.receive((HEADER + WEAK_A).encode("utf-8"),
                                        "bank.csv")
            self.assertFalse(received["reused"])
            self.assertEqual(received["result"]["new_events"], 1)

            self.assertTrue(caller.in_transaction)
            caller.execute("ROLLBACK")
            self.assertFalse(caller.in_transaction)
        finally:
            caller.close()
            store.close()
