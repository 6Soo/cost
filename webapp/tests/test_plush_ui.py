"""Build-path containment and real-session gate for the opt-in UI."""
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from webapp import plush_ui


class Handler:
    def __init__(self):
        self.headers = {"Cookie": "synthetic-session"}
        self.wfile = BytesIO()
        self.response_headers = {}
        self.status = None
        self.json = None

    def _cookies(self):
        return {"session": "synthetic"}

    def _send_json(self, value, code=200):
        self.status, self.json = code, value

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<main id="root"></main>', encoding="utf-8")
    (root / "assets" / "app.js").write_text("export {}", encoding="utf-8")
    return root


def call(path, dist, session=object()):
    handler = Handler()
    board = SimpleNamespace(require_session=lambda headers, cookies: session)
    handled = plush_ui.dispatch(handler, urlsplit(path), board=board, dist=dist)
    return handled, handler


def test_unrelated_route_untouched(dist):
    handled, handler = call("/board", dist)
    assert not handled and handler.status is None


def test_anonymous_cannot_read_shell_or_assets(dist):
    for path in ("/ui/", "/ui/assets/app.js"):
        _, handler = call(path, dist, session=None)
        assert handler.status == 401
        assert not handler.wfile.getvalue()


def test_real_session_failure_propagates_to_board_refusal(dist):
    def refuse(headers, cookies):
        assert headers["Cookie"] == "synthetic-session"
        assert cookies == {"session": "synthetic"}
        raise PermissionError("expired")
    with pytest.raises(PermissionError):
        plush_ui.dispatch(Handler(), urlsplit("/ui/"),
                          board=SimpleNamespace(require_session=refuse), dist=dist)


@pytest.mark.parametrize("path", ["/ui/", "/ui/board?tab=synthetic", "/ui/receipts"])
def test_deep_links_serve_undecorated_shell(dist, path):
    _, handler = call(path, dist)
    assert handler.status == 200
    assert handler.wfile.getvalue() == b'<main id="root"></main>'
    assert handler.response_headers["Cache-Control"] == "no-store"


def test_redirect_preserves_query(dist):
    _, handler = call("/ui?tab=synthetic", dist)
    assert handler.status == 308
    assert handler.response_headers["Location"] == "/ui/?tab=synthetic"


def test_assets_have_correct_mime_and_never_fall_back_to_html(dist):
    _, handler = call("/ui/assets/app.js", dist)
    assert handler.status == 200
    assert handler.response_headers["Content-Type"].startswith("text/javascript")
    assert handler.wfile.getvalue() == b"export {}"
    _, missing = call("/ui/assets/missing.js", dist)
    assert missing.status == 404


@pytest.mark.parametrize("path", [
    "/ui/../private.js", "/ui/%2e%2e/private.js", "/ui/assets%5c..%5cprivate.js",
    "/ui/C:/private.js", "/ui/%00.js", "/ui//private.js", "/ui/assets/app.js.map",
    "/ui/package.json", "/ui/src/main.tsx",
])
def test_path_escape_and_source_files_refused(dist, path):
    _, handler = call(path, dist)
    assert handler.status == 404
    assert not handler.wfile.getvalue()


def test_missing_build_is_unavailable_not_false_success(tmp_path):
    _, handler = call("/ui/", tmp_path)
    assert handler.status == 503
    assert handler.json["code"] == "UI_NOT_BUILT"


@pytest.fixture
def http_ui(dist, monkeypatch, tmp_path):
    import threading
    from webapp import access_control, ledger_board
    from webapp.ledger_store import LedgerStore

    monkeypatch.setenv("WEBLEDGER_DB", str(tmp_path / "synthetic.sqlite"))
    monkeypatch.setattr(plush_ui, "DIST", dist)
    store = LedgerStore(tmp_path / "synthetic.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("synthetic-ui-owner")
    access.create_account(user_id="synthetic-ui-viewer", role="viewer")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    server = ledger_board.serve(port=0, with_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], access
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()


def test_http_session_gate_and_shell_for_both_roles(http_ui):
    import urllib.error
    import urllib.request
    from webapp import access_control

    port, access = http_ui
    for user, expected in [(None, 401), ("synthetic-ui-owner", 200),
                           ("synthetic-ui-viewer", 200), ("unknown-ui-account", 401)]:
        headers = {access_control.SyntheticSessionAdapter.HEADER: user} if user else {}
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ui/board", headers=headers)
        try:
            response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            assert response.status == expected
            body = response.read()
            if expected == 200:
                assert body == b'<main id="root"></main>'
            else:
                assert b'<main id="root">' not in body


def test_http_stale_session_cannot_retrieve_built_asset(http_ui):
    import urllib.error
    import urllib.request
    from webapp import access_control

    port, access = http_ui
    access.bump_session_generation("synthetic-ui-viewer")
    headers = {
        access_control.SyntheticSessionAdapter.HEADER: "synthetic-ui-viewer",
        access_control.SyntheticSessionAdapter.GENERATION_HEADER: "1",
    }
    req = urllib.request.Request(f"http://127.0.0.1:{port}/ui/assets/app.js", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(req)
    assert caught.value.code == 401
