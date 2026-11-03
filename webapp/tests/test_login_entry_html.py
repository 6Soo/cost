"""First-screen login entry: HTML 401 for GET / and /board only.

Synthetic accounts only. No real Google OIDC, no reservation API,
no customer data and no outbound network call is in this file.
Drives the real ledger_board routes over HTTP.
"""

import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore


class _Server:
    def _boot(self, name):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / name)
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        board_mod.bind_oidc(None)
        self._prev_oidc = board_mod.oidc_flow()

    def _shutdown(self):
        try:
            board_mod.bind_oidc(None)
        except Exception:
            board_mod._OIDC = None
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def _get(self, path, accept=None, cookie=None, method="GET", data=None,
             content_type=None):
        headers = {}
        if accept is not None:
            headers["Accept"] = accept
        if cookie is not None:
            headers["Cookie"] = cookie
        if content_type is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return (resp.status,
                        str(resp.headers.get("Content-Type") or ""),
                        resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            return (exc.code,
                    str(exc.headers.get("Content-Type") or ""),
                    exc.read().decode("utf-8", "replace"))


class LoginEntryHtmlTests(_Server, unittest.TestCase):
    def setUp(self):
        self._boot("login-entry.sqlite")

    def tearDown(self):
        self._shutdown()

    def test_root_html_accept_returns_login_page(self):
        status, ctype, body = self._get("/", accept="text/html")
        self.assertEqual(status, 401)
        self.assertIn("text/html", ctype)
        self.assertIn("웹 장부", body)
        self.assertIn("로그인 후 소유자의 승인이 필요합니다.", body)
        self.assertIn("width=device-width", body)
        self.assertIn('data-refusal="AUTH_REQUIRED"', body)

    def test_board_html_accept_returns_login_page(self):
        status, ctype, body = self._get("/board", accept="text/html")
        self.assertEqual(status, 401)
        self.assertIn("text/html", ctype)
        self.assertIn("웹 장부", body)
        self.assertIn("로그인 후 소유자의 승인이 필요합니다.", body)

    def test_review_html_accept_returns_login_page(self):
        status, ctype, body = self._get("/review", accept="text/html")
        self.assertEqual(status, 401)
        self.assertIn("text/html", ctype)
        self.assertIn('data-refusal="AUTH_REQUIRED"', body)

    def test_import_html_accept_returns_login_page(self):
        status,ctype,body=self._get('/import',accept='text/html')
        self.assertEqual(status,401)
        self.assertIn('text/html',ctype)
        self.assertIn('data-refusal="AUTH_REQUIRED"',body)

    def test_direct_application_pages_offer_login(self):
        for path in ('/cards/all', '/ota', '/receipts', '/trips',
                     '/flight-passengers', '/reserve-links', '/export', '/rules'):
            with self.subTest(path=path):
                status, ctype, body = self._get(path, accept='text/html')
                self.assertEqual(status, 401)
                self.assertIn('text/html', ctype)
                self.assertIn('data-refusal="AUTH_REQUIRED"', body)

    def test_direct_application_page_json_accept_stays_json(self):
        status, ctype, body = self._get('/cards/all', accept='application/json')
        self.assertEqual(status, 401)
        self.assertIn('application/json', ctype)
        self.assertIn('AUTH_REQUIRED', body)

    def test_review_json_accept_stays_json(self):
        status, ctype, body = self._get("/review", accept="application/json")
        self.assertEqual(status, 401)
        self.assertIn("application/json", ctype)
        import json as _json
        payload = _json.loads(body)
        self.assertEqual(payload["code"], "AUTH_REQUIRED")

    def test_review_wildcard_accept_returns_login_page(self):
        status, ctype, body = self._get("/review", accept="*/*")
        self.assertEqual(status, 401)
        self.assertIn("text/html", ctype)
        self.assertIn('data-refusal="AUTH_REQUIRED"', body)

    def test_json_accept_stays_json(self):
        status, ctype, body = self._get("/", accept="application/json")
        self.assertEqual(status, 401)
        self.assertIn("application/json", ctype)
        import json as _json
        payload = _json.loads(body)
        self.assertEqual(payload["code"], "AUTH_REQUIRED")

    def test_api_html_accept_stays_json(self):
        status, ctype, body = self._get("/api/tabs", accept="text/html")
        self.assertEqual(status, 401)
        self.assertIn("application/json", ctype)
        import json as _json
        payload = _json.loads(body)
        self.assertEqual(payload["code"], "AUTH_REQUIRED")
        self.assertNotIn("웹 장부", body)

    def test_post_html_accept_stays_json(self):
        status, ctype, body = self._get(
            "/board", accept="text/html", method="POST",
            data=b"{}", content_type="application/json")
        self.assertEqual(status, 401)
        self.assertIn("application/json", ctype)
        import json as _json
        payload = _json.loads(body)
        self.assertEqual(payload["code"], "AUTH_REQUIRED")

    def test_flow_none_has_setup_guidance_and_no_button(self):
        self.assertIsNone(board_mod.oidc_flow())
        status, ctype, body = self._get("/", accept="text/html")
        self.assertEqual(status, 401)
        self.assertIn("배포 환경 설정", body)
        self.assertNotIn('href="/auth/login"', body)
        self.assertNotIn("Google 계정으로 로그인</a>", body)

    def test_flow_present_button_href_fixed(self):
        board_mod._OIDC = object()
        try:
            status, ctype, body = self._get("/", accept="text/html")
        finally:
            board_mod._OIDC = None
        self.assertEqual(status, 401)
        self.assertIn('href="/auth/login"', body)
        self.assertIn("Google 계정으로 로그인", body)
        self.assertIn("로그인 후 소유자의 승인이 필요합니다.", body)
        # fixed href only: no approval passthrough, no tab echo
        self.assertNotIn("approve", body.lower())
        self.assertNotIn("return_to", body)

    def test_query_and_tab_not_reflected_no_external_url(self):
        evil = "/?tab=trip-demo-a&q=%3Cscript%3Ealert(1)%3C%2Fscript%3E&kind=x"
        status, ctype, body = self._get(evil, accept="text/html")
        self.assertEqual(status, 401)
        self.assertIn("text/html", ctype)
        self.assertNotIn("trip-demo-a", body)
        self.assertNotIn("<script>", body)
        self.assertNotIn("alert(1)", body)
        # Static Open Graph metadata may contain the public site URL; the
        # login page must not create a navigable external link from the query.
        self.assertNotIn('href="http', body.lower())
        self.assertNotIn("href='http", body.lower())
        self.assertNotIn("accounts.", body.lower())

    def test_expired_cookie_same_html_policy(self):
        status, ctype, body = self._get(
            "/", accept="text/html", cookie="__Host-webledger=expired-value")
        self.assertEqual(status, 401)
        self.assertIn("text/html", ctype)
        self.assertIn("웹 장부", body)

    def test_unknown_path_html_accept_stays_json(self):
        status, ctype, body = self._get(
            "/no-such-xyz", accept="text/html")
        self.assertEqual(status, 401)
        self.assertIn("application/json", ctype)


if __name__ == "__main__":
    unittest.main()
