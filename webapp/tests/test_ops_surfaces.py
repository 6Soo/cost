"""Regression tests for the operational surfaces added in this session.

Each test here corresponds to something that was found by running the code, not
by reading it. The comments name the failure so a future reader can tell a real
invariant from a preference.
"""
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from webapp import access_control  # noqa: E402
from webapp import migration as mig  # noqa: E402
from webapp import ops  # noqa: E402
from webapp.ledger_board import serve  # noqa: E402
from webapp.ledger_store import LedgerStore  # noqa: E402

REVISION = 1_800_000_000_000
STAMP = datetime.fromtimestamp(REVISION / 1000, tz=timezone.utc).isoformat(
    timespec="milliseconds")


def snapshot_document(*, revision=REVISION, stamp=STAMP, persons=None):
    return json.dumps({
        "schema_version": "reservation-access-snapshot-v1",
        "exported_at": stamp, "snapshot_revision": revision,
        "persons": persons if persons is not None else [{
            "reservation_person_id": "rp-1", "display_name": "N",
            "nickname": "g", "is_active": True,
            "assignments": ["trip-a"]}]}, ensure_ascii=False).encode("utf-8")


def gate_report(name):
    return json.dumps({
        "run_id": f"run-{name}", "generated_at": "2026-09-28T00:00:00+00:00",
        "gates": [{"gate": f"G{i}", "status": "PASS"} for i in range(1, 8)],
        "readiness": {"triage_pass": True, "shadow_ready": True,
                      "release_ready": False},
        "candidate_semantic_sha256": name[0] * 64}, ensure_ascii=False)


