"""Regressions for the five operational-readiness defects this audit closed.

Each test states the specification clause it defends and the behaviour that was
actually observed before the fix. The synthetic paths are temporary; there is no
hosting resource, no OAuth client, no reservation API and no production DB here.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from webapp import access_control
from webapp import ops
from webapp.ledger_store import LedgerStore


def store_factory(db_path):
    store = LedgerStore(Path(db_path))
    access_control.attach_to_ledger_store(store).ensure_schema()
    return store


def assert_every_figure_line_is_written(case, figures, text):
    """Each measured figure must appear on its own line, value and label.

    The expected lines are rebuilt here from the figures dict rather than taken
    from `ops.recovery_lines`, because comparing a function to itself would pass
    even when the function stops writing a figure. What this catches is a figure
    that is computed and then dropped, or replaced by a constant, before it
    reaches the document.
    """
    written = {line.strip() for line in text.splitlines() if line.strip()}
    rng = figures["max_input_range_at_risk"]
    seconds = figures["trial_restore_seconds"]
    shown = seconds if seconds is not None else "미측정"
    expected = [
        f"- 최대 잃을 수 있는 최근 입력 범위: {rng['note']}",
        f"  - 장부의 최신 입력: {figures['newest_input_in_store']}",
        f"  - 백업 기준 시점: {figures['bundle_created_at']}",
        f"  - 백업 시점 이후 입력 건수: {rng.get('inputs_after_backup')}",
        f"- 시험 복구에 걸린 시간: {shown} ({figures['trial_restore_note']})",
        f"- 저장 비용과 보관 기간: 묶음 {figures['bundle_count']}개, "
        f"합계 {figures['bytes_on_disk']} bytes, "
        f"개당 추정 {figures['bytes_per_bundle_estimate']} bytes, "
        f"보관 {figures['retention_keep']}개",
        f"  - 데이터 루트 남은 공간: "
        f"{figures['free_bytes_at_data_root']} bytes",
    ]
    for line in expected:
        case.assertIn(line.strip(), written,
                      f"computed but not written as stated: {line!r}")
    for promise in figures["promises_not_made"]:
        case.assertIn(f"- {promise}", written,
                      f"the promise is missing from the runbook: {promise!r}")
    case.assertIn(f"- {figures['rpo_note']}", written)
    case.assertIn(f"- {figures['rto_note']}", written)


class RestoreRefusesAnUnverifiableDatabase(unittest.TestCase):
    """A bundle whose manifest lost the db hash must not restore at all.

    Observed before the fix: `if expected and actual != expected` skipped the
    comparison when the manifest had no db entry, so a database that was not a
    database was copied into the restore target and the call then raised
    `sqlite3.DatabaseError` instead of reporting which bundle failed.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="restore-gate-"))
        self.root = self.tmp / "d"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.config = ops.DurableConfig(
            data_root=self.root, db_path=self.root / "board.sqlite",
            export_dir=self.root / "exports", evidence_dir=self.root / "evidence",
            source_dir=self.root / "source")
        self.store = store_factory(self.config.db_path)
        before = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=before["revision"],
                        client_request_id="rg-1", change_mode="exception",
                        changes={"operator_note": "게이트 확인"})

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _bundle(self, label):
        manifest = ops.make_backup_bundle(self.config, self.store, label=label)
        return manifest, self.config.data_root / "backups" / manifest["bundle"]

    def _strip_db_hash(self, bundle, new_name):
        target = bundle.parent / new_name
        shutil.copytree(bundle, target)
        manifest = json.loads((target / "manifest.json").read_text(
            encoding="utf-8"))
        manifest["files"].pop("db", None)
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        return target

    def test_a_manifest_without_a_db_hash_is_refused(self):
        _manifest, bundle = self._bundle("with-hash")
        stripped = self._strip_db_hash(bundle, "no-hash")
        result = ops.restore_bundle(self.config, stripped,
                                    target_root=self.tmp / "t1",
                                    store_factory=store_factory)
        self.assertFalse(result["ok"])
        self.assertFalse(result["restored"])
        self.assertTrue(any("no db sha256" in p for p in result["problems"]),
                        result["problems"])

    def test_a_corrupt_database_is_refused_without_raising(self):
        _manifest, bundle = self._bundle("corrupt")
        stripped = self._strip_db_hash(bundle, "corrupt-no-hash")
        (stripped / "board.sqlite").write_bytes(b"this is not a database")
        # The call must return a report. Raising here is the defect.
        result = ops.restore_bundle(self.config, stripped,
                                    target_root=self.tmp / "t2",
                                    store_factory=store_factory)
        self.assertFalse(result["ok"])
        self.assertFalse(result["restored"])
        self.assertTrue(result["problems"])

    def test_a_refused_restore_leaves_nothing_usable_in_the_target(self):
        _manifest, bundle = self._bundle("leftover")
        stripped = self._strip_db_hash(bundle, "leftover-no-hash")
        (stripped / "board.sqlite").write_bytes(b"not a database")
        target = self.tmp / "t3"
        target.mkdir(parents=True, exist_ok=True)
        result = ops.restore_bundle(self.config, stripped, target_root=target,
                                    store_factory=store_factory)
        self.assertFalse(result["ok"])
        # Nothing that looks like a usable restore may be left behind.
        self.assertEqual(list(target.glob("*.sqlite")), [])
        self.assertIsNone(result["restored_db"])

    def test_a_corrupt_database_with_a_matching_hash_still_cannot_restore(self):
        """The hash gate is not the only defence; the open must be verified."""
        _manifest, bundle = self._bundle("matching")
        # Rewrite both the file and the recorded hash so the comparison passes.
        (bundle / "board.sqlite").write_bytes(b"not a database either")
        from webapp.contracts import sha256_file

        manifest = json.loads((bundle / "manifest.json").read_text(
            encoding="utf-8"))
        manifest["files"]["db"][0]["sha256"] = sha256_file(
            bundle / "board.sqlite")
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        result = ops.restore_bundle(self.config, bundle,
                                    target_root=self.tmp / "t4",
                                    store_factory=store_factory)
        self.assertFalse(result["ok"])
        self.assertTrue(any("could not be opened" in p
                            for p in result["problems"]), result["problems"])
        # Nothing may be left that looks like a usable restore. A store that
        # fails to open keeps its SQLite connection unclosed, so on Windows the
        # file can stay locked; in that case the report must say the target is
        # not clean rather than pretend it is.
        leftovers = list((self.tmp / "t4").glob("*.sqlite"))
        if leftovers:
            self.assertTrue(
                any("not clean" in p for p in result["problems"]),
                f"left {leftovers} without reporting it: {result['problems']}")
        else:
            self.assertEqual(leftovers, [])

    def test_discard_reports_what_it_could_not_remove(self):
        target = self.tmp / "locked"
        target.mkdir(parents=True)
        (target / "a.txt").write_text("x", encoding="utf-8")
        (target / "b.txt").write_text("y", encoding="utf-8")
        self.assertEqual(ops._discard_restored(target), [])
        self.assertEqual(list(target.glob("*")), [])

    def test_discard_reports_a_locked_file_instead_of_swallowing_it(self):
        target = self.tmp / "busy"
        target.mkdir(parents=True)
        held = target / "held.bin"
        held.write_text("x", encoding="utf-8")
        handle = open(held, "rb")
        try:
            problems = ops._discard_restored(target)
        finally:
            handle.close()
        self.assertTrue(problems, "a file that stayed must be reported")
        self.assertTrue(any("not clean" in p for p in problems), problems)

    def test_a_good_bundle_still_restores(self):
        _manifest, bundle = self._bundle("good")
        result = ops.restore_bundle(self.config, bundle,
                                    target_root=self.tmp / "t5",
                                    store_factory=store_factory)
        self.assertTrue(result["ok"], result["problems"])
        self.assertTrue(Path(result["restored_db"]).is_file())


