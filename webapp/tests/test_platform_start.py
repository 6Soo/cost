"""Tests for the platform start contract: P4-1 through P4-7.

Nothing here provisions anything. A PaaS, a volume, a certificate and an
account are all external; what can be checked locally is that the repository
states one start command, reads the port the platform assigns, answers a probe
without a login, and names a persistent data root.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from webapp import ledger_board as board  # noqa: E402
from webapp import ops  # noqa: E402
from webapp.ledger_store import LedgerStore  # noqa: E402


def requirement_lines(path):
    """The pinned requirements of a requirements file, comments removed."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if text:
            out.append(text)
    return sorted(out)


class BothRequirementsFilesAgree(unittest.TestCase):
    """P4-1: two lists drift apart quietly and only fail at login time."""

    def test_the_root_and_the_package_list_the_same_requirements(self):
        root = requirement_lines(ROOT / "requirements.txt")
        package = requirement_lines(ROOT / "webapp/requirements.txt")
        self.assertEqual(root, package,
                         "the two requirements files disagree; a platform that "
                         "reads one of them installs a different set of "
                         "dependencies than the one that was tested")

    def test_the_oidc_dependencies_are_declared_in_both(self):
        """The Google login path is a real dependency, not an optional extra."""
        for rel in ("requirements.txt", "webapp/requirements.txt"):
            text = "\n".join(requirement_lines(ROOT / rel)).lower()
            for package in ("openpyxl", "google-auth", "pyjwt", "requests"):
                self.assertIn(package, text,
                              f"{package} is missing from {rel}")

    def test_the_google_oidc_module_imports_without_a_key(self):
        """A declared dependency that does not import is a declaration only."""
        from webapp import google_oidc

        self.assertTrue(google_oidc.REQUIRED_ENV)
        self.assertIsNotNone(google_oidc.try_connect_from_env.__doc__)


class ThePlatformPortIsRead(unittest.TestCase):
    """P4-2: a PaaS assigns the port at start time."""

    def setUp(self):
        import run_candidate

        self.entry = run_candidate
        self.saved = {k: os.environ.get(k) for k in ("PORT",
                                                     "WEBLEDGER_DATA_ROOT")}

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_the_platform_port_is_used_when_the_flag_is_absent(self):
        os.environ["PORT"] = "4321"
        self.assertEqual(self.entry.resolve_port(None), 4321)

    def test_the_flag_wins_over_the_platform_port(self):
        os.environ["PORT"] = "4321"
        self.assertEqual(self.entry.resolve_port(9000), 9000)

    def test_without_a_platform_port_the_documented_default_is_used(self):
        os.environ.pop("PORT", None)
        self.assertEqual(self.entry.resolve_port(None), self.entry.DEFAULT_PORT)

    def test_a_port_that_is_not_a_number_is_a_refusal(self):
        os.environ["PORT"] = "not-a-port"
        with self.assertRaises(ops.OpsError) as caught:
            self.entry.resolve_port(None)
        self.assertEqual(caught.exception.code, "PORT_NOT_A_NUMBER")

    def test_an_out_of_range_port_is_a_refusal(self):
        os.environ["PORT"] = "70000"
        with self.assertRaises(ops.OpsError) as caught:
            self.entry.resolve_port(None)
        self.assertEqual(caught.exception.code, "PORT_OUT_OF_RANGE")

    def test_the_parser_leaves_the_port_unset_so_the_platform_wins(self):
        args = self.entry.build_parser().parse_args([])
        self.assertIsNone(args.port,
                          "a fixed default here would ignore the platform's "
                          "PORT before resolve_port was ever called")


class ThereIsOneStartCommand(unittest.TestCase):
    """P4-3: a repository should say how it is started, once."""

    def test_a_procfile_exists_and_names_the_real_entry_point(self):
        procfile = ROOT / "Procfile"
        self.assertTrue(procfile.is_file(),
                        "no start command is declared anywhere in the repo")
        line = procfile.read_text(encoding="utf-8").strip()
        self.assertTrue(line.startswith("web:"), line)
        command = line.split(":", 1)[1].strip()
        self.assertIn("run_candidate.py", command)
        self.assertTrue((ROOT / "run_candidate.py").is_file())
        # Every file the command names has to exist here.
        for part in command.split():
            if part.endswith(".py"):
                self.assertTrue((ROOT / part).is_file(), part)

    def test_the_procfile_command_is_one_the_parser_accepts(self):
        line = (ROOT / "Procfile").read_text(encoding="utf-8").strip()
        command = line.split(":", 1)[1].strip()
        import run_candidate

        args = run_candidate.build_parser().parse_args(
            command.split()[2:])
        self.assertEqual(args.environment, "production")
        self.assertTrue(args.require_ready,
                        "the start command must be gated in production")
        self.assertTrue(args.behind_proxy,
                        "a 0.0.0.0 bind has to say a TLS edge is in front")
        self.assertEqual(args.host, "0.0.0.0")

    def test_the_manifest_entry_command_is_runnable(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="startcmd-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        config = ops.durable_config_for(tmp / "data",
                                        environment="local-synthetic",
                                        create=True)
        manifest = ops.build_deploy_manifest(config)
        command = manifest["entry"]["command"]
        self.assertTrue(ops._entry_command_is_runnable(command), command)
        # The old default required a snapshot nobody supplied.
        self.assertFalse(any("webapp.cli" in part for part in command),
                         "the entry command is still the one that needs a "
                         "snapshot it was never given")


