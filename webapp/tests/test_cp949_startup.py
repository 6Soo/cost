"""Windows cp949 console startup regression.

Confirmed failure (LOG 2026-09-30): `run_candidate.py` startup prints raised
`UnicodeEncodeError` on a cp949 console because fixed literals contained
U+2014 EM DASH, which cp949 cannot encode. The production readiness gate is
unchanged; only the fixed startup wording must stay cp949-encodable.
"""
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import run_candidate  # noqa: E402


def assert_cp949_encodable(text: str, label: str) -> None:
    try:
        text.encode("cp949")
    except UnicodeEncodeError as exc:
        raise AssertionError(
            f"{label} is not cp949-encodable: {ascii(text)} ({exc})"
        ) from exc


class Cp949StartupTest(unittest.TestCase):
    def test_fixed_startup_source_has_no_non_cp949_chars(self):
        source = (ROOT / "run_candidate.py").read_text(encoding="utf-8")
        bad = sorted({c for c in source if not _encodable(c)})
        self.assertEqual(
            bad, [],
            f"run_candidate.py has non-cp949 fixed chars: "
            f"{[f'U+{ord(c):04X}' for c in bad]}",
        )

    def test_bind_shape_line_uses_ascii_separator(self):
        source = (ROOT / "run_candidate.py").read_text(encoding="utf-8")
        self.assertNotIn("\u2014", source)
        # The fixed startup separator must be ASCII so a cp949 console
        # can print it; dynamic note text is covered by the source scan.
        self.assertIn('bind shape: {bind[\'shape\']} - {bind[\'note\']}', source)

    def test_describe_oidc_unconnected_is_cp949_encodable(self):
        text = run_candidate.describe_oidc(None)
        assert_cp949_encodable(text, "describe_oidc(None)")
        self.assertNotIn("\u2014", text)


class Cp949SubprocessSmokeTest(unittest.TestCase):
    """The startup lines must survive a real cp949 stdout pipe.

    The in-process checks above prove the strings are encodable. This
    test proves they actually print: the child runs with
    ``PYTHONIOENCODING=cp949:strict`` so a non-encodable character
    raises ``UnicodeEncodeError`` and fails the child instead of being
    replaced silently. The child only formats read-only strings and
    never touches a data root, a port, or any production setting.
    """

    def test_startup_lines_print_under_cp949_strict_stdout(self):
        child = (
            "import sys; sys.path.insert(0, " + repr(str(ROOT)) + "); "
            "import run_candidate; "
            "from webapp import ops; "
            "bind = ops.require_safe_bind('127.0.0.1'); "
            "print('bind shape: ' + bind['shape'] + ' - ' + bind['note']); "
            "print('google login: ' + run_candidate.describe_oidc(None))"
        )
        env = {**os.environ, "PYTHONIOENCODING": "cp949:strict"}
        env.pop("PYTHONUTF8", None)
        proc = subprocess.run(
            [sys.executable, "-c", child],
            capture_output=True,
            cwd=str(ROOT),
            env=env,
            timeout=60,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "startup lines failed under cp949 stdout: "
            + proc.stderr.decode("cp949", errors="replace"),
        )
        out = proc.stdout.decode("cp949")
        self.assertIn("bind shape:", out)
        self.assertIn("google login:", out)


