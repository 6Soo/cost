"""LOCAL-HOST-002 loopback-only entry page for the web ledger.

A developer who has the legacy local review port open gets sent to the real
published review screen, and to nothing else. This process is a door, not a
server: it holds no data, reads no file, sets no cookie, and proxies no API.

That narrowness is the whole point, so each of these is enforced rather than
merely intended:

* It binds loopback only, so it is not reachable from the network.
* It answers only ``GET /``. Every other path is a 404, which means there is no
  route to proxy the published API through, and no path to reach the review data
  with. The redirect target is a module constant, so a request cannot choose it:
  an open redirect here would be a way off this origin with a crafted link, and
  the one thing a door should not do.
* The ``Host`` header must be ``localhost`` or ``127.0.0.1`` on the port this
  server is actually listening on. Without that check the answer would depend on
  a header the caller writes.
* ``allow_reuse_address`` is off. A port already in use is a refusal to start,
  not a reason to share the port, because sharing it silently would mean this
  process and something else are both answering for ``http://127.0.0.1:<port>``
  and nobody would know which one a user got.

Stdlib only. ``tools/serve_review.py`` is the legacy local review server and is
untouched: this does not replace it, it only sends people from its port to the
published screen.

This worker is not authorised to run against the real deployment, so the
PowerShell files beside it are prepared and not installed; see
``TASK_RESULT_LOCAL_HOST.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__all__ = [
    "EntryServer",
    "EntryError",
    "create_entry_server",
    "main",
    "BIND_HOST",
    "REVIEW_URL",
    "ALLOWED_HOSTNAMES",
]

#: Loopback and nothing else. There is no option to widen this, on purpose: a
#: flag to change the bind address is a flag to publish a redirect server.
BIND_HOST = "127.0.0.1"

#: The one destination, fixed at build time. Not read from the request, the
#: environment or a config file, because every one of those is writable by
#: something that is not this process.
REVIEW_URL = "https://ledger.foresttour.kr/review"

#: Host names that name this machine. Anything else is a refusal, so a page
#: reached by an unexpected name cannot get a redirect out of this port.
ALLOWED_HOSTNAMES = ("localhost", "127.0.0.1")

CODE_HOST_MISMATCH = "HOST_MISMATCH"
CODE_UNKNOWN_PATH = "UNKNOWN_PATH"
CODE_METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
CODE_INVALID_ARGUMENT = "INVALID_ARGUMENT"
CODE_PORT_IN_USE = "PORT_IN_USE"


class EntryError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class EntryServer(ThreadingHTTPServer):
    """Loopback-only, and deliberately not willing to share its port."""

    daemon_threads = True
    allow_reuse_address = False


class _EntryHandler(BaseHTTPRequestHandler):
    server_version = "ReviewEntry"
    sys_version = ""

    def log_message(self, *args):
        return None

    def log_error(self, *args):
        return None

    # ------------------------------------------------------------- answering
    def _port(self):
        return self.server.server_address[1]

    def _expected_hosts(self):
        return {f"{name}:{self._port()}" for name in ALLOWED_HOSTNAMES}

    def _send(self, status, body=b"", content_type="application/json",
              location=None):
        self.send_response(status)
        if location is not None:
            self.send_header("Location", location)
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The answer is the same for everyone and is not about anyone, so it is
        # never stored: a cached 302 would keep sending a browser to the
        # published screen after the user decided to come back to this port.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _deny(self, status, code):
        payload = json.dumps({"error": {"code": code}}, sort_keys=True)
        self._send(status, payload.encode("utf-8"))

    def _refuse_method(self):
        # One answer for every verb, and no Allow list, because there is nothing
        # here to POST to and naming the methods would only invite a retry.
        self._deny(405, CODE_METHOD_NOT_ALLOWED)

    def _guard_host(self):
        if self.headers.get("Host") not in self._expected_hosts():
            self._deny(403, CODE_HOST_MISMATCH)
            return False
        return True

    # ------------------------------------------------------------------ wire
    def do_GET(self):
        if not self._guard_host():
            return
        # Only the root. `/review`, `/api/...`, and anything else is a 404, so
        # this port cannot be used as a second way in to the published screen or
        # as a proxy in front of it.
        if self.path != "/":
            self._deny(404, CODE_UNKNOWN_PATH)
            return
        self._send(302, location=REVIEW_URL)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self._refuse_method()

    def do_PUT(self):
        self._refuse_method()

    def do_PATCH(self):
        self._refuse_method()

    def do_DELETE(self):
        self._refuse_method()

    def do_OPTIONS(self):
        self._refuse_method()


def create_entry_server(port=0):
    """Bind the entry page on loopback.

    A port that is already taken is refused rather than shared, and `OSError` is
    left to the caller so the refusal is the one the operating system made, not
    one this file invented.
    """
    if type(port) is not int or isinstance(port, bool) or not 0 <= port <= 65535:
        raise EntryError(CODE_INVALID_ARGUMENT)
    return EntryServer((BIND_HOST, port), _EntryHandler)


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="serve_review_entry",
        description=("Redirect a local review port to the published review "
                     "screen. Serves nothing else."))
    parser.add_argument("--port", type=int, default=8781,
                        help="Loopback port. Default 8781. Refused if in use.")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        server = create_entry_server(args.port)
    except EntryError as exc:
        sys.stdout.write(json.dumps({"error": {"code": exc.code}},
                                    sort_keys=True) + "\n")
        return 2
    except OSError:
        # A busy port is a refusal with a name of its own, because the operator
        # needs to tell "the port is taken" from "the arguments were wrong".
        sys.stdout.write(json.dumps({"error": {"code": CODE_PORT_IN_USE}},
                                    sort_keys=True) + "\n")
        return 2
    sys.stdout.write(json.dumps(
        {"listening": {"host": BIND_HOST, "port": server.server_address[1]},
         "redirects_to": REVIEW_URL}, sort_keys=True) + "\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
