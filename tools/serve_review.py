"""REVIEW-UI-001 local review server, core writer scope.

Stdlib only. Reads exactly three input files, verifies SHA-256 bindings
before and after startup and immediately before and after every export,
and serves the static review screen with a same-origin JSON API.

Wire: GET / serves render_review_ui HTML. GET /api/model serves the
model plus a per-server CSRF nonce. POST /api/export requires exact Host
on every request plus exact Origin, X-Review-CSRF and Content-Type
application/json, then runs the core export against sealed startup
inputs. Exports stay in memory. Input files are never written.

Every refusal is a fixed value-free code. Nothing received is logged.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from webapp.contracts import sha256_bytes, sha256_text
from webapp.review_context import ReviewContextError, build_review_context, build_review_export
from webapp.review_ui import render_review_ui

__all__ = [
    "ServerError",
    "ReviewServer",
    "create_review_server",
    "main",
    "MAX_BODY_BYTES",
    "BIND_HOST",
]

BIND_HOST = "127.0.0.1"
MAX_BODY_BYTES = 2 * 1024 * 1024

CODE_INVALID_ARGUMENT = "INVALID_ARGUMENT"
CODE_INVALID_SHA256 = "INVALID_SHA256"
CODE_INPUT_NOT_FOUND = "INPUT_NOT_FOUND"
CODE_INPUT_UNREADABLE = "INPUT_UNREADABLE"
CODE_INPUT_ENCODING_INVALID = "INPUT_ENCODING_INVALID"
CODE_INPUT_HASH_MISMATCH = "INPUT_HASH_MISMATCH"
CODE_HOST_MISMATCH = "HOST_MISMATCH"
CODE_ORIGIN_MISMATCH = "ORIGIN_MISMATCH"
CODE_CSRF_MISMATCH = "CSRF_MISMATCH"
CODE_CONTENT_TYPE_MISMATCH = "CONTENT_TYPE_MISMATCH"
CODE_BODY_TOO_LARGE = "BODY_TOO_LARGE"
CODE_MALFORMED_BODY = "MALFORMED_BODY"
CODE_DECISION_SHAPE_INVALID = "DECISION_SHAPE_INVALID"
CODE_UNKNOWN_PATH = "UNKNOWN_PATH"
CODE_METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
CODE_INPUT_DRIFT = "INPUT_DRIFT"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"


class ServerError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _is_hex64(value):
    if type(value) is not str or len(value) != 64:
        return False
    for char in value:
        if char not in "0123456789abcdefABCDEF":
            return False
    return True


def _read_exact(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        raise ServerError(CODE_INPUT_NOT_FOUND)
    except OSError:
        raise ServerError(CODE_INPUT_UNREADABLE)


def _decode_utf8(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ServerError(CODE_INPUT_ENCODING_INVALID)


def _fingerprint(raw):
    return {"sha256": sha256_bytes(raw), "size": len(raw)}


def _load_inputs(snapshot_path, review_path, master_path):
    snapshot_bytes = _read_exact(snapshot_path)
    review_raw = _read_exact(review_path)
    master_raw = _read_exact(master_path)
    review_text = _decode_utf8(review_raw)
    master_text = _decode_utf8(master_raw)
    return {
        "snapshot_bytes": snapshot_bytes,
        "review_text": review_text,
        "master_text": master_text,
        "fingerprints": {
            "snapshot": _fingerprint(snapshot_bytes),
            "review": _fingerprint(review_raw),
            "master": _fingerprint(master_raw),
        },
    }


def create_review_server(snapshot_path, review_path, master_path,
                         snapshot_sha256, review_sha256, master_sha256,
                         port=0):
    for path in (snapshot_path, review_path, master_path):
        if type(path) is not str or path == "":
            raise ServerError(CODE_INVALID_ARGUMENT)
    for digest in (snapshot_sha256, review_sha256, master_sha256):
        if not _is_hex64(digest):
            raise ServerError(CODE_INVALID_SHA256)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ServerError(CODE_INVALID_ARGUMENT)
    inputs = _load_inputs(snapshot_path, review_path, master_path)
    if sha256_bytes(inputs["snapshot_bytes"]) != snapshot_sha256:
        raise ServerError(CODE_INPUT_HASH_MISMATCH)
    if sha256_text(inputs["review_text"]) != review_sha256:
        raise ServerError(CODE_INPUT_HASH_MISMATCH)
    if sha256_text(inputs["master_text"]) != master_sha256:
        raise ServerError(CODE_INPUT_HASH_MISMATCH)
    try:
        model = build_review_context(
            inputs["snapshot_bytes"], inputs["review_text"],
            inputs["master_text"], snapshot_sha256, review_sha256,
            master_sha256)
    except ReviewContextError as exc:
        raise ServerError(exc.code)
    state = {
        "paths": (snapshot_path, review_path, master_path),
        "fingerprints": inputs["fingerprints"],
        "snapshot_bytes": inputs["snapshot_bytes"],
        "review_text": inputs["review_text"],
        "master_text": inputs["master_text"],
        "model": model,
        "nonce": secrets.token_urlsafe(32),
        "ui_html": render_review_ui().encode("utf-8"),
    }
    server = ReviewServer((BIND_HOST, port), _ReviewHandler)
    server.review_state = state
    if not _fingerprints_match(state):
        try:
            server.server_close()
        finally:
            raise ServerError(CODE_INPUT_DRIFT)
    return server


def _fingerprints_match(state):
    try:
        current = _load_inputs(*state["paths"])
    except ServerError:
        return False
    return current["fingerprints"] == state["fingerprints"]


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


_Q = chr(39)
_CSP = (
    "default-src " + _Q + "none" + _Q + "; "
    "script-src " + _Q + "unsafe-inline" + _Q + "; "
    "style-src " + _Q + "unsafe-inline" + _Q + "; "
    "connect-src " + _Q + "self" + _Q + "; "
    "img-src " + _Q + "none" + _Q + "; "
    "font-src " + _Q + "none" + _Q + "; "
    "object-src " + _Q + "none" + _Q + "; "
    "base-uri " + _Q + "none" + _Q + "; "
    "form-action " + _Q + "none" + _Q + "; "
    "frame-ancestors " + _Q + "none" + _Q
)


def _security_headers(handler):
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Content-Security-Policy", _CSP)


class _ReviewHandler(BaseHTTPRequestHandler):
    server_version = "ReviewUI"
    sys_version = ""

    def log_message(self, *args):
        return None

    def log_error(self, *args):
        return None

    def _state(self):
        return self.server.review_state

    def _expected_host(self):
        return BIND_HOST + ":" + str(self.server.server_address[1])

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        _security_headers(self)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_html(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        _security_headers(self)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _deny(self, status, code):
        self._send_json(status, {"error": {"code": code}})

    def _guard_host(self):
        if self.headers.get("Host") != self._expected_host():
            self._deny(403, CODE_HOST_MISMATCH)
            return False
        return True

    def do_GET(self):
        if not self._guard_host():
            return
        if self.path == "/":
            self._send_html(200, self._state()["ui_html"])
        elif self.path == "/api/model":
            state = self._state()
            model = state["model"]
            self._send_json(200, {
                "snapshotsha": model["snapshotsha"],
                "reviewsha": model["reviewsha"],
                "mastersha": model["mastersha"],
                "rows": model["rows"],
                "csrf_nonce": state["nonce"],
            })
        else:
            self._deny(404, CODE_UNKNOWN_PATH)

    def do_POST(self):
        if not self._guard_host():
            return
        if self.path != "/api/export":
            self._deny(404, CODE_UNKNOWN_PATH)
            return
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._deny(415, CODE_CONTENT_TYPE_MISMATCH)
            return
        try:
            declared = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            declared = 0
        if declared < 0:
            declared = 0
        if declared > MAX_BODY_BYTES:
            self._deny(413, CODE_BODY_TOO_LARGE)
            return
        try:
            body = self.rfile.read(declared) if declared else b""
        except Exception:
            self._deny(400, CODE_MALFORMED_BODY)
            return
        if len(body) > MAX_BODY_BYTES:
            self._deny(413, CODE_BODY_TOO_LARGE)
            return
        state = self._state()
        if self.headers.get("Origin") != "http://" + self._expected_host():
            self._deny(403, CODE_ORIGIN_MISMATCH)
            return
        token = self.headers.get("X-Review-CSRF") or ""
        try:
            csrf_ok = hmac.compare_digest(token, state["nonce"])
        except Exception:
            csrf_ok = False
        if not csrf_ok:
            self._deny(403, CODE_CSRF_MISMATCH)
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._deny(400, CODE_MALFORMED_BODY)
            return
        if type(payload) is not dict or type(payload.get("decisions")) is not list:
            self._deny(400, CODE_DECISION_SHAPE_INVALID)
            return
        if not _fingerprints_match(state):
            self._deny(409, CODE_INPUT_DRIFT)
            return
        try:
            result = build_review_export(state["model"], state["review_text"], payload["decisions"])
        except ReviewContextError as exc:
            self._deny(400, exc.code)
            return
        except Exception:
            self._deny(500, CODE_INTERNAL_ERROR)
            return
        if not _fingerprints_match(state):
            self._deny(409, CODE_INPUT_DRIFT)
            return
        self._send_json(200, {
            "decision_csv": result["decision_csv"],
            "plan_json": json.dumps(result["plan_json"], ensure_ascii=False, sort_keys=True),
            "counts": result["counts"],
            "plan_digest": result["plan_digest"],
        })

    def do_PUT(self):
        if self._guard_host():
            self._deny(405, CODE_METHOD_NOT_ALLOWED)

    def do_DELETE(self):
        if self._guard_host():
            self._deny(405, CODE_METHOD_NOT_ALLOWED)

    def do_PATCH(self):
        if self._guard_host():
            self._deny(405, CODE_METHOD_NOT_ALLOWED)

    def do_OPTIONS(self):
        if self._guard_host():
            self._deny(405, CODE_METHOD_NOT_ALLOWED)

    def do_HEAD(self):
        if self._guard_host():
            self._deny(405, CODE_METHOD_NOT_ALLOWED)


class _CliError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _CliError(CODE_INVALID_ARGUMENT)


def _build_parser():
    parser = _Parser(
        prog="serve_review",
        description="Serve the local review UI for one sealed snapshot.")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--master", required=True)
    parser.add_argument("--master-sha256", required=True)
    parser.add_argument("--port", type=int, default=0)
    return parser


def _fail_cli(code):
    sys.stdout.write(json.dumps({"error": {"code": code}}, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 2


def main(argv=None):
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _CliError as exc:
        return _fail_cli(exc.code)
    try:
        server = create_review_server(
            args.snapshot, args.review, args.master,
            args.snapshot_sha256, args.review_sha256, args.master_sha256,
            args.port)
    except ServerError as exc:
        return _fail_cli(exc.code)
    except Exception:
        return _fail_cli(CODE_INTERNAL_ERROR)
    port = server.server_address[1]
    sys.stdout.write(json.dumps({"listening": {"host": BIND_HOST, "port": port}}, sort_keys=True) + "\n")
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
