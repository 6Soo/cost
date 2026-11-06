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
                        # The HTTP catalog intentionally serves a pending index
                        # while rebuilding. Verify its actual ready response,
                        # rather than relying on another test having warmed it.
                        catalog = json.loads(body)
                        deadline = time.monotonic() + 10
                        while catalog['refresh_state'] != 'ready' and time.monotonic() < deadline:
                            self.assertNotEqual(catalog['refresh_state'], 'failed', catalog)
                            time.sleep(.05)
                            status, body, headers = self.request(path, cookie=self.cookie(user))
                            self.assertEqual(status, 200, body)
                            self.assertEqual(headers.get('Cache-Control'), 'no-store')
                            catalog = json.loads(body)
                        self.assertEqual(catalog['refresh_state'], 'ready', catalog)
                        self.assertEqual(catalog['total'], 1)
                        self.assertEqual(catalog['rows'][0]['booking_ref'], 'BOOK-1')

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
        initial_service = SimpleNamespace(display_context=lambda: (
            {"data": {"passengers": {"SYNTH-PNR": evidence}}},
            {"fresh": True, "generation": "synthetic-flight-generation"}))
        route_store._flight_booking_service = None
        with patch.dict(os.environ, {"WEBLEDGER_OTA_REVIEW_DB": ""}), patch(
                "webapp.flight_booking_index.prewarm", side_effect=lambda target:
                setattr(target, "_flight_booking_service", initial_service)) as warm:
            path = f"/api/trips/{trip['tab_id']}/flight-bookings"
            status, body, _ = self.request(path, cookie=self.cookie(OWNER))
            self.assertEqual(status, 200, body)
            self.assertEqual(warm.call_count, 1)
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

    def test_batch_card_upload_keeps_owner_and_csrf_boundaries(self):
        raw = b'--boundary\r\nContent-Disposition: form-data; name="files"; filename="invalid.csv"\r\n\r\ninvalid\r\n--boundary--\r\n'
        for user, csrf, expected in ((OWNER, board.CSRF_TOKEN, 202), (OWNER, '', 403),
                                     (VIEWER, board.CSRF_TOKEN, 403), (None, board.CSRF_TOKEN, 401)):
            with self.subTest(user=user, csrf=bool(csrf)):
                headers = {'Content-Type': 'multipart/form-data; boundary=boundary', 'X-CSRF-Token': csrf}
                if user:
                    headers['Cookie'] = f'{google_oidc.COOKIE_NAME}={self.cookie(user)}'
                req = Request(f'http://127.0.0.1:{self.port}/api/imports/upload-batch', data=raw, headers=headers)
                try:
                    response = self.opener.open(req, timeout=5)
                except HTTPError as error:
                    response = error
                result = json.loads(response.read())
                self.assertEqual(response.code, expected, result)
                if expected == 202:
                    self.assertEqual(len(result['files']), 1)
                    self.assertNotIn('status_url', result['files'][0])

    def test_signed_coverage_upload_confirmation_and_read_boundaries(self):
        from tests.card_pipeline.test_card_upload_coverage import content
        from urllib.parse import quote
        raw = content(rows=False, preamble=[
            ['조회기간', '2026-04-01 ~ 2026-04-10'], ['조회기준', '이용일'],
            ['카드사', 'SYNTH'], ['카드번호', '1234-56**-****-1111']])
        headers = {'Content-Type': 'application/octet-stream',
                   'X-CSRF-Token': board.CSRF_TOKEN, 'X-Filename': quote('synthetic.csv'),
                   'Cookie': f'{google_oidc.COOKIE_NAME}={self.cookie(OWNER)}'}
        req = Request(f'http://127.0.0.1:{self.port}/api/imports', data=raw, headers=headers)
        response = self.opener.open(req, timeout=5)
        self.assertEqual(response.code, 200)
        uploaded = json.loads(response.read())
        self.assertTrue(uploaded['coverage_available'])
        batch_path = '/api/imports/' + uploaded['batch_id'] + '/coverage'
        evidence = dict(uploaded['coverage_evidence'], complete=True)
        status, body, _ = self.request('/api/cards/coverage/summary', cookie=self.cookie(OWNER))
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['coverages'], [])
        for user, token, expected in ((None, board.CSRF_TOKEN, 401),
                                      (VIEWER, board.CSRF_TOKEN, 403), (OWNER, '', 403),
                                      (OWNER, board.CSRF_TOKEN, 200)):
            status, body, _ = self.request(batch_path + '/confirm',
                cookie=self.cookie(user) if user else None,
                payload={'evidence': evidence}, headers={'X-CSRF-Token': token})
            self.assertEqual(status, expected, body)
        status, body, _ = self.request('/api/cards/coverage/summary?through=2026-04-10',
                                       cookie=self.cookie(OWNER))
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['coverages'][0]['periods'],
                         [{'start': '2026-04-01', 'end': '2026-04-10'}])
        for user, expected in ((OWNER, 200), (VIEWER, 403), (None, 401)):
            status, body, _ = self.request(batch_path, cookie=self.cookie(user) if user else None)
            self.assertEqual(status, expected, body)

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
        actual_status, actual_body, response_headers = self.request(
            path, cookie=cookie, headers={'Accept': 'application/json', **(headers or {})})
        self.assertEqual(actual_status, status, actual_body)
        self.assertIn('application/json', response_headers.get('Content-Type', ''))
        self.assertEqual(json.loads(actual_body), body)

    def test_private_pages_and_apis_never_cache_signed_or_denied_responses(self):
        # The Google ledger routes were retired; only receipt routes continue
        # to exercise signed-role access and private no-cache responses here.
        for user, receipt_status in ((OWNER, 200), (VIEWER, 404), (None, 401)):
            cookie = self.cookie(user) if user else None
            for path, expected in (('/receipts', receipt_status), ('/api/receipts', receipt_status)):
                status, body, headers = self.request(path, cookie=cookie)
                self.assertEqual(status, expected, (path, body))
                self.assertEqual(headers.get('Cache-Control'), 'no-store', path)
        for path in ('/google-ledger', '/api/google-ledger'):
            status, _, headers = self.request(path, cookie=self.cookie(OWNER))
            self.assertEqual(status, 404, path)
            self.assertEqual(headers.get('Cache-Control'), 'no-store', path)

    def test_real_pages_and_apis_enforce_each_role(self):
        # These endpoints are intentionally no longer served by the product.
        owner, viewer = self.cookie(OWNER), self.cookie(VIEWER)
        for path in ("/google-ledger", "/api/google-ledger"):
            for user in (OWNER, VIEWER, None):
                status, body, _ = self.request(path, cookie=self.cookie(user) if user else None)
                self.assertEqual(status, 401 if user is None else 404, (path, user, body))

        for path in ("/receipts", "/api/receipts"):
            status, body, _ = self.request(path, cookie=owner)
            self.assertEqual(status, 200, body)
            if path.startswith('/api/'):
                self.assertEqual(json.loads(body), {
                    "candidates": [], "holds": [], "images": [], "pdfs": [], "uploads": []
                })
            else:
                self.assertIn('영수증', body)
            viewer_status, viewer_body, _ = self.request(path, cookie=viewer)
            self.assertEqual(viewer_status, 404)
            self.assertEqual(viewer_body, "없음")
            if not path.startswith('/api/'):
                denied, login, response_headers = self.request(path)
                self.assertEqual(denied, 401)
                self.assertIn('text/html', response_headers.get('Content-Type', ''))
                self.assertIn('/auth/login', login)
                self.assertNotIn(OWNER, login)
                self.assertNotIn(VIEWER, login)
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
        }, status=401, body={"code": "AUTH_REQUIRED", "message": "다시 로그인해 주세요"})

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
        self.assertEqual(headers.get('Location'), '/cards/all')
        status, body, headers = self.request('/import?scope=all', cookie=self.cookie(OWNER))
        self.assertEqual(status, 302, body)
        self.assertEqual(headers.get('Location'), '/cards/all?scope=all')
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
            self.assert_json_response("/api/google-ledger", cookie=invalid, status=401,
                                      body={"code": "AUTH_REQUIRED", "message": "다시 로그인해 주세요"})

        self.access.bump_session_generation(OWNER)
        self.assert_json_response("/api/google-ledger", cookie=live, status=401,
                                  body={"code": "AUTH_REQUIRED", "message": "다시 로그인해 주세요"})
        fresh = self.cookie(VIEWER)
        self.access.set_account_active(user_id=VIEWER, is_active=False)
        self.assert_json_response("/api/google-ledger", cookie=fresh, status=401,
                                  body={"code": "AUTH_REQUIRED", "message": "다시 로그인해 주세요"})

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
        # The Google ledger HTTP surface has been retired (google_ledger_page.ROUTES
        # is empty); its former grant workflow is no longer an HTTP contract.
        for path in ('/api/google-ledger', '/google-ledger',
                     '/api/google-ledger/rows?key=SYNTH-GOOGLE-TRIP&source=main'):
            for user in (OWNER, VIEWER, None):
                with self.subTest(path=path, user=user):
                    status, body, _ = self.request(path, cookie=self.cookie(user) if user else None)
                    self.assertEqual(status, 401 if user is None else 404, (path, body))

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
