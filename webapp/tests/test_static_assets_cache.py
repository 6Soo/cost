"""Hashed static CSS/JS: cache headers, hash changes with content, served outside store_lock."""

import io
import re
import threading
from types import SimpleNamespace
from unittest.mock import patch

from webapp import ledger_board, ledger_design, site_shell, static_assets


class _Handler:
    def __init__(self):
        self.code = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


def _get(path):
    handler = _Handler()
    assert static_assets.dispatch(handler, path) is True
    return handler


def test_hashed_url_is_immutable_and_serves_bundle_bytes():
    url = static_assets.url("css", "ledger_design")
    assert re.fullmatch(r"/static/css/ledger_design\.[0-9a-f]{8}\.css", url)
    handler = _get(url)
    assert handler.code == 200
    assert handler.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert handler.headers["Content-Type"].startswith("text/css")
    assert handler.wfile.getvalue() == ledger_design.STYLE.encode("utf-8")


def test_stale_hash_is_never_cached_long_and_unknown_is_404():
    stale = _get("/static/js/site_shell.00000000.js")
    assert stale.code == 200 and stale.headers["Cache-Control"] == "no-store"
    assert _get("/static/css/nope.12345678.css").code == 404
    assert _get("/static/../ledger_board.py").code == 404
    assert _get("/static/css/ledger_design.12345678.js").code == 404


def test_tokens_import_target_no_longer_404():
    handler = _get("/static/css/tokens.css")
    assert handler.code == 200
    assert b"--shell-control-min" in handler.wfile.getvalue()


def test_hash_changes_when_asset_changes():
    before = static_assets.url("css", "site_shell")
    with patch.dict(static_assets._HASHES, {("css", "site_shell"): "deadbeef"}):
        assert static_assets.url("css", "site_shell") != before
    import hashlib
    assert before.split(".")[-2] == hashlib.sha256(static_assets._BODIES[("css", "site_shell")]).hexdigest()[:8]
    assert hashlib.sha256(b"a").hexdigest()[:8] != hashlib.sha256(b"b").hexdigest()[:8]


def test_pages_link_assets_instead_of_inlining_them():
    html = ledger_design.render(ledger_design.page("trip-demo-a"))
    assert static_assets.link("ledger_design") in html
    assert static_assets.script("ledger_design") in html
    assert "<style>" not in html.split("</head>")[0] or ledger_design.STYLE not in html
    assert ledger_design.SCRIPT not in html


def test_static_get_does_not_wait_for_store_lock():
    lock = threading.RLock()
    calls = []

    class Fake:
        command = "GET"
        path = "/static/css/missing.css"
        server = SimpleNamespace(store_lock=lock)

    @ledger_board._store_request_locked
    def method(self):
        calls.append(lock._is_owned())

    holder = threading.Event()
    release = threading.Event()

    def hold():
        with lock:
            holder.set()
            release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    holder.wait(5)
    try:
        runner = threading.Thread(target=lambda: method(Fake()))
        runner.start()
        runner.join(2)
        assert not runner.is_alive(), "static request queued behind store_lock"
        assert calls == [False]
    finally:
        release.set()
        thread.join()
