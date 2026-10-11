"""Signed Google sessions are enforced by the board's real HTTP routes."""

import json
import os
import tempfile
import threading
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from unittest.mock import patch

from webapp import access_control, google_oidc
from webapp import ledger_board as board
from app import google_authority
from webapp.ledger_store import LedgerStore

SECRET = "k7Qm2Zx9Tb4Nq8Vr3Ls6Wy1Pd5Gj0Hf7Ce2Ui4Ok8Mn1"
CLIENT_ID = "synthetic-client.apps.googleusercontent.com"
CLIENT_SECRET = "synthetic-client-secret"
OWNER = "synthetic-owner-sub"
VIEWER = "synthetic-viewer-sub"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FakeVerifier(google_oidc.GoogleAuthTokenVerifier):
    def __init__(self):
        super().__init__(client_id=CLIENT_ID)
        self.claims = {}
        self._idinfo_loader = lambda token: dict(self.claims)


class FakeExchange:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"id_token": "synthetic-id-token", "access_token": "discarded"}


class SignedSessionHttpTests(unittest.TestCase):
    def setUp(self):
        self.previous = (board._STORE, board._ACCESS, board._OIDC, access_control.session_adapter())
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.store = LedgerStore(str(self.root / "board.sqlite"))
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.ensure_schema()
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER,
                                   is_synthetic=False)

        self.snapshot = self.root / "google-snapshot.json"
        self.rows = self.root / "google-rows.json"
        generation = "synthetic-generation"
        self.snapshot.write_text(json.dumps({
            "schema": "google-authority-readonly-v2", "rows_generation": generation,
            "synced_at": None, "sources": {}, "trips": [],
        }), encoding="utf-8")
        google_authority._rows_file(self.rows, generation).write_text(json.dumps({
            "schema": "google-authority-rows-private-v1", "generation": generation,
            "sources": {},
        }), encoding="utf-8")
        self.receipts = self.root / "receipts.json"
        self.env = patch.dict(os.environ, {
            'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1',
            "WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT": str(self.snapshot),
            "WEBLEDGER_GOOGLE_LEDGER_ROWS": str(self.rows),
            "WEBLEDGER_RECEIPTS_STORE": str(self.receipts),
        })
        self.env.start()

        cfg = google_oidc.OIDCConfig.from_env({
            google_oidc.ENV_CLIENT_ID: CLIENT_ID,
            google_oidc.ENV_CLIENT_SECRET: CLIENT_SECRET,
            google_oidc.ENV_SESSION_SECRET: SECRET,
            google_oidc.ENV_PUBLIC_BASE_URL: "https://ledger.synthetic.test",
            google_oidc.ENV_OWNER_SUB: OWNER,
        })
        self.verifier = FakeVerifier()
        self.exchange = FakeExchange()
        self.flow = google_oidc.connect_oidc(cfg, self.access,
                                             verifier=self.verifier,
                                             exchange=self.exchange)
        board.bind_store(self.store)
        board.bind_access(self.access)
        board.bind_oidc(self.flow)
        self.server = board.serve(port=0, db_path=self.root / 'http-board.sqlite',
                                  with_worker=False, seed_demo=False)
        from webapp.card_flow import CardFlow
        CardFlow(self.server.card_store)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(NoRedirect)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server.card_store.close()
        old_store, old_access, old_oidc, old_adapter = self.previous
        board.bind_store(old_store)
        board.bind_access(old_access)
        board.bind_oidc(old_oidc)
        access_control.bind_sessions(old_adapter)
        self.store.close()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, path, *, cookie=None, headers=None, payload=None):
        all_headers = dict(headers or {})
        if cookie:
            all_headers["Cookie"] = f"{google_oidc.COOKIE_NAME}={cookie}"
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            all_headers['Content-Type'] = 'application/json'
        request = Request(f"http://127.0.0.1:{self.port}{path}", headers=all_headers, data=data)
        try:
            response = self.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        return response.code, response.read().decode("utf-8"), response.headers

    def cookie(self, user):
        account = self.access.account(user)
        identity = {"sub": user, "name": user, "email": f"{user}@synthetic.test"}
        return self.flow.adapter.issue_cookie(
            identity, generation=account["session_generation"])

    def assert_json_response(self, path, *, cookie, status, body, headers=None):
        actual_status, actual_body, _ = self.request(path, cookie=cookie, headers=headers)
        self.assertEqual(actual_status, status, actual_body)
        self.assertEqual(json.loads(actual_body), body)

    def test_real_pages_and_apis_enforce_each_role(self):
        owner = self.cookie(OWNER)
        viewer = self.cookie(VIEWER)
        for path in ("/google-ledger", "/api/google-ledger"):
            status, body, _ = self.request(path, cookie=owner)
            self.assertEqual(status, 200, body)
            if path.startswith("/api/"):
                self.assertEqual(json.loads(body), {"synced_at": None, "sources": {}, "trips": []})
            else:
                self.assertIn("Google", body)
            viewer_status, viewer_body, _ = self.request(path, cookie=viewer)
            self.assertEqual(viewer_status, 200, viewer_body)
            if path.startswith("/api/"):
                self.assertEqual(json.loads(viewer_body), {"synced_at": None, "sources": {}, "trips": []})
            else:
                self.assertIn("볼 수 있는 여행이 없습니다", viewer_body)
            self.assert_json_response(path, cookie=None, status=403,
                                      body={"code": "LOGIN_REQUIRED", "message": "로그인한 계정만 볼 수 있습니다"})

        for path in ("/receipts", "/api/receipts"):
            status, body, _ = self.request(path, cookie=owner)
            self.assertEqual(status, 200, body)
            if path.startswith('/api/'):
                self.assertEqual(json.loads(body), {"candidates": [], "holds": [], "images": []})
            else:
                self.assertIn('영수증', body)
            viewer_status, viewer_body, _ = self.request(path, cookie=viewer)
            self.assertEqual(viewer_status, 404)
            self.assertEqual(viewer_body, "없음")
            self.assert_json_response(path, cookie=None, status=401,
                                      body={"code": "AUTH_REQUIRED", "message": "다시 로그인해 주세요"})

    def test_owner_api_uses_the_signed_role_and_synthetic_headers_are_ignored(self):
        owner = self.cookie(OWNER)
        viewer = self.cookie(VIEWER)
        status, body, _ = self.request("/access/admin", cookie=owner)
        self.assertEqual(status, 200, body)
        self.assert_json_response("/access/admin", cookie=viewer, status=403,
                                  body={"code": "ACTION_FORBIDDEN", "message": "이 동작은 owner만 할 수 있어요"})
        self.assert_json_response("/access/admin", cookie=None, status=401,
                                  body={"code": "AUTH_REQUIRED", "message": "다시 로그인해 주세요"})
        self.assert_json_response("/api/google-ledger", cookie=None, headers={
            access_control.SyntheticSessionAdapter.HEADER: OWNER,
        }, status=403, body={"code": "LOGIN_REQUIRED", "message": "로그인한 계정만 볼 수 있습니다"})

    def test_new_write_routes_refuse_viewer_and_anonymous_before_any_effect(self):
        paths = ('/api/google-ledger/choice', '/api/google-ledger/grants', '/api/google-ledger/mapping',
                 '/api/receipts/scan', '/api/receipts/edit', '/api/receipts/confirm', '/api/receipts/image',
                 '/api/receipts/upload', '/api/imports/batch-syn/rule-proposal',
                 '/api/imports/batch-syn/rule-proposal/approve', '/api/imports/batch-syn/company-exclusion')
        conn = self.server.card_store.conn
        before = conn.total_changes
        for path in paths:
            for user, status, code in ((VIEWER, 403, 'ACTION_FORBIDDEN'), (None, 401, 'AUTH_REQUIRED')):
                with self.subTest(path=path, user=user):
                    actual, body, _ = self.request(path, cookie=self.cookie(user) if user else None,
                        headers={'X-CSRF-Token': board.CSRF_TOKEN}, payload={'role': 'owner', 'user_id': OWNER})
                    self.assertEqual(actual, status, body)
                    self.assertEqual(json.loads(body)['code'], code)
        self.assertEqual(conn.total_changes, before)
        self.assertFalse(self.receipts.exists())
        self.assertFalse(self.snapshot.with_name('google-canonical-choices.json').exists())
        self.assertFalse(self.snapshot.with_name('google-viewer-grants.json').exists())
        self.assertFalse(self.snapshot.with_name('google-tab-mapping.json').exists())

    def test_expired_tampered_revoked_and_deactivated_cookies_are_refused_over_http(self):
        signer = self.flow.adapter.signer
        generation = self.access.session_generation(OWNER)
        expired = signer.sign({"sub": OWNER, "name": OWNER, "email": "owner@synthetic.test",
                               "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600,
                               "gen": generation, "jti": "expired"})
        live = self.cookie(OWNER)
        parts = live.split(".")
        tampered = f"{parts[0]}.{parts[1]}.invalid-signature"
        for invalid in (expired, tampered):
            self.assert_json_response("/api/google-ledger", cookie=invalid, status=403,
                                      body={"code": "LOGIN_REQUIRED", "message": "로그인한 계정만 볼 수 있습니다"})

        self.access.bump_session_generation(OWNER)
        self.assert_json_response("/api/google-ledger", cookie=live, status=403,
                                  body={"code": "LOGIN_REQUIRED", "message": "로그인한 계정만 볼 수 있습니다"})
        fresh = self.cookie(VIEWER)
        self.access.set_account_active(user_id=VIEWER, is_active=False)
        self.assert_json_response("/api/google-ledger", cookie=fresh, status=403,
                                  body={"code": "LOGIN_REQUIRED", "message": "로그인한 계정만 볼 수 있습니다"})

    def test_login_start_and_callback_run_signed_state_nonce_and_cookie_over_http(self):
        status, body, headers = self.request("/auth/login?return_to=%2Faccess%2Fme")
        self.assertEqual(status, 303, body)
        location = headers["Location"]
        parsed = urlparse(location)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "accounts.google.com")
        params = parse_qs(parsed.query)
        state, nonce = params["state"][0], params["nonce"][0]
        self.assertEqual(params["redirect_uri"][0], "https://ledger.synthetic.test/auth/callback")
        self.verifier.claims = {
            "iss": google_oidc.GOOGLE_ISSUER, "sub": OWNER, "aud": CLIENT_ID,
            "exp": int(time.time()) + 3600, "iat": int(time.time()),
            "email": "owner@synthetic.test", "email_verified": True,
            "name": "Synthetic Owner", "nonce": nonce,
        }
        status, body, headers = self.request(f"/auth/callback?code=synthetic-code&state={state}")
        self.assertEqual(status, 303, body)
        self.assertEqual(headers["Location"], "/access/me")
        self.assertEqual(len(self.exchange.calls), 1)
        cookie_header = headers["Set-Cookie"]
        jar = SimpleCookie()
        jar.load(cookie_header)
        signed_cookie = jar[google_oidc.COOKIE_NAME].value
        status, body, _ = self.request("/access/me", cookie=signed_cookie)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["role"], "owner")
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertTrue(self.exchange.calls[0]['code_verifier'])
        # Callback state is single use; a retry must not exchange the code again.
        status, body, headers = self.request(f"/auth/callback?code=synthetic-code&state={state}")
        self.assertEqual(status, 400, body)
        self.assertIn('data-refusal="STATE_INVALID"', body)
        self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(len(self.exchange.calls), 1)

    def test_callback_refuses_unknown_state_and_wrong_nonce_without_cookie(self):
        status, body, headers = self.request('/auth/callback?code=synthetic-code&state=unknown')
        self.assertEqual(status, 400, body)
        self.assertIn('data-refusal="STATE_INVALID"', body)
        self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(self.exchange.calls, [])
        _, _, headers = self.request('/auth/login')
        state = parse_qs(urlparse(headers['Location']).query)['state'][0]
        self.verifier.claims = {
            'iss': google_oidc.GOOGLE_ISSUER, 'sub': OWNER, 'aud': CLIENT_ID,
            'exp': int(time.time()) + 3600, 'iat': int(time.time()),
            'email': 'owner@synthetic.test', 'email_verified': True,
            'name': 'Synthetic Owner', 'nonce': 'wrong-nonce',
        }
        status, body, headers = self.request(f'/auth/callback?code=synthetic-code&state={state}')
        self.assertEqual(status, 400, body)
        self.assertIn('data-refusal="NONCE_MISMATCH"', body)
        self.assertNotIn('Set-Cookie', headers)


if __name__ == "__main__":
    unittest.main()
