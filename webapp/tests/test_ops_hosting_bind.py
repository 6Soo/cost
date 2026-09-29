"""HOSTING preparation: the bind address, the durable data root, the service shape.

SPEC_REFINEMENT 19.2 says only the HTTPS app path may be exposed, and that the
SQLite file, the source directories and the worker port must not be. The app is
a stdlib HTTP server with no TLS, so the supported shape is a reverse proxy on
the same machine terminating HTTPS and forwarding to loopback. These tests pin
that shape down, and pin down the two ways a local run could have quietly gone
the other way.

Nothing here creates a hosting resource, a VM, a certificate, an account or a
service. The unit file is text written to a temporary path.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from webapp import ops

# The checkout root, taken from the module that decides what counts as the
# checkout, so the test and the rule cannot disagree about it.
REPO = Path(ops.__file__).resolve().parent.parent
ENTRY = REPO / "run_candidate.py"


class BindAddressIsClassifiedNotHardcoded(unittest.TestCase):
    """The bind address is explicit, and loopback is what it defaults to."""

    def test_loopback_addresses_are_recognised(self):
        for host in ("127.0.0.1", "localhost", "::1", "127.0.0.53"):
            with self.subTest(host=host):
                self.assertTrue(ops.is_loopback_host(host))
                self.assertTrue(ops.bind_posture(host)["acceptable"])

    def test_wildcards_and_routable_addresses_are_not_loopback(self):
        for host in ("0.0.0.0", "::", "", "*", "10.0.0.5", "192.168.1.10"):
            with self.subTest(host=host):
                self.assertFalse(ops.is_loopback_host(host))
                self.assertFalse(ops.bind_posture(host)["acceptable"])

    def test_an_unresolvable_name_is_treated_as_external(self):
        # A name that is not an address and not a known loopback alias must not
        # be mistaken for a safe one.
        self.assertFalse(ops.is_loopback_host("ledger.internal"))
        self.assertFalse(ops.is_loopback_host("example.com"))

    def test_the_default_shape_is_loopback_behind_a_proxy(self):
        report = ops.bind_posture("127.0.0.1")
        self.assertEqual(report["shape"], "loopback-behind-https-proxy")
        self.assertEqual(report["external_exposure"], "none")
        self.assertTrue(report["acceptable"])

    def test_an_external_bind_names_what_it_would_expose(self):
        report = ops.bind_posture("0.0.0.0")
        self.assertEqual(report["shape"], "external-bind")
        self.assertEqual(report["external_exposure"], "app port, without TLS")
        self.assertFalse(report["acceptable"])
        self.assertIn("TLS", report["note"])

    def test_require_safe_bind_refuses_an_external_bind_by_default(self):
        with self.assertRaises(ops.OpsError) as ctx:
            ops.require_safe_bind("0.0.0.0")
        self.assertEqual(ctx.exception.code, "UNSAFE_BIND")

    def test_require_safe_bind_allows_loopback_with_no_flag(self):
        # The recommended shape needs no acknowledgement at all.
        report = ops.require_safe_bind("127.0.0.1")
        self.assertTrue(report["acceptable"])

    def test_an_acknowledged_external_bind_is_a_different_shape(self):
        report = ops.require_safe_bind("0.0.0.0", behind_proxy=True)
        self.assertEqual(report["shape"], "non-loopback-for-proxy")
        self.assertTrue(report["acceptable"])
        self.assertNotEqual(report["shape"], "loopback-behind-https-proxy")


class TheManifestDoesNotBlessAPublicBind(unittest.TestCase):
    """A dry run must not come back green for a plain-HTTP public bind.

    Observed before the fix: `build_deploy_manifest` defaulted
    `behind_proxy=True`, so `ops dry-run --host 0.0.0.0` returned
    `ok: true, failed: []` on a server that terminates no TLS.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bind-manifest-"))
        self.config = ops.durable_config_for(self.tmp / "data", create=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_manifest_records_the_bind_posture(self):
        manifest = ops.build_deploy_manifest(self.config)
        self.assertEqual(manifest["bind"]["host"], "127.0.0.1")
        self.assertTrue(manifest["bind"]["acceptable"])
        self.assertEqual(manifest["bind"]["external_exposure"], "none")

    def test_an_external_bind_fails_the_dry_run(self):
        manifest = ops.build_deploy_manifest(self.config, bind_host="0.0.0.0")
        run = ops.dry_run_deploy(self.config, manifest)
        self.assertFalse(run["ok"])
        self.assertIn("app_port_not_exposed_without_tls", run["failed"])
        names = {c["check"]: c for c in run["checks"]}
        self.assertFalse(names["app_port_not_exposed_without_tls"]["ok"])

    def test_an_acknowledged_external_bind_passes_and_is_marked(self):
        manifest = ops.build_deploy_manifest(self.config, bind_host="0.0.0.0",
                                             behind_proxy=True)
        run = ops.dry_run_deploy(self.config, manifest)
        self.assertTrue(run["ok"], run["failed"])
        # passing is not the same as recommended: the shape stays different
        self.assertEqual(manifest["bind"]["shape"], "non-loopback-for-proxy")
        self.assertEqual(manifest["bind"]["external_exposure"],
                         "app port, without TLS")

    def test_a_manifest_with_no_bind_posture_fails_the_dry_run(self):
        manifest = ops.build_deploy_manifest(self.config)
        manifest.pop("bind")
        run = ops.dry_run_deploy(self.config, manifest)
        self.assertFalse(run["ok"])
        self.assertIn("bind_posture_recorded", run["failed"])

    def test_the_manifest_names_a_runnable_entry_command(self):
        """A command that is present, printable and cannot be run is a fiction.

        The default used to be `webapp.cli serve`, which requires `--snapshot`.
        The dry run only asked whether a command was present, so it passed and
        the deployment failed on first start. The requirement is that the
        recorded command could be executed as it stands, which is what the
        dry run's `entry_command_is_runnable` check now asserts.
        """
        manifest = ops.build_deploy_manifest(self.config)
        command = manifest["entry"]["command"]
        self.assertTrue(command)
        self.assertTrue(ops._entry_command_is_runnable(command),
                        f"the default entry command is not runnable: {command}")
        # Whatever it names, every file in it has to exist in this checkout.
        for part in command:
            if part.endswith(".py"):
                self.assertTrue(pathlib.Path(part).is_file(), part)
        run = ops.dry_run_deploy(self.config, manifest)
        self.assertIn("entry_command_is_runnable",
                      {c["check"]: c["ok"] for c in run["checks"]})

    def test_an_entry_command_missing_a_required_argument_fails_the_dry_run(self):
        """The defect itself, kept as a check: a required argument left empty."""
        manifest = ops.build_deploy_manifest(self.config)
        manifest["entry"]["command"] = [sys.executable,
                                        str(pathlib.Path(ops.__file__)
                                            .resolve().parent.parent
                                            / "run_candidate.py")]
        self.assertFalse(ops._entry_command_is_runnable(
            manifest["entry"]["command"]))
        run = ops.dry_run_deploy(self.config, manifest)
        self.assertFalse(run["ok"])
        self.assertIn("entry_command_is_runnable", run["failed"])

    def test_a_manifest_without_an_entry_command_fails_the_dry_run(self):
        manifest = ops.build_deploy_manifest(self.config)
        manifest["entry"]["command"] = []
        run = ops.dry_run_deploy(self.config, manifest)
        self.assertFalse(run["ok"])
        self.assertIn("entry_command_present", run["failed"])


class DurableDataRootIsNotInsideTheCheckout(unittest.TestCase):
    """18.3 item 2: durable data does not live in a checkout.

    Observed before the fix: `run_candidate.py` defaulted the database to
    `<checkout>/runtime/board.sqlite`, so a redeploy or a checkout wipe took the
    ledger with it, and the serving entry point bypassed every refusal that
    `DurableConfig` already enforced.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="durable-"))
        self.inside = REPO / "runtime" / "audit-data-root"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(REPO / "runtime", ignore_errors=True)

    def test_durable_config_for_uses_the_conventional_layout(self):
        config = ops.durable_config_for(self.tmp / "data", create=True)
        self.assertEqual(config.data_root, (self.tmp / "data").resolve())
        self.assertEqual(config.db_path, config.data_root / "board.sqlite")
        self.assertEqual(config.export_dir, config.data_root / "exports")
        self.assertEqual(config.evidence_dir, config.data_root / "evidence")
        self.assertEqual(config.source_dir, config.data_root / "source")
        self.assertFalse(ops._inside_source_checkout(config.data_root))

    def test_a_production_data_root_inside_the_checkout_is_refused(self):
        self.inside.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ops.OpsError) as ctx:
            ops.DurableConfig(
                data_root=self.inside, db_path=self.inside / "board.sqlite",
                export_dir=self.inside / "exports",
                evidence_dir=self.inside / "evidence",
                source_dir=self.inside / "source", environment="production")
        self.assertEqual(ctx.exception.code, "CHECKOUT_DATA_ROOT")

    def test_a_synthetic_run_may_sit_inside_the_checkout_on_purpose(self):
        self.inside.mkdir(parents=True, exist_ok=True)
        config = ops.DurableConfig(
            data_root=self.inside, db_path=self.inside / "board.sqlite",
            export_dir=self.inside / "exports",
            evidence_dir=self.inside / "evidence",
            source_dir=self.inside / "source", environment="local-synthetic")
        self.assertEqual(config.data_root, self.inside.resolve())

    def test_the_dry_run_names_a_checkout_data_root(self):
        self.inside.mkdir(parents=True, exist_ok=True)
        config = ops.DurableConfig(
            data_root=self.inside, db_path=self.inside / "board.sqlite",
            export_dir=self.inside / "exports",
            evidence_dir=self.inside / "evidence",
            source_dir=self.inside / "source", environment="local-synthetic")
        run = ops.dry_run_deploy(config,
                                 ops.build_deploy_manifest(config))
        names = {c["check"]: c for c in run["checks"]}
        self.assertIn("data_root_outside_source_checkout", names)
        self.assertFalse(names["data_root_outside_source_checkout"]["ok"])


class TheEntryPointRefusesCleanly(unittest.TestCase):
    """The first command an operator runs must refuse, not traceback."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="entry-"))
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        self.env.pop("WEBLEDGER_DATA_ROOT", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        # A short timeout on purpose. Every call here is expected to be refused,
        # so a change that lets one through would start a real server and block.
        # The timeout turns that into a failure instead of a stray process that
        # outlives the test run.
        return subprocess.run(
            [sys.executable, str(ENTRY), *args], capture_output=True,
            text=True, encoding="utf-8", errors="replace", cwd=str(REPO),
            env=self.env, timeout=60)

    def test_no_data_root_is_a_refusal_not_a_checkout_default(self):
        # Another test may legitimately have left a `runtime` directory here, so
        # this compares before and after rather than asserting the directory is
        # absent. The point is that this call did not create it.
        existed_before = (REPO / "runtime").exists()
        result = self._run()
        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("WEBLEDGER_DATA_ROOT", combined)
        self.assertNotIn("Traceback", combined)
        self.assertEqual((REPO / "runtime").exists(), existed_before)
        # and the entry point carries no checkout-relative default at all
        source = ENTRY.read_text(encoding="utf-8")
        self.assertNotIn('HERE / "runtime"', source)

    def test_every_refusal_uses_one_exit_code(self):
        # One code for every refusal, so a runbook or a service can act on it
        # without parsing the message. Every case here must be refused; a case
        # that starts serving is itself the failure, which is why the timeout
        # is short.
        cases = {
            "no data root": (),
            "unsafe bind": ("--data-root", str(self.tmp / "b"),
                            "--host", "0.0.0.0"),
            "production root in temp": ("--data-root", str(self.tmp / "c"),
                                        "--environment", "production"),
            "production root in the checkout": (
                "--data-root", str(REPO / "runtime" / "audit"),
                "--environment", "production"),
        }
        for label, extra in cases.items():
            with self.subTest(case=label):
                (REPO / "runtime" / "audit").mkdir(parents=True, exist_ok=True)
                try:
                    result = self._run(*extra)
                    self.assertEqual(result.returncode, 2, label)
                    self.assertNotIn("Traceback",
                                     result.stdout + result.stderr)
                finally:
                    shutil.rmtree(REPO / "runtime", ignore_errors=True)

    def test_an_external_bind_is_refused_with_a_code(self):
        result = self._run("--data-root", str(self.tmp / "data"),
                           "--host", "0.0.0.0")
        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("UNSAFE_BIND", combined)
        self.assertNotIn("Traceback", combined)
    def test_a_production_data_root_inside_the_checkout_is_refused(self):
        self.inside = REPO / "runtime" / "audit-root"
        self.inside.mkdir(parents=True, exist_ok=True)
        try:
            result = self._run("--data-root", str(self.inside),
                               "--environment", "production")
            self.assertEqual(result.returncode, 2)
            combined = result.stdout + result.stderr
            self.assertIn("CHECKOUT_DATA_ROOT", combined)
            self.assertNotIn("Traceback", combined)
        finally:
            shutil.rmtree(REPO / "runtime", ignore_errors=True)

    def test_a_production_data_root_in_a_temp_directory_is_refused(self):
        result = self._run("--data-root", str(self.tmp / "data"),
                           "--environment", "production")
        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("TEMP_DATA_ROOT", combined)
        self.assertNotIn("Traceback", combined)

    def test_the_entry_point_offers_the_operations_commands(self):
        source = ENTRY.read_text(encoding="utf-8")
        for command in ("ops", "health", "actions", "drill"):
            self.assertIn(command, source)
        self.assertIn("--data-root", source)
        self.assertIn("--behind-proxy", source)


class TheServiceExampleIsTextAndNotAnInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="unit-"))
        self.config = ops.durable_config_for(self.tmp / "data", create=True)
        self.manifest = ops.build_deploy_manifest(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_unit_binds_loopback_and_uses_the_data_root(self):
        text = ops.service_unit_text(self.config, self.manifest)
        self.assertIn(f"WorkingDirectory={self.config.data_root}", text)
        self.assertIn("--host 127.0.0.1", text)
        self.assertIn(f"Environment=WEBLEDGER_DATA_ROOT={self.config.data_root}",
                      text)
        self.assertIn(f"ReadWritePaths={self.config.data_root}", text)

    def test_the_unit_never_carries_a_secret_value(self):
        secret = "synthetic-not-a-real-key"
        env = {**os.environ, "MUSE_KEY": secret, "PYTHONIOENCODING": "utf-8"}
        original = dict(os.environ)
        os.environ.update(env)
        try:
            text = ops.service_unit_text(self.config, self.manifest)
        finally:
            os.environ.clear()
            os.environ.update(original)
        self.assertNotIn(secret, text)
        self.assertNotIn(secret, ops.configure if False else "")
        # it points at a secret store instead
        self.assertIn("EnvironmentFile", text)

    def test_the_unit_states_the_procedures_to_run_by_hand(self):
        text = ops.service_unit_text(self.config, self.manifest)
        for command in ("ops", "health", "actions", "drill", "dry-run"):
            self.assertIn(command, text)
        # the commands appear as commented lines, not as ExecStart
        for line in text.splitlines():
            if line.strip().startswith("ExecStart"):
                self.assertNotIn("ops health", line)
                self.assertNotIn("drill", line)

    def test_the_unit_marks_itself_as_an_example(self):
        text = ops.service_unit_text(self.config, self.manifest)
        self.assertIn("[Service]", text)
        self.assertIn("ExecStart", text)
        # the comment block has to say it installs nothing
        head = "\n".join(text.splitlines()[:6])
        self.assertIn("예시", head)
        self.assertIn("설치", head)

    def test_the_runbook_states_the_bind_shape_and_the_procedures(self):
        path = ops.write_deploy_runbook(
            self.tmp / "RUNBOOK.md", self.config, self.manifest,
            ops.dry_run_deploy(self.config, self.manifest),
            unit_path="/etc/web-ledger/web-ledger.service")
        text = path.read_text(encoding="utf-8")
        self.assertIn("loopback-behind-https-proxy", text)
        self.assertIn("127.0.0.1", text)
        for command in ("ops health", "ops actions", "ops drill", "ops dry-run"):
            self.assertIn(command, text)
        self.assertIn("/etc/web-ledger/web-ledger.service", text)


class TheCliWritesTheUnitWithoutInstallingIt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cli-unit-"))
        self.config = ops.durable_config_for(self.tmp / "data", create=True)
        self.env = {**os.environ,
                    "WEBLEDGER_DATA_ROOT": str(self.config.data_root),
                    "WEBLEDGER_DB": str(self.config.db_path),
                    "WEBLEDGER_EXPORT_DIR": str(self.config.export_dir),
                    "WEBLEDGER_EVIDENCE_DIR": str(self.config.evidence_dir),
                    "WEBLEDGER_SOURCE_DIR": str(self.config.source_dir),
                    "MUSE_KEY": "synthetic-not-a-real-key",
                    "PYTHONIOENCODING": "utf-8"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "webapp.cli", *args], capture_output=True,
            text=True, encoding="utf-8", errors="replace", cwd=str(REPO),
            env=self.env, timeout=600)

    def test_dry_run_writes_the_unit_and_reports_its_path(self):
        unit = self.tmp / "web-ledger.service"
        runbook = self.tmp / "RUNBOOK.md"
        result = self._cli("ops", "dry-run", "--secret", "MUSE_KEY",
                           "--unit", str(unit), "--runbook", str(runbook))
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"]["ok"], payload["dry_run"]["failed"])
        self.assertTrue(unit.is_file())
        self.assertEqual(payload["unit_example"], str(unit))
        # the runbook links to it
        self.assertIn(str(unit), runbook.read_text(encoding="utf-8"))

    def test_dry_run_refuses_an_external_bind_and_says_which_check(self):
        result = self._cli("ops", "dry-run", "--secret", "MUSE_KEY",
                           "--host", "0.0.0.0")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["dry_run"]["ok"])
        self.assertIn("app_port_not_exposed_without_tls",
                      payload["dry_run"]["failed"])

    def test_dry_run_accepts_an_external_bind_once_acknowledged(self):
        result = self._cli("ops", "dry-run", "--secret", "MUSE_KEY",
                           "--host", "0.0.0.0", "--behind-proxy")
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"]["ok"], payload["dry_run"]["failed"])
        self.assertEqual(payload["manifest"]["bind"]["shape"],
                         "non-loopback-for-proxy")

    def test_dry_run_without_a_unit_flag_writes_no_unit(self):
        result = self._cli("ops", "dry-run", "--secret", "MUSE_KEY")
        payload = json.loads(result.stdout)
        self.assertIsNone(payload["unit_example"])