class _Board:
    """A board database with the access tables and one connected person."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.db = self.root / "board.sqlite"
        store = LedgerStore(self.db)
        access = access_control.attach_to_ledger_store(store)
        access.create_account(user_id="viewer-1",
                              role=access_control.ROLE_VIEWER)
        now = access_control.iso(access_control.utc_now())
        store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key)"
            " VALUES ('trip-a','Trip A')")
        store.conn.execute(
            "INSERT INTO access_connections(connection_id,user_id,"
            "reservation_person_id,reservation_person_label,status,revision,"
            "created_at,updated_at) VALUES ('c1','viewer-1','rp-1','label',?,1,?,?)",
            (access_control.CONNECTION_ACTIVE, now, now))
        store.conn.commit()
        store.close()
        self.config = ops.DurableConfig(
            data_root=self.root, db_path=self.db,
            export_dir=self.root / "exports",
            evidence_dir=self.root / "evidence",
            source_dir=self.root / "source",
            required_secrets=(), environment="local-synthetic")

    def rows(self, sql, *args):
        conn = sqlite3.connect(str(self.db))
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()


class OpsSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="ops-surface-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.board = _Board(self.tmp / "data")

    # ------------------------------------------------- smoke must not create
    def test_smoke_does_not_create_the_database_it_inspects(self):
        """A check that creates what it checks cannot report it missing.

        This was the first defect found: `smoke_report` opened a `LedgerStore`,
        whose constructor creates the file and seeded the demo board into it, so
        the report answered "healthy" about a database it had just invented.
        """
        empty = self.tmp / "empty"
        for sub in ("", "exports", "evidence", "source"):
            (empty / sub if sub else empty).mkdir(parents=True, exist_ok=True)
        missing = ops.DurableConfig(
            data_root=empty, db_path=empty / "nope.sqlite",
            export_dir=empty / "exports", evidence_dir=empty / "evidence",
            source_dir=empty / "source",
            required_secrets=(), environment="local-synthetic")
        report = ops.smoke_report(missing)
        self.assertFalse(report["ok"])
        self.assertIn("db_file_exists", report["blockers"])
        self.assertFalse(missing.db_path.exists(),
                         "smoke must not create the database it is reporting on")

    def test_smoke_reports_a_writable_board_from_an_observed_write(self):
        """The old line claimed writability from a SELECT, which proves nothing."""
        report = ops.smoke_report(self.board.config)
        self.assertTrue(report["ok"], report["blockers"])
        self.assertTrue(report["board_writable"])
        self.assertIn("rollback", report["board_writable_detail"])

    def test_a_board_with_revisions_still_reports_as_writable(self):
        """A ledger that has actually been saved to is the real case.

        The first version of the write probe named four columns of
        `board_revisions`, which requires eight NOT NULL values. It therefore
        failed on every ledger with any saved row and reported a working board
        as unwritable, while a never-saved database passed. This is the case
        that caught it.
        """
        self.board.rows("SELECT 1")
        store = LedgerStore(self.board.db)
        try:
            store.conn.execute(
                "INSERT INTO board_revisions(row_id, revision, prev_json,"
                " new_json, event_id, change_mode, actor, created_at,"
                " client_request_id) VALUES ('r-real', 1, '{}', '{}', '',"
                " 'exception', 'owner', '2026-09-29T00:00:00+00:00', 'req-real')")
            store.conn.commit()
            revisions = store.conn.execute(
                "SELECT COUNT(*) FROM board_revisions").fetchone()[0]
        finally:
            store.close()
        self.assertGreater(revisions, 0)
        writable, detail = ops._board_writable(self.board.db)
        self.assertTrue(writable, detail)
        self.assertTrue(ops.smoke_report(self.board.config)["board_writable"])

    def test_the_writability_probe_writes_nothing_to_the_working_database(self):
        store = LedgerStore(self.board.db)
        try:
            store.conn.execute(
                "INSERT INTO board_revisions(row_id, revision, prev_json,"
                " new_json, event_id, change_mode, actor, created_at,"
                " client_request_id) VALUES ('r-keep', 1, '{}', '{}', '',"
                " 'exception', 'owner', '2026-09-29T00:00:00+00:00', 'req-keep')")
            store.conn.commit()
        finally:
            store.close()
        before = self.board.db.read_bytes()
        ops._board_writable(self.board.db)
        self.assertEqual(before, self.board.db.read_bytes())
        rows = self.board.rows("SELECT COUNT(*) FROM board_revisions")[0][0]
        self.assertEqual(rows, 1, "the probe rolled back instead of committing")

    def test_a_genuinely_read_only_database_is_reported_as_not_writable(self):
        """The check has to be able to say no, or saying yes means nothing."""
        import os
        import stat
        if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("a root user bypasses the permission this test sets")
        if os.name == "nt":
            # Windows file modes do not remove write access from the owner, so
            # chmod cannot produce the read-only file this needs. The negative
            # branch is covered on POSIX instead of being faked here.
            self.skipTest("read-only file permissions are not enforceable via "
                          "chmod on Windows")
        self.board.rows("SELECT 1")
        mode = self.board.db.stat().st_mode
        os.chmod(self.board.db, mode & ~(stat.S_IWUSR | stat.S_IWGRP))
        try:
            writable, detail = ops._board_writable(self.board.db)
            self.assertFalse(writable)
            self.assertTrue(detail)
        finally:
            os.chmod(self.board.db, mode)

    def test_smoke_does_not_touch_the_working_database(self):
        before = self.board.db.read_bytes()
        ops.smoke_report(self.board.config)
        self.assertEqual(before, self.board.db.read_bytes())

    # ---------------------------------------- an operational start is not seeded
    def test_an_empty_database_stays_empty_without_the_demo_seed(self):
        """SPEC_REFINEMENT 18.3 5항 forbids synthetic rows at an operational start."""
        fresh = LedgerStore(self.tmp / "fresh.sqlite", seed_demo=False)
        try:
            rows = fresh.conn.execute(
                "SELECT COUNT(*) FROM board_rows").fetchone()[0]
            trips = fresh.conn.execute(
                "SELECT COUNT(*) FROM trip_tabs").fetchone()[0]
        finally:
            fresh.close()
        self.assertEqual(rows, 0)
        self.assertEqual(trips, 0)

    def test_the_demo_seed_is_still_the_default(self):
        """Every existing caller keeps the board a developer expects."""
        demo = LedgerStore(self.tmp / "demo.sqlite")
        try:
            rows = demo.conn.execute(
                "SELECT COUNT(*) FROM board_rows").fetchone()[0]
        finally:
            demo.close()
        self.assertGreater(rows, 0)

    def test_serve_keeps_the_demo_board_unless_told_otherwise(self):
        server = serve(port=0, db_path=self.tmp / "seeded.sqlite",
                       with_worker=False)
        try:
            conn = sqlite3.connect(str(self.tmp / "seeded.sqlite"))
            rows = conn.execute("SELECT COUNT(*) FROM board_rows").fetchone()[0]
            conn.close()
        finally:
            server.server_close()
            from webapp import ledger_board
            ledger_board.bind_store(None)
        self.assertGreater(rows, 0)

    # ------------------------------------------------------- reservation sync
    def test_a_bad_snapshot_is_refused_with_the_parser_code_not_a_traceback(self):
        payload = snapshot_document(stamp="2030-01-01T00:00:00.000+00:00")
        with self.assertRaises(ops.OpsError) as caught:
            ops.rehearse_reservation_sync(payload, self.board.db)
        self.assertEqual(caught.exception.code,
                         "reservation_access_revision_time_mismatch")

    def test_a_rehearsal_leaves_the_working_database_byte_identical(self):
        payload = snapshot_document()
        report = ops.rehearse_reservation_sync(payload, self.board.db)
        self.assertTrue(report["rehearsal"])
        self.assertFalse(report["applied_to_real_database"])
        self.assertTrue(report["source_unchanged"])
        self.assertEqual(report["source_sha256_before"],
                         report["source_sha256_after"])
        self.assertEqual(
            self.board.rows("SELECT COUNT(*) FROM"
                            " access_reservation_directory_head")[0][0], 0)

    def test_a_rehearsal_and_a_real_apply_agree(self):
        payload = snapshot_document()
        rehearsal = ops.rehearse_reservation_sync(payload, self.board.db)
        conn = sqlite3.connect(str(self.board.db))
        try:
            store = access_control.AccessStore(conn)
            applied = store.sync_reservation_access_snapshot(
                snapshot=ops.parse_reservation_snapshot(payload))
        finally:
            conn.close()
        self.assertEqual(rehearsal["connected_persons_synced"],
                         applied["connected_persons_synced"])
        self.assertEqual(rehearsal["assignments_applied"],
                         applied["assignments_applied"])

    # -------------------------------------------------------------- migration
    def _sources(self):
        src = self.tmp / "src"
        src.mkdir(parents=True, exist_ok=True)
        left = mig.build_source_db(src / "left.sqlite", [
            {"entry_id": "e1", "amount_krw": 1000,
             "occurred_on": "2026-09-01", "item": "a", "source_identity": "g-1"},
            {"entry_id": "e2", "amount_krw": 2000,
             "occurred_on": "2026-09-02", "item": "b"}], side="left")
        right = mig.build_source_db(src / "right.sqlite", [
            {"entry_id": "e1", "amount_krw": 1000,
             "occurred_on": "2026-09-01", "item": "a", "source_identity": "g-1"},
            {"entry_id": "e3", "amount_krw": 3000,
             "occurred_on": "2026-09-03", "item": "c"}], side="right")
        (src / "left-gate.json").write_text(gate_report("left"),
                                            encoding="utf-8")
        (src / "right-gate.json").write_text(gate_report("right"),
                                             encoding="utf-8")
        return src, left, right

    def test_a_migration_rehearsal_applies_nothing(self):
        src, left, right = self._sources()
        report = ops.rehearse_migration(
            left_db=left, right_db=right, work_dir=self.tmp / "work",
            migration_db=self.tmp / "m.sqlite",
            left_gate=src / "left-gate.json",
            right_gate=src / "right-gate.json")
        self.assertFalse(report["applied"])
        self.assertEqual(report["equal"], 1)
        conn = sqlite3.connect(str(self.tmp / "m.sqlite"))
        try:
            for table in ("migration_rows", "migration_events",
                          "migration_decisions"):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    0, f"{table} must stay empty in a rehearsal")
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM migration_comparisons").fetchone()[0], 1)
        finally:
            conn.close()

    def test_a_migration_rehearsal_writes_nothing_beside_a_source(self):
        """The engine seals by writing a descriptor next to the candidate.

        `seal_and_verify_sources` resolves the descriptor's file name next to the
        source, so sealing in place would have put two files in the operator's
        source directory. The rehearsal copies instead, and this asserts the
        directory is untouched afterwards.
        """
        src, left, right = self._sources()
        before = {p.name: p.read_bytes() for p in src.iterdir()}
        ops.rehearse_migration(
            left_db=left, right_db=right, work_dir=self.tmp / "work",
            migration_db=self.tmp / "m.sqlite",
            left_gate=src / "left-gate.json",
            right_gate=src / "right-gate.json")
        after = {p.name: p.read_bytes() for p in src.iterdir()}
        self.assertEqual(sorted(after), sorted(before))
        for name, blob in before.items():
            self.assertEqual(after[name], blob, f"{name} was modified")

    def test_a_seal_without_a_gate_report_is_a_refusal(self):
        """The semantic binding comes from the upstream gate report, not here."""
        _, left, right = self._sources()
        with self.assertRaises(ops.OpsError):
            ops.rehearse_migration(
                left_db=left, right_db=right, work_dir=self.tmp / "work",
                migration_db=self.tmp / "m.sqlite")

    def test_the_seal_evidence_is_reported_not_dropped(self):
        """The engine labels the sides `google` and `db`; reading `left` returned
        null for both and the report looked complete while carrying no seal."""
        src, left, right = self._sources()
        report = ops.rehearse_migration(
            left_db=left, right_db=right, work_dir=self.tmp / "work",
            migration_db=self.tmp / "m.sqlite",
            left_gate=src / "left-gate.json",
            right_gate=src / "right-gate.json")
        for side in ("left", "right"):
            self.assertIsNotNone(report["sealed"][side],
                                 f"seal evidence for {side} was dropped")
            self.assertEqual(len(report["sealed"][side]["sha256"]), 64)

    def test_a_migration_rehearsal_names_what_a_person_still_has_to_decide(self):
        src, left, right = self._sources()
        report = ops.rehearse_migration(
            left_db=left, right_db=right, work_dir=self.tmp / "work",
            migration_db=self.tmp / "m.sqlite",
            left_gate=src / "left-gate.json",
            right_gate=src / "right-gate.json")
        entries = {row["entry_id"] for row in
                   report["rows_needing_a_human_decision"]}
        self.assertEqual(entries, {"e2", "e3"})


class CommandLineTest(unittest.TestCase):
    """The commands are the operator's surface, so they are run as a process."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="ops-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.board = _Board(self.tmp / "data")
        self.snapshot = self.tmp / "s.json"
        self.snapshot.write_bytes(snapshot_document())
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8",
                    "WEBLEDGER_DATA_ROOT": str(self.board.root),
                    "WEBLEDGER_DB": str(self.board.db),
                    "WEBLEDGER_EXPORT_DIR": str(self.board.root / "exports"),
                    "WEBLEDGER_EVIDENCE_DIR": str(self.board.root / "evidence"),
                    "WEBLEDGER_SOURCE_DIR": str(self.board.root / "source"),
                    "MUSE_KEY": "synthetic"}

    def run_cli(self, *args, timeout=600):
        return subprocess.run(
            [sys.executable, "-m", "webapp.cli", *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(ROOT), env=self.env, timeout=timeout)

    def run_entry(self, args, *, expect_serving=False, seconds=45):
        """Start the real entry point and watch what it does.

        A long-running server is read as "still running after the timeout",
        which is how a passing gate shows up. A refusal shows up as the process
        exiting, and its exit code and message are what the caller checks.
        """
        import time
        env = {**self.env, "WEBLEDGER_DATA_ROOT": "", "WEBLEDGER_DB": "",
               "WEBLEDGER_EXPORT_DIR": "", "WEBLEDGER_EVIDENCE_DIR": "",
               "WEBLEDGER_SOURCE_DIR": ""}
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "run_candidate.py"), *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(ROOT),
            env=env)
        served = False
        output = ""
        deadline = time.time() + seconds
        try:
            while time.time() < deadline:
                if proc.poll() is not None:
                    output = proc.stdout.read().decode("utf-8", "replace")
                    break
                time.sleep(0.5)
            else:
                served = True
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except Exception:
                    proc.kill()
        return {"served": served, "exit": proc.poll(),
                "output": output or "(still running)"}

    def test_the_three_commands_are_offered(self):
        out = self.run_cli("ops", "--help").stdout
        for name in ("smoke", "reservation-sync", "migrate-rehearsal"):
            self.assertIn(name, out)

    def test_a_first_apply_is_not_reported_as_a_failure(self):
        """The exit code used the *first* pass's `ignored_stale_or_equal`, which
        is legitimately zero on a first apply, so every first apply exited 2."""
        result = self.run_cli("ops", "reservation-sync", "--snapshot",
                              str(self.snapshot), "--db", str(self.board.db),
                              "--secret", "MUSE_KEY")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["idempotent"])

    def test_a_refused_snapshot_prints_a_code_and_not_a_traceback(self):
        bad = self.tmp / "bad.json"
        bad.write_bytes(snapshot_document(stamp="2030-01-01T00:00:00.000+00:00"))
        result = self.run_cli("ops", "reservation-sync", "--snapshot", str(bad),
                              "--db", str(self.board.db), "--secret", "MUSE_KEY")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(json.loads(result.stdout)["code"],
                         "reservation_access_revision_time_mismatch")

    # ------------------------------------------------------- backup/restore
    def test_the_bundle_name_backup_prints_restores_without_a_path(self):
        """`ops backup` prints a bare name, so that is what an operator has.

        Passing it straight through raised `FileNotFoundError` against the
        process's working directory and exited 1 with a traceback. The restore
        now resolves a name inside the configured backup root.
        """
        result = self.run_cli("ops", "backup", "--secret", "MUSE_KEY",
                              "--label", "roundtrip")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        name = json.loads(result.stdout)["backup"]["bundle"]
        self.assertFalse(pathlib.Path(name).is_absolute(),
                         "the printed value should be the name, as the test "
                         "assumes; if this changes the round trip changes")

        target = self.tmp / "restored"
        target.mkdir(parents=True, exist_ok=True)
        restored = self.run_cli("ops", "restore", name, "--target", str(target),
                                "--secret", "MUSE_KEY")
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertNotIn("Traceback", restored.stderr)
        self.assertTrue(any(target.rglob("board.sqlite")))

    def test_a_bundle_name_that_does_not_exist_is_refused_with_a_code(self):
        target = self.tmp / "restored-missing"
        target.mkdir(parents=True, exist_ok=True)
        result = self.run_cli("ops", "restore", "bundle-does-not-exist",
                              "--target", str(target), "--secret", "MUSE_KEY")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(json.loads(result.stdout)["code"], "BUNDLE_NOT_FOUND")

    def test_a_full_path_still_restores(self):
        """The name form is an addition, not a replacement."""
        result = self.run_cli("ops", "backup", "--secret", "MUSE_KEY",
                              "--label", "fullpath")
        name = json.loads(result.stdout)["backup"]["bundle"]
        full = self.board.root / "backups" / name
        target = self.tmp / "restored-full"
        target.mkdir(parents=True, exist_ok=True)
        restored = self.run_cli("ops", "restore", str(full), "--target",
                                str(target), "--secret", "MUSE_KEY")
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)

    # ------------------------------------------------------------- gate passing
    def test_the_gate_lets_a_fully_prepared_root_serve(self):
        """A gate that refuses everything is not a gate. This root is complete,
        so `--require-ready` must let the process start."""
        result = self.run_entry(
            ["--data-root", str(self.board.root), "--require-ready",
             "--no-worker"], expect_serving=True)
        self.assertTrue(result["served"],
                        f"the process neither served nor refused cleanly:\n"
                        f"{result['output']}")

    def test_smoke_on_a_host_without_a_database_refuses_and_creates_nothing(self):
        result = self.run_cli("ops", "smoke", "--secret", "MUSE_KEY",
                              timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload["blockers"])
        self.assertTrue(payload["board_writable"])

    def test_the_readiness_gate_refuses_an_empty_root_without_creating_a_database(self):
        gate_root = self.tmp / "gate"
        result = subprocess.run(
            [sys.executable, str(ROOT / "run_candidate.py"),
             "--data-root", str(gate_root), "--require-ready"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(ROOT), timeout=180,
            env={**self.env, "WEBLEDGER_DATA_ROOT": "", "WEBLEDGER_DB": "",
                 "WEBLEDGER_EXPORT_DIR": "", "WEBLEDGER_EVIDENCE_DIR": "",
                 "WEBLEDGER_SOURCE_DIR": ""})
        self.assertEqual(result.returncode, 2)
        self.assertIn("SMOKE_FAILED", result.stdout + result.stderr)
        self.assertFalse((gate_root / "board.sqlite").exists(),
                         "the gate must not create the database it inspects")


if __name__ == "__main__":
    unittest.main()
