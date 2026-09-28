"""APP_SPEC 3, the `새 탭 추가` path: create a trip tab over the real route.

The screen takes `날짜` and `행선지`, the server makes the internal `tab_id`,
and a date and destination that already has a live tab comes back as that tab
without a second row and without a merge decision.

Two harnesses, because two different claims are being made:

  * `TripCreateHttpTests` runs the real server in local single-user mode and
    checks the create contract itself over real HTTP.
  * `TripCreateAccessTests` binds the Phase 7 access store and checks that the
    same endpoint answers a session-less caller 401 and a viewer 403, so the new
    path is not a way around the boundary the other tab writes already use.

Synthetic accounts and synthetic rows only. No real Google OIDC, no reservation
API, no customer data and no outbound network call is in this file.
"""

import json
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

OWNER = "syn-owner-create"
VIEWER = "syn-staff-create"

DEST = "오사카"
DATE = "2026-11-03"
END = "2026-11-07"


class _CreateServer:
    """A real product server on a real store, with a real socket in front."""

    def _boot(self, tmp_name, with_access):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / tmp_name)
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        self.access = None
        if with_access:
            self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        if with_access:
            access_control.bind_synthetic_sessions(True)
            board_mod.bind_access(self.access)

    def _shutdown(self):
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

    def _request(self, path, payload=None, method="GET", user=None):
        data = None
        headers = {}
        if payload is not None:
            payload = dict(payload)
            payload.setdefault("csrf", board_mod.CSRF_TOKEN)
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def _form_post(self, path, fields):
        """Post the way the screen form does: urlencoded, not JSON."""
        from urllib.parse import urlencode

        body = dict(fields)
        body.setdefault("csrf", board_mod.CSRF_TOKEN)
        data = urlencode(body).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        try:
            with urllib.request.build_opener(_NoRedirect).open(
                    request, timeout=10) as response:
                return response.status, response.headers.get("Location")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Location")

    def _json(self, path, payload=None, method="GET", user=None):
        status, body = self._request(path, payload, method, user)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None

    def _trip_rows(self, destination):
        return self.store.conn.execute(
            "SELECT COUNT(*) FROM trip_tabs WHERE destination=? AND deleted=0",
            (destination,)).fetchone()[0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A form post answers 303; the test wants to see the answer, not follow it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TripCreateHttpTests(_CreateServer, unittest.TestCase):
    """The create contract, proven on the served response."""

    def setUp(self):
        self._boot("create.sqlite", with_access=False)

    def tearDown(self):
        self._shutdown()

    def _create(self, **over):
        payload = {"starts_on": DATE, "destination": DEST, "ends_on": END,
                   "client_request_id": "create-http-1"}
        payload.update(over)
        return self._json("/api/tabs", payload, "POST")

    def test_an_owner_post_creates_the_tab_and_the_server_names_it(self):
        status, result = self._create()
        self.assertEqual(status, 200)
        self.assertEqual(result["outcome"], "created")
        self.assertTrue(result["created"])
        tab = result["trip"]
        # the internal id is made by the server, not taken from the request
        self.assertTrue(tab["tab_id"])
        self.assertNotEqual(tab["tab_id"], DEST)
        self.assertEqual(tab["starts_on"], DATE)
        self.assertEqual(tab["destination"], DEST)
        # section 3's initial display name is the MMDD_destination form
        self.assertEqual(tab["display_key"], "1103_오사카")
        self.assertEqual(self._trip_rows(DEST), 1)

    def test_the_created_tab_keeps_the_five_tab_model_fields_apart(self):
        _, result = self._create()
        tab = result["trip"]
        self.assertEqual(tab["event_year"], 2026)
        self.assertEqual(tab["tab_kind"], "trip")
        self.assertEqual(tab["sort_order"], 1)
        # `tab_lifecycle` is derived, so it cannot drift from the stored flags
        self.assertEqual(tab["tab_lifecycle"], "active")
        self.assertFalse(tab["archived"])
        self.assertFalse(tab["deleted"])

    def test_creating_a_tab_does_not_make_the_schedule_authoritative(self):
        """4.2: a tab with no authority basis is needs_review, not confirmed."""
        _, result = self._create()
        self.assertEqual(result["trip"]["authority_status"], "needs_review")
        self.assertEqual(result["trip"]["source_sha256"], "")
        self.assertNotEqual(result["trip"]["authority_status"], "authoritative")

    def test_an_authority_digest_is_stored_but_does_not_confirm_by_itself(self):
        digest = "a" * 64
        _, result = self._create(source_sha256=digest,
                                 client_request_id="create-digest-1")
        self.assertEqual(result["trip"]["source_sha256"], digest)
        # storing a digest is not the same as being confirmed
        self.assertEqual(result["trip"]["authority_status"], "needs_review")

    def test_a_digest_the_server_cannot_read_is_refused(self):
        status, result = self._create(source_sha256="not-a-digest",
                                      client_request_id="create-digest-2")
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_the_tab_kind_is_kept_apart_from_the_display_name(self):
        _, result = self._create(tab_kind="overhead",
                                 client_request_id="create-kind-1")
        self.assertEqual(result["trip"]["tab_kind"], "overhead")
        # 3: the kind is its own field and is never folded into the name
        self.assertEqual(result["trip"]["display_key"], "1103_오사카")

    def test_a_tab_kind_outside_the_list_is_refused(self):
        status, result = self._create(tab_kind="nope",
                                      client_request_id="create-kind-2")
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_the_same_date_and_destination_returns_the_tab_that_is_already_there(self):
        _, first = self._create()
        status, second = self._create(client_request_id="create-http-2")
        self.assertEqual(status, 200)
        self.assertEqual(second["outcome"], "existing")
        self.assertFalse(second["created"])
        self.assertEqual(second["tab_id"], first["tab_id"])
        # no second row, and no merge decided either way
        self.assertEqual(self._trip_rows(DEST), 1)
        self.assertFalse(second["merge_decided"])

    def test_a_retry_of_the_same_request_id_creates_nothing_new(self):
        _, first = self._create()
        status, again = self._create()
        self.assertEqual(status, 200)
        self.assertEqual(again["tab_id"], first["tab_id"])
        self.assertEqual(again["revision"], first["revision"])
        self.assertEqual(self._trip_rows(DEST), 1)

    def test_the_same_request_id_with_other_content_is_refused(self):
        self._create()
        status, result = self._create(
            client_request_id="create-http-1", destination="후쿠오카")
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "REQUEST_ID_REUSED")
        # the refusal added nothing
        self.assertEqual(self._trip_rows(DEST), 1)
        self.assertEqual(self._trip_rows("후쿠오카"), 0)

    def test_a_missing_date_or_destination_is_refused_with_422(self):
        for field in ("starts_on", "destination"):
            status, result = self._create(**{field: "  "})
            self.assertEqual(status, 422, field)
            self.assertEqual(result["code"], "INVALID_VALUE", field)
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_a_date_the_server_cannot_read_is_refused(self):
        for bad in ("2026-13-40", "20261103", "어제"):
            status, result = self._create(starts_on=bad,
                                         client_request_id=f"bad-{bad}")
            self.assertEqual(status, 422, bad)
            self.assertEqual(result["code"], "INVALID_VALUE", bad)

    def test_an_end_before_the_start_is_refused(self):
        status, result = self._create(starts_on=DATE, ends_on="2026-11-01",
                                      client_request_id="ends-early")
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_a_request_without_its_id_is_refused(self):
        status, result = self._create(client_request_id="")
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_a_write_without_the_confirmation_token_is_refused(self):
        status, _ = self._request(
            "/api/tabs",
            {"starts_on": DATE, "destination": DEST,
             "client_request_id": "no-csrf", "csrf": "wrong"},
            "POST")
        self.assertEqual(status, 403)
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_a_refused_create_leaves_no_half_written_trip_behind(self):
        self._create(ends_on="2026-11-01", client_request_id="rollback-1")
        self.assertEqual(self._trip_rows(DEST), 0)
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM trip_tab_requests"
                " WHERE client_request_id='rollback-1'").fetchone()[0], 0)
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM trip_tab_history"
                " WHERE tab_id LIKE 'trip-%'").fetchone()[0], 0)


