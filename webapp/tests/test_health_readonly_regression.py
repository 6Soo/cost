"""P1: ops health는 읽기 전용이다. 스키마 초기화를 하지 않는다.

재현: sentinel 테이블 하나뿐인 임시 SQLite를 데이터 루트로 두고
`python -m webapp.cli ops health`를 실행하면 exit 0, 테이블 1->32,
DB digest 변경이 관측됐다. 원인은 cmd_ops_health가
LedgerStore(seed_demo=False)를 생성해 스키마를 초기화했기 때문이다.
seed_demo=False는 데모 행만 막을 뿐 스키마 생성 자체는 막지 못한다.

수용 기준:
- 없는 DB와 불완전 DB의 health 실행은 파일/테이블/행 생성/수정 없이
  실패 상태와 nonzero exit를 낸다.
- 정상 DB의 기존 health 의미는 유지되며 읽기 부작용이 없다.
합성 입력만 사용한다.
"""
import contextlib
import hashlib
import io
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tables(path: Path) -> list:
    conn = sqlite3.connect(str(path))
    try:
        return sorted(
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        )
    finally:
        conn.close()


def _run_health(env: dict):
    from webapp import cli

    original = dict(os.environ)
    os.environ.update(env)
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["ops", "health"])
    finally:
        os.environ.clear()
        os.environ.update(original)
    import json

    return code, out.getvalue()


class OpsHealthReadonlyRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p1-health-ro-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "data"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(
                parents=True, exist_ok=True
            )

    def _env(self, db: Path):
        return {
            "WEBLEDGER_DATA_ROOT": str(self.root),
            "WEBLEDGER_DB": str(db),
            "WEBLEDGER_EXPORT_DIR": str(self.root / "exports"),
            "WEBLEDGER_EVIDENCE_DIR": str(self.root / "evidence"),
            "WEBLEDGER_SOURCE_DIR": str(self.root / "source"),
        }

    def test_missing_db_fails_without_creating_file(self):
        missing = self.root / "never-created.sqlite"
        self.assertFalse(missing.exists())
        code, payload = _run_health(self._env(missing))
        import json

        report = json.loads(payload)
        self.assertEqual(code, 2)
        self.assertFalse(report["ok"])
        self.assertFalse(missing.exists(), "health가 없는 DB 파일을 만들었다")

    def test_sentinel_db_fails_without_schema_init(self):
        sentinel = self.root / "board.sqlite"
        conn = sqlite3.connect(str(sentinel))
        try:
            conn.execute("CREATE TABLE sentinel (id INTEGER PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()
        before_tables = _tables(sentinel)
        self.assertEqual(before_tables, ["sentinel"])
        before_digest = _sha256(sentinel)
        before_size = sentinel.stat().st_size

        code, payload = _run_health(self._env(sentinel))
        import json

        report = json.loads(payload)
        self.assertEqual(code, 2, payload)
        self.assertFalse(report["ok"], payload)
        after_tables = _tables(sentinel)
        self.assertEqual(
            after_tables,
            ["sentinel"],
            f"health가 스키마를 초기화했다: {after_tables}",
        )
        self.assertEqual(_sha256(sentinel), before_digest, "DB digest가 바뀌었다")
        self.assertEqual(sentinel.stat().st_size, before_size)
        # 쓰기 부작용 산물들이 생기면 안 된다.
        self.assertFalse((self.root / "board.operator.sqlite").exists())
        self.assertFalse(Path(str(sentinel) + "-wal").exists())
        self.assertFalse(Path(str(sentinel) + "-shm").exists())

    def test_healthy_db_passes_without_mutation(self):
        from webapp.ledger_store import LedgerStore

        db = self.root / "board.sqlite"
        store = LedgerStore(db, seed_demo=False)
        store.close()
        before_tables = _tables(db)
        self.assertGreater(len(before_tables), 1)
        before_digest = _sha256(db)
        conn = sqlite3.connect(str(db))
        try:
            rows_before = conn.execute(
                "SELECT COUNT(*) FROM board_rows"
            ).fetchone()[0]
        finally:
            conn.close()

        code, payload = _run_health(self._env(db))
        import json

        report = json.loads(payload)
        self.assertEqual(code, 0, payload)
        self.assertTrue(report["ok"], payload)
        self.assertEqual(_tables(db), before_tables)
        self.assertEqual(_sha256(db), before_digest, "정상 DB가 health로 바뀌었다")
        conn = sqlite3.connect(str(db))
        try:
            rows_after = conn.execute(
                "SELECT COUNT(*) FROM board_rows"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(rows_before, rows_after)


if __name__ == "__main__":
    unittest.main()