class Cp949LiveServerSmokeTest(unittest.TestCase):
    """A real run_candidate.py server under a cp949 console.

    Starts the entry point with a TemporaryDirectory data root on
    loopback with a free port (local-synthetic, synthetic sessions, no
    worker). The child runs with ``PYTHONIOENCODING=cp949:strict`` and
    without ``PYTHONUTF8`` so a non-encodable startup print crashes the
    child instead of passing silently. ``/healthz`` and ``/readyz`` must
    both answer 200/ok then the parent sends one ASCII shutdown line on
    stdin; a daemon helper thread in the child turns it into
    ``KeyboardInterrupt`` in the main thread, exercising the existing
    ``KeyboardInterrupt`` -> finally cleanup -> return 0 path with no
    product change. The listener must reach zero afterwards.
    """

    def test_cp949_server_serves_then_stops_with_no_listener(self):
        import json
        import socket
        import tempfile
        import time
        import urllib.error
        import urllib.request

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        finally:
            probe.close()

        with tempfile.TemporaryDirectory(prefix="cp949-live-") as data_root:
            env = {**os.environ, "PYTHONIOENCODING": "cp949:strict"}
            env.pop("PYTHONUTF8", None)
            argv = [
                "--data-root", data_root,
                "--port", str(port),
                "--host", "127.0.0.1",
                "--environment", "local-synthetic",
                "--synthetic-sessions",
                "--no-worker",
            ]
            child = "\n".join([
                "import sys, threading, _thread",
                f"sys.path.insert(0, {str(ROOT)!r})",
                "import run_candidate",
                # Windows 확장 모듈 초기화가 stdin 대기 스레드와 경합하지 않게 한다.
                "import app",
                "def _wait_shutdown():",
                "    try:",
                "        sys.stdin.buffer.readline()",
                "    except Exception:",
                "        return",
                "    _thread.interrupt_main()",
                "threading.Thread(target=_wait_shutdown, daemon=True).start()",
                f"raise SystemExit(run_candidate.main({argv!r}))",
            ])
            cmd = [sys.executable, "-u", "-c", child]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(ROOT),
                env=env,
            )
            try:
                deadline = time.time() + 45
                health_ok = False
                ready_ok = False
                last = ""
                while time.time() < deadline:
                    if proc.poll() is not None:
                        rest = proc.stdout.read().decode("cp949", errors="replace")
                        self.fail(
                            f"child exited early with {proc.poll()}: {rest}"
                        )
                    for path, flag in (("/healthz", "health"), ("/readyz", "ready")):
                        try:
                            with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}{path}", timeout=5
                            ) as response:
                                body = json.loads(response.read().decode("utf-8"))
                        except Exception as exc:  # noqa: BLE001 - probe and retry
                            last = f"{path}: {exc!r}"
                            continue
                        if response.status == 200 and body.get("ok"):
                            if flag == "health":
                                health_ok = True
                            else:
                                ready_ok = True
                        else:
                            last = f"{path}: {response.status} {body!r}"
                    if health_ok and ready_ok:
                        break
                    time.sleep(0.5)
                self.assertTrue(health_ok, f"/healthz never 200/ok: {last}")
                self.assertTrue(ready_ok, f"/readyz never 200/ok: {last}")

                proc.stdin.write(b"stop\n")
                proc.stdin.flush()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/healthz", timeout=3
                        ) as probe_response:
                            probe_body = probe_response.read().decode(
                                "utf-8", errors="replace"
                            )
                            post_event = (
                                "health-after-event: HTTP "
                                f"{probe_response.status} {probe_body[:200]}"
                            )
                    except Exception as exc:  # noqa: BLE001 - diagnostic only
                        post_event = (
                            "health-after-event: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    proc.kill()
                    rest = proc.stdout.read().decode("cp949", errors="replace")
                    self.fail(
                        "child did not stop within 20s of the stdin line; "
                        + post_event
                        + "; partial output: "
                        + rest
                    )
                exit_code = proc.returncode
                self.assertEqual(
                    exit_code,
                    0,
                    f"child exit code was {exit_code}, want 0",
                )
                self.assertIsNotNone(
                    proc.poll(),
                    "child still alive after the stdin shutdown line",
                )
                try:
                    conn = socket.create_connection(
                        ("127.0.0.1", port), timeout=5
                    )
                except OSError:
                    pass
                else:
                    conn.close()
                    self.fail(
                        f"listener still up on 127.0.0.1:{port} "
                        f"after child exit (exit={exit_code})"
                    )
                out = proc.stdout.read().decode("cp949")
                self.assertIn("bind shape:", out)
                self.assertIn("google login:", out)
            finally:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except OSError:
                    pass
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=10)


def _encodable(ch: str) -> bool:
    try:
        ch.encode("cp949")
        return True
    except UnicodeEncodeError:
        return False


if __name__ == "__main__":
    unittest.main()
