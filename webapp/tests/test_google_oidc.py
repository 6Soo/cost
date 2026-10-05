"""Real Google OIDC: the flow, the cookie, the identity rules, the routes.

There is no network and no credential here. The verifier and the token exchange
are injected, exactly as `provider_transport` injects its transport, so the
protocol is exercised end to end while nothing leaves the machine. Every value
in this file is an obvious placeholder; none of it is a real client id or secret.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from webapp import access_control
from webapp import google_oidc
from webapp import ledger_board
from webapp import ops
from webapp.ledger_store import LedgerStore

# Obvious placeholders. The session secret has to look real to the length check
# and unlike the banned markers, which is the point of those checks.
FAKE_SESSION_SECRET = "k7Qm2Zx9Tb4Nq8Vr3Ls6Wy1Pd5Gj0Hf7Ce2Ui4Ok8Mn1"
FAKE_CLIENT_ID = "not-a-real-client-id.apps.googleusercontent.com"
FAKE_CLIENT_SECRET = "not-a-real-client-secret"
FAKE_BASE_URL = "https://ledger.example.test"
OWNER_SUB = "104392118726514019283"
STAFF_SUB = "105817364928471635012"


def env(**overrides) -> dict:
    base = {
        google_oidc.ENV_CLIENT_ID: FAKE_CLIENT_ID,
        google_oidc.ENV_CLIENT_SECRET: FAKE_CLIENT_SECRET,
        google_oidc.ENV_SESSION_SECRET: FAKE_SESSION_SECRET,
        google_oidc.ENV_PUBLIC_BASE_URL: FAKE_BASE_URL,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


class FakeVerifier(google_oidc.GoogleAuthTokenVerifier):
    """A verifier that returns canned claims, standing in for google-auth.

    The production path is `GoogleAuthTokenVerifier` with no loader, which calls
    `google.oauth2.id_token.verify_oauth2_token`. The claim checks in
    `validate_claims` still run for both, so a claim that does not belong is
    refused here too.
    """

    def __init__(self, *, claims_by_token=None, client_id=FAKE_CLIENT_ID,
                 available=True, **kwargs):
        super().__init__(client_id=client_id, **kwargs)
        self.claims_by_token = claims_by_token or {}
        self.default_claims = None
        self._available = available
        self.seen = []
        # The base class only calls `_idinfo_loader`, so that is the seam
        # this subclass has to fill. Without it every "verified" test would
        # quietly fall through to importing google-auth.
        self._idinfo_loader = self._load

    @property
    def available(self):
        return self._available

    def _load(self, id_token):
        self.seen.append(id_token)
        if id_token in self.claims_by_token:
            value = self.claims_by_token[id_token]
            if isinstance(value, Exception):
                raise value
            return value
        if self.default_claims is not None:
            return dict(self.default_claims)
        raise google_oidc.OIDCError("ID_TOKEN_INVALID", "알 수 없는 token 이에요")


class FakeExchange:
    """Stands in for the HTTPS POST to Google's token endpoint."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else {
            "id_token": "good-token", "access_token": "not-stored",
            "token_type": "Bearer", "expires_in": 3600}
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def make_store(tmp: Path) -> LedgerStore:
    store = LedgerStore(tmp / "board.sqlite")
    access_control.attach_to_ledger_store(store).ensure_schema()
    return store


def make_flow(store, *, claims=None, exchange=None, verifier=None,
              config=None, **config_kwargs):
    cfg = config or google_oidc.OIDCConfig.from_env(
        env(**config_kwargs))
    v = verifier or FakeVerifier(client_id=cfg.client_id,
                                 clock_skew=cfg.allowed_clock_skew)
    if claims is not None:
        v.default_claims = claims
    return google_oidc.connect_oidc(cfg, access_control.attach_to_ledger_store(
        store), verifier=v, exchange=exchange or FakeExchange())


def good_claims(sub=STAFF_SUB, nonce="n", **overrides) -> dict:
    now = int(time.time())
    claims = {"iss": google_oidc.GOOGLE_ISSUER, "aud": FAKE_CLIENT_ID,
              "sub": sub, "exp": now + 3600, "iat": now,
              "email": "staff@example.test", "email_verified": True,
              "name": "김민수", "nonce": nonce}
    claims.update(overrides)
    return claims


