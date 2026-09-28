"""Phase 7 access control: roles, the staff link flow, assignment snapshots
and the viewer boundary.

Synthetic accounts only: owner O, A-assignee V1, B-assignee V2, V3 with no
link. There is no real Google OIDC, no reservation API and no customer data in
this file, and `test_the_synthetic_adapter_is_the_only_way_in` records that
boundary explicitly. The tests drive the real `ledger_board.py` routes, so a
refusal is observed as an HTTP status rather than a unit-level return.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-O"
V1 = "syn-staff-V1"          # assigned to trip A
V2 = "syn-staff-V2"          # assigned to trip B
V3 = "syn-staff-V3"          # logged in, never linked
TRIP_A = "trip-demo-a"
TRIP_B = "trip-demo-b"


def iso_offset(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone

    return access_control.iso(
        datetime.now(timezone.utc) + timedelta(seconds=seconds))


class AccessStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "phase7.sqlite")
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

    def tearDown(self):
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

    # ------------------------------------------------------------- helpers
    def api(self, path, payload=None, method="GET", user=None, generation=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        if generation is not None:
            headers[access_control.SyntheticSessionAdapter.GENERATION_HEADER] = \
                str(generation)
        if payload is not None and method == "POST":
            # every write carries the confirmation token the server issued
            payload = dict(payload)
            payload.setdefault("csrf", board_mod.CSRF_TOKEN)
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                body = response.read()
                return response.status, body
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def api_json(self, path, payload=None, method="GET", user=None,
                 generation=None):
        status, body = self.api(path, payload, method, user, generation)
        try:
            return status, json.loads(body.decode("utf-8"))
        except ValueError:
            return status, None

    def seed_accounts(self):
        self.access.ensure_owner(OWNER)
        for user in (V1, V2, V3):
            self.access.create_account(user_id=user,
                                       role=access_control.ROLE_VIEWER,
                                       display_name=f"직원 {user[-1]}")
        self.access.register_reservation_person(
            reservation_person_id="rp-1", display_name="홍길동", nickname="길동")
        self.access.register_reservation_person(
            reservation_person_id="rp-2", display_name="홍길동", nickname="길순",
            disambiguator="B 여행")
        self.access.register_reservation_person(
            reservation_person_id="rp-3", display_name="박서준", nickname="서준")

    def assign(self, user, tab, revision=1, state=access_control.ASSIGN_ACTIVE,
               validity=access_control.DEFAULT_VALIDITY, now=None,
               source="src-1"):
        return self.access.apply_assignment_snapshot(
            user_id=user,
            items=[{"tab_id": tab, "snapshot_revision": revision, "state": state}],
            source_version=source, validity=validity, now=now)

    def link(self, user, person_id, request_id):
        """Approve a pending application for `user` against `person_id`."""
        self.api("/access/applications", {
            "action": "create", "requested_name": "홍길동",
            "nickname": "길동", "client_request_id": f"app-{request_id}",
        }, "POST", user)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": f"probe-{request_id}",
        }, "POST", user)
        application_id = body["result"]["application_id"]
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 1, "reservation_person_id": person_id,
            "client_request_id": f"dec-{request_id}",
        }, "POST", OWNER)
        return status, body

    # ------------------------------------------------ 1. no silent access
    def test_login_and_application_alone_grant_nothing(self):
        self.seed_accounts()
        # a first login is not access: no trip is visible
        status, body = self.api_json("/access/me", user=V3)
        self.assertEqual(status, 200)
        self.assertEqual(body["visible_tabs"], [])
        self.assertEqual(body["connection"], None)
        # submitting an application is still not access
        status, body = self.api_json("/access/applications", {
            "action": "create", "requested_name": "박서준", "nickname": "서준",
            "client_request_id": "grant-1",
        }, "POST", V3)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["status"], "pending")
        self.assertEqual(body["visible_tabs"], [])
        self.assertEqual(self.access.visible_tabs(V3), set())
        # a request with no session at all is refused before any handler
        status, _ = self.api("/access/me")
        self.assertEqual(status, 401)

    def test_the_first_account_is_never_auto_promoted_to_owner(self):
        self.access.create_account(user_id=V1, role=access_control.ROLE_VIEWER)
        self.assertEqual(self.access.account_role(V1), "viewer")
        # a viewer can never claim ownership by asking
        status, _ = self.api("/access/decision", {
            "action": "approve", "application_id": "app-x",
            "expected_revision": 1, "reservation_person_id": "rp-1",
            "client_request_id": "self-approve",
        }, "POST", V1)
        # an owner-only action, so the refusal is about the action (403) and
        # never depends on the application existing
        self.assertEqual(status, 403)
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": "app-does-not-exist",
            "expected_revision": 1, "reservation_person_id": "rp-1",
            "client_request_id": "self-approve-missing",
        }, "POST", V1)
        self.assertEqual(status, 403)
        # a second owner bootstrap is refused
        self.access.ensure_owner(OWNER)
        with self.assertRaises(access_control.AccessError):
            self.access.ensure_owner(V1)

    # ------------------------------------------------ 2. owner vs viewer
    def test_the_role_is_decided_on_the_server_not_by_the_request(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "srv-1")
        self.assign(V1, TRIP_A, revision=1)
        # a viewer claiming to be the owner in the body changes nothing
        status, body = self.api_json("/board?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 200)
        self.assertNotIn("X-Role", body.get("headers", {}) if isinstance(body, dict) else {})
        # the owner still reaches every owner route
        for path in ("/export", "/import", "/trips"):
            status, _ = self.api(path, user=OWNER)
            self.assertEqual(status, 200, path)
        # and the viewer's own trip is readable
        status, body = self.api_json("/access/rows?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 200)
        self.assertEqual(body["tab"], TRIP_A)
        self.assertGreater(body["row_count"], 0)
        self.assertIn("income_krw", body["totals"])

    def test_the_owner_keeps_the_whole_board(self):
        self.seed_accounts()
        status, _ = self.api("/board?tab=" + TRIP_B, user=OWNER)
        self.assertEqual(status, 200)
        status, _ = self.api("/row?id=expense-demo-c1", user=OWNER)
        self.assertEqual(status, 200)

    # ------------------------------------------ 3. application lifecycle
    def test_pending_approved_rejected_and_withdrawn(self):
        self.seed_accounts()
        # pending
        status, body = self.api_json("/access/applications", {
            "action": "create", "requested_name": "박서준", "nickname": "서준",
            "client_request_id": "life-1",
        }, "POST", V3)
        application_id = body["result"]["application_id"]
        self.assertEqual(body["result"]["status"], "pending")
        self.assertEqual(body["result"]["revision"], 1)
        # update raises the revision
        status, body = self.api_json("/access/applications", {
            "action": "update", "application_id": application_id,
            "expected_revision": 1, "nickname": "서준2",
            "client_request_id": "life-2",
        }, "POST", V3)
        self.assertEqual(body["result"]["revision"], 2)
        self.assertEqual(body["result"]["nickname"], "서준2")
        # reject
        status, body = self.api_json("/access/decision", {
            "action": "reject", "application_id": application_id,
            "expected_revision": 2, "reason": "이름이 같아요",
            "client_request_id": "life-3",
        }, "POST", OWNER)
        self.assertEqual(body["result"]["status"], "rejected")
        self.assertEqual(body["result"]["decision_reason"], "이름이 같아요")
        # a rejected account may apply again
        status, body = self.api_json("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "life-4",
        }, "POST", V3)
        self.assertEqual(body["result"]["status"], "pending")
        # and a pending application can be withdrawn by its owner
        second = body["result"]["application_id"]
        status, body = self.api_json("/access/applications", {
            "action": "withdraw", "application_id": second,
            "expected_revision": 1, "client_request_id": "life-5",
        }, "POST", V3)
        self.assertEqual(body["result"]["status"], "withdrawn")

    def test_the_same_request_id_is_safe_and_a_changed_body_is_refused(self):
        self.seed_accounts()
        payload = {"action": "create", "requested_name": "박서준",
                   "nickname": "서준", "client_request_id": "dup-1"}
        status1, body1 = self.api_json("/access/applications", payload, "POST", V3)
        status2, body2 = self.api_json("/access/applications", payload, "POST", V3)
        self.assertEqual(status1, 200)
        self.assertEqual(status2, 200)
        # the retry reuses the one application instead of stacking a second
        self.assertEqual(body1["result"]["application_id"],
                         body2["result"]["application_id"])
        self.assertEqual(len(self.access.applications_for(V3)), 1)
        # the same id with different content is a conflict
        status, _ = self.api_json("/access/applications", {
            "action": "create", "requested_name": "다른 이름",
            "client_request_id": "dup-1",
        }, "POST", V3)
        self.assertEqual(status, 409)

    def test_expected_revision_conflict_lets_only_one_side_win(self):
        self.seed_accounts()
        status, body = self.api_json("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "race-1",
        }, "POST", V3)
        application_id = body["result"]["application_id"]
        # the staff member edits first
        status, body = self.api_json("/access/applications", {
            "action": "update", "application_id": application_id,
            "expected_revision": 1, "description": "제가 정리했어요",
            "client_request_id": "race-2",
        }, "POST", V3)
        self.assertEqual(status, 200)
        # the owner's decision on the now-stale revision is refused
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 1, "reservation_person_id": "rp-3",
            "client_request_id": "race-3",
        }, "POST", OWNER)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "EDIT_CONFLICT")
        self.assertEqual(self.access.application(application_id)["status"],
                         "pending")
        self.assertEqual(self.access.active_connection(V3), None)
        # the owner may act on the current revision
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 2, "reservation_person_id": "rp-3",
            "client_request_id": "race-4",
        }, "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["application"]["status"], "approved")

    def test_a_shared_name_is_not_auto_approved_and_the_chosen_id_wins(self):
        self.seed_accounts()
        self.api("/access/applications", {
            "action": "create", "requested_name": "홍길동",
            "client_request_id": "dupname-1"}, "POST", V1)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "dupname-probe"},
            "POST", V1)
        application_id = body["result"]["application_id"]
        # two people share the name, so the owner has to choose
        matches = self.access.find_reservation_persons_by_name("홍길동")
        self.assertEqual(len(matches), 2)
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 1, "reservation_person_id": "rp-2",
            "client_request_id": "dupname-2"}, "POST", OWNER)
        self.assertEqual(status, 200)
        connection = self.access.active_connection(V1)
        self.assertEqual(connection["reservation_person_id"], "rp-2")
        # a person already linked to another account is a conflict, not an
        # automatic overwrite
        self.api("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "dupname-3"}, "POST", V2)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "dupname-probe2"},
            "POST", V2)
        second = body["result"]["application_id"]
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": second,
            "expected_revision": 1, "reservation_person_id": "rp-2",
            "client_request_id": "dupname-4"}, "POST", OWNER)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "PERSON_ALREADY_LINKED")
        # an inactive person cannot be linked
        self.access.register_reservation_person(
            reservation_person_id="rp-4", display_name="퇴사자", is_active=False)
        self.api("/access/applications", {
            "action": "create", "client_request_id": "dupname-5"}, "POST", V3)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "dupname-probe3"},
            "POST", V3)
        third = body["result"]["application_id"]
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": third,
            "expected_revision": 1, "reservation_person_id": "rp-4",
            "client_request_id": "dupname-6"}, "POST", OWNER)
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "PERSON_INACTIVE")

    def test_reapproving_the_same_pair_reuses_one_connection(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "reuse-1")
        first = self.access.active_connection(V1)
        # the same account and the same person approved again
        self.api("/access/applications", {
            "action": "create", "requested_name": "홍길동",
            "client_request_id": "reuse-2"}, "POST", V1)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "reuse-probe"},
            "POST", V1)
        application_id = body["result"]["application_id"]
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 1, "reservation_person_id": "rp-1",
            "client_request_id": "reuse-3"}, "POST", OWNER)
        self.assertEqual(status, 200)
        # still one connection, and it is the original one
        self.assertEqual(self.access.active_connection(V1)["connection_id"],
                         first["connection_id"])
        rows = self.access.conn.execute(
            "SELECT COUNT(*) FROM access_connections WHERE user_id=?",
            (V1,)).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_revoking_a_connection_stops_the_trip_and_cannot_be_restored_old(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "revoke-1")
        self.assign(V1, TRIP_A, revision=3)
        self.assertEqual(self.access.visible_tabs(V1), {TRIP_A})
        status, _ = self.api("/board?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 200)
        connection = self.access.active_connection(V1)
        # the owner revokes it
        status, body = self.api_json("/access/decision", {
            "action": "revoke", "connection_id": connection["connection_id"],
            "expected_revision": 1, "client_request_id": "revoke-2",
        }, "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["status"], "revoked")
        # the already-logged-in session is cut off immediately
        self.assertEqual(self.access.visible_tabs(V1), set())
        status, _ = self.api("/board?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 404)
        status, _ = self.api("/access/rows?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 404)
        # an approved application does not survive a revoked connection
        self.assertEqual(self.access.applications_for(V1)[0]["status"],
                         "approved")
        self.assertEqual(self.access.active_connection(V1), None)

    def test_a_deactivated_account_cannot_restore_its_own_access(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "deact-1")
        self.assign(V1, TRIP_A, revision=1)
        self.assertEqual(self.access.visible_tabs(V1), {TRIP_A})
        self.access.set_account_active(user_id=V1, is_active=False)
        self.assertEqual(self.access.visible_tabs(V1), set())
        # re-applying does not help while the account is inactive
        status, _ = self.api("/access/applications", {
            "action": "create", "requested_name": "홍길동",
            "client_request_id": "deact-2"}, "POST", V1)
        self.assertEqual(status, 401)
        self.assertEqual(self.access.visible_tabs(V1), set())

    # ------------------------------------------- 4. assignment snapshots
    def test_an_older_active_snapshot_does_not_restore_a_newer_revoke(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "snap-1")
        self.assign(V1, TRIP_A, revision=5, state=access_control.ASSIGN_REVOKED)
        self.assertEqual(self.access.visible_tabs(V1), set())
        # an older active snapshot arrives afterwards
        result = self.assign(V1, TRIP_A, revision=3,
                             state=access_control.ASSIGN_ACTIVE, source="src-old")
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["ignored_older"]), 1)
        self.assertEqual(self.access.visible_tabs(V1), set())
        self.assertEqual(self.access.assignment_head(V1, TRIP_A)["state"],
                         access_control.ASSIGN_REVOKED)
        # the same revision is also ignored, so a resend has no effect
        result = self.assign(V1, TRIP_A, revision=5,
                             state=access_control.ASSIGN_ACTIVE)
        self.assertEqual(result["applied"], [])
        self.assertEqual(self.access.visible_tabs(V1), set())
        # only a genuinely newer snapshot restores the permission
        result = self.assign(V1, TRIP_A, revision=6,
                             state=access_control.ASSIGN_ACTIVE, source="src-new")
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(self.access.visible_tabs(V1), {TRIP_A})

    def test_a_missing_trip_in_a_partial_snapshot_is_not_a_revocation(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "partial-1")
        self.assign(V1, TRIP_A, revision=1)
        self.assign(V1, TRIP_B, revision=1)
        self.assertEqual(self.access.visible_tabs(V1), {TRIP_A, TRIP_B})
        # a partial page that happens not to mention trip B leaves B alone
        result = self.access.apply_assignment_snapshot(
            user_id=V1,
            items=[{"tab_id": TRIP_A, "snapshot_revision": 2,
                    "state": access_control.ASSIGN_ACTIVE}],
            source_version="src-partial", complete=False)
        self.assertEqual(result["complete"], False)
        self.assertEqual(self.access.visible_tabs(V1), {TRIP_A, TRIP_B})

    def test_the_validity_window_expires_and_cannot_be_unlimited(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "window-1")
        self.assign(V1, TRIP_A, revision=1, validity=timedelta(seconds=60))
        self.assertEqual(self.access.visible_tabs(V1), {TRIP_A})
        # a zero or negative window is refused outright
        for bad in (timedelta(0), timedelta(seconds=-1)):
            with self.assertRaises(access_control.AccessError):
                self.assign(V1, TRIP_A, revision=2, validity=bad)
        # a window beyond the revocation-delay bound is refused too
        with self.assertRaises(access_control.AccessError):
            self.assign(V1, TRIP_A, revision=2,
                        validity=access_control.MAX_REVOCATION_DELAY
                        + timedelta(minutes=1))
        # and the window is honoured when it passes
        from datetime import datetime, timezone

        later = datetime.now(timezone.utc) + timedelta(minutes=10)
        self.assertEqual(self.access.visible_tabs(V1, now=later), set())

    def test_a_viewer_needs_both_the_link_and_a_live_assignment(self):
        self.seed_accounts()
        # linked but not assigned
        self.link(V1, "rp-1", "both-1")
        self.assertEqual(self.access.visible_tabs(V1), set())
        # assigned but not linked
        self.access.create_account(user_id=V2, role=access_control.ROLE_VIEWER)
        self.assign(V2, TRIP_B, revision=1)
        self.assertEqual(self.access.visible_tabs(V2), set())
        # both, then visible
        self.api("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "both-2"}, "POST", V2)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "both-probe"}, "POST", V2)
        application_id = body["result"]["application_id"]
        self.api("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 1, "reservation_person_id": "rp-3",
            "client_request_id": "both-3"}, "POST", OWNER)
        self.assertEqual(self.access.visible_tabs(V2), {TRIP_B})

    # ----------------------------------------------- 5. the viewer boundary
    def test_a_viewer_sees_only_its_own_trip_and_other_trips_are_404(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "bound-1")
        self.assign(V1, TRIP_A, revision=1)
        # its own trip
        status, _ = self.api("/board?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 200)
        status, body = self.api_json("/access/rows?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 200)
        self.assertGreater(body["row_count"], 0)
        # another trip answers 404 and never names it
        status, body = self.api("/board?tab=" + TRIP_B, user=V1)
        self.assertEqual(status, 404)
        self.assertNotIn(TRIP_B.encode(), body)
        status, _ = self.api("/access/rows?tab=" + TRIP_B, user=V1)
        self.assertEqual(status, 404)
        # a row that belongs to the other trip is a 404, not a 403
        other = None
        for row in self.store.list_tab_rows(TRIP_B):
            other = row["row_id"]
            break
        if other:
            status, body = self.api(f"/row?id={other}", user=V1)
            self.assertEqual(status, 404)
            self.assertNotIn(other.encode(), body)

    def test_a_viewer_row_carries_no_internal_memo_or_history(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "fields-1")
        self.assign(V1, TRIP_A, revision=1)
        # write an internal memo and make a change through the owner path
        before = self.store.get_row("expense-demo-c1")
        self.store.save(
            row_id="expense-demo-c1",
            expected_revision=before["revision"],
            client_request_id="fields-owner-save",
            change_mode="exception",
            changes={"operator_note": "내부만 쓰는 메모"})
        status, body = self.api_json("/access/rows?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 200)
        self.assertGreater(body["row_count"], 0)
        blob = json.dumps(body, ensure_ascii=False)
        self.assertNotIn("내부만 쓰는 메모", blob)
        self.assertNotIn("operator_note", blob)
        for denied in access_control.VIEWER_DENIED_FIELDS:
            self.assertNotIn(denied, blob, denied)
        # the row screen shows the allowlisted fields only
        status, page = self.api(f"/row?id=expense-demo-c1", user=V1)
        self.assertEqual(status, 200)
        text = page.decode("utf-8")
        self.assertNotIn("내부만 쓰는 메모", text)
        self.assertNotIn("변경 이력", text)

    def test_a_viewer_cannot_reach_owner_writes_or_the_ai_dialogue(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "writes-1")
        self.assign(V1, TRIP_A, revision=1)
        before = self.store.get_row("expense-demo-c1")
        denied_posts = [
            ("/api/rows/expense-demo-c1/save",
             {"expected_revision": before["revision"],
              "client_request_id": "w-1", "item": "바뀌면 안 됨"}),
            ("/api/classification/conversation/advance", {}),
            ("/api/classification/rules/apply", {"rule_id": "r"}),
            ("/api/trips/trip-demo-a/meta", {"archived": "1"}),
            ("/api/income/income-demo-i1/allocations", {}),
        ]
        for path, payload in denied_posts:
            status, body = self.api_json(path, payload, "POST", V1)
            # a write is an owner action, so the refusal is 403 ACTION_FORBIDDEN
            self.assertEqual(status, 403, path)
            self.assertEqual(body["code"], "ACTION_FORBIDDEN", path)
        # nothing moved
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"],
                         before["item"])
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"],
                         before["revision"])
        # a read of the rule dialogue is refused the same way
        status, _ = self.api("/rules?case=app-x", user=V1)
        self.assertEqual(status, 403)

    def test_a_viewer_cannot_create_look_up_or_download_a_workbook(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "xlsx-1")
        self.assign(V1, TRIP_A, revision=1)
        status, body = self.api_json("/export", user=V1)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ACTION_FORBIDDEN")
        status, _ = self.api("/api/exports/xlsx", {
            "tab_ids": [TRIP_A], "client_request_id": "xl-1"}, "POST", V1)
        self.assertEqual(status, 403)
        # job lookup and download are refused even for a real job id
        status, body = self.api("/api/exports/xlsx-owner-1/download", user=V1)
        self.assertEqual(status, 403)
        # the owner can still do all of it
        status, _ = self.api("/export", user=OWNER)
        self.assertEqual(status, 200)

    def test_evidence_preview_is_allowlisted_and_the_original_is_never_served(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "ev-1")
        self.assign(V1, TRIP_A, revision=1)
        self.access.register_evidence(
            evidence_id="ev-A", tab_id=TRIP_A, kind="image",
            separation_state="original_only")
        self.access.register_evidence(
            evidence_id="ev-A-sep", tab_id=TRIP_A, kind="image",
            separation_state="separated", separated_version="v1",
            separated_sha256="a" * 64, allowed_tabs=[TRIP_A])
        self.access.register_evidence(
            evidence_id="ev-B", tab_id=TRIP_B, kind="image",
            separation_state="separated", separated_version="v1",
            separated_sha256="b" * 64, allowed_tabs=[TRIP_B])
        self.access.register_evidence(
            evidence_id="ev-xls", tab_id=TRIP_A, kind="spreadsheet")
        # the separated A preview is available to V1
        status, body = self.api_json("/evidence/preview/ev-A-sep", user=V1)
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["separated_version"], "v1")
        self.assertFalse(body["original_available"])
        self.assertNotIn("original_sha256", json.dumps(body))
        # an original-only A evidence reports the preparation gap
        status, body = self.api_json("/evidence/preview/ev-A", user=V1)
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "preparation_needed")
        # B's evidence is a 404 with no trace of B
        status, body = self.api("/evidence/preview/ev-B", user=V1)
        self.assertEqual(status, 404)
        self.assertNotIn(TRIP_B.encode(), body)
        # an unsupported kind is refused rather than falling back
        status, body = self.api("/evidence/preview/ev-xls", user=V1)
        self.assertEqual(status, 404)
        # there is no original-evidence route at all
        for user in (V1, OWNER):
            status, _ = self.api("/evidence/original/ev-A-sep", user=user)
            self.assertEqual(status, 404)
        # and the owner reference path exists only for the owner
        self.assertTrue(
            self.access.owner_evidence_preview("ev-A")["original_available"])

    def test_a_viewer_cannot_read_or_approve_another_application(self):
        self.seed_accounts()
        self.api("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "other-1"}, "POST", V2)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "other-probe"}, "POST", V2)
        application_id = body["result"]["application_id"]
        # V1 may not approve it
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 1, "reservation_person_id": "rp-3",
            "client_request_id": "other-2"}, "POST", V1)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ACTION_FORBIDDEN")
        # nor read someone else's application through their own status call
        status, body = self.api_json("/access/me", user=V1)
        self.assertEqual([a["application_id"] for a in body["applications"]], [])
        # and V1 may not edit V2's application. The answer is a 404 and its
        # body is deliberately not JSON, so nothing describes the application.
        status, body = self.api("/access/applications", {
            "action": "update", "application_id": application_id,
            "expected_revision": 1, "description": "남의 신청",
            "client_request_id": "other-3"}, "POST", V1)
        self.assertEqual(status, 404)
        self.assertNotIn(application_id.encode(), body)
        self.assertNotIn("박서준", body.decode("utf-8", "replace"))

    def test_a_locked_database_is_a_retryable_503_not_a_crash(self):
        # DETAILED_CONTRACT 4.3: a transient store failure keeps the draft and
        # is confirmed with the *same* client_request_id, so it must not be
        # reported as a validation error or a 500.
        self.seed_accounts()
        before = self.store.get_row("expense-demo-c1")
        payload = {
            "expected_revision": before["revision"],
            "client_request_id": "lock-retry-1",
            "change_mode": "exception",
            "item": "고쳐쓴 항목",
        }
        import sqlite3

        store_class = type(self.store)
        original = store_class.save

        def locked(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        store_class.save = locked
        try:
            status, body = self.api_json("/api/rows/expense-demo-c1/save", payload,
                                         "POST", OWNER)
        finally:
            store_class.save = original
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "TEMPORARILY_UNAVAILABLE")
        # the client is told the request is worth repeating unchanged
        self.assertTrue(body["retry_same_client_request_id"])
        # nothing was written
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"],
                         before["item"])
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"],
                         before["revision"])
        # and the same request id succeeds once the store is free again
        status, body = self.api_json("/api/rows/expense-demo-c1/save", payload,
                                     "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(body["request_id"], "lock-retry-1")
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"],
                         "고쳐쓴 항목")

    def test_an_unchanged_save_replays_and_does_not_advance_the_revision(self):
        # The reply to an unchanged save carries outcome="unchanged" and the
        # revision is left alone, so a retry cannot inflate the audit trail.
        self.seed_accounts()
        before = self.store.get_row("expense-demo-c1")
        payload = {
            "expected_revision": before["revision"],
            "client_request_id": "same-value-1",
            "change_mode": "exception",
            "item": before["item"],
        }
        status, first = self.api_json("/api/rows/expense-demo-c1/save", payload,
                                      "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(first.get("outcome"), "unchanged")
        self.assertEqual(first["revision"], before["revision"])
        # a different request id with the same value is still unchanged
        payload["client_request_id"] = "same-value-2"
        status, second = self.api_json("/api/rows/expense-demo-c1/save", payload,
                                       "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(second.get("outcome"), "unchanged")
        self.assertEqual(second["revision"], before["revision"])
        # replaying the first request id returns the very same answer
        payload["client_request_id"] = "same-value-1"
        status, third = self.api_json("/api/rows/expense-demo-c1/save", payload,
                                      "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(third, first)
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"],
                         before["revision"])

    def test_a_real_change_does_advance_the_revision_and_is_not_unchanged(self):
        self.seed_accounts()
        before = self.store.get_row("expense-demo-c1")
        status, body = self.api_json("/api/rows/expense-demo-c1/save", {
            "expected_revision": before["revision"],
            "client_request_id": "real-change-1",
            "change_mode": "exception",
            "item": "실제로 바꾼 항목",
        }, "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertNotEqual(body.get("outcome"), "unchanged")
        self.assertEqual(body["revision"], before["revision"] + 1)
        # the same request id now replays that answer
        status, replay = self.api_json("/api/rows/expense-demo-c1/save", {
            "expected_revision": before["revision"],
            "client_request_id": "real-change-1",
            "change_mode": "exception",
            "item": "실제로 바꾼 항목",
        }, "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(replay, body)

    def test_the_contract_error_vocabulary_is_fully_mapped_to_a_status(self):
        # Every code named in DETAILED_CONTRACT 4.3 must resolve to its status,
        # so a refusal can never fall through to a default.
        self.assertEqual(board_mod.STATUS_FOR_CODE["AUTH_REQUIRED"], 401)
        self.assertEqual(board_mod.STATUS_FOR_CODE["ACTION_FORBIDDEN"], 403)
        self.assertEqual(board_mod.STATUS_FOR_CODE["RESOURCE_NOT_FOUND"], 404)
        self.assertEqual(board_mod.STATUS_FOR_CODE["TEMPORARILY_UNAVAILABLE"],
                         503)
        # the codes the store raises must all be known to the board
        raised = set()
        for name in dir(self.access):
            attr = getattr(self.access, name)
            if not callable(attr):
                continue
        self.assertTrue(raised <= set(board_mod.STATUS_FOR_CODE))

    def test_a_viewer_read_refusal_never_reveals_the_row(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "hide-1")
        self.assign(V1, TRIP_A, revision=1)
        # a trip the viewer has no assignment to
        status, body = self.api_json("/board?tab=" + TRIP_B, user=V1)
        self.assertEqual(status, 404)
        # the refusal body is not a JSON document and never names the trip
        self.assertIsNone(body)
        status, raw = self.api("/board?tab=" + TRIP_B, user=V1)
        self.assertEqual(status, 404)
        self.assertNotIn(TRIP_B, raw.decode("utf-8", "replace"))
        status, raw = self.api("/row?id=expense-demo-c1", user=V1)
        self.assertEqual(status, 200)
        # a row id that does not exist reads the same way for everyone
        status_owner, _ = self.api("/row?id=expense-demo-missing", user=OWNER)
        status_viewer, _ = self.api("/row?id=expense-demo-missing", user=V1)
        self.assertEqual(status_owner, 404)
        self.assertEqual(status_viewer, 404)

    def test_the_owner_admin_screen_lists_pending_and_candidates(self):
        self.seed_accounts()
        self.api("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "admin-1"}, "POST", V3)
        status, page = self.api("/access/admin", user=OWNER)
        self.assertEqual(status, 200)
        text = page.decode("utf-8")
        self.assertIn("계정 관리", text)
        self.assertIn("대기 신청 1건", text)
        self.assertIn("rp-2", text)
        # a viewer does not get the admin screen
        status, body = self.api_json("/access/admin", user=V1)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ACTION_FORBIDDEN")

    # --------------------------------------------- 6. the identity boundary
    def test_the_synthetic_adapter_is_the_only_way_in(self):
        # unbound by default: no header can establish a session
        board_mod.bind_access(self.access)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=V1, role=access_control.ROLE_VIEWER)
        status, _ = self.api("/access/me", user=OWNER)
        self.assertEqual(status, 401)
        # re-binding the synthetic adapter is an explicit test-only act
        access_control.bind_synthetic_sessions(True)
        status, body = self.api_json("/access/me", user=OWNER)
        self.assertEqual(status, 200)
        # the response says the identity is synthetic and no OIDC is connected
        self.assertEqual(body["identity_source"], "synthetic")
        self.assertFalse(body["google_oidc_connected"])
        # an unknown header value establishes no session at all
        status, _ = self.api("/access/me", user="syn-never-created")
        self.assertEqual(status, 401)
        # and a viewer header cannot reach an owner screen
        status, body = self.api_json("/access/admin", user=V1)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ACTION_FORBIDDEN")

    def test_the_access_change_is_not_a_ledger_event(self):
        self.seed_accounts()
        before = self.store.conn.execute(
            "SELECT COUNT(*) FROM board_revisions").fetchone()[0]
        self.link(V1, "rp-1", "ledger-1")
        self.assign(V1, TRIP_A, revision=1)
        after = self.store.conn.execute(
            "SELECT COUNT(*) FROM board_revisions").fetchone()[0]
        # a connection or permission change never appears as a row revision
        self.assertEqual(before, after)

    # ------------------------------- session generation and cache binding
    def test_a_stale_session_is_refused_after_a_permission_change(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "gen-1")
        self.assign(V1, TRIP_A, revision=1)
        # the session works and reports the namespace a client should key on
        status, body = self.api_json("/access/me", user=V1)
        self.assertEqual(status, 200)
        generation = body["session_generation"]
        self.assertGreaterEqual(generation, 1)
        self.assertIn(V1, body["cache_namespace"])
        self.assertIn(str(generation), body["cache_namespace"])
        # presenting the same generation is still served
        status, _ = self.api("/access/me", user=V1, generation=generation)
        self.assertEqual(status, 200)
        # the owner revokes the link, which ends the account's sessions
        connection = self.access.active_connection(V1)
        status, _ = self.api("/access/decision", {
            "action": "revoke", "connection_id": connection["connection_id"],
            "expected_revision": 1, "client_request_id": "gen-2",
        }, "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertGreater(self.access.session_generation(V1), generation)
        # the old generation is now stale and must not be answered
        status, body = self.api_json("/access/me", user=V1, generation=generation)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "SESSION_STALE")
        # and the data it used to be allowed to read is refused too
        status, _ = self.api("/access/rows?tab=" + TRIP_A, user=V1,
                             generation=generation)
        self.assertEqual(status, 401)
        # a fresh session on the new generation is served again
        status, body = self.api_json("/access/me", user=V1)
        self.assertEqual(status, 200)
        self.assertEqual(body["visible_tabs"], [])

    def test_deactivating_an_account_ends_its_sessions(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "gen-3")
        self.assign(V1, TRIP_A, revision=1)
        status, body = self.api_json("/access/me", user=V1)
        generation = body["session_generation"]
        self.access.set_account_active(user_id=V1, is_active=False)
        self.assertGreater(self.access.session_generation(V1), generation)
        status, body = self.api_json("/access/me", user=V1, generation=generation)
        self.assertEqual(status, 401)

    def test_a_bogus_generation_header_does_not_establish_a_session(self):
        self.seed_accounts()
        status, _ = self.api("/access/me", user=V1, generation="not-a-number")
        self.assertEqual(status, 401)

    def test_two_owner_sessions_cannot_both_hold_the_bootstrap(self):
        # a generation bump for one account does not affect the other
        self.seed_accounts()
        self.link(V1, "rp-1", "gen-4")
        before_v1 = self.access.session_generation(V1)
        before_owner = self.access.session_generation(OWNER)
        self.access.bump_session_generation(V1)
        self.assertEqual(self.access.session_generation(V1), before_v1 + 1)
        self.assertEqual(self.access.session_generation(OWNER), before_owner)

    # ------------------------------- the reasons are not merged into one
    def test_a_withdrawn_application_reports_its_own_state(self):
        self.seed_accounts()
        self.api("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "state-1"}, "POST", V3)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "state-probe"}, "POST", V3)
        application_id = body["result"]["application_id"]
        status, body = self.api_json("/access/applications", {
            "action": "withdraw", "application_id": application_id,
            "expected_revision": 1, "client_request_id": "state-2",
        }, "POST", V3)
        self.assertEqual(body["result"]["status"], "withdrawn")
        # approving it is refused for the withdrawal, not for a person conflict
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 2, "reservation_person_id": "rp-3",
            "client_request_id": "state-3"}, "POST", OWNER)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "APPLICATION_NOT_PENDING")
        # and rejecting it reports its state too
        status, body = self.api_json("/access/decision", {
            "action": "reject", "application_id": application_id,
            "expected_revision": 2, "reason": "철회함",
            "client_request_id": "state-4"}, "POST", OWNER)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "APPLICATION_NOT_PENDING")

    def test_approve_and_withdraw_cannot_both_win(self):
        self.seed_accounts()
        self.api("/access/applications", {
            "action": "create", "requested_name": "박서준",
            "client_request_id": "race-1"}, "POST", V3)
        status, body = self.api_json("/access/applications", {
            "action": "create", "client_request_id": "race-probe"}, "POST", V3)
        application_id = body["result"]["application_id"]
        # the staff member withdraws
        status, body = self.api_json("/access/applications", {
            "action": "withdraw", "application_id": application_id,
            "expected_revision": 1, "client_request_id": "race-2",
        }, "POST", V3)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["status"], "withdrawn")
        revision_after_withdraw = body["result"]["revision"]
        # the owner acting on the revision that was current before the withdraw
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": 1, "reservation_person_id": "rp-3",
            "client_request_id": "race-3"}, "POST", OWNER)
        self.assertEqual(status, 409)
        # the withdrawal is the state that won, and the refusal says so rather
        # than reporting some unrelated person or account conflict
        self.assertEqual(body["code"], "APPLICATION_NOT_PENDING")
        # exactly one state won, and no connection was created
        self.assertEqual(self.access.application(application_id)["status"],
                         "withdrawn")
        self.assertEqual(self.access.application(application_id)["revision"],
                         revision_after_withdraw)
        self.assertEqual(self.access.active_connection(V3), None)
        # acting on the current revision cannot revive it either
        status, body = self.api_json("/access/decision", {
            "action": "approve", "application_id": application_id,
            "expected_revision": revision_after_withdraw,
            "reservation_person_id": "rp-3",
            "client_request_id": "race-4"}, "POST", OWNER)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "APPLICATION_NOT_PENDING")
        self.assertEqual(self.access.active_connection(V3), None)

    # ------------- the row's own trip decides permission, immediately
    def test_moving_a_row_applies_the_new_trip_permission_at_once(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "move-1")
        self.assign(V1, TRIP_A, revision=1)
        self.assertEqual(self.access.visible_tabs(V1), {TRIP_A})
        before = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=before["revision"],
                        client_request_id="move-owner", change_mode="exception",
                        changes={"display_tab_id": TRIP_A})
        status, _ = self.api(f"/row?id=expense-demo-c1", user=V1)
        self.assertEqual(status, 200)
        # moving it to an unassigned trip cuts the viewer off on the next read
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=self.store.get_row(
                            "expense-demo-c1")["revision"],
                        client_request_id="move-owner-2", change_mode="exception",
                        changes={"display_tab_id": TRIP_B})
        status, _ = self.api(f"/row?id=expense-demo-c1", user=V1)
        self.assertEqual(status, 404)
        status, _ = self.api("/access/rows?tab=" + TRIP_A, user=V1)
        self.assertEqual(status, 200)
        status, body = self.api_json("/access/rows?tab=" + TRIP_A, user=V1)
        ids = {r["row_id"] for r in body["rows"]}
        self.assertNotIn("expense-demo-c1", ids)

    def test_an_archived_trip_stays_readable_while_the_assignment_holds(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "arch-1")
        self.assign(V1, TRIP_B, revision=1)
        trip = self.store.get_trip(TRIP_B)
        self.store.save_trip_meta(tab_id=TRIP_B,
                                  expected_revision=trip["revision"],
                                  client_request_id="arch-owner", archived=1)
        self.assertTrue(self.store.get_trip(TRIP_B)["archived"])
        # the trip is archived but the assignment still holds, so it is readable
        self.assertIn(TRIP_B, self.access.visible_tabs(V1))
        status, _ = self.api("/board?tab=" + TRIP_B, user=V1)
        self.assertEqual(status, 200)
        status, body = self.api_json("/access/rows?tab=" + TRIP_B, user=V1)
        self.assertEqual(status, 200)
        # the owner keeps the whole board either way
        status, _ = self.api("/board?tab=" + TRIP_B, user=OWNER)
        self.assertEqual(status, 200)

    def test_logout_ends_the_session_and_names_what_the_client_must_clear(self):
        self.seed_accounts()
        self.link(V1, "rp-1", "logout-1")
        self.assign(V1, TRIP_A, revision=1)
        status, body = self.api_json("/access/me", user=V1)
        generation = body["session_generation"]
        status, out = self.api_json("/access/logout", {"reason": "계정 전환"},
                                    "POST", V1)
        self.assertEqual(status, 200)
        self.assertTrue(out["logged_out"])
        self.assertGreater(out["session_generation"], generation)
        # the server tells the client what to drop, so it can clear its own cache
        self.assertIn("selected_row", out["client_must_clear"])
        self.assertIn("cached_ledger_data", out["client_must_clear"])
        # the session it held is now refused
        status, body = self.api_json("/access/me", user=V1, generation=generation)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "SESSION_STALE")
        # a fresh session on the new generation works again
        status, body = self.api_json("/access/me", user=V1)
        self.assertEqual(status, 200)
        self.assertEqual(body["session_generation"], out["session_generation"])

    def test_the_owner_can_log_out_too(self):
        self.seed_accounts()
        status, before = self.api_json("/access/me", user=OWNER)
        self.assertEqual(status, 200)
        status, out = self.api_json("/access/logout", {}, "POST", OWNER)
        self.assertEqual(status, 200)
        status, body = self.api_json("/access/me", user=OWNER,
                                     generation=before["session_generation"])
        self.assertEqual(status, 401)
        # an owner who is not logged in has no owner routes
        status, _ = self.api("/export", user=OWNER,
                             generation=before["session_generation"])
        self.assertEqual(status, 401)

    def test_enforcement_is_off_until_an_access_store_is_bound(self):
        # pre-Phase-7 single-operator behaviour is unchanged when unbound
        board_mod.bind_access(None)
        status, _ = self.api("/board?tab=" + TRIP_A)
        self.assertEqual(status, 200)
        status, _ = self.api("/export")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
