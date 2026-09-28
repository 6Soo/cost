"""Phase 9 local operations readiness: config, backup, restore, restart,
health, deploy dry run, retention and the external-condition report.

Everything runs on synthetic paths in a temporary directory. There is no
hosting resource, no Google OAuth client, no reservation API, no production DB
and no deployment in this file, and the tests assert that the local run does
not claim any of them.
"""

import json
import os
import shutil
import sqlite3
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


class Phase9OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase9-"))
        # a durable root outside the source tree and outside a temp default
        self.root = self.tmp / "durable"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True, exist_ok=True)
        self.config = ops.DurableConfig(
            data_root=self.root,
            db_path=self.root / "board.sqlite",
            export_dir=self.root / "exports",
            evidence_dir=self.root / "evidence",
            source_dir=self.root / "source",
            required_secrets=("MUSE_KEY",),
            keep_backups=7,
            environment="local-synthetic")
        self.store = store_factory(self.config.db_path)
        # an invariant source file, an evidence file and an output to back up
        (self.config.source_dir / "reference.csv").write_text(
            "entry_id,amount_krw\ng1,120000\n", encoding="utf-8")
        (self.config.evidence_dir / "ev-1.png").write_bytes(b"\x89PNG-synthetic")
        (self.config.export_dir / "ledger-x.xlsx").write_bytes(b"PK-synthetic")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env_with_secret(self):
        env = dict(os.environ)
        env["MUSE_KEY"] = "synthetic-not-a-real-key"
        return env

    # ------------------------------------------ 1. durable config, fail closed
    def test_a_valid_config_describes_its_paths_and_keeps_secrets_out(self):
        described = self.config.describe(self.env_with_secret())
        self.assertEqual(described["data_root"], str(self.root))
        self.assertEqual(described["keep_backups"], 7)
        self.assertEqual(described["required_secrets"], ["MUSE_KEY"])
        # presence is reported, never the value
        self.assertTrue(described["secret_state"]["MUSE_KEY"])
        self.assertNotIn("synthetic-not-a-real-key", json.dumps(described))

    def test_a_missing_required_setting_fails_closed(self):
        with self.assertRaises(ops.OpsError) as ctx:
            ops.DurableConfig.from_env({}, secrets=("MUSE_KEY",))
        self.assertEqual(ctx.exception.code, "MISSING_SETTING")
        with self.assertRaises(ops.OpsError) as ctx:
            ops.DurableConfig.from_env({"WEBLEDGER_DATA_ROOT": str(self.root)},
                                       secrets=())
        # the db setting is required, not defaulted
        self.assertEqual(ctx.exception.code, "MISSING_SETTING")

    def test_a_development_default_path_is_refused(self):
        # the historical relative defaults
        for bad_db, code in (
                (Path("webledger.work.sqlite"), "RELATIVE_SETTING"),
                (self.root / "webledger.work.sqlite", "REFUSED_DEFAULT_PATH"),
                (self.root / "board.sqlite", None),
        ):
            if code is None:
                continue
            with self.assertRaises(ops.OpsError) as ctx:
                ops.DurableConfig(
                    data_root=self.root, db_path=bad_db,
                    export_dir=self.root / "exports",
                    evidence_dir=self.root / "evidence",
                    source_dir=self.root / "source")
            self.assertEqual(ctx.exception.code, code, str(bad_db))
        # a development export default is refused as well
        with self.assertRaises(ops.OpsError) as ctx:
            ops.DurableConfig(
                data_root=self.root, db_path=self.root / "board.sqlite",
                export_dir=self.root / "webledger-exports",
                evidence_dir=self.root / "evidence",
                source_dir=self.root / "source")
        self.assertEqual(ctx.exception.code, "REFUSED_DEFAULT_PATH")
        # a relative export dir is refused too
        with self.assertRaises(ops.OpsError) as ctx:
            ops.DurableConfig(
                data_root=self.root, db_path=self.root / "board.sqlite",
                export_dir=Path("webledger-exports"),
                evidence_dir=self.root / "evidence",
                source_dir=self.root / "source")
        self.assertEqual(ctx.exception.code, "RELATIVE_SETTING")

    def test_a_production_data_root_inside_the_temp_dir_is_refused(self):
        inside_temp = Path(tempfile.gettempdir()).resolve() / "p9-should-not-run"
        inside_temp.mkdir(parents=True, exist_ok=True)
        try:
            # a declared synthetic environment may sit there on purpose
            ops.DurableConfig(
                data_root=inside_temp, db_path=inside_temp / "board.sqlite",
                export_dir=inside_temp / "exports",
                evidence_dir=inside_temp / "evidence",
                source_dir=inside_temp / "source",
                environment="local-synthetic")
            # but a production configuration may not
            with self.assertRaises(ops.OpsError) as ctx:
                ops.DurableConfig(
                    data_root=inside_temp, db_path=inside_temp / "board.sqlite",
                    export_dir=inside_temp / "exports",
                    evidence_dir=inside_temp / "evidence",
                    source_dir=inside_temp / "source",
                    environment="production")
            self.assertEqual(ctx.exception.code, "TEMP_DATA_ROOT")
        finally:
            shutil.rmtree(inside_temp, ignore_errors=True)

    def test_a_missing_data_root_is_refused(self):
        with self.assertRaises(ops.OpsError) as ctx:
            ops.DurableConfig(
                data_root=self.root / "not-created",
                db_path=self.root / "board.sqlite",
                export_dir=self.root / "exports",
                evidence_dir=self.root / "evidence",
                source_dir=self.root / "source")
        self.assertEqual(ctx.exception.code, "MISSING_DATA_ROOT")

    # ----------------------------------------------- 2. backup bundle + restore
    def _save_row(self, store, request_id="p9-save-1"):
        before = store.get_row("expense-demo-c1")
        result = store.save(
            row_id="expense-demo-c1", expected_revision=before["revision"],
            client_request_id=request_id, change_mode="exception",
            changes={"display_tab_id": "trip-demo-b",
                     "operator_note": "운영 준비 메모"})
        return result

    def test_a_backup_bundle_carries_the_db_and_the_invariant_metadata(self):
        self._save_row(self.store)
        manifest = ops.make_backup_bundle(self.config, self.store, label="b1")
        bundle = self.config.data_root / "backups" / manifest["bundle"]
        self.assertTrue((bundle / "board.sqlite").is_file())
        self.assertTrue((bundle / "source" / "reference.csv").is_file())
        self.assertTrue((bundle / "evidence" / "ev-1.png").is_file())
        self.assertTrue((bundle / "export" / "ledger-x.xlsx").is_file())
        self.assertTrue((bundle / "manifest.json").is_file())
        # the manifest records the content hash of each copied file
        for key in ("source", "evidence", "export"):
            for item in manifest["files"][key]:
                self.assertEqual(len(item["sha256"]), 64)
        # and the state the restore has to reproduce
        self.assertIn("rows", manifest["state"])
        self.assertGreater(manifest["state"]["revisions"], 0)

    def test_a_restore_goes_to_a_separate_path_and_keeps_the_original(self):
        self._save_row(self.store)
        manifest = ops.make_backup_bundle(self.config, self.store, label="b2")
        bundle = self.config.data_root / "backups" / manifest["bundle"]
        live_before = ops.sha256_file(self.config.db_path)
        target = self.tmp / "restored"
        result = ops.restore_bundle(self.config, bundle, target_root=target,
                                    store_factory=store_factory)
        self.assertTrue(result["ok"], result["problems"])
        self.assertTrue(Path(result["restored_db"]).is_file())
        # the live DB was not touched by the restore
        self.assertEqual(ops.sha256_file(self.config.db_path), live_before)
        # the original bundle still holds its files
        self.assertTrue((bundle / "board.sqlite").is_file())
        # the restored rows and events came back
        self.assertEqual(result["state"]["observed"]["rows"],
                         manifest["state"]["rows"])
        self.assertTrue(result["state"]["events_present"])

    def test_a_corrupt_bundle_is_refused_instead_of_restored(self):
        self._save_row(self.store)
        manifest = ops.make_backup_bundle(self.config, self.store, label="b3")
        bundle = self.config.data_root / "backups" / manifest["bundle"]
        (bundle / "board.sqlite").write_bytes(b"not a database")
        result = ops.restore_bundle(self.config, bundle,
                                    target_root=self.tmp / "restored-bad",
                                    store_factory=store_factory)
        self.assertFalse(result["ok"])
        self.assertFalse(result["restored"])
        self.assertTrue(any("sha256" in p for p in result["problems"]))
        self.assertFalse((self.tmp / "restored-bad" / "board.sqlite").is_file())

    # ------------------- 3. restore re-verifies events, access and idempotency
    def test_a_restore_rechecks_access_state_and_synthetic_sessions(self):
        self._save_row(self.store)
        access = access_control.attach_to_ledger_store(self.store)
        access.ensure_owner("syn-owner-O")
        access.create_account(user_id="syn-staff-V1",
                              role=access_control.ROLE_VIEWER)
        access.register_reservation_person(reservation_person_id="rp-1",
                                          display_name="홍길동")
        access.create_application(user_id="syn-staff-V1",
                                  requested_name="홍길동",
                                  client_request_id="p9-app-1")
        application = access.applications_for("syn-staff-V1")[0]
        access.approve_application(
            application_id=application["application_id"],
            owner_id="syn-owner-O", expected_revision=1,
            reservation_person_id="rp-1", client_request_id="p9-app-2")
        access.apply_assignment_snapshot(
            user_id="syn-staff-V1",
            items=[{"tab_id": "trip-demo-a", "snapshot_revision": 1,
                    "state": "active"}],
            source_version="p9-src")
        manifest = ops.make_backup_bundle(self.config, self.store, label="b4")
        bundle = self.config.data_root / "backups" / manifest["bundle"]
        result = ops.restore_bundle(self.config, bundle,
                                    target_root=self.tmp / "restored-access",
                                    store_factory=store_factory)
        self.assertTrue(result["ok"], result["problems"])
        checked = result["access"]
        # the link and the assignment both survived
        self.assertEqual([a["user_id"] for a in checked["accounts"]],
                         ["syn-owner-O", "syn-staff-V1"])
        self.assertEqual(checked["connections"][0]["status"], "active")
        # and the auth cache and the synthetic allowance are reported, not
        # assumed. A restore must not widen access.
        self.assertIn("auth_cache", checked)
        self.assertIn("synthetic_sessions_allowed", checked)
        # a synthetic allowance is a finding, not a healthy auth path
        if checked["synthetic_sessions_allowed"]:
            self.assertTrue(any("synthetic" in p for p in checked["problems"]))

    def test_a_restore_rechecks_that_a_request_id_still_replays(self):
        self._save_row(self.store, request_id="p9-idem-1")
        manifest = ops.make_backup_bundle(self.config, self.store, label="b5")
        bundle = self.config.data_root / "backups" / manifest["bundle"]
        result = ops.restore_bundle(self.config, bundle,
                                    target_root=self.tmp / "restored-idem",
                                    store_factory=store_factory)
        self.assertTrue(result["ok"], result["problems"])
        self.assertTrue(result["idempotency"]["checked"])
        self.assertTrue(result["idempotency"]["replayed"])
        self.assertTrue(result["idempotency"]["request_id_present"])

    def test_a_lost_request_table_is_reported(self):
        self._save_row(self.store, request_id="p9-idem-2")
        # build a bundle first, so the copy is a consistent online backup
        manifest = ops.make_backup_bundle(self.config, self.store, label="b-lost")
        bundle = self.config.data_root / "backups" / manifest["bundle"]
        target = self.tmp / "lost-requests"
        target.mkdir(parents=True, exist_ok=True)
        copy = target / "board.sqlite"
        shutil.copy2(bundle / "board.sqlite", copy)
        # simulate a backup that lost the request table
        conn = sqlite3.connect(str(copy))
        try:
            conn.execute("DELETE FROM board_requests")
            conn.commit()
        finally:
            conn.close()
        fresh = store_factory(copy)
        try:
            report = ops.verify_request_idempotency_after_restore(fresh)
        finally:
            fresh.close()
        self.assertFalse(report["checked"])
        self.assertEqual(report["reason"], "no request to replay in this bundle")

    # ------------------------------------------------ 4. restart survival
    def test_a_real_restart_keeps_the_rows_and_the_work_state(self):
        result = ops.restart_survival_check(
            self.config.db_path, store_factory=store_factory,
            request_id="p9-restart-1",
            save_row=lambda store: self._save_row(store, "p9-restart-1"))
        self.assertTrue(result["ok"], result["problems"])
        self.assertGreater(result["events"], 0)
        self.assertTrue(result["reopened_from"])
        # a fresh store sees the same row, revision and trip assignment
        fresh = store_factory(self.config.db_path)
        try:
            row = fresh.get_row(result["row_id"])
            self.assertEqual(row["revision"], result["revision"])
            self.assertEqual(row["display_tab_id"], "trip-demo-b")
        finally:
            fresh.close()

    def test_a_trip_switch_survives_a_restart(self):
        first = store_factory(self.config.db_path)
        try:
            before = first.get_trip("trip-demo-b")
            first.save_trip_meta(tab_id="trip-demo-b",
                                 expected_revision=before["revision"],
                                 client_request_id="p9-trip-1",
                                 display_key="전환 확인 여행")
        finally:
            first.close()
        second = store_factory(self.config.db_path)
        try:
            after = second.get_trip("trip-demo-b")
            self.assertEqual(after["display_key"], "전환 확인 여행")
            self.assertEqual(after["revision"], before["revision"] + 1)
        finally:
            second.close()

    # ------------------------------------------ 5. health and readiness
    def test_health_does_not_hide_a_missing_db_or_a_missing_secret(self):
        # a config whose DB has never been created
        absent = ops.DurableConfig(
            data_root=self.root,
            db_path=self.root / "never-created.sqlite",
            export_dir=self.root / "exports",
            evidence_dir=self.root / "evidence",
            source_dir=self.root / "source",
            required_secrets=("MUSE_KEY",))
        report = ops.health_check(absent)
        names = {c["check"]: c for c in report["checks"]}
        self.assertFalse(names["db_file_exists"]["ok"])
        self.assertIn("db_file_exists", report["failed"])
        self.assertFalse(report["ok"])
        # the secret check is its own line, reported separately
        self.assertIn("required_secrets", names)
        self.assertFalse(names["required_secrets"]["ok"])
        # and the schema is still reported, not silently skipped
        self.assertIn("db_schema", names)

    def test_health_passes_only_when_everything_is_present(self):
        self._save_row(self.store, "p9-health-1")
        original = dict(os.environ)
        os.environ["MUSE_KEY"] = "synthetic-not-a-real-key"
        try:
            report = ops.health_check(self.config, self.store)
        finally:
            os.environ.clear()
            os.environ.update(original)
        names = {c["check"]: c for c in report["checks"]}
        self.assertTrue(names["db_file_exists"]["ok"])
        self.assertTrue(names["db_integrity"]["ok"])
        self.assertEqual(names["db_integrity"]["detail"], "ok")
        self.assertTrue(names["db_schema"]["ok"])
        self.assertTrue(names["free_space"]["ok"])
        self.assertTrue(names["required_secrets"]["ok"])
        self.assertTrue(names["data_root_exists"]["ok"])
        self.assertTrue(report["ok"], report["failed"])

    def test_health_names_a_missing_schema_table(self):
        empty = self.tmp / "empty.sqlite"
        conn = sqlite3.connect(str(empty))
        try:
            conn.execute("CREATE TABLE unrelated (x INTEGER)")
            conn.commit()
        finally:
            conn.close()
        broken = ops.DurableConfig(
            data_root=self.root, db_path=empty,
            export_dir=self.root / "exports",
            evidence_dir=self.root / "evidence",
            source_dir=self.root / "source")
        report = ops.health_check(broken)
        names = {c["check"]: c for c in report["checks"]}
        self.assertFalse(names["db_schema"]["ok"])
        self.assertIn("missing tables", names["db_schema"]["detail"])
        self.assertFalse(report["ok"])

    def test_the_readiness_report_measures_and_does_not_claim_a_release(self):
        self._save_row(self.store, "p9-ready-1")
        report = ops.readiness_report(
            self.config, self.store,
            measurements={"provider_turns": {"attempted": 1, "waiting": 1,
                                             "completed": 0},
                          "save_timings_ms": {"count": 1, "max": 4},
                          "reconciliations": {"full_runs": 0}})
        self.assertIn("counts", report)
        self.assertGreaterEqual(report["counts"]["row_events"], 1)
        # a waiting or failed turn is counted as such, never as a completed call
        self.assertEqual(report["provider_turns"]["completed"], 0)
        self.assertEqual(report["provider_turns"]["waiting"], 1)
        self.assertEqual(report["save_timings_ms"]["count"], 1)
        # the external conditions are separate from the code result
        self.assertTrue(report["external_conditions_still_unmet"])
        ids = {c["id"] for c in report["external_conditions_still_unmet"]}
        for required in ("HOSTING-RESOURCE", "GOOGLE-OIDC-CLIENT",
                         "RESERVATION-API", "PRODUCTION-DB", "DEPLOY"):
            self.assertIn(required, ids)
        for condition in report["external_conditions_still_unmet"]:
            self.assertNotEqual(condition["state"], "ready")

    # ------------------------------------------- 6. deploy manifest and runbook
    def test_the_deploy_dry_run_validates_locally_and_applies_nothing(self):
        manifest = ops.build_deploy_manifest(self.config)
        self.assertFalse(manifest["applied"])
        original = dict(os.environ)
        os.environ["MUSE_KEY"] = "synthetic-not-a-real-key"
        try:
            run = ops.dry_run_deploy(self.config, manifest)
        finally:
            os.environ.clear()
            os.environ.update(original)
        self.assertTrue(run["ok"], run["failed"])
        self.assertFalse(run["applied"])
        names = {c["check"]: c for c in run["checks"]}
        self.assertTrue(names["manifest_not_applied"]["ok"])
        self.assertTrue(names["data_root_absolute"]["ok"])
        self.assertTrue(names["paths_inside_data_root"]["ok"])
        self.assertTrue(names["directories_created"]["ok"])
        # a synthetic session allowance is not a valid runbook state
        self.assertIn("synthetic_sessions_not_operational", names)
        self.assertTrue(run["external_conditions_still_unmet"])

    def test_a_dry_run_fails_when_a_secret_is_missing(self):
        manifest = ops.build_deploy_manifest(self.config)
        original = dict(os.environ)
        os.environ.pop("MUSE_KEY", None)
        try:
            run = ops.dry_run_deploy(self.config, manifest)
        finally:
            os.environ.clear()
            os.environ.update(original)
        self.assertFalse(run["ok"])
        self.assertIn("required_secrets_present", run["failed"])

    def test_the_runbook_states_the_unmet_external_conditions(self):
        manifest = ops.build_deploy_manifest(self.config)
        original = dict(os.environ)
        os.environ["MUSE_KEY"] = "synthetic-not-a-real-key"
        try:
            run = ops.dry_run_deploy(self.config, manifest)
        finally:
            os.environ.clear()
            os.environ.update(original)
        path = ops.write_deploy_runbook(self.tmp / "RUNBOOK.md", self.config,
                                       manifest, run)
        text = path.read_text(encoding="utf-8")
        self.assertIn("실행하지 않음", text)
        self.assertIn("수동 단계", text)
        self.assertIn("HOSTING-RESOURCE", text)
        self.assertIn("GOOGLE-OIDC-CLIENT", text)
        self.assertIn("DEPLOY", text)

    # --------------------------------- 8. retention and duplicate suppression
    def test_retention_keeps_the_newest_seven_and_drops_duplicates(self):
        # nine distinct bundles
        for index in range(9):
            self.store.save(
                row_id="expense-demo-c1",
                expected_revision=self.store.get_row(
                    "expense-demo-c1")["revision"],
                client_request_id=f"p9-ret-{index}", change_mode="exception",
                changes={"operator_note": f"note {index}"})
            ops.make_backup_bundle(self.config, self.store, label=f"r{index}")
        found = ops.list_bundles(self.config)
        self.assertEqual(len(found), 9)
        result = ops.apply_retention(self.config)
        self.assertEqual(result["retention"], 7)
        self.assertEqual(result["kept_count"], 7)
        self.assertEqual(len(result["kept"]), 7)
        self.assertTrue(any("retention" in r["reason"] for r in result["removed"]))
        # the newest bundles are the ones kept
        self.assertEqual(result["kept"][-1], found[-1]["bundle"])

    def test_a_duplicate_content_hash_is_not_kept_twice(self):
        self._save_row(self.store, "p9-dup-1")
        first = ops.make_backup_bundle(self.config, self.store, label="dup")
        # a second bundle with identical content
        again_dir = self.config.data_root / "backups"
        target = again_dir / (first["bundle"] + "-copy")
        shutil.copytree(again_dir / first["bundle"], target)
        manifest = json.loads((target / "manifest.json").read_text(
            encoding="utf-8"))
        manifest["bundle"] = target.name
        manifest["created_at"] = ops.utc_now()
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        before = len(ops.list_bundles(self.config))
        self.assertEqual(before, 2)
        result = ops.apply_retention(self.config)
        self.assertEqual(len(result["kept"]), 1)
        self.assertTrue(any("same content hash" in r["reason"]
                            for r in result["removed"]))

    def test_the_retention_setting_must_be_positive(self):
        with self.assertRaises(ops.OpsError) as ctx:
            ops.DurableConfig(
                data_root=self.root, db_path=self.root / "board.sqlite",
                export_dir=self.root / "exports",
                evidence_dir=self.root / "evidence",
                source_dir=self.root / "source", keep_backups=0)
        self.assertEqual(ctx.exception.code, "INVALID_RETENTION")

    # ------------------------------- 9. external conditions are not code wins
    def test_the_external_condition_list_is_not_a_release_approval(self):
        states = {c["id"]: c for c in ops.EXTERNAL_CONDITIONS}
        self.assertEqual(states["HOSTING-RESOURCE"]["state"], "not_provisioned")
        self.assertEqual(states["GOOGLE-OIDC-CLIENT"]["state"], "no_credentials")
        self.assertEqual(states["RESERVATION-API"]["state"], "not_connected")
        self.assertEqual(states["PRODUCTION-DB"]["state"], "not_migrated")
        self.assertEqual(states["DEPLOY"]["state"], "not_deployed")
        for condition in ops.EXTERNAL_CONDITIONS:
            self.assertTrue(condition["needs"])
            self.assertIn("code_status", condition)

    def test_a_local_run_never_reports_a_deployment(self):
        manifest = ops.build_deploy_manifest(self.config)
        self.assertFalse(manifest["applied"])
        self.assertIn("applied", manifest)
        run = ops.dry_run_deploy(self.config, manifest)
        self.assertFalse(run["applied"])
        # nothing was created outside the data root
        self.assertTrue(all(p.resolve().is_relative_to(self.root)
                            for p in (self.config.export_dir,
                                      self.config.evidence_dir,
                                      self.config.source_dir)))

    # ------------------------------------ the runbook commands actually run
    def _cli(self, argv):
        from webapp import cli

        return cli.main(argv)

    def test_the_ops_cli_commands_run_and_report(self):
        import contextlib
        import io as _io

        env = {
            "WEBLEDGER_DATA_ROOT": str(self.root),
            "WEBLEDGER_DB": str(self.config.db_path),
            "WEBLEDGER_EXPORT_DIR": str(self.config.export_dir),
            "WEBLEDGER_EVIDENCE_DIR": str(self.config.evidence_dir),
            "WEBLEDGER_SOURCE_DIR": str(self.config.source_dir),
            "MUSE_KEY": "synthetic-not-a-real-key",
        }
        original = dict(os.environ)
        os.environ.update(env)
        try:
            self._save_row(self.store, "p9-cli-1")

            # health
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self._cli(["ops", "health", "--secret", "MUSE_KEY"])
            report = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(report["ok"])
            self.assertIn("db_schema", {c["check"] for c in report["checks"]})

            # backup
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self._cli(["ops", "backup", "--secret", "MUSE_KEY",
                                  "--label", "cli"])
            payload = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            bundle = payload["backup"]["bundle"]
            self.assertTrue(
                (self.config.data_root / "backups" / bundle / "board.sqlite")
                .is_file())
            self.assertEqual(payload["retention"]["retention"], 7)

            # restore into a separate target
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self._cli([
                    "ops", "restore",
                    str(self.config.data_root / "backups" / bundle),
                    "--target", str(self.tmp / "cli-restored"),
                    "--secret", "MUSE_KEY"])
            restored = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(restored["ok"])
            self.assertTrue(Path(restored["restored_db"]).is_file())

            # dry run writes a runbook and applies nothing
            runbook = self.tmp / "cli-RUNBOOK.md"
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self._cli(["ops", "dry-run", "--secret", "MUSE_KEY",
                                  "--runbook", str(runbook)])
            dry = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(dry["dry_run"]["applied"])
            self.assertTrue(runbook.is_file())

            # readiness names the unmet external conditions
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self._cli(["ops", "readiness", "--secret", "MUSE_KEY"])
            report = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(report["external_conditions_still_unmet"])
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_an_unconfigured_ops_command_fails_closed_with_a_code(self):
        import contextlib
        import io as _io

        original = dict(os.environ)
        os.environ.pop("WEBLEDGER_DATA_ROOT", None)
        try:
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self._cli(["ops", "health"])
            payload = json.loads(out.getvalue())
            self.assertEqual(code, 2)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["code"], "MISSING_SETTING")
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_a_production_cli_run_on_a_temp_root_fails_closed(self):
        import contextlib
        import io as _io

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
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self._cli(["ops", "health", "--environment",
                                  "production"])
            payload = json.loads(out.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "TEMP_DATA_ROOT")
        finally:
            os.environ.clear()
            os.environ.update(original)



