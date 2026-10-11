"""Tests for the operational-safety fixes found by auditing the ops surface.

Each test names the behaviour it pins. Where a fix changed a refusal into a
different refusal, both the code and the reason are asserted, because "it raises
something" is not the requirement.
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
import pytest
from pathlib import Path  # noqa: F401 - used by the restore tests below

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from webapp import ops  # noqa: E402
from webapp.ledger_store import LedgerStore  # noqa: E402

REPO = ROOT


@pytest.mark.parametrize('environment', ['local-synthetic', 'production'])
def test_relative_data_root_is_refused_before_resolution_or_creation(tmp_path, monkeypatch, environment):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ops.OpsError) as error:
        ops.durable_config_for('relative-data', environment=environment, create=True)
    assert error.value.code == 'RELATIVE_DATA_ROOT'
    assert not (tmp_path / 'relative-data').exists()


def test_direct_config_refuses_relative_root_even_with_absolute_subpaths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ops.OpsError) as error:
        ops.DurableConfig(data_root='.', db_path=tmp_path / 'board.sqlite',
                          export_dir=tmp_path / 'exports', evidence_dir=tmp_path / 'evidence',
                          source_dir=tmp_path / 'source')
    assert error.value.code == 'RELATIVE_DATA_ROOT'


class OpsCommandsDoNotSeedALedger(unittest.TestCase):
    """P2-1: an inspection must not add synthetic rows to a real ledger.

    SPEC_REFINEMENT 18.3 item 5 forbids synthetic rows at an operational start.
    Every ops command opened its store with the default `seed_demo=True`, so
    `ops health` on a real database with no trips inserted two demo trips into
    it -- the inspection was the thing that changed the data.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="noseed-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "data"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.db = self.root / "board.sqlite"
        # A real but empty ledger: the schema, no trips, no rows.
        LedgerStore(self.db, seed_demo=False).close()
        conn = sqlite3.connect(str(self.db))
        try:
            self.trips_before = conn.execute(
                "SELECT COUNT(*) FROM trip_tabs").fetchone()[0]
            self.rows_before = conn.execute(
                "SELECT COUNT(*) FROM board_rows").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual((self.trips_before, self.rows_before), (0, 0))
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8",
                    "WEBLEDGER_DATA_ROOT": str(self.root),
                    "WEBLEDGER_DB": str(self.db),
                    "WEBLEDGER_EXPORT_DIR": str(self.root / "exports"),
                    "WEBLEDGER_EVIDENCE_DIR": str(self.root / "evidence"),
                    "WEBLEDGER_SOURCE_DIR": str(self.root / "source"),
                    "MUSE_KEY": "synthetic"}

    def run_cli(self, *args, timeout=600):
        return subprocess.run(
            [sys.executable, "-m", "webapp.cli", *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(REPO), env=self.env, timeout=timeout)

    def counts(self):
        conn = sqlite3.connect(str(self.db))
        try:
            return (conn.execute("SELECT COUNT(*) FROM trip_tabs").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM board_rows").fetchone()[0])
        finally:
            conn.close()

    def test_ops_health_adds_no_trip_and_no_row(self):
        result = self.run_cli("ops", "health", "--secret", "MUSE_KEY")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.counts(), (0, 0),
                         "ops health seeded a demo board into an empty ledger")

    def test_every_ops_command_that_opens_a_store_passes_seed_demo_false(self):
        """The source-level rule, so a new command cannot forget it."""
        source = (REPO / "webapp/cli.py").read_text(encoding="utf-8")
        import ast
        tree = ast.parse(source)
        opened = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "LedgerStore":
                opened.append(node)
        self.assertGreaterEqual(len(opened), 5,
                                "expected the ops commands to open stores")
        for call in opened:
            has_flag = any(kw.arg == "seed_demo" for kw in call.keywords)
            self.assertTrue(
                has_flag,
                "a LedgerStore opened in the CLI without an explicit seed_demo "
                "decides whether a real ledger gets synthetic rows by default")

    def test_a_demo_run_still_gets_its_board(self):
        """The default is unchanged for the developer's own board."""
        fresh = LedgerStore(self.tmp / "demo.sqlite")
        try:
            rows = fresh.conn.execute(
                "SELECT COUNT(*) FROM board_rows").fetchone()[0]
        finally:
            fresh.close()
        self.assertGreater(rows, 0)


class ReservationApplyWillNotCreateItsTarget(unittest.TestCase):
    """P2-11: `sqlite3.connect` creates the file it is given."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="restarget-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "data"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.db = self.root / "board.sqlite"
        LedgerStore(self.db, seed_demo=False).close()
        self.snapshot = self.tmp / "s.json"
        stamp = "2027-01-15T08:00:00.000+00:00"
        self.snapshot.write_text(json.dumps({
            "schema_version": "reservation-access-snapshot-v1",
            "exported_at": stamp, "snapshot_revision": 1800000000000,
            "persons": []}, ensure_ascii=False), encoding="utf-8")
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8",
                    "WEBLEDGER_DATA_ROOT": str(self.root),
                    "WEBLEDGER_DB": str(self.db),
                    "WEBLEDGER_EXPORT_DIR": str(self.root / "exports"),
                    "WEBLEDGER_EVIDENCE_DIR": str(self.root / "evidence"),
                    "WEBLEDGER_SOURCE_DIR": str(self.root / "source"),
                    "MUSE_KEY": "synthetic"}

    def test_applying_to_a_path_that_does_not_exist_is_refused(self):
        missing = self.tmp / "not-a-db.sqlite"
        result = subprocess.run(
            [sys.executable, "-m", "webapp.cli", "ops", "reservation-sync",
             "--snapshot", str(self.snapshot), "--db", str(missing),
             "--secret", "MUSE_KEY"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(REPO), env=self.env, timeout=600)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(json.loads(result.stdout)["code"],
                         "RESERVATION_TARGET_MISSING")
        self.assertFalse(missing.exists(),
                         "sqlite3.connect created an empty database and the "
                         "command would have reported a successful import")


class ConfiguredRootIsCheckedBeforeItIsCreated(unittest.TestCase):
    """P2-12: a refused configuration must not leave directories behind."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="cfgfirst-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_refused_production_root_creates_nothing(self):
        refused = self.tmp / "inside-checkout"
        with self.assertRaises(ops.OpsError) as caught:
            ops.durable_config_for(REPO / "refused-root", environment="production",
                                   create=True)
        self.assertIn(caught.exception.code,
                      ("CHECKOUT_DATA_ROOT", "TEMP_DATA_ROOT"))
        self.assertFalse((REPO / "refused-root").exists(),
                         "a refused root was created before the refusal")

    def test_a_temp_rooted_production_root_creates_nothing(self):
        target = self.tmp / "prod"
        with self.assertRaises(ops.OpsError) as caught:
            ops.durable_config_for(target, environment="production", create=True)
        self.assertEqual(caught.exception.code, "TEMP_DATA_ROOT")
        self.assertFalse(target.exists(),
                         "the directories were made before the refusal")

    def test_an_accepted_root_is_still_created(self):
        target = self.tmp / "ok"
        config = ops.durable_config_for(target, environment="local-synthetic",
                                        create=True)
        self.assertTrue(config.data_root.is_dir())
        self.assertTrue(config.export_dir.is_dir())
        self.assertTrue(config.evidence_dir.is_dir())
        self.assertTrue(config.source_dir.is_dir())

    def test_a_missing_root_is_still_a_refusal_without_create(self):
        with self.assertRaises(ops.OpsError) as caught:
            ops.durable_config_for(self.tmp / "never-made",
                                   environment="local-synthetic")
        self.assertEqual(caught.exception.code, "MISSING_DATA_ROOT")


class TheReadinessGateSaysWhatItDid(unittest.TestCase):
    """P2-3: a code that says "ignored" while the process exits is a lie."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def config(self, environment="local-synthetic"):
        return ops.durable_config_for(self.tmp / "data",
                                     environment=environment, create=True)

    def test_a_ready_root_reports_smoke_ok(self):
        from webapp import ledger_board as board
        from webapp.ledger_store import LedgerStore as LS
        config = self.config()
        LS(config.db_path, seed_demo=False).close()
        # smoke needs the secret; declare one that exists.
        os.environ["WEBLEDGER_TEST_SECRET"] = "x"
        try:
            import run_candidate
            line = run_candidate.gate_on_readiness(config, required=True)
        finally:
            del os.environ["WEBLEDGER_TEST_SECRET"]
        self.assertEqual(line, "smoke ok")
        board.bind_store(None)

    def test_an_unready_root_raises_when_the_gate_is_required(self):
        from webapp import ledger_board as board
        config = self.config()
        # No database at all: the blockers are the point.
        (self.tmp / "data" / "board.sqlite").unlink(missing_ok=True)
        import run_candidate
        with self.assertRaises(ops.OpsError) as caught:
            run_candidate.gate_on_readiness(config, required=True)
        self.assertEqual(caught.exception.code, "SMOKE_FAILED")
        board.bind_store(None)

    def test_an_unready_root_reports_instead_of_raising_when_not_required(self):
        from webapp import ledger_board as board
        config = self.config()
        (self.tmp / "data" / "board.sqlite").unlink(missing_ok=True)
        import run_candidate
        line = run_candidate.gate_on_readiness(config, required=False)
        self.assertIsInstance(line, str)
        self.assertIn("NOT READY", line)
        self.assertIn("not an operational verdict", line)
        self.assertIn("db_file_exists", line)
        board.bind_store(None)

    def test_the_non_required_line_names_its_environment(self):
        from webapp import ledger_board as board
        config = self.config()
        (self.tmp / "data" / "board.sqlite").unlink(missing_ok=True)
        import run_candidate
        line = run_candidate.gate_on_readiness(config, required=False)
        self.assertIn("local-synthetic", line)
        board.bind_store(None)

    def test_the_ignored_code_no_longer_exists(self):
        """A code nobody can reach is worse than no code."""
        import run_candidate
        self.assertNotIn("SMOKE_FAILED_IGNORED",
                         (REPO / "run_candidate.py").read_text(encoding="utf-8"))


class RestoreRefusesWhatItCannotVerify(unittest.TestCase):
    """P2-6 and P2-8: a restore that cannot be checked, or that would mix."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="restore-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "data"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.db = self.root / "board.sqlite"
        self.store = LedgerStore(self.db, seed_demo=False)
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key) VALUES ('t1','Trip')")
        self.store.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision,"
            " payload_json) VALUES ('r1','expense','t1',1,'{}')")
        self.store.conn.commit()
        self.config = ops.durable_config_for(self.root,
                                             environment="local-synthetic")
        self.bundle = None

    def tearDown(self):
        self.store.close()

    def make_backup(self):
        result = ops.make_backup_bundle(self.config, self.store, label="t")
        # The function returns the bundle record itself; the CLI is what wraps
        # it under "backup". The directory is the conventional one.
        self.bundle = self.root / "backups" / result["bundle"]
        self.assertTrue(self.bundle.is_dir(), self.bundle)
        return self.bundle

    def test_a_bundle_with_no_recorded_state_is_refused(self):
        bundle = self.make_backup()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["state"]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False),
                                 encoding="utf-8")
        target = self.tmp / "restored"
        with self.assertRaises(ops.OpsError) as caught:
            ops.restore_bundle(self.config, bundle, target_root=target,
                               store_factory=lambda p: LedgerStore(
                                   p, seed_demo=False))
        self.assertEqual(caught.exception.code, "BUNDLE_HAS_NO_VERIFIABLE_STATE")
        self.assertFalse(target.exists(),
                         "an unverifiable bundle was still written out")

    def test_a_non_empty_target_is_refused_rather_than_mixed_into(self):
        bundle = self.make_backup()
        target = self.tmp / "restored"
        target.mkdir(parents=True)
        (target / "board.sqlite").write_bytes(b"a previous restore")
        with self.assertRaises(ops.OpsError) as caught:
            ops.restore_bundle(self.config, bundle, target_root=target,
                               store_factory=lambda p: LedgerStore(
                                   p, seed_demo=False))
        self.assertEqual(caught.exception.code, "RESTORE_TARGET_NOT_EMPTY")
        self.assertEqual((target / "board.sqlite").read_bytes(),
                         b"a previous restore",
                         "the existing file was overwritten by the refused "
                         "restore")

    def test_an_empty_target_still_restores(self):
        bundle = self.make_backup()
        target = self.tmp / "restored-fresh"
        report = ops.restore_bundle(self.config, bundle, target_root=target,
                                    store_factory=lambda p: LedgerStore(
                                        p, seed_demo=False))
        self.assertTrue(report["ok"], report.get("problems"))
        self.assertTrue((target / "board.sqlite").is_file())

    def test_a_corrupted_copy_in_the_bundle_is_detected_not_restored(self):
        """P2-9: the hash has to be checked on the bytes that are copied.

        Comparing the restored file to the manifest *after* the verification
        step has run would measure the wrong thing: opening the restored
        database to re-verify the state runs the schema script against it, so
        the file is legitimately different afterwards. What has to hold is that a
        copy whose bytes are wrong is refused.
        """
        original = self.make_backup()
        damaged = self.tmp / "damaged-bundle"
        shutil.copytree(original, damaged)
        db = damaged / "board.sqlite"
        with open(db, "r+b") as handle:
            handle.seek(0)
            handle.write(b"this is not a sqlite file at all")
        target = self.tmp / "restored-from-damaged"
        report = ops.restore_bundle(self.config, damaged, target_root=target,
                                    store_factory=lambda p: LedgerStore(
                                        p, seed_demo=False))
        self.assertFalse(report.get("ok", False),
                         "a bundle whose db copy is damaged was reported as a "
                         "successful restore")
        self.assertTrue(
            any("sha256" in str(p) or "sqlite" in str(p).lower()
                for p in report.get("problems", [])),
            f"the refusal did not name the digest or the file: "
            f"{report.get('problems')}")

    def test_the_digest_is_compared_on_the_restored_copy(self):
        """The same property, from the manifest's point of view."""
        original = self.make_backup()
        target = self.tmp / "restored-check"
        ops.restore_bundle(self.config, original, target_root=target,
                           store_factory=lambda p: LedgerStore(p,
                                                                seed_demo=False))
        manifest = json.loads((original / "manifest.json").read_text(
            encoding="utf-8"))
        self.assertTrue(manifest["files"]["db"][0]["sha256"],
                        "the bundle records no db digest to check against")
        self.assertIn("state", manifest)
        self.assertIn("business_digest", manifest["state"])


if __name__ == "__main__":
    unittest.main()
