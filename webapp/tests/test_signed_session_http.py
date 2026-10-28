"""Signed Google sessions are enforced by the board's real HTTP routes."""

import json
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
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

    def test_public_social_preview_preserves_private_routes(self):
        code, html, _ = self.request("/share")
        self.assertEqual(code, 200)
        self.assertIn('property="og:image"', html)
        self.assertNotIn(OWNER, html)
        self.assertNotIn(VIEWER, html)
        code, html, _ = self.request("/")
        self.assertEqual(code, 401)
        self.assertIn('property="og:image"', html)
        code, _, _ = self.request("/api/cards")
        self.assertNotEqual(code, 200)

    def test_ota_catalog_signed_role_boundaries_and_no_cache(self):
        from webapp.tests.test_ota_catalog import source_database
        source = self.root / 'ota.sqlite'
        source_database(source)
        with patch.dict(os.environ, {'WEBLEDGER_OTA_SOURCES_JSON': json.dumps({
                'portal_databases': [str(source)], 'mail_directories': []}), 'WEBLEDGER_REVIEW_CONFIG': ''}):
            for user, expected in ((OWNER, 200), (VIEWER, 403), (None, 401)):
                for path in ('/ota', '/ota?state=unassigned', '/api/ota?state=unassigned'):
                    status, body, headers = self.request(path, cookie=self.cookie(user) if user else None)
                    self.assertEqual(status, expected, body)
                    self.assertEqual(headers.get('Cache-Control'), 'no-store')
                    if user != OWNER:
                        self.assertNotIn('BOOK-1', body)
                        self.assertNotIn('합성 호텔', body)
                    elif path.startswith('/api/'):
                        self.assertEqual(json.loads(body)['total'], 2)

    def test_trip_flight_booking_route_uses_signed_trip_visibility_and_snapshot(self):
        route_store = board._active_store()
        trip = route_store.create_trip(starts_on="2026-11-07", ends_on="2026-11-10",
            destination="합성도시", client_request_id="synthetic-trip-flight")
        evidence = {"source_digests": ["synthetic-digest"], "digest": "synthetic-digest",
            "passengers": [{"surname": "SYNTH", "given_name": "PERSON"}],
            "legs": [{"label": "가는편", "departure_on": "2026-11-07", "segments": [
                {"departure_airport": "ICN", "arrival_airport": "FUK", "flight_number": "SYN123"}]}],
            "cancellation_status": "NONE", "booking_date_status": "FIRST_RECEIVED",
            "reserved_on": "2026-05-04"}
        route_store._flight_booking_service = SimpleNamespace(display_context=lambda: (
            {"data": {"passengers": {"SYNTH-PNR": evidence}}},
            {"fresh": True, "generation": "synthetic-flight-generation"}))
        with patch.dict(os.environ, {"WEBLEDGER_OTA_REVIEW_DB": str(self.root / "absent-review.sqlite")}):
            path = f"/api/trips/{trip['tab_id']}/flight-bookings"
            status, body, _ = self.request(path, cookie=self.cookie(OWNER))
            self.assertEqual(status, 200, body)
            listing = json.loads(body)
            self.assertEqual(listing["total_bookings"], 1)
            self.assertEqual(listing["items"][0]["assignment_status"], "AUTO_INFERRED")
            self.assertNotIn("SYNTH PERSON", body)
            key = listing["items"][0]["booking_key"]
            service = route_store._flight_booking_service
            route_store._flight_booking_service = SimpleNamespace(display_context=lambda: (
                {"data": {"passengers": {"SYNTH-PNR": evidence}}},
                {"fresh": True, "generation": "synthetic-next-generation"}))
            status, _, _ = self.request(path + "?booking_key=" + key +
                "&generation=" + listing["source_generation"], cookie=self.cookie(OWNER))
            self.assertEqual(status, 409)
            route_store._flight_booking_service = service
            status, body, _ = self.request(path + "?booking_key=" + key +
                "&generation=" + listing["source_generation"], cookie=self.cookie(OWNER))
            self.assertEqual(status, 200, body)
            detail = json.loads(body)
            self.assertEqual(detail["item"]["passengers"], ["SYNTH PERSON"])
            self.assertEqual(detail["item"]["booking_date_label"], "최초 메일 수신일 기준 2026-05-04")

            status, body, _ = self.request(path, cookie=self.cookie(VIEWER))
            self.assertEqual(status, 404)
            self.assertNotIn("SYNTH-PNR", body)
            status, _, _ = self.request(path)
            self.assertEqual(status, 401)
            status, _, _ = self.request(path, cookie=self.cookie(OWNER), payload={})
            self.assertEqual(status, 405)

        with patch("webapp.ledger_design.page", return_value="<main>synthetic board</main>") as page:
            status, _, _ = self.request("/board?tab=" + trip["tab_id"] + "&participant_page=2",
                                        cookie=self.cookie(OWNER))
            self.assertEqual(status, 200)
            self.assertEqual(page.call_args.kwargs["participant_query"]["participant_page"], ["2"])

    def test_signed_owner_binary_upload_preserves_bytes_and_denies_other_roles(self):
        from webapp.tests.test_receipt_review import PNG
        for user, expected in ((OWNER, 200), (VIEWER, 403), (None, 401)):
            with self.subTest(user=user):
                headers = {'Content-Type': 'application/octet-stream', 'X-CSRF-Token': board.CSRF_TOKEN}
                if user:
                    headers['Cookie'] = f'{google_oidc.COOKIE_NAME}={self.cookie(user)}'
                request = Request(f'http://127.0.0.1:{self.port}/api/receipts/image', data=PNG, headers=headers)
                try:
                    response = self.opener.open(request, timeout=5)
                except HTTPError as error:
                    response = error
                body = json.loads(response.read())
                self.assertEqual(response.code, expected, body)
                if user == OWNER:
                    from webapp import receipt_review
                    self.assertEqual(receipt_review.image_bytes(self.receipts, body['sha256']), PNG)

    def test_signed_card_xlsx_upload_keeps_amount_and_csrf_gate(self):
        from tests.card_pipeline.fixtures import make_xlsx, domestic_row
        content = make_xlsx([domestic_row(merchant='합성 업로드 상점', amount=37000, approval='PREVIEW-XLSX')])
        for user, csrf, expected in ((OWNER, '', 403), (VIEWER, board.CSRF_TOKEN, 403),
                                     (None, board.CSRF_TOKEN, 401), (OWNER, board.CSRF_TOKEN, 200)):
            with self.subTest(user=user, csrf=bool(csrf)):
                headers = {'Content-Type': 'application/octet-stream', 'X-CSRF-Token': csrf,
                           'X-Filename': 'synthetic.xlsx'}
                if user:
                    headers['Cookie'] = f'{google_oidc.COOKIE_NAME}={self.cookie(user)}'
                request = Request(f'http://127.0.0.1:{self.port}/api/imports', data=content, headers=headers)
                try:
                    response = self.opener.open(request, timeout=5)
                except HTTPError as error:
                    response = error
                body = json.loads(response.read())
                self.assertEqual(response.code, expected, body)
                count = self.server.card_store.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
                self.assertEqual(count, 1 if expected == 200 else 0)
                if expected == 200:
                    self.assertEqual(body['rows'][0]['amount_krw'], 37000)

    def assert_json_response(self, path, *, cookie, status, body, headers=None):
        actual_status, actual_body, _ = self.request(path, cookie=cookie, headers=headers)
        self.assertEqual(actual_status, status, actual_body)
        self.assertEqual(json.loads(actual_body), body)

    def test_private_pages_and_apis_never_cache_signed_or_denied_responses(self):
        for user, google_status, receipt_status in ((OWNER, 200, 200), (VIEWER, 200, 404), (None, 403, 401)):
            cookie = self.cookie(user) if user else None
            for path, expected in (('/google-ledger', google_status), ('/api/google-ledger', google_status),
                                   ('/receipts', receipt_status), ('/api/receipts', receipt_status)):
                status, body, headers = self.request(path, cookie=cookie)
                self.assertEqual(status, expected, (path, body))
                self.assertEqual(headers.get('Cache-Control'), 'no-store', path)

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
                 '/api/google-ledger/auto-mapping',
                 '/api/receipts/scan', '/api/receipts/edit', '/api/receipts/image',
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

    def test_all_cards_route_is_owner_only_and_read_only(self):
        before = self.server.card_store.conn.total_changes
        status, body, headers = self.request('/cards', cookie=self.cookie(OWNER))
        self.assertEqual(status, 302, body)
        self.assertEqual(headers.get('Location'), '/import?scope=all')
        status, body, _ = self.request('/import?scope=all', cookie=self.cookie(OWNER))
        self.assertEqual(status, 200, body)
        self.assertIn('전체 카드 거래 검색', body)
        for user in (VIEWER, None):
            status, body, _ = self.request('/import?scope=all', cookie=self.cookie(user) if user else None)
            self.assertNotEqual(status, 200)
            self.assertNotIn('전체 카드 거래 검색', body)
        self.assertEqual(self.server.card_store.conn.total_changes, before)

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

    def test_signed_viewer_grant_detail_and_revocation_with_concurrent_requests(self):
        from concurrent.futures import ThreadPoolExecutor
        from webapp import google_ledger_page
        stamp = google_ledger_page.dt.datetime.now(google_authority.KST).isoformat()
        key = 'SYN-GOOGLE-TRIP'
        snapshot = json.loads(self.snapshot.read_text())
        block = lambda value: {'total': value, 'verified': True}
        snapshot.update(synced_at=stamp, sources={'main': {'status': 'ok', 'stale': False, 'last_ok_at': stamp}},
            trips=[{'key': key, 'closure': 'open', 'closure_current': True, 'canonical_source': 'main',
                    'income_total': 100, 'expense_total': 10, 'net': 90, 'verified': True, 'review': [],
                    'copies': {'main': {'layout': 'rev', 'income': block(100), 'expense': block(10)}}}])
        self.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
        rows_path = google_authority._rows_file(self.rows, snapshot['rows_generation'])
        rows = json.loads(rows_path.read_text())
        rows['sources'] = {'main': {'trips': {key: {'income': [], 'expense': []}}}}
        rows_path.write_text(json.dumps(rows), encoding='utf-8')
        tab = self.server.card_store.create_trip(starts_on='2026-10-11', ends_on='2026-10-12',
            destination='Synthetic Trip', client_request_id='signed-trip')['tab_id']
        self.access.register_reservation_person(reservation_person_id='person-syn',
                                               display_name='Synthetic Viewer', nickname='Synthetic')
        owner, viewer = self.cookie(OWNER), self.cookie(VIEWER)
        headers = {'X-CSRF-Token': board.CSRF_TOKEN}

        def post(path, payload, cookie=owner):
            status, body, _ = self.request(path, cookie=cookie, headers=headers, payload=payload)
            self.assertEqual(status, 200, body)
            return json.loads(body)

        application = post('/access/applications', {'action': 'create', 'requested_name': 'Synthetic Viewer',
            'nickname': 'Synthetic', 'client_request_id': 'signed-application'}, cookie=viewer)
        post('/access/decision', {'action': 'approve', 'application_id': application['result']['application_id'],
            'expected_revision': 1, 'reservation_person_id': 'person-syn', 'client_request_id': 'signed-approval'})
        self.access.apply_assignment_snapshot(user_id=VIEWER,
            items=[{'tab_id': tab, 'snapshot_revision': 1, 'state': access_control.ASSIGN_ACTIVE}],
            source_version='synthetic-assignment', validity=access_control.DEFAULT_VALIDITY, now=None, complete=False)
        post('/api/google-ledger/mapping', {'key': key, 'tab_id': tab})
        post('/api/google-ledger/grants', {'user_id': VIEWER, 'keys': [key], 'granted': True})
        # Linking an account can invalidate its earlier cookie; use its current generation.
        viewer = self.cookie(VIEWER)
        status, body, _ = self.request('/api/google-ledger', cookie=viewer)
        self.assertEqual(status, 200, body)
        self.assertEqual([trip['key'] for trip in json.loads(body)['trips']], [key])
        detail_path = '/api/google-ledger/rows?key=' + key + '&source=main'
        status, body, _ = self.request(detail_path, cookie=viewer)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['key'], key)
        # Adding a second copy makes the canonical source unresolved until the
        # owner chooses it. A signed viewer must not bypass this with a URL.
        snapshot['sources']['archive'] = dict(snapshot['sources']['main'])
        snapshot['trips'][0]['copies']['archive'] = snapshot['trips'][0]['copies']['main']
        rows['sources']['archive'] = rows['sources']['main']
        self.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
        rows_path.write_text(json.dumps(rows), encoding='utf-8')
        for prefix in ('/api/google-ledger/rows', '/google-ledger/rows'):
            for source in ('main', 'archive'):
                with self.subTest(unresolved=source, prefix=prefix):
                    status, body, _ = self.request(prefix + '?key=' + key + '&source=' + source, cookie=viewer)
                    self.assertEqual(status, 404, body)
                    self.assertEqual(json.loads(body)['code'], 'NOT_FOUND')
        post('/api/google-ledger/choice', {'key': key, 'source': 'archive'})
        for prefix in ('/api/google-ledger/rows', '/google-ledger/rows'):
            status, body, _ = self.request(prefix + '?key=' + key + '&source=main', cookie=viewer)
            self.assertEqual(status, 404, body)
            status, body, _ = self.request(prefix + '?key=' + key + '&source=archive', cookie=viewer)
            self.assertEqual(status, 200, body)
            # Owners retain access to both copies for comparison.
            status, body, _ = self.request(prefix + '?key=' + key + '&source=main', cookie=owner)
            self.assertEqual(status, 200, body)
        detail_path = '/api/google-ledger/rows?key=' + key + '&source=archive'
        # A later snapshot losing the selected copy must not silently authorize
        # the remaining main copy, even if private archive rows still exist.
        archive_copy = snapshot['trips'][0]['copies'].pop('archive')
        self.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
        for source in ('main', 'archive'):
            status, body, _ = self.request('/api/google-ledger/rows?key=' + key + '&source=' + source, cookie=viewer)
            self.assertEqual(status, 404, body)
        post('/api/google-ledger/choice', {'key': key, 'source': 'main'})
        status, body, _ = self.request('/api/google-ledger/rows?key=' + key + '&source=main', cookie=viewer)
        self.assertEqual(status, 200, body)
        snapshot['trips'][0]['copies']['archive'] = archive_copy
        self.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
        post('/api/google-ledger/choice', {'key': key, 'source': 'archive'})
        post('/api/google-ledger/grants', {'user_id': VIEWER, 'keys': [key], 'granted': False})
        paths = ['/api/google-ledger', detail_path,
                 '/google-ledger/rows?key=' + key + '&source=archive'] * 3
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda path: self.request(path, cookie=viewer), paths))
        for path, (status, body, _) in zip(paths, replies):
            if '/rows?' in path:
                self.assertEqual(status, 404, body)
                self.assertEqual(json.loads(body)['code'], 'NOT_FOUND')
            else:
                self.assertEqual(status, 200, body)
                self.assertEqual(json.loads(body)['trips'], [])

    def test_callback_verifies_rsa_signature_with_real_google_auth_library_offline(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from google.auth import crypt, jwt
        from google.oauth2 import id_token as library

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        certificate_requests = []

        def certificates(url, method='GET', **kwargs):
            self.assertEqual(url, library._GOOGLE_OAUTH2_CERTS_URL)
            self.assertEqual(method, 'GET')
            certificate_requests.append(url)
            return type('CertificateResponse', (), {
                'status': 200, 'data': json.dumps({'synthetic-kid': public}).encode()})()

        self.flow.verifier = google_oidc.GoogleAuthTokenVerifier(client_id=CLIENT_ID)
        with patch('requests.sessions.Session.request', side_effect=AssertionError('unexpected network')), \
                patch('google.auth.transport.requests.Request', return_value=certificates):
            for valid_signature in (True, False):
                with self.subTest(valid_signature=valid_signature):
                    _, _, started = self.request('/auth/login?return_to=%2Faccess%2Fme')
                    params = parse_qs(urlparse(started['Location']).query)
                    claims = {'iss': google_oidc.GOOGLE_ISSUER, 'aud': CLIENT_ID, 'sub': OWNER,
                              'iat': int(time.time()), 'exp': int(time.time()) + 3600,
                              'nonce': params['nonce'][0], 'email': 'owner@synthetic.test',
                              'email_verified': True, 'name': 'Synthetic Owner'}
                    signing_key = key if valid_signature else rsa.generate_private_key(public_exponent=65537, key_size=2048)
                    private = signing_key.private_bytes(serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
                    signer = crypt.RSASigner.from_string(private, key_id='synthetic-kid')
                    token = jwt.encode(signer, claims).decode()
                    self.flow.exchange = lambda **kwargs: {'id_token': token}
                    before = self.store.conn.execute('SELECT * FROM access_accounts ORDER BY user_id').fetchall()
                    status, body, headers = self.request(
                        '/auth/callback?code=synthetic-code&state=' + params['state'][0])
                    if valid_signature:
                        self.assertEqual(status, 303, body)
                        jar = SimpleCookie()
                        jar.load(headers['Set-Cookie'])
                        status, body, _ = self.request('/access/me', cookie=jar[google_oidc.COOKIE_NAME].value)
                        self.assertEqual(status, 200, body)
                        self.assertEqual(json.loads(body)['role'], 'owner')
                    else:
                        self.assertEqual(status, 400, body)
                        self.assertIn('data-refusal="ID_TOKEN_INVALID"', body)
                        self.assertNotIn('Set-Cookie', headers)
                        self.assertEqual(self.store.conn.execute(
                            'SELECT * FROM access_accounts ORDER BY user_id').fetchall(), before)
        self.assertEqual(len(certificate_requests), 2)


if __name__ == "__main__":
    unittest.main()
