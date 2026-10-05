"""Owner bootstrap security: sub self-discovery and session invalidation.

Sol-approved scope in this isolated worktree:
1. An operator discovers only their own Google `sub` from authenticated
   `/access/me` (`own_google_sub`). No endpoint lists other subs and the
   configured owner value is never echoed.
2. Promoting an existing viewer to owner bumps `session_generation`, so
   cookies issued under the old viewer role are refused instead of silently
   gaining owner rights.

Synthetic values only. No network, no real credential.
"""

import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from webapp import access_control
from webapp import google_oidc
from webapp import ledger_board
from webapp.ledger_store import LedgerStore

FAKE_SESSION_SECRET = "k7Qm2Zx9Tb4Nq8Vr3Ls6Wy1Pd5Gj0Hf7Ce2Ui4Ok8Mn1"
FAKE_CLIENT_ID = "not-a-real-client-id.apps.googleusercontent.com"
FAKE_CLIENT_SECRET = "not-a-real-client-secret"
FAKE_BASE_URL = "https://ledger.example.test"
OWNER_SUB = "104392118726514019283"
STAFF_SUB = "105817364928471635012"


def env(**overrides):
    base = {
        google_oidc.ENV_CLIENT_ID: FAKE_CLIENT_ID,
        google_oidc.ENV_CLIENT_SECRET: FAKE_CLIENT_SECRET,
        google_oidc.ENV_SESSION_SECRET: FAKE_SESSION_SECRET,
        google_oidc.ENV_PUBLIC_BASE_URL: FAKE_BASE_URL,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


class FakeVerifier(google_oidc.GoogleAuthTokenVerifier):
    def __init__(self, *, client_id=FAKE_CLIENT_ID, **kwargs):
        super().__init__(client_id=client_id, **kwargs)
        self.default_claims = None
        self._idinfo_loader = self._load

    def _load(self, id_token):
        if self.default_claims is not None:
            return dict(self.default_claims)
        raise google_oidc.OIDCError("ID_TOKEN_INVALID", "bad token")


class FakeExchange:
    def __call__(self, **kwargs):
        return {"id_token": "good-token"}


def make_store(tmp: Path) -> LedgerStore:
    store = LedgerStore(tmp / "board.sqlite")
    access_control.attach_to_ledger_store(store).ensure_schema()
    return store


def good_claims(sub=STAFF_SUB, nonce="n"):
    now = int(time.time())
    return {"iss": google_oidc.GOOGLE_ISSUER, "aud": FAKE_CLIENT_ID,
            "sub": sub, "exp": now + 3600, "iat": now,
            "email": "staff@example.test", "email_verified": True,
            "name": "Staff", "nonce": nonce}


def make_flow(store, **config_kwargs):
    cfg = google_oidc.OIDCConfig.from_env(env(**config_kwargs))
    verifier = FakeVerifier(client_id=cfg.client_id,
                            clock_skew=cfg.allowed_clock_skew)
    access = access_control.attach_to_ledger_store(store)
    return google_oidc.connect_oidc(cfg, access, verifier=verifier,
                                    exchange=FakeExchange())


class BootstrapInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="owner-boot-sec-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        access_control.bind_sessions(None)
        ledger_board.bind_oidc(None)
        ledger_board.bind_access(None)

    def _complete(self, flow, sub):
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(sub=sub,
                                                   nonce=started["nonce"])
        return flow.complete(code="c", state=started["state"]), started

    def test_promotion_bumps_generation_and_invalidates_old_viewer_cookie(self):
        flow = make_flow(self.store,
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        # Existing viewer session before bootstrap.
        self.access.create_account(user_id=OWNER_SUB,
                                   role=access_control.ROLE_VIEWER)
        old_generation = self.access.session_generation(OWNER_SUB)
        old_cookie = flow.adapter.issue_cookie(
            {"sub": OWNER_SUB, "name": "Owner", "email": "o@example.test"},
            generation=old_generation)
        self.assertIsNotNone(
            flow.adapter.session_for(
                {"Cookie": f"{google_oidc.COOKIE_NAME}={old_cookie}"}))
        result, _ = self._complete(flow, OWNER_SUB)
        self.assertTrue(result["bootstrap"]["promoted"])
        self.assertTrue(result["bootstrap"]["session_invalidated"])
        self.assertGreater(result["generation"], old_generation)
        # The pre-bootstrap viewer cookie is now stale.
        self.assertIsNone(
            flow.adapter.session_for(
                {"Cookie": f"{google_oidc.COOKIE_NAME}={old_cookie}"}))
        # The newly issued cookie works and carries the new generation.
        fresh = flow.adapter.session_for(
            {"Cookie": f"{google_oidc.COOKIE_NAME}={result['cookie_value']}"})
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.session_generation, result["generation"])

    def test_fresh_owner_has_no_prior_sessions_to_invalidate(self):
        flow = make_flow(self.store,
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        result, _ = self._complete(flow, OWNER_SUB)
        self.assertTrue(result["bootstrap"]["promoted"])
        self.assertFalse(result["bootstrap"]["session_invalidated"])
        # The viewer row is created moments earlier in the same login, so a
        # generation is present but no prior cookie existed to invalidate.

    def test_repeated_owner_login_does_not_bump_generation(self):
        flow = make_flow(self.store,
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        result, _ = self._complete(flow, OWNER_SUB)
        generation = result["generation"]
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(sub=OWNER_SUB,
                                                   nonce=started["nonce"])
        second = flow.complete(code="c", state=started["state"])
        self.assertFalse(second["bootstrap"]["promoted"])
        self.assertEqual(second["generation"], generation)


class SelfDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="owner-disc-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)
        ledger_board.bind_access(self.access)

    def tearDown(self):
        ledger_board.bind_oidc(None)
        ledger_board.bind_access(None)
        access_control.bind_sessions(None)
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_me_returns_only_own_sub_with_guidance(self):
        flow = make_flow(self.store)
        ledger_board.bind_oidc(flow)
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        session = access_control.Session(
            user_id=STAFF_SUB, provider="google", is_synthetic=False,
            session_generation=self.access.session_generation(STAFF_SUB))
        payload = ledger_board.access_control_render_viewer_status(
            session, self.access)
        self.assertEqual(payload["own_google_sub"], STAFF_SUB)
        self.assertFalse(payload["owner_exists"])
        self.assertIn("WEBLEDGER_OWNER_GOOGLE_SUB",
                      payload["bootstrap_guidance"])
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(FAKE_CLIENT_SECRET, rendered)
        self.assertNotIn(FAKE_SESSION_SECRET, rendered)
        # No other account identifier is listed.
        self.assertNotIn(OWNER_SUB, rendered)

    def test_synthetic_session_does_not_claim_a_google_sub(self):
        flow = make_flow(self.store)
        ledger_board.bind_oidc(flow)
        self.access.create_account(user_id=STAFF_SUB,
                                   role=access_control.ROLE_VIEWER)
        session = access_control.Session(
            user_id=STAFF_SUB, provider="synthetic", is_synthetic=True,
            session_generation=self.access.session_generation(STAFF_SUB))
        payload = ledger_board.access_control_render_viewer_status(
            session, self.access)
        self.assertEqual(payload["own_google_sub"], "")

    def test_state_and_me_never_echo_sub_values(self):
        flow = make_flow(self.store,
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        ledger_board.bind_oidc(flow)
        state = ledger_board.google_oidc_connection_state()
        self.assertTrue(state["owner_bootstrap_configured"])
        self.assertFalse(state["owner_exists"])
        self.assertTrue(state["bootstrap_open"])
        rendered = json.dumps(state, ensure_ascii=False)
        self.assertNotIn(OWNER_SUB, rendered)
        self.assertNotIn(STAFF_SUB, rendered)
        self.assertNotIn(FAKE_CLIENT_SECRET, rendered)


class OwnerAtomicityTests(unittest.TestCase):
    """Sol hardening: check, promotion and generation bump are one transaction.

    The coordinator reproduced the race with two `AccessStore` instances on
    separate SQLite connections calling `ensure_owner` concurrently for two
    synthetic IDs: both calls succeeded and two active owner rows existed.
    The in-process lock cannot serialize separate connections, so the fix is
    `BEGIN IMMEDIATE` plus a partial unique backstop index. These tests pin
    that behaviour with synthetic values only.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="owner-atom-"))
        self.store = make_store(self.tmp)
        self.access = access_control.attach_to_ledger_store(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        access_control.bind_sessions(None)
        ledger_board.bind_oidc(None)
        ledger_board.bind_access(None)

    def test_single_active_owner_index_exists(self):
        rows = self.store.conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index'"
            " AND name='access_single_active_owner'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("role", rows[0][1])
        self.assertIn("is_active", rows[0][1])

    def test_concurrent_promotions_leave_exactly_one_owner(self):
        db_path = self.tmp / "race.sqlite"
        conn_a = sqlite3.connect(str(db_path), check_same_thread=False)
        conn_b = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            store_a = access_control.AccessStore(conn_a)
            store_b = access_control.AccessStore(conn_b)
            barrier = threading.Barrier(2)
            outcomes = {}

            def promote(store, user_id, key):
                try:
                    barrier.wait(timeout=10)
                    store.ensure_owner(user_id)
                    outcomes[key] = ("ok", None)
                except access_control.AccessError as exc:
                    outcomes[key] = ("refused", exc.code)
                except Exception as exc:  # noqa: BLE001 - reported, not hidden
                    outcomes[key] = ("error", type(exc).__name__)

            thread_a = threading.Thread(
                target=promote, args=(store_a, "race-owner-a", "a"))
            thread_b = threading.Thread(
                target=promote, args=(store_b, "race-owner-b", "b"))
            thread_a.start()
            thread_b.start()
            thread_a.join(timeout=30)
            thread_b.join(timeout=30)
            self.assertFalse(thread_a.is_alive())
            self.assertFalse(thread_b.is_alive())
            codes = sorted(outcomes.values())
            self.assertEqual(len(codes), 2)
            self.assertIn(("ok", None), codes)
            self.assertIn(("refused", "OWNER_ALREADY_SET"), codes)
            owners = conn_a.execute(
                "SELECT user_id FROM access_accounts WHERE role='owner'"
                " AND is_active=1").fetchall()
            self.assertEqual(len(owners), 1)
            self.assertIn(owners[0][0], ("race-owner-a", "race-owner-b"))
        finally:
            conn_a.close()
            conn_b.close()

    def test_promotion_preserves_identity_and_bumps_once(self):
        self.access.create_account(
            user_id=STAFF_SUB, role=access_control.ROLE_VIEWER,
            display_name="Staff Name", email="staff@example.test",
            is_synthetic=False)
        before = self.access.session_generation(STAFF_SUB)
        account = self.access.ensure_owner(STAFF_SUB)
        self.assertEqual(account["role"], access_control.ROLE_OWNER)
        self.assertEqual(account["display_name"], "Staff Name")
        self.assertEqual(account["email"], "staff@example.test")
        self.assertFalse(account["is_synthetic"])
        self.assertEqual(account["session_generation"], before + 1)

    def test_fresh_owner_stays_at_generation_one_and_repeat_is_stable(self):
        account = self.access.ensure_owner("fresh-owner-1")
        self.assertEqual(account["session_generation"], 1)
        again = self.access.ensure_owner("fresh-owner-1")
        self.assertEqual(again["session_generation"], 1)

    def test_direct_owner_write_is_refused_when_an_owner_exists(self):
        self.access.ensure_owner(OWNER_SUB)
        with self.assertRaises(access_control.AccessError) as ctx:
            self.access.create_account(user_id=STAFF_SUB,
                                       role=access_control.ROLE_OWNER)
        self.assertEqual(ctx.exception.code, "OWNER_ALREADY_SET")
        # A viewer write for another user still works.
        viewer = self.access.create_account(
            user_id=STAFF_SUB, role=access_control.ROLE_VIEWER)
        self.assertEqual(viewer["role"], access_control.ROLE_VIEWER)

    def test_bootstrap_race_loser_stays_viewer_without_login_failure(self):
        flow = make_flow(self.store,
                         **{google_oidc.ENV_OWNER_SUB: OWNER_SUB})
        self.access.ensure_owner("another-owner")
        started = flow.authorization_url()
        flow.verifier.default_claims = good_claims(sub=OWNER_SUB,
                                                   nonce=started["nonce"])
        result = flow.complete(code="c", state=started["state"])
        self.assertTrue(result["bootstrap"]["attempted"])
        self.assertFalse(result["bootstrap"]["promoted"])
        self.assertEqual(result["role"], access_control.ROLE_VIEWER)
        self.assertEqual(self.access.account_role(OWNER_SUB),
                         access_control.ROLE_VIEWER)

    def test_legacy_duplicate_owners_refuse_to_open_without_auto_resolve(self):
        # A database written before the single-owner index that holds two
        # active owners must refuse to open fail-closed. The migration never
        # chooses, deactivates, or deletes an owner.
        db_path = self.tmp / "legacy-dup.sqlite"
        raw = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            raw.executescript(access_control.SCHEMA_SQL)
            for user_id in ("legacy-owner-a", "legacy-owner-b"):
                raw.execute(
                    "INSERT INTO access_accounts(user_id, display_name, email,"
                    " role, is_active, is_synthetic, session_generation,"
                    " created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (user_id, "", "", access_control.ROLE_OWNER, 1, 1, 1,
                     "2026-09-30T00:00:00+00:00", "2026-09-30T00:00:00+00:00"))
            raw.commit()
        finally:
            raw.close()
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            with self.assertRaises(access_control.AccessError) as ctx:
                access_control.AccessStore(conn)
            self.assertEqual(ctx.exception.code, "OWNER_CONFLICT")
            # Neither owner was deactivated or deleted by the refusal.
            rows = conn.execute(
                "SELECT user_id FROM access_accounts WHERE role='owner'"
                " AND is_active=1 ORDER BY user_id").fetchall()
            self.assertEqual([r[0] for r in rows],
                             ["legacy-owner-a", "legacy-owner-b"])
            index = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index'"
                " AND name='access_single_active_owner'").fetchone()
            self.assertIsNone(index)
        finally:
            conn.close()

    def test_legacy_single_owner_opens_and_gains_the_index(self):
        db_path = self.tmp / "legacy-single.sqlite"
        raw = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            raw.executescript(access_control.SCHEMA_SQL)
            raw.execute(
                "INSERT INTO access_accounts(user_id, display_name, email,"
                " role, is_active, is_synthetic, session_generation,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("legacy-owner", "", "", access_control.ROLE_OWNER, 1, 1, 1,
                 "2026-09-30T00:00:00+00:00", "2026-09-30T00:00:00+00:00"))
            raw.commit()
        finally:
            raw.close()
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            store = access_control.AccessStore(conn)
            self.assertTrue(store.owner_exists())
            index = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND name='access_single_active_owner'").fetchone()
            self.assertIsNotNone(index)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