class ThePlatformProbesAnswer(unittest.TestCase):
    """P4-4: a load balancer's probe carries no login."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="probe-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.server = board.serve(port=0, db_path=self.tmp / "board.sqlite",
                                  with_worker=False, seed_demo=False)
        self.addCleanup(board.bind_store, None)
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}{path}", timeout=15) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_healthz_answers_without_a_session(self):
        status, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["probe"], "healthz")

    def test_readyz_answers_without_a_session(self):
        status, body = self.get("/readyz")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"], body.get("problems"))

    def test_readyz_fails_when_the_database_cannot_be_read(self):
        """A probe that always says yes is decoration.

        "No store bound" is not a state a running server can be in: a request is
        answered from the store of the server that accepted it, so the global is
        restored before the handler runs. The state a platform really hits is a
        store whose database has become unreadable -- a truncated or replaced
        file on the volume -- and the probe has to answer 503 for that so the
        platform stops sending traffic.
        """
        import sqlite3

        # Close the store, then destroy the file it had open, so the next
        # request finds a database it cannot read.
        store = getattr(self.server, "card_store", None)
        self.assertIsNotNone(store)
        try:
            store.conn.close()
        except sqlite3.Error:
            pass
        with open(store.path, "wb") as handle:
            handle.write(b"not a database at all")

        status, body = self.get("/readyz")
        self.assertEqual(status, 503, body)
        self.assertFalse(body["ok"])
        self.assertIn("database_unreadable", body["problems"])

    def test_healthz_still_answers_when_readyz_would_not(self):
        """Liveness and readiness are different questions."""
        status, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_the_probes_say_nothing_about_the_data(self):
        for path in ("/healthz", "/readyz"):
            status, body = self.get(path)
            text = json.dumps(body, ensure_ascii=False)
            for leak in ("board.sqlite", "Synthetic", "trip", "amount",
                         "customer", "rows"):
                self.assertNotIn(leak, text,
                                 f"{path} leaked {leak!r}: {text}")

    def test_a_probe_is_not_cached(self):
        status, _ = self.get("/healthz")
        self.assertEqual(status, 200)
        status, _ = self.get("/healthz")
        self.assertEqual(status, 200)


class ServingDirectlyCannotBypassProductionSafety(unittest.TestCase):
    """P4-6: the entry point, not a default, is what keeps the demo board out."""

    def test_the_entry_point_refuses_to_seed_outside_local_synthetic(self):
        source = (ROOT / "run_candidate.py").read_text(encoding="utf-8")
        self.assertIn('seed_demo=args.environment == "local-synthetic"',
                      source,
                      "the serving entry point must decide the seed flag from "
                      "the declared environment, not from a default")

    def test_the_serve_default_is_still_the_developer_board(self):
        """A developer running the board module directly is not an operator."""
        import inspect

        signature = inspect.signature(board.serve)
        self.assertIs(signature.parameters["seed_demo"].default, True)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="seeddefault-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        server = board.serve(port=0, db_path=tmp / "b.sqlite", with_worker=False)
        try:
            import sqlite3
            conn = sqlite3.connect(str(tmp / "b.sqlite"))
            try:
                rows = conn.execute(
                    "SELECT COUNT(*) FROM board_rows").fetchone()[0]
            finally:
                conn.close()
        finally:
            server.server_close()
            board.bind_store(None)
        self.assertGreater(rows, 0)


class TheVolumeIsNamedWhereAnOperatorWillLook(unittest.TestCase):
    """P4-7: the data root has to be a mounted path, and said so."""

    def test_the_docs_name_the_data_root_variable_and_a_volume_path(self):
        for rel in ("docs/WEB_LEDGER_IMPLEMENTATION_LOG.md",
                    "docs/handoff/2026-09-27/README.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("WEBLEDGER_DATA_ROOT", text,
                          f"{rel} does not name the data root variable")

    def test_the_config_refuses_a_relative_root(self):
        """The first half of the volume contract: no working-directory data."""
        with self.assertRaises(ops.OpsError) as caught:
            ops.DurableConfig(
                data_root=pathlib.Path("relative-root"),
                db_path=pathlib.Path("relative-root/board.sqlite"),
                export_dir=pathlib.Path("relative-root/exports"),
                evidence_dir=pathlib.Path("relative-root/evidence"),
                source_dir=pathlib.Path("relative-root/source"))
        # `data_root` is resolved on the way in, so the refusal names whichever
        # relative path was seen first. Both codes mean the same thing: a
        # working-directory-relative data root.
        self.assertIn(caught.exception.code,
                      ("RELATIVE_DATA_ROOT", "RELATIVE_SETTING"))

    def test_the_start_command_needs_no_directory_argument_from_the_platform(self):
        """The volume arrives as a variable, not as an argument a platform
        cannot know to pass."""
        import run_candidate

        source = (ROOT / "Procfile").read_text(encoding="utf-8").strip()
        self.assertNotIn("--data-root", source,
                         "the start command should take the data root from "
                         "WEBLEDGER_DATA_ROOT, which is what a mounted volume "
                         "provides")


if __name__ == "__main__":
    unittest.main()