class OIDCConfigTests(unittest.TestCase):
    def test_a_complete_environment_produces_a_configuration(self):
        cfg = google_oidc.OIDCConfig.from_env(env())
        self.assertEqual(cfg.client_id, FAKE_CLIENT_ID)
        self.assertEqual(cfg.redirect_uri, f"{FAKE_BASE_URL}/auth/callback")

    def test_every_missing_variable_is_refused(self):
        for name in google_oidc.REQUIRED_ENV:
            with self.subTest(missing=name):
                with self.assertRaises(google_oidc.OIDCError) as ctx:
                    google_oidc.OIDCConfig.from_env(env(**{name: None}))
                self.assertEqual(ctx.exception.code, "OIDC_NOT_CONFIGURED")
                self.assertIn(name, ctx.exception.message)

    def test_a_placeholder_session_secret_is_refused(self):
        for bad in ("changeme", "secret", "a" * 40, "not-a-secret", "x"):
            with self.subTest(secret=bad):
                with self.assertRaises(google_oidc.OIDCError) as ctx:
                    google_oidc.OIDCConfig.from_env(
                        env(**{google_oidc.ENV_SESSION_SECRET: bad}))
                self.assertEqual(ctx.exception.code, "WEAK_SESSION_SECRET")

    def test_a_plaintext_or_loopback_base_url_is_refused(self):
        for bad in ("http://ledger.example.test", "https://127.0.0.1",
                    "https://localhost:8765", "ledger.example.test"):
            with self.subTest(base=bad):
                with self.assertRaises(google_oidc.OIDCError) as ctx:
                    google_oidc.OIDCConfig.from_env(
                        env(**{google_oidc.ENV_PUBLIC_BASE_URL: bad}))
                self.assertIn(ctx.exception.code,
                              ("INSECURE_PUBLIC_BASE_URL",
                               "LOOPBACK_PUBLIC_BASE_URL"))

    def test_describe_never_carries_a_secret_value(self):
        report = google_oidc.OIDCConfig.from_env(env()).describe()
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(FAKE_CLIENT_SECRET, rendered)
        self.assertNotIn(FAKE_SESSION_SECRET, rendered)
        self.assertTrue(report["client_secret_present"])
        self.assertTrue(report["session_secret_present"])

    def test_the_ledger_asks_for_no_mail_or_file_scope(self):
        report = google_oidc.OIDCConfig.from_env(env()).describe()
        # The banned access is mail, Drive and Sheets. `email` is a scope this
        # ledger does need and it contains the substring "mail", so the check
        # names the products rather than the substring.
        for scope in report["scopes"]:
            for banned in ("gmail", "drive", "spreadsheet", "calendar",
                           "contacts", "photos"):
                self.assertNotIn(banned, scope.lower())
        self.assertIn("openid", report["scopes"])
        self.assertIn("email", report["scopes"])


class ClaimValidationTests(unittest.TestCase):
    def _verify(self, **overrides):
        claims = good_claims(**overrides)
        verifier = FakeVerifier()
        return verifier.verify(
            "t", audience=FAKE_CLIENT_ID, nonce=claims.get("nonce"),
        ) if False else google_oidc.validate_claims(
            claims, audience=FAKE_CLIENT_ID, nonce=claims.get("nonce"))

    def test_a_good_token_verifies(self):
        identity = self._verify()
        self.assertEqual(identity["sub"], STAFF_SUB)
        self.assertEqual(identity["email"], "staff@example.test")

    def test_another_issuer_is_refused(self):
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            self._verify(iss="https://evil.example")
        self.assertEqual(ctx.exception.code, "ID_TOKEN_ISSUER")

    def test_another_audience_is_refused(self):
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            google_oidc.validate_claims(good_claims(), audience="other-app")
        self.assertEqual(ctx.exception.code, "ID_TOKEN_AUDIENCE")

    def test_an_expired_token_is_refused(self):
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            self._verify(exp=int(time.time()) - 7200)
        self.assertEqual(ctx.exception.code, "ID_TOKEN_EXPIRED")

    def test_a_token_without_an_expiry_is_refused(self):
        claims = good_claims()
        del claims["exp"]
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            google_oidc.validate_claims(claims, audience=FAKE_CLIENT_ID)
        self.assertEqual(ctx.exception.code, "ID_TOKEN_NO_EXPIRY")

    def test_a_token_without_a_sub_is_refused(self):
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            self._verify(sub="")
        self.assertEqual(ctx.exception.code, "ID_TOKEN_NO_SUB")

    def test_a_mismatched_nonce_is_refused(self):
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            google_oidc.validate_claims(good_claims(nonce="a"),
                                        audience=FAKE_CLIENT_ID, nonce="b")
        self.assertEqual(ctx.exception.code, "NONCE_MISMATCH")

    def test_the_email_is_never_the_account_key(self):
        identity = self._verify()
        self.assertNotEqual(identity["sub"], identity["email"])
        self.assertIn("sub", identity)
        self.assertTrue(google_oidc.OIDCConfig.from_env(env()).describe()
                        ["email_used_as_identity_key"] is False)


