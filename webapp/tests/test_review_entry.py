"""LOCAL-HOST-002 tests for the loopback review entry page and its startup files.

Synthetic only. Nothing here reads a real source, a real configuration file or a
real credential: the entry server has no file to read, and the PowerShell files
are parsed as text, which is the only thing that can be done to them from here —
they are prepared for an operator to install, not installed by this worker.

`tools/serve_review.py` is the legacy local review server and is deliberately not
covered here: its contract is unchanged, so its behaviour is not this task's to
re-assert.
"""

from __future__ import annotations

import http.client
import json
import pathlib
import subprocess
import sys
import threading
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import serve_review_entry as entry

HOST = "127.0.0.1"


class EntryServerTests(unittest.TestCase):
    """One loopback server, answered over a real socket."""

    def setUp(self):
        self.server = entry.create_entry_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path="/", host=None, method="GET", raw_target=None):
        """A real request, so the assertions are about the wire and not a stub."""
        connection = http.client.HTTPConnection(HOST, self.port, timeout=10)
        self.addCleanup(connection.close)
        target = raw_target if raw_target is not None else path
        headers = {"Host": f"{host}:{self.port}" if host is not None
                   else f"127.0.0.1:{self.port}"}
        connection.request(method, target, headers=headers)
        response = connection.getresponse()
        body = response.read()
        return response, body

    def test_the_root_redirects_to_the_published_review_screen(self):
        response, _body = self.request("/")
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"),
                         "https://ledger.foresttour.kr/review")

    def test_localhost_is_accepted_as_well_as_the_address(self):
        """The two names a person actually types both work.

        Someone reaching for `localhost:8781` and someone reaching for
        `127.0.0.1:8781` are on the same machine and want the same answer, and
        refusing the first would just send them to the wrong thing.
        """
        for name in ("localhost", "127.0.0.1"):
            with self.subTest(host=name):
                response, _body = self.request("/", host=name)
                self.assertEqual(response.status, 302)
                self.assertEqual(response.getheader("Location"),
                                 entry.REVIEW_URL)

    def test_another_host_name_is_refused_and_gets_no_redirect(self):
        """A `Host` is written by the caller, so it cannot be what decides.

        Without this check any page that could reach this port could get an
        answer shaped like this server's, on a name of its own choosing.
        """
        response, body = self.request("/", host="evil.example")
        self.assertEqual(response.status, 403)
        self.assertEqual(json.loads(body)["error"]["code"],
                         entry.CODE_HOST_MISMATCH)
        self.assertIsNone(response.getheader("Location"))

    def test_the_port_is_part_of_the_host_that_must_match(self):
        """`localhost` alone, or a different port, is not this server.

        A Host of `localhost` with no port is a different origin to
        `localhost:8781`, and one carrying a live session elsewhere is the
        reason the port is checked rather than just the name.
        """
        connection = http.client.HTTPConnection(HOST, self.port, timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/", headers={"Host": "localhost"})
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 403)

    def test_an_absolute_form_request_for_another_origin_is_refused(self):
        """The target in the request line is not a way around the Host check.

        A proxy-style request line names a host of its own. It is answered here
        as the unknown path it is, and never as a redirect.
        """
        response, _body = self.request(
            raw_target="http://evil.example/anything")
        self.assertIn(response.status, (403, 404))
        self.assertIsNone(response.getheader("Location"))

    def test_only_the_root_is_served(self):
        """Everything else is a 404, which is what makes this a door.

        There is no route that could stand in for the published API and no route
        that could serve review data. `/review` in particular is not an alias for
        the redirect: the destination is one fixed URL, reached the one way.
        """
        for path in ("/review", "/api/review/model", "/api/model", "/index.html",
                     "/?next=https://evil.example", "/../webapp/ledger_board.py"):
            with self.subTest(path=path):
                response, body = self.request(path)
                self.assertEqual(response.status, 404, path)
                self.assertEqual(json.loads(body)["error"]["code"],
                                 entry.CODE_UNKNOWN_PATH, path)
                self.assertIsNone(response.getheader("Location"), path)

    def test_the_destination_cannot_be_chosen_by_the_request(self):
        """No query, no header and no environment value picks the target.

        A redirect whose destination can be supplied is an open redirect, and on
        a loopback port that is still a way to send a browser somewhere a
        developer trusts because it came from their own machine. The target is a
        constant, so the only way to change it is to change this file.
        """
        for path in ("/?next=https://evil.example",
                     "/?url=https://evil.example",
                     "/?redirect_to=https://evil.example"):
            with self.subTest(path=path):
                response, _body = self.request(path)
                self.assertNotEqual(response.status, 200, path)
                if response.status == 302:
                    self.assertEqual(response.getheader("Location"),
                                     entry.REVIEW_URL, path)
        self.assertEqual(entry.REVIEW_URL,
                         "https://ledger.foresttour.kr/review")
        self.assertNotIn("evil", entry.REVIEW_URL)

    def test_nothing_but_get_is_answered(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                response, body = self.request("/", method=method)
                self.assertEqual(response.status, 405, method)
                self.assertEqual(json.loads(body)["error"]["code"],
                                 entry.CODE_METHOD_NOT_ALLOWED, method)

    def test_every_answer_is_no_store(self):
        """A cached redirect would outlive the decision to come back.

        A browser that stored the 302 would keep sending the user to the
        published screen after they had closed it, and no reload would fix it.
        """
        for path, host, expected in (("/", None, 302),
                                     ("/review", None, 404),
                                     ("/", "evil.example", 403)):
            with self.subTest(path=path, host=host):
                response, _body = self.request(path, host=host)
                self.assertEqual(response.status, expected)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_it_sets_no_cookie(self):
        """Nothing to log in here, so nothing to remember either.

        There is no account on this port and no session to keep. A `Set-Cookie`
        here would be a cookie for a screen that holds nothing, and it would
        follow the user to whatever the redirect points at.
        """
        response, _body = self.request("/")
        self.assertIsNone(response.getheader("Set-Cookie"))

    def test_it_binds_loopback_only(self):
        """The address it listens on is loopback, and cannot be changed.

        A bind flag would be a publish switch, so there is not one. The
        localhost names it accepts are the two that name this machine, and the
        module has no other.
        """
        self.assertEqual(entry.BIND_HOST, "127.0.0.1")
        self.assertEqual(entry.ALLOWED_HOSTNAMES, ("localhost", "127.0.0.1"))
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


class PortCollisionTests(unittest.TestCase):
    def test_a_port_already_in_use_is_refused_rather_than_shared(self):
        """A collision must be loud, because sharing it would be invisible.

        With reuse allowed, a second process would bind the same port and the two
        would answer for `http://127.0.0.1:<port>` between them. The user would
        get an answer from a program they did not choose and would have no way to
        tell. So the second bind is refused, and the operator decides.
        """
        first = entry.create_entry_server(0)
        self.addCleanup(first.server_close)
        port = first.server_address[1]
        self.assertFalse(entry.EntryServer.allow_reuse_address)
        with self.assertRaises(OSError):
            entry.create_entry_server(port)

    def test_the_cli_reports_a_busy_port_with_a_code_of_its_own(self):
        """"The port is taken" and "the arguments were wrong" are different."""
        first = entry.create_entry_server(0)
        self.addCleanup(first.server_close)
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "serve_review_entry.py"),
             "--port", str(first.server_address[1])],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["error"]["code"],
                         entry.CODE_PORT_IN_USE)

    def test_an_out_of_range_port_is_refused_before_binding(self):
        for port in (-1, 65536, "8781", True):
            with self.subTest(port=port):
                with self.assertRaises(entry.EntryError) as caught:
                    entry.create_entry_server(port)
                self.assertEqual(caught.exception.code,
                                 entry.CODE_INVALID_ARGUMENT)


if __name__ == "__main__":
    unittest.main()