class RestoreComparesContentNotOnlyCounts(unittest.TestCase):
    """SPEC_REFINEMENT 17.3 item 2: equal totals must not pass a restore.

    Observed before the fix: `verify_restored_state` compared five row counts,
    so a database with the same number of rows but a different amount, a
    different trip assignment or a different rule version would have restored
    as OK. It now also compares a digest over the named business columns.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="digest-"))
        self.root = self.tmp / "d"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.config = ops.DurableConfig(
            data_root=self.root, db_path=self.root / "board.sqlite",
            export_dir=self.root / "exports", evidence_dir=self.root / "evidence",
            source_dir=self.root / "source")
        self.store = store_factory(self.config.db_path)
        before = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=before["revision"],
                        client_request_id="dg-1", change_mode="exception",
                        changes={"display_tab_id": "trip-demo-b"})
        self.manifest = ops.make_backup_bundle(self.config, self.store,
                                               label="dg")
        self.bundle = self.config.data_root / "backups" / self.manifest["bundle"]

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_manifest_records_a_content_digest(self):
        digest = self.manifest["state"]["business_digest"]
        self.assertTrue(digest)
        for table in ("board_rows", "board_revisions", "trip_tabs",
                      "board_requests"):
            self.assertIn(table, digest)
        # and the rule versions the clause names are covered
        self.assertIn("classification_rule_versions", digest)
        self.assertIn("classification_rules", digest)

    def test_a_matching_restore_reports_that_content_was_compared(self):
        result = ops.restore_bundle(self.config, self.bundle,
                                    target_root=self.tmp / "ok",
                                    store_factory=store_factory)
        self.assertTrue(result["ok"], result["problems"])
        self.assertTrue(result["state"]["content_compared"])
        self.assertEqual(result["state"]["business_digest"]["digest"],
                         self.manifest["state"]["business_digest"])

    def test_equal_counts_with_different_content_is_still_refused(self):
        """The case 17.3 2항 forbids: same row count, different business content."""
        target = self.tmp / "tampered"
        target.mkdir(parents=True, exist_ok=True)
        db = target / "board.sqlite"
        shutil.copy2(self.bundle / "board.sqlite", db)
        # Change the business content without changing any count: retarget the
        # trip on an existing row and rewrite the manifest to match the file.
        conn = __import__("sqlite3").connect(str(db))
        try:
            conn.execute("UPDATE board_rows SET display_tab_id='trip-demo-c'"
                         " WHERE row_id='expense-demo-c1'")
            conn.commit()
        finally:
            conn.close()
        from webapp.contracts import sha256_file

        manifest = json.loads((self.bundle / "manifest.json").read_text(
            encoding="utf-8"))
        manifest["files"]["db"][0]["sha256"] = sha256_file(db)
        shutil.copy2(self.bundle / "manifest.json", target / "manifest.json")
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        result = ops.restore_bundle(self.config, target,
                                    target_root=self.tmp / "out",
                                    store_factory=store_factory)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("business content differs" in p for p in result["problems"]),
            result["problems"])

    def test_the_digest_names_the_table_that_moved(self):
        first = ops.business_state_digest(self.store)
        self.store.conn.execute(
            "UPDATE trip_tabs SET display_key='바뀐 여행' "
            "WHERE tab_id='trip-demo-b'")
        self.store.conn.commit()
        second = ops.business_state_digest(self.store)
        self.assertNotEqual(first["digest_of"], second["digest_of"])
        self.assertNotEqual(first["digest"]["trip_tabs"],
                            second["digest"]["trip_tabs"])
        # a table that did not move keeps its digest
        self.assertEqual(first["digest"]["board_rows"],
                         second["digest"]["board_rows"])


class ReadinessReportsOnlyMeasuredNumbers(unittest.TestCase):
    """A readiness report must not state a number the run never observed.

    Observed before the fix: `waiting_turns` was assigned 0 inside a branch
    that did nothing, so the report always claimed zero waiting turns even when
    the measured value said otherwise.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="waiting-"))
        self.root = self.tmp / "d"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.config = ops.DurableConfig(
            data_root=self.root, db_path=self.root / "board.sqlite",
            export_dir=self.root / "exports", evidence_dir=self.root / "evidence",
            source_dir=self.root / "source")
        self.store = store_factory(self.config.db_path)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_reported_waiting_count_is_the_measured_one(self):
        report = ops.readiness_report(
            self.config, self.store,
            measurements={"provider_turns": {"attempted": 3, "waiting": 2,
                                             "completed": 1}})
        self.assertEqual(report["waiting_turns"], 2)
        self.assertTrue(report["waiting_turns_measured"])

    def test_without_a_measurement_the_answer_is_not_measured_not_zero(self):
        report = ops.readiness_report(self.config, self.store)
        self.assertIsNone(report["waiting_turns"])
        self.assertFalse(report["waiting_turns_measured"])

    def test_zero_waiting_is_reported_as_a_measured_zero(self):
        report = ops.readiness_report(
            self.config, self.store,
            measurements={"provider_turns": {"attempted": 1, "waiting": 0,
                                             "completed": 1}})
        self.assertEqual(report["waiting_turns"], 0)
        self.assertTrue(report["waiting_turns_measured"])

    def test_the_health_schema_list_names_only_tables_that_exist(self):
        tables = {r[0] for r in self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for name in ops.HEALTH_SCHEMA_TABLES:
            self.assertIn(name, tables)


class RecoveryRunbookCarriesTheSeventeentwoFigures(unittest.TestCase):
    """SPEC_REFINEMENT 17.2 names the figures an operator must be shown.

    Observed before the fix: the runbook listed only the manual steps and the
    external conditions. It carried no input range, no measured restore time,
    no storage figure and no refusal to promise lossless recovery.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="figures-"))
        self.root = self.tmp / "d"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.config = ops.DurableConfig(
            data_root=self.root, db_path=self.root / "board.sqlite",
            export_dir=self.root / "exports", evidence_dir=self.root / "evidence",
            source_dir=self.root / "source", keep_backups=7)
        self.store = store_factory(self.config.db_path)
        before = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=before["revision"],
                        client_request_id="fg-1", change_mode="exception",
                        changes={"operator_note": "수치 확인"})

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _runbook(self, figures):
        manifest = ops.build_deploy_manifest(self.config)
        dry = ops.dry_run_deploy(self.config, manifest)
        path = ops.write_deploy_runbook(self.tmp / "RUNBOOK.md", self.config,
                                        manifest, dry, figures=figures)
        return path.read_text(encoding="utf-8")

    def _assert_every_figure_line_is_written(self, figures, text):
        assert_every_figure_line_is_written(self, figures, text)

    def test_a_measured_drill_produces_every_figure(self):
        drill = ops.run_restore_drill(
            self.config, self.store, target_root=self.tmp / "drill",
            store_factory=store_factory)
        self.assertTrue(drill["recoverable"], drill["restore"]["problems"])
        figures = drill["figures"]
        self.assertIsNotNone(figures["newest_input_in_store"])
        self.assertTrue(figures["max_input_range_at_risk"]["measured"])
        self.assertIsInstance(figures["trial_restore_seconds"], float)
        self.assertGreaterEqual(figures["bundle_count"], 1)
        self.assertGreater(figures["bytes_on_disk"], 0)
        self.assertEqual(figures["retention_keep"], 7)

        self._assert_every_figure_line_is_written(
            figures, self._runbook(figures))

    def test_the_figures_say_when_nothing_was_measured(self):
        figures = ops.recovery_figures(self.config, self.store)
        self.assertIsNone(figures["trial_restore_seconds"])
        text = self._runbook(figures)
        self._assert_every_figure_line_is_written(figures, text)
        # an unmeasured figure is shown as unmeasured, never as a number
        self.assertIn("미측정", text)
        self.assertTrue(figures["promises_not_made"])

    def test_an_unmeasured_input_range_says_so_instead_of_guessing(self):
        rng = ops._input_range(None, None)
        self.assertFalse(rng["measured"])
        self.assertIn("못 정해", rng["note"])

    def test_input_after_the_backup_is_called_out(self):
        rng = ops._input_range("2026-09-27T12:00:00", "2026-09-27T10:00:00")
        self.assertTrue(rng["measured"])
        self.assertIsNone(rng["inputs_after_backup"])
        self.assertIn("복구되지", rng["note"])

    def test_no_input_after_the_backup_is_reported_as_zero(self):
        rng = ops._input_range("2026-09-27T10:00:00", "2026-09-27T10:00:00")
        self.assertTrue(rng["measured"])
        self.assertEqual(rng["inputs_after_backup"], 0)


class TheDrillIsRunnableAndLeavesTheLiveDataAlone(unittest.TestCase):
    """17.3 4항: a restore is rehearsed, and the live database is not overwritten."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="drill-"))
        self.root = self.tmp / "d"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.config = ops.DurableConfig(
            data_root=self.root, db_path=self.root / "board.sqlite",
            export_dir=self.root / "exports", evidence_dir=self.root / "evidence",
            source_dir=self.root / "source")
        self.store = store_factory(self.config.db_path)
        before = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=before["revision"],
                        client_request_id="dr-1", change_mode="exception",
                        changes={"operator_note": "연습"})
        self.live_before = ops.sha256_file(self.config.db_path)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_drill_restores_to_a_separate_path(self):
        drill = ops.run_restore_drill(
            self.config, self.store, target_root=self.tmp / "elsewhere",
            store_factory=store_factory)
        self.assertTrue(drill["recoverable"])
        self.assertTrue(Path(drill["restore"]["restored_db"]).is_file())
        self.assertTrue(
            Path(drill["restore"]["restored_db"]).resolve().is_relative_to(
                (self.tmp / "elsewhere").resolve()))
        # the live database is byte-identical to what it was before the drill
        self.assertEqual(ops.sha256_file(self.config.db_path), self.live_before)

    def test_the_drill_command_runs_and_reports(self):
        import contextlib
        import io as _io
        import os

        from webapp import cli

        env = {
            "WEBLEDGER_DATA_ROOT": str(self.root),
            "WEBLEDGER_DB": str(self.config.db_path),
            "WEBLEDGER_EXPORT_DIR": str(self.config.export_dir),
            "WEBLEDGER_EVIDENCE_DIR": str(self.config.evidence_dir),
            "WEBLEDGER_SOURCE_DIR": str(self.config.source_dir),
        }
        original = dict(os.environ)
        os.environ.update(env)
        try:
            runbook = self.tmp / "DRILL.md"
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["ops", "drill", "--target",
                                 str(self.tmp / "cli-drill"),
                                 "--runbook", str(runbook)])
            payload = json.loads(out.getvalue())
            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["drill"]["recoverable"])
            self.assertIsNotNone(
                payload["drill"]["figures"]["trial_restore_seconds"])
            text = runbook.read_text(encoding="utf-8")
            assert_every_figure_line_is_written(
                self, payload["drill"]["figures"], text)
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_a_drill_on_an_empty_target_still_reports_its_figures(self):
        """A drill that finds nothing wrong still reports what it measured."""
        drill = ops.run_restore_drill(
            self.config, self.store, target_root=self.tmp / "fresh",
            store_factory=store_factory)
        self.assertTrue(drill["recoverable"])
        self.assertIsNotNone(drill["figures"]["trial_restore_seconds"])
        self.assertTrue(drill["figures"]["promises_not_made"])


if __name__ == "__main__":
    unittest.main()