class SessionCookieTests(unittest.TestCase):
    def setUp(self):
        self.signer = google_oidc.SessionSigner(FAKE_SESSION_SECRET)

    def test_a_signed_cookie_round_trips(self):
        payload = {"sub": STAFF_SUB, "exp": int(time.time()) + 60, "gen": 3}
        self.assertEqual(self.signer.verify(self.signer.sign(payload)), payload)

    def test_a_tampered_payload_is_refused(self):
        cookie = self.signer.sign({"sub": STAFF_SUB, "gen": 1,
                                   "exp": int(time.time()) + 60})
        forged = cookie.replace("s", "z", 1)
        self.assertIsNone(self.signer.verify(forged))

    def test_a_cookie_signed_with_another_key_is_refused(self):
        other = google_oidc.SessionSigner(
            "Zq4Wm8Xb2Lt7Nv3Ks6Pd1Hg5Jc9Rf0Eu3Ti5Qo8Ny1Ab")
        self.assertIsNone(
            self.signer.verify(other.sign({"sub": STAFF_SUB, "exp": 9})))

    def test_a_malformed_cookie_is_absent_not_an_error(self):
        for bad in ("", "x", "v1.only-two", "v1.a.b.c", "v2.a.b", None, 7):
            with self.subTest(cookie=bad):
                self.assertIsNone(self.signer.verify(bad))

    def test_the_cookie_is_httponly_samesite_lax_and_secure(self):
        header = self.signer.set_cookie_header("abc")
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Lax", header)
        self.assertIn("Secure", header)
        self.assertIn("Path=/", header)
        self.assertTrue(header.startswith(f"{google_oidc.COOKIE_NAME}=abc"))

    def test_the_clear_header_removes_the_same_cookie(self):
        header = google_oidc.clear_cookie_header()
        self.assertIn(f"{google_oidc.COOKIE_NAME}=", header)
        self.assertIn("Max-Age=0", header)
        self.assertIn("Path=/", header)
        self.assertIn("HttpOnly", header)
        self.assertIn("Secure", header)

    def test_the_google_token_is_never_put_in_the_cookie(self):
        value = google_oidc.SessionSigner(FAKE_SESSION_SECRET).sign(
            {"sub": STAFF_SUB, "exp": int(time.time()) + 60, "gen": 1,
             "access_token": "ya29.super-secret"})
        self.assertNotIn("super-secret", value)


class PendingLoginTests(unittest.TestCase):
    def test_a_state_can_be_spent_exactly_once(self):
        pending = google_oidc.PendingLogins()
        state, nonce, _ = pending.issue()
        self.assertEqual(pending.spend(state).nonce, nonce)
        self.assertIsNone(pending.spend(state), "a replayed state must fail")

    def test_an_unknown_state_is_refused(self):
        self.assertIsNone(google_oidc.PendingLogins().spend("made-up"))

    def test_an_expired_state_is_refused(self):
        pending = google_oidc.PendingLogins(ttl=0)
        state, _, _ = pending.issue()
        time.sleep(1.1)
        self.assertIsNone(pending.spend(state))

    def test_two_logins_get_different_values(self):
        pending = google_oidc.PendingLogins()
        first, _, _ = pending.issue()
        second, _, _ = pending.issue()
        self.assertNotEqual(first, second)

    def test_the_store_stays_bounded(self):
        pending = google_oidc.PendingLogins(limit=10)
        for _ in range(40):
            pending.issue()
        self.assertLessEqual(pending.pending_count(), 10)


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oidc-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        access_control.bind_sessions(None)
        ledger_board.bind_oidc(None)

    def _complete(self, flow, sub=STAFF_SUB, **claim_overrides):
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(
            sub=sub, nonce=started["nonce"], **claim_overrides)
        return flow.complete(code="auth-code", state=started["state"]), started

    def test_the_authorization_url_carries_state_and_nonce(self):
        flow = make_flow(self.store, claims=good_claims())
        started = flow.authorization_url()
        self.assertIn(google_oidc.GOOGLE_AUTH_ENDPOINT, started["url"])
        for expected in ("client_id=" + FAKE_CLIENT_ID, "response_type=code",
                         "state=", "nonce=", "code_challenge=",
                         "code_challenge_method=S256", "prompt=select_account"):
            self.assertIn(expected, started["url"])
        # the client secret is never in a URL
        self.assertNotIn(FAKE_CLIENT_SECRET, started["url"])

    def test_a_full_login_registers_a_viewer_and_issues_a_cookie(self):
        flow = make_flow(self.store, claims=good_claims())
        result, _ = self._complete(flow)
        self.assertTrue(result["created"])
        self.assertEqual(result["role"], access_control.ROLE_VIEWER)
        self.assertFalse(result["bootstrap"]["promoted"])
        self.assertEqual(result["account"]["user_id"], STAFF_SUB)
        # the account is keyed on the sub, and marked as not synthetic
        self.assertEqual(result["account"]["is_synthetic"], False)
        self.assertEqual(self.access.account(STAFF_SUB)["role"],
                         access_control.ROLE_VIEWER)

    def test_a_replayed_callback_is_refused_before_any_token_request(self):
        exchange = FakeExchange()
        flow = make_flow(self.store, exchange=exchange, claims=good_claims())
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(nonce=started["nonce"])
        flow.complete(code="auth-code", state=started["state"])
        calls_after_first = len(exchange.calls)
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            flow.complete(code="auth-code", state=started["state"])
        self.assertEqual(ctx.exception.code, "STATE_INVALID")
        self.assertEqual(len(exchange.calls), calls_after_first,
                         "a replay must not reach the token endpoint")

    def test_a_callback_with_the_wrong_state_is_refused(self):
        flow = make_flow(self.store, claims=good_claims())
        flow.authorization_url()
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            flow.complete(code="auth-code", state="not-the-state")
        self.assertEqual(ctx.exception.code, "STATE_INVALID")

    def test_a_token_whose_nonce_does_not_match_is_refused(self):
        flow = make_flow(self.store, claims=good_claims())
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(nonce="a-different-nonce")
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            flow.complete(code="auth-code", state=started["state"])
        self.assertEqual(ctx.exception.code, "NONCE_MISMATCH")
        self.assertIsNone(self.access.account(STAFF_SUB))

    def test_a_refused_exchange_does_not_create_an_account(self):
        flow = make_flow(self.store, exchange=FakeExchange(
            error=google_oidc.OIDCError("TOKEN_EXCHANGE_REFUSED", "no")))
        started = flow.authorization_url()
        with self.assertRaises(google_oidc.OIDCError):
            flow.complete(code="auth-code", state=started["state"])
        self.assertIsNone(self.access.account(STAFF_SUB))

    def test_a_missing_code_is_refused(self):
        flow = make_flow(self.store, claims=good_claims())
        started = flow.authorization_url()
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            flow.complete(code="", state=started["state"])
        self.assertEqual(ctx.exception.code, "AUTH_CODE_MISSING")

    def test_the_verifier_is_consulted_and_the_library_is_named(self):
        verifier = FakeVerifier(available=False)
        flow = make_flow(self.store, verifier=verifier)
        with self.assertRaises(google_oidc.OIDCError) as ctx:
            flow.authorization_url()
        self.assertEqual(ctx.exception.code, "OIDC_LIBRARY_MISSING")
        self.assertIn("google-auth", ctx.exception.message)


class OwnerBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oidc-owner-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        access_control.bind_sessions(None)
        ledger_board.bind_oidc(None)

    def test_no_owner_sub_means_no_owner_at_all(self):
        flow = make_flow(self.store, claims=good_claims(sub=OWNER_SUB))
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(
            sub=OWNER_SUB, nonce=started["nonce"])
        result = flow.complete(code="c", state=started["state"])
        self.assertFalse(result["bootstrap"]["attempted"])
        self.assertEqual(result["role"], access_control.ROLE_VIEWER)
        self.assertIsNone(self.access.conn.execute(
            "SELECT user_id FROM access_accounts WHERE role='owner'"
        ).fetchone())

    def test_a_matching_owner_sub_bootstraps_exactly_one_owner(self):
        flow = make_flow(self.store, claims=good_claims(sub=OWNER_SUB),
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(
            sub=OWNER_SUB, nonce=started["nonce"])
        result = flow.complete(code="c", state=started["state"])
        self.assertTrue(result["bootstrap"]["promoted"])
        self.assertEqual(result["role"], access_control.ROLE_OWNER)
        self.assertTrue(self.access.is_owner(OWNER_SUB))

    def test_a_non_matching_sub_stays_a_viewer(self):
        flow = make_flow(self.store, claims=good_claims(sub=STAFF_SUB),
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(
            sub=STAFF_SUB, nonce=started["nonce"])
        result = flow.complete(code="c", state=started["state"])
        self.assertTrue(result["bootstrap"]["attempted"])
        self.assertFalse(result["bootstrap"]["promoted"])
        self.assertEqual(result["role"], access_control.ROLE_VIEWER)

    def test_a_second_owner_is_not_handed_out(self):
        first = make_flow(self.store, claims=good_claims(sub=OWNER_SUB),
                          **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        started = first.authorization_url()
        first.verifier.default_claims = good_claims(
            sub=OWNER_SUB, nonce=started["nonce"])
        first.complete(code="c", state=started["state"])
        other = make_flow(self.store, claims=good_claims(sub=STAFF_SUB),
                          **{google_oidc.ENV_OWNER_SUB: STAFF_SUB})
        started2 = other.authorization_url()
        other.verifier.default_claims = good_claims(
            sub=STAFF_SUB, nonce=started2["nonce"])
        result = other.complete(code="c", state=started2["state"])
        self.assertFalse(result["bootstrap"]["promoted"])
        self.assertIn("already exists", result["bootstrap"]["reason"])
        self.assertEqual(self.access.account_role(STAFF_SUB),
                         access_control.ROLE_VIEWER)

    def test_a_login_never_changes_an_existing_role(self):
        access_control.AccessStore.ensure_owner(self.access, STAFF_SUB)
        flow = make_flow(self.store, claims=good_claims(sub=STAFF_SUB))
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(
            sub=STAFF_SUB, nonce=started["nonce"])
        result = flow.complete(code="c", state=started["state"])
        self.assertFalse(result["created"])
        self.assertEqual(self.access.account_role(STAFF_SUB),
                         access_control.ROLE_OWNER)

    def test_a_login_never_reactivates_a_deactivated_account(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        self.access.set_account_active(user_id=STAFF_SUB, is_active=False)
        flow = make_flow(self.store, claims=good_claims(sub=STAFF_SUB))
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(
            sub=STAFF_SUB, nonce=started["nonce"])
        flow.complete(code="c", state=started["state"])
        self.assertFalse(self.access.account(STAFF_SUB)["is_active"])


class AdapterAndGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oidc-gen-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        access_control.bind_sessions(None)
        ledger_board.bind_oidc(None)

    def _signed_cookie(self, generation, sub=STAFF_SUB, **extra):
        return google_oidc.SessionSigner(FAKE_SESSION_SECRET).sign(
            {"sub": sub, "email": "s@example.test", "name": "김민수",
             "iat": int(time.time()), "exp": int(time.time()) + 600,
             "gen": generation, **extra})

    def test_a_valid_cookie_yields_a_session(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        cookie = self._signed_cookie(self.access.session_generation(STAFF_SUB))
        session = flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"})
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, STAFF_SUB)
        self.assertEqual(session.provider, "google")
        self.assertFalse(session.is_synthetic)

    def test_a_cookie_from_a_jar_is_read_too(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        cookie = self._signed_cookie(self.access.session_generation(STAFF_SUB))
        jar = {"webledger_session": cookie}
        self.assertIsNotNone(flow.adapter.session_for({}, jar))

    def test_a_stale_generation_is_refused(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        old_generation = self.access.session_generation(STAFF_SUB)
        self.access.bump_session_generation(STAFF_SUB)
        cookie = self._signed_cookie(old_generation)
        self.assertIsNone(
            flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"}))

    def test_a_logout_bumps_the_generation_and_invalidates_the_cookie(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        cookie = self._signed_cookie(self.access.session_generation(STAFF_SUB))
        self.assertIsNotNone(
            flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"}))
        new_generation = self.access.bump_session_generation(STAFF_SUB)
        self.assertIsNone(
            flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"}))
        fresh = self._signed_cookie(new_generation)
        self.assertIsNotNone(
            flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={fresh}"}))

    def test_a_cookie_for_an_unknown_or_deactivated_account_is_refused(self):
        flow = make_flow(self.store, claims=good_claims())
        unknown = self._signed_cookie(1, sub="nobody")
        self.assertIsNone(
            flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={unknown}"}))
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        live = self._signed_cookie(self.access.session_generation(STAFF_SUB))
        self.access.set_account_active(user_id=STAFF_SUB, is_active=False)
        self.assertIsNone(
            flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={live}"}))

    def test_an_expired_cookie_is_refused(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        cookie = google_oidc.SessionSigner(FAKE_SESSION_SECRET).sign(
            {"sub": STAFF_SUB, "exp": int(time.time()) - 10, "gen": 1})
        self.assertIsNone(
            flow.adapter.session_for({"Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"}))

    def test_the_adapter_never_accepts_a_synthetic_header(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        headers = {access_control.SyntheticSessionAdapter.HEADER: STAFF_SUB}
        self.assertFalse(flow.adapter.allow_synthetic)
        self.assertIsNone(flow.adapter.session_for(headers))

    def test_require_session_refuses_a_stale_cookie_end_to_end(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_access(self.access)
        try:
            stale = self._signed_cookie(self.access.session_generation(STAFF_SUB))
            self.access.bump_session_generation(STAFF_SUB)
            with self.assertRaises(access_control.AccessError) as ctx:
                ledger_board.require_session(
                    {"Cookie": f"{google_oidc.COOKIE_NAME}={stale}"})
            # The adapter refuses the stale cookie outright, so there is no
            # session left to call stale and the answer is AUTH_REQUIRED.
            # That is deliberate: a stale cookie has to look exactly like no
            # cookie, or the difference tells the holder of an old one that it
            # once worked.
            self.assertEqual(ctx.exception.code, "AUTH_REQUIRED")
            self.assertEqual(ctx.exception.status, 401)
        finally:
            ledger_board.bind_access(None)


class RouteTests(unittest.TestCase):
    """The three routes and the state line, over a real socket."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oidc-routes-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)
        self.port = 0
        with __import__("socket").socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = ledger_board.serve(port=self.port,
                                         db_path=self.tmp / "board.sqlite",
                                         with_worker=False)
        ledger_board.bind_access(self.access)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        ledger_board.bind_oidc(None)
        ledger_board.bind_access(None)
        access_control.bind_sessions(None)
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, path, headers=None, follow=False):
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(url, headers=headers or {})
        opener = (urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
                  if follow else urllib.request.build_opener(
                      _NoRedirect()))
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), \
                    response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), \
                exc.read().decode("utf-8", "replace")

    def test_login_redirects_to_google(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        status, headers, _ = self._get("/auth/login")
        self.assertEqual(status, 303)
        location = headers["Location"]
        self.assertIn("accounts.google.com", location)
        self.assertIn("state=", location)
        self.assertIn("nonce=", location)

    def test_card_flow_login_uses_home_and_preserves_an_explicit_board_target(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        with patch.dict(os.environ, {"WEBLEDGER_CARD_FLOW": "1"}):
            for path, target in (("/auth/login", "/"),
                                 ("/auth/login?return_to=%2Fboard", "/board")):
                with self.subTest(path=path):
                    status, headers, _ = self._get(path)
                    self.assertEqual(status, 303)
                    params = parse_qs(urlparse(headers["Location"]).query)
                    flow.verifier.default_claims = good_claims(nonce=params["nonce"][0])
                    status, headers, _ = self._get(
                        f"/auth/callback?code=auth-code&state={params['state'][0]}")
                    self.assertEqual(status, 303)
                    self.assertEqual(headers["Location"], target)
                    self.assertIn(google_oidc.COOKIE_NAME, headers["Set-Cookie"])

    def test_login_answers_503_when_nothing_is_configured(self):
        status, _, body = self._get("/auth/login")
        self.assertEqual(status, 503)
        self.assertNotIn("accounts.google.com", body)

    def test_callback_without_a_flow_answers_503(self):
        status, _, _ = self._get("/auth/callback?code=c&state=s")
        self.assertEqual(status, 503)

    def test_callback_with_a_bad_state_is_refused(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        status, _, body = self._get("/auth/callback?code=c&state=wrong")
        self.assertEqual(status, 400)
        self.assertIn('data-refusal="STATE_INVALID"', body)
        self.assertIsNone(self.access.account(STAFF_SUB))

    def test_callback_that_google_refused_is_reported(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        status, _, _ = self._get("/auth/callback?error=access_denied")
        self.assertEqual(status, 400)

    def test_a_full_callback_sets_the_cookie_and_redirects(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(nonce=started["nonce"])
        status, headers, _ = self._get(
            f"/auth/callback?code=auth-code&state={started['state']}")
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"]
        self.assertIn(google_oidc.COOKIE_NAME, cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Secure", cookie)
        self.assertNotIn(FAKE_SESSION_SECRET, cookie)
        # and the browser now has a session the server accepts
        value = cookie.split(";")[0]
        self.assertIsNotNone(
            flow.adapter.session_for({"Cookie": value}))

    def test_logout_clears_the_cookie(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        status, headers, _ = self._get("/access/logout")
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"]
        self.assertIn("Max-Age=0", cookie)
        self.assertIn(google_oidc.COOKIE_NAME, cookie)
        self.assertIn("HttpOnly", cookie)

    def test_the_post_logout_clears_the_cookie_too(self):
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        generation = self.access.session_generation(STAFF_SUB)
        cookie = google_oidc.SessionSigner(FAKE_SESSION_SECRET).sign(
            {"sub": STAFF_SUB, "exp": int(time.time()) + 600, "gen": generation})
        body = json.dumps({}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/access/logout", data=body,
            headers={"Content-Type": "application/json",
                     "Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            headers = dict(response.headers)
        self.assertTrue(payload["logged_out"])
        self.assertTrue(payload["cookie_cleared"])
        self.assertGreater(payload["session_generation"], generation)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])

    def test_the_state_line_reports_the_connection(self):
        flow = make_flow(self.store, claims=good_claims(),
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        ledger_board.bind_oidc(flow)
        status, _, body = self._get("/auth/state")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["google_oidc_connected"])
        self.assertTrue(payload["owner_bootstrap_configured"])
        self.assertEqual(payload["account_key"], "google sub")
        self.assertNotIn(FAKE_CLIENT_SECRET, body)
        self.assertNotIn(FAKE_SESSION_SECRET, body)

    def test_the_state_line_says_so_when_nothing_is_connected(self):
        status, _, body = self._get("/auth/state")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertFalse(payload["google_oidc_connected"])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class OpsReportingTests(unittest.TestCase):
    """The operational surfaces have to describe the login, not imply one.

    `ops health` and `ops dry-run` are what an operator reads before a cutover.
    A line that says "connected" when nothing is connected is worse than a
    missing line, because it is the one that gets believed.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oidc-ops-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)
        self.root = self.tmp / "data"
        for sub in ("", "exports", "evidence", "source"):
            (self.root / sub if sub else self.root).mkdir(parents=True,
                                                          exist_ok=True)
        self.config = ops.durable_config_for(self.root, create=True)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        access_control.bind_sessions(None)
        ledger_board.bind_oidc(None)

    def _health_lines(self):
        report = ops.health_check(self.config)
        return {c["check"]: c for c in report["checks"]}

    def test_health_reports_the_oidc_line_as_not_connected(self):
        line = self._health_lines()["google_oidc_connected"]
        self.assertFalse(line["ok"])
        # The detail is the reason, not a label with the reason somewhere else.
        self.assertTrue(line["detail"].strip())
        self.assertIn("refuses every session", line["detail"])

    def test_health_reports_connected_only_when_a_flow_is_bound(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        line = self._health_lines()["google_oidc_connected"]
        self.assertTrue(line["ok"], line["detail"])
        self.assertIn("google OIDC connected", line["detail"])

    def test_health_does_not_claim_a_connection_from_the_environment(self):
        # The environment can be fully set while the process serves no flow, for
        # example after a restart that failed to bind. Health has to describe the
        # process, not the settings someone meant to apply.
        saved = {name: os.environ.get(name) for name in google_oidc.REQUIRED_ENV}
        os.environ.update(env())
        try:
            line = self._health_lines()["google_oidc_connected"]
            self.assertFalse(line["ok"])
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_health_never_prints_a_secret(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        rendered = json.dumps(ops.health_check(self.config), ensure_ascii=False)
        self.assertNotIn(FAKE_CLIENT_SECRET, rendered)
        self.assertNotIn(FAKE_SESSION_SECRET, rendered)

    def test_a_production_dry_run_needs_a_connected_login(self):
        manifest = ops.build_deploy_manifest(self.config)
        run = ops.dry_run_deploy(self.config, manifest)
        names = {c["check"]: c for c in run["checks"]}
        # A production runbook is checked in its own environment, so the strict
        # line only appears there.
        self.assertIn("google_oidc_connection_recorded", names)
        self.assertNotIn("google_oidc_connected", run["failed"])

    def _production_config(self):
        """A production config, with the temp-root refusal moved out of the way.

        A temp-rooted production root is refused on its own, which is correct and
        has its own test. Pointing the temp root elsewhere for the duration lets
        these two tests look at the login gate instead of that one.
        """
        original = ops.tempfile.gettempdir
        ops.tempfile.gettempdir = lambda: str(Path("Z:/a-temp-root-that-is-not-here"))
        try:
            return ops.durable_config_for(self.root, environment="production")
        finally:
            ops.tempfile.gettempdir = original

    def test_a_temp_rooted_production_config_is_refused_on_its_own(self):
        # The reason these two tests need the temp root moved aside: this gate
        # fires first and would hide the login one.
        with self.assertRaises(ops.OpsError) as ctx:
            ops.durable_config_for(self.root, environment="production")
        self.assertEqual(ctx.exception.code, "TEMP_DATA_ROOT")

    def test_a_production_dry_run_fails_without_a_login(self):
        production = self._production_config()
        run = ops.dry_run_deploy(production,
                                 ops.build_deploy_manifest(production))
        self.assertIn("google_oidc_connected", run["failed"])
        names = {c["check"]: c for c in run["checks"]}
        self.assertFalse(names["google_oidc_connected"]["ok"])

    def test_a_production_dry_run_passes_with_a_login(self):
        flow = make_flow(self.store, claims=good_claims())
        ledger_board.bind_oidc(flow)
        production = self._production_config()
        run = ops.dry_run_deploy(production,
                                 ops.build_deploy_manifest(production))
        self.assertNotIn("google_oidc_connected", run["failed"])
        names = {c["check"]: c for c in run["checks"]}
        self.assertTrue(names["google_oidc_connected"]["ok"])

    def test_the_state_reports_presence_not_values(self):
        state = google_oidc.connection_state(None)
        self.assertFalse(state["google_oidc_connected"])
        self.assertEqual(state["library"], "google-auth")
        flow = make_flow(self.store, claims=good_claims())
        rendered = json.dumps(google_oidc.connection_state(flow),
                              ensure_ascii=False)
        self.assertNotIn(FAKE_CLIENT_SECRET, rendered)
        self.assertNotIn(FAKE_SESSION_SECRET, rendered)
        self.assertNotIn(FAKE_CLIENT_ID, rendered)


class AccessMeConnectionStateTests(unittest.TestCase):
    """`/access/me` must report the deployment's real login state.

    Observed before the fix: `access_control_render_viewer_status` carried
    `"google_oidc_connected": False` as a literal, so a host where a real Google
    login worked still answered `false` on `/access/me` while `ops health` and
    `/auth/state` both answered `true`. Three surfaces, two answers.

    These tests bind a working flow and read the same route, so the value has to
    come from the bound flow rather than from a constant.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oidc-me-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        self.port = 0
        with __import__("socket").socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = ledger_board.serve(port=self.port,
                                         db_path=self.tmp / "board.sqlite",
                                         with_worker=False)
        ledger_board.bind_access(self.access)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        ledger_board.bind_oidc(None)
        ledger_board.bind_access(None)
        access_control.bind_sessions(None)
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _me(self, flow=None):
        if flow is None:
            # No Google flow bound. Reaching the route needs some session, and
            # the synthetic seam is the one that exists in that state. The
            # connection state on the payload is a deployment fact, so it does
            # not depend on which session type got us here.
            ledger_board.bind_oidc(None)
            access_control.bind_synthetic_sessions(True)
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/access/me",
                headers={access_control.SyntheticSessionAdapter.HEADER:
                         STAFF_SUB})
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        ledger_board.bind_oidc(flow)
        generation = self.access.session_generation(STAFF_SUB)
        cookie = flow.adapter.issue_cookie(
            {"sub": STAFF_SUB, "name": "김민수",
             "email": "staff@example.test"}, generation=generation)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/access/me",
            headers={"Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_a_connected_login_is_reported_as_connected(self):
        flow = make_flow(self.store, claims=good_claims())
        payload = self._me(flow)
        self.assertTrue(payload["google_oidc_connected"])
        self.assertEqual(payload["identity_source"], "google_oidc")
        self.assertEqual(payload["user_id"], STAFF_SUB)

    def test_no_connection_is_reported_as_not_connected(self):
        payload = self._me(None)
        self.assertFalse(payload["google_oidc_connected"])
        self.assertIn("reason", payload["google_oidc"])

    def test_the_route_and_health_never_disagree(self):
        """The defect was three surfaces answering two different things."""
        for bound in (True, False):
            with self.subTest(connected=bound):
                flow = make_flow(self.store, claims=good_claims()) if bound else None
                from_me = self._me(flow)["google_oidc_connected"]
                from_state = google_oidc.connection_state(
                    ledger_board.oidc_flow())["google_oidc_connected"]
                from_ops = ops.google_oidc_state()["google_oidc_connected"]
                self.assertEqual(from_me, from_state)
                self.assertEqual(from_me, from_ops)
                self.assertEqual(from_me, bound)

    def test_the_response_carries_the_state_it_used(self):
        flow = make_flow(self.store, claims=good_claims(),
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        payload = self._me(flow)
        state = payload["google_oidc"]
        # The detail is present so an operator can see why, not just the verdict.
        self.assertTrue(state["configured"])
        self.assertEqual(state["account_key"], "google sub")
        self.assertTrue(state["owner_bootstrap_configured"])
        self.assertEqual(state["library"], "google-auth")

    def test_the_response_carries_no_secret(self):
        flow = make_flow(self.store, claims=good_claims())
        payload = self._me(flow)
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(FAKE_CLIENT_SECRET, rendered)
        self.assertNotIn(FAKE_SESSION_SECRET, rendered)
        self.assertNotIn(FAKE_CLIENT_ID, rendered)

    def test_the_view_helper_reads_the_bound_flow(self):
        # The renderer itself, without the socket, so a caller that builds a
        # status payload elsewhere gets the same answer.
        session = access_control.Session(
            user_id=STAFF_SUB, provider="google", is_synthetic=False,
            session_generation=self.access.session_generation(STAFF_SUB))
        ledger_board.bind_oidc(None)
        before = ledger_board.access_control_render_viewer_status(
            session, self.access)["google_oidc_connected"]
        self.assertFalse(before)
        ledger_board.bind_oidc(make_flow(self.store, claims=good_claims()))
        after = ledger_board.access_control_render_viewer_status(
            session, self.access)["google_oidc_connected"]
        self.assertTrue(after)

    def test_a_bound_flow_without_the_library_is_not_connected(self):
        # A configured client that cannot verify a token cannot log anyone in, so
        # reporting it as connected would be the same lie in a new place.
        flow = make_flow(self.store,
                         verifier=FakeVerifier(available=False))
        ledger_board.bind_oidc(flow)
        state = ledger_board.google_oidc_connection_state()
        self.assertFalse(state["google_oidc_connected"])
        self.assertFalse(state["library_available"])

    def test_the_route_reads_the_verdict_and_not_merely_the_configuration(self):
        """`configured` and `google_oidc_connected` are different facts.

        A deployment can be fully configured and still not able to log anyone
        in, because `google-auth` is missing and a token cannot be verified.
        This checks that case at the route, where a substitution of one fact for
        the other would otherwise be invisible: with a working flow both facts
        are true and the two cannot be told apart.
        """
        flow = make_flow(self.store,
                         verifier=FakeVerifier(available=False))
        # Bind before reading: with no flow bound the state is the early
        # "nothing configured" answer, which has no `configured` key at all.
        ledger_board.bind_oidc(flow)
        state = ledger_board.google_oidc_connection_state()
        self.assertTrue(state["configured"],
                        "the client is configured in this scenario")
        self.assertFalse(state["google_oidc_connected"])
        self.assertFalse(state["library_available"])

        generation = self.access.session_generation(STAFF_SUB)
        cookie = flow.adapter.issue_cookie(
            {"sub": STAFF_SUB, "name": "김민수", "email": "s@example.test"},
            generation=generation)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/access/me",
            headers={"Cookie": f"{google_oidc.COOKIE_NAME}={cookie}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertFalse(payload["google_oidc_connected"])
        self.assertTrue(payload["google_oidc"]["configured"])
        self.assertFalse(payload["google_oidc"]["library_available"])


class OpsUsesTheSameAnswerTests(unittest.TestCase):
    """`ops` must not keep its own copy of the answer.

    Two implementations that are supposed to agree eventually disagree, and the
    one that is believed at a cutover is the one an operator reads. These check
    behaviour rather than source text: a string search for the helper name
    passes while the call is still bypassed.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oidc-ops-share-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)

    def tearDown(self):
        ledger_board.bind_oidc(None)
        access_control.bind_sessions(None)
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_both_paths_return_the_same_value(self):
        for bound in (True, False):
            with self.subTest(connected=bound):
                flow = make_flow(self.store, claims=good_claims()) if bound else None
                ledger_board.bind_oidc(flow)
                from_ops = ops.google_oidc_state()
                from_board = ledger_board.google_oidc_connection_state()
                self.assertEqual(from_ops["google_oidc_connected"],
                                 from_board["google_oidc_connected"])
                self.assertEqual(from_ops["google_oidc_connected"], bound)
                self.assertEqual(
                    ops.google_oidc_state()["google_oidc_connected"],
                    google_oidc.connection_state(
                        ledger_board.oidc_flow())["google_oidc_connected"])

    def test_ops_follows_the_process_and_not_the_environment(self):
        # The environment can be fully set while the process serves no flow, for
        # example after a restart that failed to bind. `ops` describes the
        # process, so it has to say "not connected" here.
        saved = {name: os.environ.get(name) for name in google_oidc.REQUIRED_ENV}
        os.environ.update(env())
        try:
            self.assertFalse(ops.google_oidc_state()["google_oidc_connected"])
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_ops_follows_a_flow_that_is_bound_after_a_restart(self):
        saved = {name: os.environ.get(name) for name in google_oidc.REQUIRED_ENV}
        for name in google_oidc.REQUIRED_ENV:
            os.environ.pop(name, None)
        try:
            self.assertFalse(ops.google_oidc_state()["google_oidc_connected"])
            flow = make_flow(self.store, claims=good_claims())
            ledger_board.bind_oidc(flow)
            self.assertTrue(ops.google_oidc_state()["google_oidc_connected"])
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_the_board_helper_is_the_one_that_exists(self):
        self.assertTrue(callable(ledger_board.google_oidc_connection_state))
        self.assertTrue(callable(ledger_board.oidc_flow))


if __name__ == "__main__":
    unittest.main()