class ActionRequiredSurfaceTests(Phase9OpsTests):
    """SPEC_REFINEMENT 17.4: only the states an operator must act on are shown.

    The four categories are 저장 실패, 처리 지연, 예약 권한 확인 지연, 백업 실패.
    Each is derived from a stored fact, so the report can neither invent a
    problem nor hide one.
    """

    def test_a_clean_store_reports_nothing_to_do_and_lists_what_was_checked(self):
        report = ops.action_required_report(self.config, self.store)
        self.assertTrue(report["ok"])
        self.assertEqual(report["items"], [])
        # The categories are listed even when empty, so a short list cannot be
        # mistaken for "not looked at".
        self.assertEqual(sorted(report["checked"]),
                         ["backup_failure", "permission_pending",
                          "processing_delay", "save_failure"])

    def test_a_save_still_pending_is_reported(self):
        self.store.conn.execute(
            "INSERT INTO board_requests(client_request_id, row_id,"
            " expected_revision, result_json, ledger_pending, created_at)"
            " VALUES ('ar-1','expense-demo-c1',1,'{}',1,'2026-09-27T10:00')")
        report = ops.action_required_report(self.config, self.store)
        self.assertFalse(report["ok"])
        category = [i for i in report["items"]
                    if i["category"] == "save_failure"]
        self.assertEqual(len(category), 1)
        self.assertEqual(category[0]["needs"], "owner")
        self.assertTrue(category[0]["action"])

    def _access(self):
        from webapp import access_control

        if not getattr(self, "_access_store", None):
            self._access_store = access_control.attach_to_ledger_store(self.store)
        return self._access_store

    def test_a_pending_staff_request_is_reported(self):
        access = self._access()
        access.create_account(user_id="syn-u1",
                              role=access_control.ROLE_VIEWER,
                              display_name="김민수")
        access.create_application(user_id="syn-u1", requested_name="김민수",
                                  client_request_id="ar-app-1")
        report = ops.action_required_report(self.config, self.store)
        found = [i for i in report["items"]
                 if i["category"] == "permission_pending"]
        self.assertEqual(len(found), 1)
        self.assertIn("계정 관리", found[0]["action"])

    def test_a_decided_request_stops_being_reported(self):
        access = self._access()
        access.ensure_owner("syn-owner-op")
        access.register_reservation_person(reservation_person_id="rp-1",
                                           display_name="김민수")
        access.create_account(user_id="syn-u2",
                              role=access_control.ROLE_VIEWER,
                              display_name="이정호")
        application = access.create_application(
            user_id="syn-u2", requested_name="이정호",
            client_request_id="ar-app-2")
        access.approve_application(
            application_id=application["application_id"], owner_id="syn-owner-op",
            expected_revision=1, reservation_person_id="rp-1",
            client_request_id="ar-app-2-approve")
        report = ops.action_required_report(self.config, self.store)
        self.assertEqual(
            [i for i in report["items"]
             if i["category"] == "permission_pending"], [])

    def test_a_failed_or_stale_backup_is_reported(self):
        class Broken:
            def last_backup_state(self):
                return {"ok": False, "detail": "봉인이 맞지 않아요"}

        class Stale:
            def last_backup_state(self):
                return {"ok": True, "stale": True, "at": "2026-01-01T00:00"}

        for config, expected in ((Broken(), "봉인이 맞지 않아요"),
                                 (Stale(), "오래됐어요")):
            with self.subTest(expected=expected):
                report = ops.action_required_report(config, self.store)
                found = [i for i in report["items"]
                         if i["category"] == "backup_failure"]
                self.assertEqual(len(found), 1)
                self.assertIn(expected, found[0]["what"])

    def test_an_unreadable_backup_state_is_a_finding_not_a_crash(self):
        class Explodes:
            def last_backup_state(self):
                raise RuntimeError("backup store is gone")

        report = ops.action_required_report(Explodes(), self.store)
        found = [i for i in report["items"] if i["category"] == "backup_failure"]
        self.assertEqual(len(found), 1)

    def test_the_readiness_report_carries_the_action_surface(self):
        report = ops.readiness_report(self.config, self.store)
        self.assertIn("action_required", report)
        self.assertIn("checked", report["action_required"])

    def test_the_cli_exposes_the_action_surface(self):
        import contextlib
        import io as _io

        from webapp import cli

        env = {
            "WEBLEDGER_DATA_ROOT": str(self.root),
            "WEBLEDGER_DB": str(self.config.db_path),
            "WEBLEDGER_EXPORT_DIR": str(self.config.export_dir),
            "WEBLEDGER_EVIDENCE_DIR": str(self.config.evidence_dir),
            "WEBLEDGER_SOURCE_DIR": str(self.config.source_dir),
            "MUSE_KEY": "synthetic-not-a-real-key",
        }
        original = dict(os.environ)
        os.environ.update(env)
        try:
            out = _io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["ops", "actions"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertIn("items", payload)
            self.assertIn("checked", payload)
            # a pending save makes the command fail closed, not pass quietly
            self.store.conn.execute(
                "INSERT INTO board_requests(client_request_id, row_id,"
                " expected_revision, result_json, ledger_pending, created_at)"
                " VALUES ('ar-cli','expense-demo-c1',1,'{}',1,"
                "'2026-09-27T10:00')")
            out2 = _io.StringIO()
            with contextlib.redirect_stdout(out2):
                code2 = cli.main(["ops", "actions"])
            self.assertEqual(code2, 2)
            again = json.loads(out2.getvalue())
            self.assertFalse(again["ok"])
            self.assertEqual(again["items"][0]["category"], "save_failure")
        finally:
            os.environ.clear()
            os.environ.update(original)

if __name__ == "__main__":
    unittest.main()
