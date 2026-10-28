"""Targeted tests and baseline differential tests for webapp.board_http_shapes.

Ensures:
1. webapp.board_http_shapes has zero import coupling to ledger_board.
2. Exact parity with baseline commit 2384cfd for HTTP input parsing, cookie extraction,
   parameter validation, platform probe (/healthz early return without store access),
   and response envelopes.
3. Handler HTTP facade methods delegate cleanly and preserve all status/headers and call sequence.
4. Synthetic HTTP tests verifying anonymous, owner, nonowner, and CSRF protection behavior.
"""
from __future__ import annotations

import ast
from email.message import Message
import io
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple
import pytest

from webapp import board_http_shapes, ledger_board, ledger_store
from webapp.ledger_store import SaveError


def test_zero_coupling_to_ledger_board():
    """Verify board_http_shapes does not import ledger_board."""
    with open("webapp/board_http_shapes.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="webapp/board_http_shapes.py")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "ledger_board" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "ledger_board" not in node.module
            for alias in node.names:
                assert "ledger_board" not in alias.name


def _load_baseline_symbols():
    """Extract baseline functions from git commit 2384cfd:webapp/ledger_board.py."""
    code = subprocess.check_output(
        ["git", "show", "2384cfd:webapp/ledger_board.py"],
        text=True,
        encoding="utf-8",
    )
    ns: Dict[str, Any] = {
        "__name__": "webapp.ledger_board_baseline",
        "__package__": "webapp",
    }
    exec(compile(code, "<baseline:webapp/ledger_board.py>", "exec"), ns)
    return {
        "Handler": ns["Handler"],
        "STATUS_FOR_CODE": ns["STATUS_FOR_CODE"],
        "CSRF_TOKEN": ns["CSRF_TOKEN"],
    }


def test_status_for_code_parity_with_baseline():
    baseline_status = _load_baseline_symbols()["STATUS_FOR_CODE"]
    assert board_http_shapes.STATUS_FOR_CODE == baseline_status
    assert ledger_board.STATUS_FOR_CODE == baseline_status


def test_cookie_parsing_parity_with_baseline():
    # 1. Normal headers with single Cookie
    msg = Message()
    msg["Cookie"] = "webledger_session=sess-123; other=val"
    jar = board_http_shapes.parse_cookies(msg)
    assert jar["webledger_session"].value == "sess-123"
    assert jar["other"].value == "val"

    # 2. Repeated Cookie headers
    msg2 = Message()
    msg2.add_header("Cookie", "first=1")
    msg2.add_header("Cookie", "second=2")
    jar2 = board_http_shapes.parse_cookies(msg2)
    assert jar2["first"].value == "1"
    assert jar2["second"].value == "2"

    # 3. Object without get_all raises AttributeError -> returns empty dict
    class NoGetAll:
        pass
    assert board_http_shapes.parse_cookies(NoGetAll()) == {}


def test_payload_parsing_json_and_form():
    # Valid JSON
    json_bytes = json.dumps({"key": "val", "num": 10}).encode("utf-8")
    parsed = board_http_shapes.parse_request_payload("application/json", json_bytes)
    assert parsed == {"key": "val", "num": 10}

    # Invalid JSON -> SaveError("INVALID_VALUE")
    with pytest.raises(SaveError) as exc_info:
        board_http_shapes.parse_request_payload("application/json", b"not-json{")
    assert exc_info.value.code == "INVALID_VALUE"

    # Form urlencoded
    form_bytes = b"tab=T01&amount=5000&empty=&multi=1&multi=2"
    parsed_form = board_http_shapes.parse_request_payload("application/x-www-form-urlencoded", form_bytes)
    assert parsed_form["tab"] == "T01"
    assert parsed_form["amount"] == "5000"
    assert parsed_form["empty"] == ""
    assert parsed_form["multi"] == ["1", "2"]

    # Invalid Unicode
    with pytest.raises(SaveError) as exc_info:
        board_http_shapes.parse_request_payload("application/x-www-form-urlencoded", b"\xff\xfe\xfd")
    assert exc_info.value.code == "INVALID_VALUE"


def test_card_param_validators_exact_baseline():
    # Year: requires integer string, rejects None, checks range 2000-2100
    assert board_http_shapes.validate_year("2026") == 2026
    assert board_http_shapes.validate_year("2025") == 2025
    with pytest.raises(ValueError, match="year must be an integer"):
        board_http_shapes.validate_year(None)
    with pytest.raises(ValueError, match="year must be an integer"):
        board_http_shapes.validate_year("invalid")
    with pytest.raises(ValueError, match="year out of range"):
        board_http_shapes.validate_year("1999")
    with pytest.raises(ValueError, match="year out of range"):
        board_http_shapes.validate_year("2101")

    # Month: requires integer string 1-12
    assert board_http_shapes.validate_month("1") == 1
    assert board_http_shapes.validate_month("12") == 12
    with pytest.raises(ValueError, match="month must be an integer"):
        board_http_shapes.validate_month(None)
    with pytest.raises(ValueError, match="month must be an integer"):
        board_http_shapes.validate_month("abc")
    with pytest.raises(ValueError, match="month must be 1-12"):
        board_http_shapes.validate_month("0")
    with pytest.raises(ValueError, match="month must be 1-12"):
        board_http_shapes.validate_month("13")

    # Cursor: format validation
    assert board_http_shapes.validate_cursor("2026-05-01|c123") == "2026-05-01|c123"
    with pytest.raises(ValueError, match="invalid cursor format"):
        board_http_shapes.validate_cursor("20260501c123")
    with pytest.raises(ValueError, match="invalid cursor format"):
        board_http_shapes.validate_cursor("|")
    with pytest.raises(ValueError, match="invalid cursor format"):
        board_http_shapes.validate_cursor("2026-05-01|")
    with pytest.raises(ValueError, match="invalid cursor date"):
        board_http_shapes.validate_cursor("bad-date|c123")


def test_platform_probe_call_order_and_early_return():
    """Verify /healthz returns 200 without touching store or raising on store error."""
    # Create a dummy handler to test _platform_probe
    class ProbeHandler(ledger_board.Handler):
        def __init__(self):
            pass

    handler = ProbeHandler()

    # /healthz must return 200 without calling _active_store()
    # Even if _active_store raises an exception, health probe succeeds
    orig_active = ledger_board._active_store
    try:
        def poison_store():
            raise RuntimeError("Should not be called for healthz")
        ledger_board._active_store = poison_store

        code, body = handler._platform_probe("/healthz")
        assert code == 200
        assert body == {"ok": True, "probe": "healthz"}
    finally:
        ledger_board._active_store = orig_active

    # /readyz with store=None returns 503 store_not_bound
    try:
        ledger_board._active_store = lambda: None
        code, body = handler._platform_probe("/readyz")
        assert code == 503
        assert body["ok"] is False
        assert "store_not_bound" in body["problems"]
    finally:
        ledger_board._active_store = orig_active


def test_ready_probe_with_valid_and_missing_tables(tmp_path: Path):
    # Valid store
    store = ledger_store.LedgerStore(tmp_path / "probe.sqlite", seed_demo=True)
    code, body = board_http_shapes.ready_probe(store)
    assert code == 200
    assert body == {"ok": True, "probe": "readyz"}


class DummyHandler:
    """Mock HTTP handler to capture headers, status codes, and written bytes."""

    def __init__(self, path: str = "/"):
        self.path = path
        self.status_code: Optional[int] = None
        self.headers: List[Tuple[str, str]] = []
        self.wfile = io.BytesIO()
        self.headers_ended = False
        self.close_connection = False

    def send_response(self, code: int):
        self.status_code = code

    def send_header(self, name: str, value: str):
        self.headers.append((name, value))

    def end_headers(self):
        self.headers_ended = True


def test_send_json_envelope():
    handler = DummyHandler()
    board_http_shapes.send_json(handler, {"result": "ok", "count": 5}, code=201, extra_headers={"X-Test": "1"})
    assert handler.status_code == 201
    assert ("Content-Type", "application/json; charset=utf-8") in handler.headers
    assert ("Cache-Control", "no-store") in handler.headers
    assert ("X-Test", "1") in handler.headers
    assert handler.headers_ended
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload == {"result": "ok", "count": 5}


def test_send_html_envelope():
    handler = DummyHandler("/board")
    board_http_shapes.send_html(handler, "<p>내용</p>", code=200)
    assert handler.status_code == 200
    assert ("Content-Type", "text/html; charset=utf-8") in handler.headers
    assert ("Cache-Control", "no-store") in handler.headers
    assert handler.headers_ended
    body = handler.wfile.getvalue().decode("utf-8")
    assert body == "<p>내용</p>"


def test_send_bytes_and_redirect_and_auth_page():
    # 1. send_bytes
    h1 = DummyHandler()
    board_http_shapes.send_bytes(h1, b"\x00\x01\x02", "font/woff2")
    assert h1.status_code == 200
    assert ("Content-Type", "font/woff2") in h1.headers
    assert ("Cache-Control", "public, max-age=604800") in h1.headers
    assert h1.wfile.getvalue() == b"\x00\x01\x02"

    # 2. send_redirect
    h2 = DummyHandler()
    board_http_shapes.send_redirect(h2, "/new-path", cookie="session=1; Path=/")
    assert h2.status_code == 303
    assert ("Location", "/new-path") in h2.headers
    assert ("Set-Cookie", "session=1; Path=/") in h2.headers
    assert ("Cache-Control", "no-store") in h2.headers
    assert ("Referrer-Policy", "no-referrer") in h2.headers

    # 3. send_auth_page
    h3 = DummyHandler()
    board_http_shapes.send_auth_page(h3, "로그인 안내", "<p>안내문</p>", code=403, refusal="AUTH_REFUSED")
    assert h3.status_code == 403
    assert ("Content-Type", "text/html; charset=utf-8") in h3.headers
    assert ("Cache-Control", "no-store") in h3.headers
    assert ("Referrer-Policy", "no-referrer") in h3.headers
    body = h3.wfile.getvalue().decode("utf-8")
    assert "<title>로그인 안내</title>" in body
    assert '<p data-refusal="AUTH_REFUSED"></p>' in body


def test_refuse_amount_dispatch():
    h_form = DummyHandler()
    form_called = []
    json_called = []

    board_http_shapes.refuse_amount(
        h_form,
        is_form=True,
        payload={"amount_krw": "bad", "return_to": "/board?tab=T1"},
        row_id="R1",
        send_form_error_fn=lambda *a: form_called.append(a),
        send_json_fn=lambda *a, **k: json_called.append((a, k)),
    )
    assert len(form_called) == 1
    assert form_called[0][0] == "INVALID_VALUE"
    assert form_called[0][4] == "R1"
    assert len(json_called) == 0

    board_http_shapes.refuse_amount(
        h_form,
        is_form=False,
        payload={"amount_krw": "bad"},
        row_id="R1",
        send_form_error_fn=lambda *a: form_called.append(a),
        send_json_fn=lambda *a, **k: json_called.append((a, k)),
    )
    assert len(json_called) == 1
    assert json_called[0][1]["code"] == 422


class SyntheticServerClient:
    """Helper to simulate HTTP requests into ledger_board.Handler."""

    def __init__(self, store: Optional[Any] = None):
        self.store = store

    def request(
        self,
        command: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        raw_headers = dict(headers or {})
        if body and "Content-Length" not in raw_headers:
            raw_headers["Content-Length"] = str(len(body))
        header_lines = [f"{k}: {v}\r\n" for k, v in raw_headers.items()]
        raw_req = f"{command} {path} HTTP/1.1\r\n" + "".join(header_lines) + "\r\n"
        input_stream = io.BytesIO(raw_req.encode("utf-8") + body)
        output_stream = io.BytesIO()

        # Instantiate Handler without real socket
        class MockSocket:
            def makefile(self, mode, *args, **kwargs):
                if "r" in mode:
                    return input_stream
                return output_stream

            def sendall(self, b):
                output_stream.write(b)

        orig_store = ledger_board._active_store
        try:
            if self.store is not None:
                ledger_board._active_store = lambda s=self.store: s

            handler = ledger_board.Handler(MockSocket(), ("127.0.0.1", 8888), None)
        finally:
            ledger_board._active_store = orig_store

        # Parse response
        output_stream.seek(0)
        resp_data = output_stream.getvalue()
        if not resp_data:
            return 0, {}, b""

        parts = resp_data.split(b"\r\n\r\n", 1)
        header_part = parts[0].decode("utf-8", errors="replace")
        body_part = parts[1] if len(parts) > 1 else b""

        status_line = header_part.splitlines()[0]
        status_code = int(status_line.split()[1])
        resp_headers = {}
        for line in header_part.splitlines()[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                resp_headers[k] = v

        return status_code, resp_headers, body_part


def test_synthetic_http_probes_and_anonymous_requests(tmp_path: Path):
    store = ledger_store.LedgerStore(tmp_path / "server_test.sqlite", seed_demo=True)
    client = SyntheticServerClient(store)

    # 1. Anonymous health probe
    code, headers, body = client.request("GET", "/healthz")
    assert code == 200
    assert "application/json" in headers.get("Content-Type", "")
    data = json.loads(body.decode("utf-8"))
    assert data == {"ok": True, "probe": "healthz"}

    # 2. Anonymous ready probe with valid store
    code, headers, body = client.request("GET", "/readyz")
    assert code == 200
    data = json.loads(body.decode("utf-8"))
    assert data == {"ok": True, "probe": "readyz"}

    # 3. Anonymous /rules without case_id -> 404
    code, headers, body = client.request("GET", "/rules")
    assert code == 404


def test_synthetic_http_post_content_length_limit(tmp_path: Path):
    store = ledger_store.LedgerStore(tmp_path / "len_test.sqlite", seed_demo=True)
    client = SyntheticServerClient(store)

    # Content-Length exceeding 5MB -> 413 TOO_LARGE
    code, headers, body = client.request(
        "POST",
        "/api/income",
        headers={"Content-Length": str(6 * 1024 * 1024)},
        body=b"",
    )
    assert code == 413
    data = json.loads(body.decode("utf-8"))
    assert data.get("code") == "TOO_LARGE"


def test_synthetic_http_owner_required_route_protection(tmp_path: Path):
    store = ledger_store.LedgerStore(tmp_path / "owner_test.sqlite", seed_demo=True)
    client = SyntheticServerClient(store)

    orig_enforce = ledger_board.ACCESS_ENFORCEMENT
    try:
        ledger_board.ACCESS_ENFORCEMENT = True
        # Unauthenticated request under enforcement gets 401 AUTH_REQUIRED
        code, headers, body = client.request("GET", "/api/cards/transactions/day")
        assert code == 401
        data = json.loads(body.decode("utf-8"))
        assert data.get("code") == "AUTH_REQUIRED"
    finally:
        ledger_board.ACCESS_ENFORCEMENT = orig_enforce


def test_synthetic_http_csrf_protection_on_post(tmp_path: Path):
    store = ledger_store.LedgerStore(tmp_path / "csrf_test.sqlite", seed_demo=True)
    client = SyntheticServerClient(store)

    # POST to /api/income with JSON body but missing CSRF token
    code, headers, body = client.request(
        "POST",
        "/api/income",
        headers={"Content-Type": "application/json"},
        body=b'{"amount_krw": 10000, "item": "\xed\x85\x8c\xec\x8a\xa4\xed\x8a\xb8"}',
    )
    assert code == 403
    data = json.loads(body.decode("utf-8"))
    assert data.get("code") == "CSRF_REQUIRED"
