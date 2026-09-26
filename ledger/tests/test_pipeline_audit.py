import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from tools import pipeline_audit as audit_tool


class PipelineAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_inventory(self, stages: list[dict], name: str = "inventory.json") -> str:
        path = self.root / "config" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"version": 1, "stages": stages}), encoding="utf-8")
        return "config/" + name

    def stage(self, kind: str = "current", entrypoints: list[str] | None = None,
              artifacts: list[dict] | None = None, stage_id: str = "stage") -> dict:
        return {"id": stage_id, "kind": kind, "entrypoints": entrypoints or [],
                "artifacts": artifacts or []}

    def make_db(self, relative: str, posting: bool = False) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE payment_transactions(payment_id TEXT, amount_krw INTEGER, payload TEXT);
            CREATE TABLE draft_rows(payment_id TEXT, status TEXT, amount_krw INTEGER, payload TEXT);
            CREATE TABLE shadow_batches(batch_id TEXT);
            CREATE TABLE shadow_lines(debit_krw INTEGER, credit_krw INTEGER, payload TEXT);
        """)
        conn.executemany("INSERT INTO payment_transactions VALUES (?, ?, ?)",
                         [("pay-001", 100, "PRIVATE_PAYLOAD"), ("pay-002", 200, "PRIVATE_PAYLOAD")])
        conn.executemany("INSERT INTO draft_rows VALUES (?, ?, ?, ?)",
                         [("pay-001", "approved", 100, "PRIVATE_PAYLOAD"),
                          ("pay-002", "pending", 200, "PRIVATE_PAYLOAD"),
                          ("pay-003", "approved", -50, "PRIVATE_PAYLOAD")])
        conn.executemany("INSERT INTO shadow_batches VALUES (?)", [("b1",), ("b2",)])
        conn.executemany("INSERT INTO shadow_lines VALUES (?, ?, ?)",
                         [(300, 200, "PRIVATE_PAYLOAD"), (0, 100, "PRIVATE_PAYLOAD")])
        if posting:
            conn.execute("ALTER TABLE draft_rows ADD COLUMN posting_eligible INTEGER DEFAULT 0")
            conn.execute("UPDATE draft_rows SET posting_eligible = 1 WHERE payment_id = 'pay-001'")
        conn.commit()
        conn.close()
        return path

    def add_audit(self, relative: str, database: Path, digest_key: str = "database_sha256",
                  value: str | None = None) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({digest_key: value or audit_tool.sha256_file(database)}),
                        encoding="utf-8")
        return relative

    def write_audit_json(self, relative: str, data: dict) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return relative

    def make_actual_db(self, relative: str = "outputs/actual.sqlite", duplicate: bool = False) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE draft_rows(payment_id TEXT, target_match_status TEXT, amount_krw INTEGER, payload TEXT);
            CREATE TABLE shadow_batches(batch_id TEXT);
            CREATE TABLE shadow_lines(batch_id TEXT, side TEXT, amount_krw INTEGER, payload TEXT);
        """)
        draft = [("pay-a", "matched", 100, "PRIVATE_PAYLOAD"),
                 ("pay-b", "unmatched", -40, "PRIVATE_PAYLOAD"),
                 ("pay-c", "matched", 20, "PRIVATE_PAYLOAD")]
        if duplicate:
            draft.append(("pay-a", "matched", 5, "PRIVATE_PAYLOAD"))
        conn.executemany("INSERT INTO draft_rows VALUES (?, ?, ?, ?)", draft)
        conn.executemany("INSERT INTO shadow_batches VALUES (?)", [("b1",), ("b2",)])
        conn.executemany("INSERT INTO shadow_lines VALUES (?, ?, ?, ?)", [
            ("b1", "debit", 100, "PRIVATE_PAYLOAD"),
            ("b1", "credit", 100, "PRIVATE_PAYLOAD"),
            ("b2", "debit", 50, "PRIVATE_PAYLOAD")])
        conn.commit()
        conn.close()
        return path

    def run_audit(self, inventory: str) -> tuple[dict, int]:
        return audit_tool.audit(self.root, inventory)

    def test_readonly_and_missing_db_do_not_create_files(self) -> None:
        existing = self.make_db("outputs/readonly.sqlite")
        missing = self.root / "outputs" / "missing.sqlite"
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/readonly.sqlite", "kind": "sqlite"}], stage_id="present"),
            self.stage(artifacts=[{"path": "outputs/missing.sqlite", "kind": "sqlite"}], stage_id="absent")])
        before = {path.relative_to(self.root) for path in self.root.rglob("*")}
        report, code = self.run_audit(inventory)
        after = {path.relative_to(self.root) for path in self.root.rglob("*")}
        self.assertFalse(missing.exists())
        self.assertEqual(before, after)
        self.assertEqual(code, 2)
        self.assertEqual(report["stages"][0]["artifacts"][0]["exists"], True)
        self.assertTrue(existing.exists())

    def test_audit_digest_mismatch_and_missing_are_not_success(self) -> None:
        database = self.make_db("outputs/a.sqlite")
        audit_path = self.add_audit("outputs/a.audit.json", database, value="0" * 64)
        artifact = {"path": "outputs/a.sqlite", "kind": "sqlite", "audit": audit_path}
        inventory = self.write_inventory([self.stage(kind="candidate", artifacts=[artifact])])
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("AUDIT_DATABASE_DIGEST_MISMATCH", {item["code"] for item in report["findings"]})
        (self.root / audit_path).write_text("{}", encoding="utf-8")
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "unverified")
        self.assertIn("AUDIT_DIGEST_MISSING", {item["code"] for item in report["findings"]})

    def test_nested_audit_digest_and_alias_conflict_are_checked(self) -> None:
        database = self.make_db("outputs/nested.sqlite")
        digest = audit_tool.sha256_file(database)
        audit_path = self.write_audit_json("outputs/nested.audit.json", {
            "outputs": {"database_sha256": "0" * 64},
            "manifest": {"shadow_database_sha256": digest}})
        artifact = {"path": "outputs/nested.sqlite", "kind": "sqlite", "audit": audit_path}
        inventory = self.write_inventory([self.stage(kind="candidate", artifacts=[artifact])])
        report, code = self.run_audit(inventory)
        codes = {item["code"] for item in report["findings"]}
        self.assertEqual(code, 1)
        self.assertIn("AUDIT_DATABASE_DIGEST_MISMATCH", codes)
        self.assertNotIn("AUDIT_DIGEST_MISSING", codes)
        self.write_audit_json("outputs/nested.audit.json", {
            "database_sha256": digest, "audit_db_sha256": "1" * 64})
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        self.assertIn("AUDIT_DATABASE_DIGEST_MISMATCH",
                      {item["code"] for item in report["findings"]})

    def test_sidecars_are_unverified_and_sqlite_is_not_opened(self) -> None:
        database = self.make_db("outputs/unsealed.sqlite")
        sidecars = [Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal")]
        for index, sidecar in enumerate(sidecars):
            sidecar.write_bytes(("sidecar-" + str(index)).encode())

        def metadata(path: Path) -> tuple:
            stat = os.lstat(path)
            return (stat.st_mode, stat.st_size, stat.st_mtime_ns,
                    stat.st_ctime_ns, stat.st_dev, stat.st_ino)

        db_bytes = database.read_bytes()
        sidecar_metadata = [metadata(sidecar) for sidecar in sidecars]
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/unsealed.sqlite", "kind": "sqlite"}])])
        hash_calls = []
        original_hash = audit_tool.sha256_file

        def capture_hash(path: Path) -> str:
            hash_calls.append(Path(path))
            return original_hash(Path(path))

        with mock.patch.object(audit_tool.sqlite3, "connect") as connect, \
             mock.patch.object(audit_tool, "sha256_file", side_effect=capture_hash):
            report, code = self.run_audit(inventory)
        connect.assert_not_called()
        self.assertTrue(all(sidecar not in hash_calls for sidecar in sidecars))
        self.assertEqual(code, 2)
        self.assertEqual(report["stages"][0]["status"], "unverified")
        self.assertIn("SQLITE_UNSEALED", {item["code"] for item in report["findings"]})
        self.assertEqual(database.read_bytes(), db_bytes)
        self.assertEqual([metadata(sidecar) for sidecar in sidecars], sidecar_metadata)

    def test_new_sidecar_during_inspection_is_detected_without_hashing(self) -> None:
        database = self.make_db("outputs/race.sqlite")
        sidecar = Path(str(database) + "-wal")
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/race.sqlite", "kind": "sqlite"}])])
        original_report = audit_tool._stage_report

        def add_sidecar(*args, **kwargs):
            result = original_report(*args, **kwargs)
            sidecar.write_bytes(b"appeared")
            return result

        hash_calls = []
        original_hash = audit_tool.sha256_file

        def capture_hash(path: Path) -> str:
            hash_calls.append(Path(path))
            return original_hash(Path(path))

        with mock.patch.object(audit_tool, "_stage_report", side_effect=add_sidecar), \
             mock.patch.object(audit_tool, "sha256_file", side_effect=capture_hash):
            report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("INPUT_CHANGED_DURING_INSPECTION",
                      {item["code"] for item in report["findings"]})
        self.assertNotIn(sidecar, hash_calls)

    def test_closed_wal_database_stays_unchanged_and_is_aggregated(self) -> None:
        database = self.root / "outputs" / "closed-wal.sqlite"
        database.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(database)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE payment_transactions(payment_id TEXT, amount_krw INTEGER);
            INSERT INTO payment_transactions VALUES ('wal-a', 10), ('wal-b', 20);
        """)
        conn.commit()
        conn.close()
        sidecars = [Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal")]
        self.assertFalse(any(sidecar.exists() for sidecar in sidecars))
        before_hash = audit_tool.sha256_file(database)
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/closed-wal.sqlite", "kind": "sqlite"}])])
        before_files = {path.relative_to(self.root) for path in self.root.rglob("*")}
        report, code = self.run_audit(inventory)
        after_files = {path.relative_to(self.root) for path in self.root.rglob("*")}
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(before_hash, audit_tool.sha256_file(database))
        self.assertEqual(before_files, after_files)
        self.assertFalse(any(sidecar.exists() for sidecar in sidecars))
        stats = report["stages"][0]["artifacts"][0]["stats"]
        self.assertEqual(stats["payment_transactions"], {"count": 2, "sum_amount_krw": 30})

    def test_actual_draft_and_shadow_schema_is_aggregated_and_flagged(self) -> None:
        database = self.make_actual_db()
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/actual.sqlite", "kind": "sqlite"}])])
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        stats = report["stages"][0]["artifacts"][0]["stats"]
        self.assertEqual(stats["draft_rows"]["status_counts"], {"matched": 2, "unmatched": 1})
        self.assertEqual(stats["draft_rows"]["sum_amount_krw"], 80)
        self.assertEqual(stats["draft_rows"]["negative_count"], 1)
        self.assertEqual(stats["draft_rows"]["negative_sum_krw"], -40)
        self.assertEqual(stats["shadow"]["lines"]["debit_krw"], 150)
        self.assertEqual(stats["shadow"]["lines"]["credit_krw"], 100)
        self.assertIn("SHADOW_DEBIT_CREDIT_UNBALANCED",
                      {item["code"] for item in report["findings"]})
        self.assertIn("SHADOW_LINES_PER_BATCH_MISMATCH",
                      {item["code"] for item in report["findings"]})

    def test_duplicate_draft_payment_id_is_an_error(self) -> None:
        self.make_actual_db(duplicate=True)
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/actual.sqlite", "kind": "sqlite"}])])
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        self.assertIn("DRAFT_PAYMENT_ID_DUPLICATE",
                      {item["code"] for item in report["findings"]})

    def test_candidate_posting_flag_blocks(self) -> None:
        database = self.make_db("outputs/posting.sqlite", posting=True)
        inventory = self.write_inventory([self.stage(
            kind="candidate", artifacts=[{"path": "outputs/posting.sqlite", "kind": "sqlite"}])])
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        self.assertEqual(report["stages"][0]["status"], "blocked")
        self.assertIn("CANDIDATE_POSTING_FLAG_NONZERO",
                      {item["code"] for item in report["findings"]})
        self.assertTrue(database.exists())

    def test_corrupt_sqlite_is_structured_failure(self) -> None:
        path = self.root / "outputs" / "bad.sqlite"
        path.parent.mkdir()
        path.write_bytes(b"not a sqlite database")
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/bad.sqlite", "kind": "sqlite"}])])
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("SQLITE_INSPECTION_FAILED", {item["code"] for item in report["findings"]})

    def test_traversal_is_rejected_without_traceback(self) -> None:
        inventory = self.write_inventory([self.stage(entrypoints=["../outside.py"])])
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 2)
        self.assertTrue(report["invalid_inventory"])
        self.assertEqual(report["findings"][0]["code"], "INVENTORY_PATH_ESCAPE")

    def test_output_collision_is_exclusive_and_does_not_overwrite(self) -> None:
        inventory = self.write_inventory([self.stage()])
        path = self.root / "config" / "inventory.json"
        original = path.read_bytes()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = audit_tool.main(["--root", str(self.root), "--inventory", inventory,
                                    "--output", inventory])
        self.assertEqual(code, 2)
        self.assertEqual(path.read_bytes(), original)
        self.assertIn("OUTPUT_INPUT_COLLISION", stdout.getvalue())

    def test_output_does_not_create_parent_directory(self) -> None:
        inventory = self.write_inventory([self.stage()])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = audit_tool.main(["--root", str(self.root), "--inventory", inventory,
                                    "--output", "new-output/report.json"])
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "new-output").exists())
        self.assertIn("OUTPUT_PARENT_MISSING", stdout.getvalue())

    def test_main_preserves_inventory_schema_error_code(self) -> None:
        inventory_path = self.root / "config" / "bad.json"
        inventory_path.parent.mkdir(exist_ok=True)
        inventory_path.write_text(json.dumps({"version": 1, "stages": [{}]}), encoding="utf-8")
        code = audit_tool.main(["--root", str(self.root), "--inventory", "config/bad.json",
                                "--output", "config/result.json"])
        self.assertEqual(code, 2)
        result = json.loads((self.root / "config" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["findings"][0]["code"], "INVENTORY_SCHEMA_INVALID")

    def test_aggregates_never_include_rows_or_payload(self) -> None:
        database = self.make_db("outputs/aggregate.sqlite")
        audit_path = self.add_audit("outputs/aggregate.audit.json", database)
        inventory = self.write_inventory([self.stage(
            artifacts=[{"path": "outputs/aggregate.sqlite", "kind": "sqlite", "audit": audit_path}])])
        report, code = self.run_audit(inventory)
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertEqual(code, 0)
        self.assertNotIn("PRIVATE_PAYLOAD", rendered)
        self.assertNotIn("pay-001", rendered)
        stats = report["stages"][0]["artifacts"][0]["stats"]
        self.assertEqual(stats["payment_transactions"], {"count": 2, "sum_amount_krw": 300})
        self.assertEqual(stats["draft_rows"]["count"], 3)
        self.assertEqual(stats["draft_rows"]["distinct_payment_id"], 3)
        self.assertEqual(stats["draft_rows"]["status_counts"], {"approved": 2, "pending": 1})
        self.assertEqual(stats["draft_rows"]["sum_amount_krw"], 250)
        self.assertEqual(stats["draft_rows"]["negative_count"], 1)
        self.assertEqual(stats["draft_rows"]["negative_sum_krw"], -50)
        self.assertEqual(stats["shadow"]["batches"]["count"], 2)
        self.assertEqual(stats["shadow"]["lines"]["count"], 2)
        self.assertEqual(stats["shadow"]["lines"]["balance_krw"], 0)
        self.assertFalse(report["release_eligible"])

    def test_entrypoints_are_hashed_not_executed(self) -> None:
        marker = self.root / "executed.marker"
        source = self.root / "evil.py"
        source.write_text("Path('executed.marker').write_text('ran')\n", encoding="utf-8")
        inventory = self.write_inventory([self.stage(kind="legacy", entrypoints=["evil.py"])])
        report, code = self.run_audit(inventory)
        self.assertEqual(code, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(report["stages"][0]["status"], "ok")

    def test_changed_input_is_an_integrity_failure(self) -> None:
        source = self.root / "source.py"
        source.write_text("first", encoding="utf-8")
        inventory = self.write_inventory([self.stage(entrypoints=["source.py"])])
        original = audit_tool._stage_report

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            source.write_text("changed", encoding="utf-8")
            return result

        with mock.patch.object(audit_tool, "_stage_report", side_effect=mutate):
            report, code = self.run_audit(inventory)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("INPUT_CHANGED_DURING_INSPECTION", {item["code"] for item in report["findings"]})


if __name__ == "__main__":
    unittest.main()
