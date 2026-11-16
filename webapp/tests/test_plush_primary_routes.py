"""Promote existing browser URLs without moving APIs or legacy edit handlers."""
from types import SimpleNamespace
from urllib.parse import urlsplit
import urllib.error
import urllib.request

import pytest

from webapp import access_control, ledger_board, plush_ui
from webapp.tests.test_plush_ui import Handler, dist, http_ui  # noqa: F401


@pytest.mark.parametrize("path", sorted(plush_ui.PRIMARY_ROUTES))
def test_existing_browser_urls_serve_the_same_shell_without_redirect(dist, path):
    handler = Handler()
    handler.headers["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
    board = SimpleNamespace(ACCESS_ENFORCEMENT=True, require_session=lambda *_: object())
    assert plush_ui.dispatch_primary(handler, urlsplit(path + "?tab=trip%20one&q=cost"), board=board, dist=dist)
    assert handler.status == 200
    assert "Location" not in handler.response_headers
    assert handler.wfile.getvalue() == b'<main id="root"></main>'


@pytest.mark.parametrize("path,accept,enforced", [
    ("/participants?trip=demo&legacy=1", "text/html", True),
    ("/participants?trip=demo", "text/html", True),
    ("/board?tab=refunds&legacy=1", "text/html", True),
    ("/cards/all", "application/json", True),
    ("/api/plush/bootstrap", "text/html", True),
    ("/api/receipts/pdf/demo", "text/html", True),
    ("/ota/booking?ref=demo", "text/html", True),
    ("/row?id=demo", "text/html", True),
    ("/auth/login", "text/html", True),
    ("/access/logout", "text/html", True),
    ("/", "text/html", False),
])
def test_legacy_details_api_auth_and_development_handlers_are_preserved(dist, path, accept, enforced):
    handler = Handler()
    handler.headers["Accept"] = accept
    board = SimpleNamespace(ACCESS_ENFORCEMENT=enforced, require_session=lambda *_: object())
    assert not plush_ui.dispatch_primary(handler, urlsplit(path), board=board, dist=dist)
    assert handler.status is None


def test_primary_pages_keep_session_gate(dist):
    handler = Handler()
    handler.headers["Accept"] = "text/html"
    board = SimpleNamespace(ACCESS_ENFORCEMENT=True, require_session=lambda *_: None)
    assert plush_ui.dispatch_primary(handler, urlsplit("/"), board=board, dist=dist)
    assert handler.status == 401 and not handler.wfile.getvalue()


@pytest.mark.parametrize("path", ["/", "/trips", "/board?tab=demo", "/cards/all", "/receipts", "/google-ledger", "/access/admin", "/rules"])
def test_actual_http_browser_uses_primary_shell(http_ui, monkeypatch, path):
    monkeypatch.setattr(ledger_board, "ACCESS_ENFORCEMENT", True)
    port, _ = http_ui
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={
        "Accept": "text/html", access_control.SyntheticSessionAdapter.HEADER: "synthetic-ui-owner",
    })
    with urllib.request.urlopen(request) as response:
        assert response.status == 200
        assert response.url.endswith(path)
        assert response.read() == b'<main id="root"></main>'


def test_actual_http_unknown_session_cannot_read_primary_shell(http_ui, monkeypatch):
    monkeypatch.setattr(ledger_board, "ACCESS_ENFORCEMENT", True)
    port, _ = http_ui
    request = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={
        "Accept": "text/html", access_control.SyntheticSessionAdapter.HEADER: "unknown-ui-account",
    })
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request)
    assert caught.value.code == 401
    assert b'<main id="root">' not in caught.value.read()