class HealthDescribesWhatItActuallyFound(unittest.TestCase):
    """A check whose detail contradicts its own verdict is not readable.

    Observed before the fix: the `synthetic_sessions` line used a fixed
    sentence saying the allowance was present, so a healthy system printed a
    warning and a real allowance printed the same warning.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="health-detail-"))
        self.config = ops.durable_config_for(self.tmp / "data", create=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _synthetic_line(self):
        report = ops.health_check(self.config)
        return {c["check"]: c for c in report["checks"]}["synthetic_sessions"]

    def test_the_detail_agrees_with_the_verdict_when_no_allowance(self):
        line = self._synthetic_line()
        self.assertTrue(line["ok"])
        # not just free of the bad phrase: it has to say what was found
        self.assertTrue(line["detail"].strip(),
                        "an empty detail explains nothing to an operator")
        self.assertNotIn("is allowed", line["detail"])
        self.assertIn("no synthetic session allowance", line["detail"])

    def test_the_detail_agrees_with_the_verdict_when_an_allowance_exists(self):
        class Allowed:
            allow_synthetic = True

        from webapp import access_control
        original = access_control.session_adapter
        access_control.session_adapter = lambda: Allowed()
        try:
            line = self._synthetic_line()
        finally:
            access_control.session_adapter = original
        self.assertFalse(line["ok"])
        self.assertIn("is allowed", line["detail"])

    def test_a_missing_database_is_reported_honestly(self):
        report = ops.health_check(self.config)
        names = {c["check"]: c for c in report["checks"]}
        self.assertFalse(names["db_file_exists"]["ok"])
        self.assertIn("missing", names["db_integrity"]["detail"])
        self.assertFalse(report["ok"])


class TheBoardServerAcceptsAHostAndKeepsLoopback(unittest.TestCase):
    def test_production_entry_binds_fail_closed_access_before_serving(self):
        from run_candidate import bind_runtime_access
        from webapp import access_control, ledger_board

        tmp = Path(tempfile.mkdtemp(prefix="runtime-access-"))
        server = None
        try:
            server = ledger_board.serve(
                port=0, db_path=tmp / "board.sqlite", with_worker=False)
            access = bind_runtime_access(server)
            self.assertTrue(ledger_board.ACCESS_ENFORCEMENT)
            self.assertIs(ledger_board.access_store(), access)
            self.assertIsNone(access_control.session_adapter().session_for({}))
        finally:
            ledger_board.bind_access(None)
            if server is not None:
                server.server_close()
            ledger_board.bind_store(None)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_serve_defaults_to_loopback(self):
        import inspect

        from webapp import ledger_board

        signature = inspect.signature(ledger_board.serve)
        self.assertEqual(signature.parameters["host"].default, "127.0.0.1")

    def test_serve_actually_binds_the_address_it_is_given(self):
        import socket
        import tempfile

        from webapp import ledger_board

        # A second loopback address, so passing the default cannot pass this
        # test by accident. Binding 127.0.0.2 proves the host is used, not
        # ignored.
        # The db path is explicit and temporary: without it this would create
        # `webledger.work.sqlite` in the working directory and leave it there.
        tmp = Path(tempfile.mkdtemp(prefix="bind-serve-"))
        try:
            for host in ("127.0.0.1", "127.0.0.2"):
                with self.subTest(host=host):
                    with socket.socket() as probe:
                        probe.bind((host, 0))
                        port = probe.getsockname()[1]
                    server = ledger_board.serve(
                        port=port, db_path=tmp / "board.sqlite",
                        with_worker=False, host=host)
                    try:
                        self.assertEqual(server.server_address[0], host)
                    finally:
                        server.server_close()
                        ledger_board.bind_store(None)
            self.assertFalse((REPO / "webledger.work.sqlite").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_serve_parser_offers_the_host(self):
        result = subprocess.run(
            [sys.executable, "-m", "webapp.cli", "serve", "--help"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(REPO), timeout=180,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--host", result.stdout)
        self.assertIn("--behind-proxy", result.stdout)


class AStalledClientMustNotHoldUpTheApp(unittest.TestCase):
    """One silent connection may not delay every other client.

    `serve()` was a plain `HTTPServer`, which accepts one connection and then
    blocks reading that socket. A browser opens a connection speculatively and
    sends nothing until it navigates, so that silent socket held the accept
    queue and the navigation waited behind it. Measured directly, one silent
    connection delayed a real request past an eight second timeout; the same
    request against a threading server was answered in 0.05s.

    It showed up as an intermittent `Page.goto: Navigation ... Timeout` in the
    screen tests (about one run in ten) and it is the same defect for a real
    user whose connection stalls, so it is pinned here rather than retried away.
    """

    def test_a_silent_connection_does_not_delay_a_real_request(self):
        import socket
        import threading
        import time
        from http.server import HTTPServer

        from webapp import ledger_board as board

        tmp = Path(tempfile.mkdtemp(prefix="stall-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        server = board.serve(port=0, db_path=tmp / "board.sqlite",
                             with_worker=False)
        self.addCleanup(board.bind_store, None)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        time.sleep(0.2)

        silent = socket.create_connection(("127.0.0.1", port))
        self.addCleanup(silent.close)
        time.sleep(0.2)

        started = time.time()
        conn = socket.create_connection(("127.0.0.1", port))
        self.addCleanup(conn.close)
        conn.sendall(b"GET /board HTTP/1.1\r\nHost: x\r\nConnection: close\r\n"
                     b"\r\n")
        conn.settimeout(10)
        head = conn.recv(16)
        elapsed = time.time() - started
        self.assertTrue(head.startswith(b"HTTP/"),
                        f"no response while a silent connection was open; "
                        f"waited {elapsed:.2f}s")
        self.assertLess(elapsed, 5.0,
                        f"a real request waited {elapsed:.2f}s behind a silent "
                        f"connection, which is the single-threaded accept queue")

    def test_the_server_is_a_threading_one(self):
        from http.server import ThreadingHTTPServer

        from webapp import ledger_board as board

        tmp = Path(tempfile.mkdtemp(prefix="thread-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        server = board.serve(port=0, db_path=tmp / "board.sqlite",
                             with_worker=False)
        self.addCleanup(board.bind_store, None)
        self.addCleanup(server.server_close)
        self.assertIsInstance(server, ThreadingHTTPServer)
        self.assertTrue(server.daemon_threads,
                        "worker threads must not keep the process alive after "
                        "the socket closes")


if __name__ == "__main__":
    unittest.main()