class TripCreateScreenTests(_CreateServer, unittest.TestCase):
    """The screen requirement, on the page the server serves."""

    def setUp(self):
        self._boot("create-screen.sqlite", with_access=False)

    def tearDown(self):
        self._shutdown()

    def test_the_owner_screen_offers_the_dialog_4_2_lists(self):
        status, page = self._request("/trips")
        self.assertEqual(status, 200)
        self.assertIn("action='/api/tabs'", page)
        self.assertIn("name='starts_on'", page)
        self.assertIn("name='destination'", page)
        self.assertIn("name='ends_on'", page)
        self.assertIn("name='tab_kind'", page)
        self.assertIn("name='source_sha256'", page)

    def test_the_rail_offers_the_add_tab_control_to_the_owner(self):
        """4.2 puts `+ 탭 추가` in the left tab rail."""
        status, page = self._request("/board?tab=trip-demo-a")
        self.assertEqual(status, 200)
        self.assertIn("+ 탭 추가", page)
        self.assertIn("id='add-trip'", page)
        self.assertIn("href='/trips#new-trip-form'", page)

    def test_a_viewer_is_not_offered_the_add_tab_control(self):
        from webapp import ledger_design

        ledger_design.page("trip-demo-a")  # same thread, so the role is decided
        import webapp.ledger_board as board_direct

        board_direct._ROLE_LOCAL.role = "viewer"
        try:
            page = ledger_design.page("trip-demo-a")
        finally:
            board_direct._ROLE_LOCAL.role = "owner"
        self.assertNotIn("+ 탭 추가", page)

    def test_the_screen_states_that_authority_is_not_decided_here(self):
        _, page = self._request("/trips")
        self.assertIn("권위 일정이 권위가 있는 것으로 바뀌지 않습니다", page)

    def test_a_viewer_is_not_given_the_owner_form(self):
        _, page = self._request("/trips?role_probe=1")
        self.assertIn("action='/api/tabs'", page)
        # the same page asked for as a viewer carries no create form
        from webapp import ledger_board as board_direct
        viewer = board_direct.trips_page("", role="viewer")
        self.assertNotIn("action='/api/tabs'", viewer)
        self.assertIn("여행 관리", viewer)

    def test_the_created_tab_shows_up_on_the_screen_with_its_standing(self):
        self._json("/api/tabs",
                   {"starts_on": DATE, "destination": DEST, "ends_on": END,
                    "client_request_id": "screen-1"}, "POST")
        _, page = self._request("/trips")
        self.assertIn("1103_오사카", page)
        # 4.2: no authority basis reads as needs_review, stated as its own value
        self.assertIn("권위 검토 필요", page)

    def test_the_form_post_reaches_the_endpoint_and_lists_the_new_trip(self):
        """The screen form posts to /api/trips; the answer is the trip list."""
        status, location = self._form_post(
            "/api/tabs",
            {"starts_on": "2026-12-01", "destination": "후쿠오카",
             "ends_on": "2026-12-05", "client_request_id": "screen-form",
             "return_to": "/trips"})
        self.assertEqual(status, 303)
        self.assertEqual(location, "/trips")
        _, page = self._request("/trips")
        self.assertIn("1201_후쿠오카", page)
        self.assertEqual(self._trip_rows("후쿠오카"), 1)


class TripCreateAccessTests(_CreateServer, unittest.TestCase):
    """The owner boundary, on the same endpoint."""

    def setUp(self):
        self._boot("create-access.sqlite", with_access=True)
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER,
                                   role=access_control.ROLE_VIEWER,
                                   display_name="직원")

    def tearDown(self):
        self._shutdown()

    def test_the_owner_may_create_a_tab(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": DATE, "destination": DEST, "ends_on": END,
             "client_request_id": "acc-owner-1"}, "POST", user=OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(result["outcome"], "created")
        self.assertEqual(self._trip_rows(DEST), 1)

    def test_a_viewer_is_refused_with_403_and_adds_nothing(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": DATE, "destination": DEST, "ends_on": END,
             "client_request_id": "acc-viewer-1"}, "POST", user=VIEWER)
        self.assertEqual(status, 403)
        self.assertEqual(result["code"], "ACTION_FORBIDDEN")
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_a_caller_without_a_session_is_asked_to_log_in_again(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": DATE, "destination": DEST, "ends_on": END,
             "client_request_id": "acc-none-1"}, "POST")
        self.assertEqual(status, 401)
        self.assertEqual(result["code"], "AUTH_REQUIRED")
        self.assertEqual(self._trip_rows(DEST), 0)

    def test_a_refused_viewer_write_leaves_no_request_record_to_replay(self):
        self._json("/api/tabs",
                   {"starts_on": DATE, "destination": DEST,
                    "ends_on": END, "client_request_id": "acc-viewer-2"},
                   "POST", user=VIEWER)
        # so the owner can still use that id afterwards
        status, result = self._json(
            "/api/tabs",
            {"starts_on": DATE, "destination": DEST, "ends_on": END,
             "client_request_id": "acc-viewer-2"}, "POST", user=OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(result["outcome"], "created")

    def test_the_role_comes_from_the_server_and_not_from_the_body(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": DATE, "destination": DEST, "ends_on": END,
             "client_request_id": "acc-role-1", "user_id": OWNER,
             "actor": "owner", "role": "owner"}, "POST", user=VIEWER)
        self.assertEqual(status, 403)
        self.assertEqual(result["code"], "ACTION_FORBIDDEN")
        self.assertEqual(self._trip_rows(DEST), 0)
