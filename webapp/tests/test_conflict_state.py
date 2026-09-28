"""APP_SPEC 9's `충돌` state, and APP_SPEC 10's canonical tab paths.

`충돌` is the one state APP_SPEC 9 requires to be told apart "in the DB and in
the row detail" while the board table stays free of classification state, and
APP_SPEC 8 asks the export dialog for its row count. A refused save therefore
leaves an append-only note in the existing change ledger, and nothing about the
row's values, revision or totals changes.

The tab paths follow APP_SPEC 10: `POST /api/tabs` is the one and only create
path, so no action answers at two URLs.

Synthetic rows and synthetic accounts only. No real Google OIDC, no reservation
API, no customer data and no outbound network call is in this file.
"""

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-conflict"
VIEWER = "syn-staff-conflict"
ROW = "expense-demo-c1"
TAB = "trip-demo-a"


class _Server:
    def _boot(self, name, with_access):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / name)
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

    def _open(self, path, payload=None, method="GET", user=None):
        headers = {}
        data = None
        if payload is not None:
            body = dict(payload)
            if method == "POST":
                body.setdefault("csrf", board_mod.CSRF_TOKEN)
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def _json(self, path, payload=None, method="GET", user=None):
        status, body = self._open(path, payload, method, user)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None

    # -- helpers -----------------------------------------------------
    def _revision(self):
        return (self.store.get_row(ROW) or {}).get("revision")

    def _save(self, note, request_id, revision=None):
        return self._json(
            f"/api/rows/{ROW}/save",
            {"expected_revision": self._revision() if revision is None else revision,
             "operator_note": note, "change_mode": "exception",
             "client_request_id": request_id}, "POST")


class ConflictStateTests(_Server, unittest.TestCase):
    def setUp(self):
        self._boot("conflict.sqlite", with_access=False)

    def tearDown(self):
        self._shutdown()

    def test_a_refused_save_leaves_a_conflict_note_and_changes_no_value(self):
        self._save("A", "cf-a")
        before = self.store.get_row(ROW)
        status, result = self._save("B", "cf-b", revision=1)
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "EDIT_CONFLICT")
        after = self.store.get_row(ROW)
        # the note is a note: no value, no revision, no totals move
        self.assertEqual(after["operator_note"], before["operator_note"])
        self.assertEqual(after["revision"], before["revision"])
        self.assertIsNotNone(self.store.row_conflict(ROW))

    def test_the_note_names_the_revision_that_was_asked_for_and_the_real_one(self):
        self._save("A", "cf-c1")
        self._save("B", "cf-c2", revision=1)
        conflict = self.store.row_conflict(ROW)
        self.assertEqual(conflict["expected_revision"], 1)
        self.assertEqual(conflict["current_revision"], self._revision())
        self.assertEqual(conflict["actor"], "owner")

    def test_the_note_remembers_what_the_user_tried_to_save(self):
        self._save("A", "cf-d1")
        self._save("B", "cf-d2", revision=1)
        conflict = self.store.row_conflict(ROW)
        self.assertEqual(conflict["attempted"].get("operator_note"), "B")
        # the request id and token are not stored as if they were a value
        self.assertNotIn("csrf", conflict["attempted"])
        self.assertNotIn("expected_revision", conflict["attempted"])

    def test_the_row_detail_shows_the_conflict_with_a_way_back(self):
        self._save("A", "cf-e1")
        self._save("B", "cf-e2", revision=1)
        status, page = self._open(f"/row?id={ROW}")
        self.assertEqual(status, 200)
        self.assertIn("충돌", page)
        # DETAILED 3.2: the row edit screen offers a way to re-edit from the
        # latest revision
        self.assertIn("최신 값을 확인한 뒤 다시 저장해 주세요", page)

    def test_the_board_table_gives_the_conflict_state_no_marker(self):
        """APP_SPEC 4.3: the 기본 표 keeps no classification state."""
        self._save("A", "cf-f1")
        self._save("B", "cf-f2", revision=1)
        status, page = self._open(f"/board?tab={TAB}")
        self.assertEqual(status, 200)
        self.assertNotIn("충돌", page)

    def test_a_later_successful_save_clears_the_conflict(self):
        self._save("A", "cf-g1")
        self._save("B", "cf-g2", revision=1)
        self.assertIsNotNone(self.store.row_conflict(ROW))
        self._save("C", "cf-g3")
        self.assertIsNone(self.store.row_conflict(ROW))
        _, page = self._open(f"/row?id={ROW}")
        self.assertNotIn(">충돌<", page)

    def test_a_conflict_on_one_row_does_not_touch_another(self):
        self._save("A", "cf-h1")
        other = "expense-demo-c2"
        before = self.store.get_row(other)
        self._save("B", "cf-h2", revision=1)
        self.assertIsNone(self.store.row_conflict(other))
        after = self.store.get_row(other)
        self.assertEqual(after["revision"], before["revision"])

    def test_the_audit_list_shows_the_note_between_the_two_saves(self):
        self._save("A", "cf-i1")
        self._save("B", "cf-i2", revision=1)
        self._save("C", "cf-i3")
        _, data = self._json(f"/api/audit/changes?row_id={ROW}")
        kinds = [c["kind"] for c in data["changes"]]
        self.assertEqual(kinds, ["save", "conflict", "save"])

    def test_the_export_dialog_counts_the_row_in_conflict(self):
        self._save("A", "cf-j1")
        self._save("B", "cf-j2", revision=1)
        _, page = self._open("/export")
        self.assertIn("충돌 1행", page)

    def test_the_export_dialog_returns_to_zero_after_the_conflict_is_resolved(self):
        self._save("A", "cf-k1")
        self._save("B", "cf-k2", revision=1)
        self._save("C", "cf-k3")
        _, page = self._open("/export")
        self.assertIn("충돌 0행", page)

    def test_the_tabs_index_reports_the_conflict_count(self):
        self._save("A", "cf-l1")
        self._save("B", "cf-l2", revision=1)
        _, data = self._json("/api/tabs")
        by_id = {t["tab_id"]: t for t in data["tabs"]}
        self.assertEqual(by_id[TAB]["conflict_rows"], 1)
        self.assertEqual(by_id["trip-demo-b"]["conflict_rows"], 0)

    def test_the_rows_listing_marks_the_row(self):
        self._save("A", "cf-m1")
        self._save("B", "cf-m2", revision=1)
        _, data = self._json(f"/api/tabs/{TAB}/rows")
        marked = {r["row_id"]: r for r in data["rows"]}
        self.assertTrue(marked[ROW]["conflict"])
        self.assertFalse(marked["expense-demo-c2"]["conflict"])

    def test_the_rows_listing_gives_the_current_revision(self):
        self._save("A", "cf-n1")
        _, data = self._json(f"/api/tabs/{TAB}/rows")
        marked = {r["row_id"]: r for r in data["rows"]}
        self.assertEqual(marked[ROW]["revision"], self._revision())

    def test_a_revert_refused_as_stale_also_leaves_a_note(self):
        self._save("A", "cf-o1")
        status, result = self._json(
            f"/api/rows/{ROW}/revert",
            {"expected_revision": 1, "client_request_id": "cf-o2"}, "POST")
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "EDIT_CONFLICT")
        self.assertIsNotNone(self.store.row_conflict(ROW))

    def test_a_valid_request_on_a_clean_row_leaves_no_note(self):
        self._save("A", "cf-p1")
        self.assertIsNone(self.store.row_conflict(ROW))

    def test_a_refused_field_leaves_no_note(self):
        """A rejected field is not a version conflict."""
        status, _ = self._open(
            f"/api/rows/{ROW}/save",
            {"expected_revision": self._revision(), "amount_krw": 5,
             "client_request_id": "cf-q1", "change_mode": "exception"},
            "POST")
        self.assertIn(status, (409, 422))
        self.assertIsNone(self.store.row_conflict(ROW))


class CanonicalTabPathTests(_Server, unittest.TestCase):
    def setUp(self):
        self._boot("tabs-path.sqlite", with_access=False)

    def tearDown(self):
        self._shutdown()

    def _trip_count(self, destination):
        return self.store.conn.execute(
            "SELECT COUNT(*) FROM trip_tabs WHERE destination=?",
            (destination,)).fetchone()[0]

    def test_post_api_tabs_is_the_create_path_named_by_the_spec(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": "2026-11-03", "destination": "오사카",
             "ends_on": "2026-11-07", "client_request_id": "cp-1"}, "POST")
        self.assertEqual(status, 200)
        self.assertEqual(result["outcome"], "created")
        self.assertEqual(self._trip_count("오사카"), 1)

    def test_post_api_trips_does_not_create_so_no_action_has_two_urls(self):
        status, result = self._json(
            "/api/trips",
            {"starts_on": "2026-12-01", "destination": "후쿠오카",
             "client_request_id": "cp-2"}, "POST")
        self.assertEqual(status, 404)
        self.assertEqual(result["code"], "RESOURCE_NOT_FOUND")
        self.assertEqual(self._trip_count("후쿠오카"), 0)

    def test_the_trip_meta_and_delete_family_is_untouched(self):
        """`/api/trips/{id}/...` stays its own family, proven already."""
        status, _ = self._json(
            f"/api/trips/{TAB}/meta",
            {"expected_revision": 1, "display_key": "이름 바꿈",
             "client_request_id": "cp-3"}, "POST")
        self.assertEqual(status, 200)
        self.assertEqual(
            self.store.get_trip(TAB)["display_key"], "이름 바꿈")

    def test_the_new_trip_form_posts_to_the_canonical_path(self):
        status, page = self._open("/trips")
        self.assertEqual(status, 200)
        self.assertIn("action='/api/tabs'", page)
        self.assertNotIn("action='/api/trips'", page)

    def test_the_rows_listing_answers_for_a_tab_that_does_not_exist(self):
        status, result = self._json("/api/tabs/no-such-tab/rows")
        self.assertEqual(status, 404)
        self.assertEqual(result["code"], "RESOURCE_NOT_FOUND")

    def test_the_rows_listing_answers_for_the_waiting_tab(self):
        status, data = self._json("/api/tabs/unclassified/rows")
        self.assertEqual(status, 200)
        self.assertEqual(data["tab_id"], "unclassified")


class ConflictAccessTests(_Server, unittest.TestCase):
    def setUp(self):
        self._boot("conflict-access.sqlite", with_access=True)
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER,
                                   role=access_control.ROLE_VIEWER,
                                   display_name="직원")

    def tearDown(self):
        self._shutdown()

    def test_a_viewer_cannot_create_a_tab_on_the_canonical_path(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": "2026-11-03", "destination": "오사카",
             "client_request_id": "ca-1"}, "POST", user=VIEWER)
        self.assertEqual(status, 403)
        self.assertEqual(result["code"], "ACTION_FORBIDDEN")
        self.assertEqual(self._trip_count_count("오사카"), 0)

    def _trip_count_count(self, destination):
        return self.store.conn.execute(
            "SELECT COUNT(*) FROM trip_tabs WHERE destination=?",
            (destination,)).fetchone()[0]

    def test_a_caller_without_a_session_is_asked_to_log_in_again(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": "2026-11-03", "destination": "오사카",
             "client_request_id": "ca-2"}, "POST")
        self.assertEqual(status, 401)
        self.assertEqual(result["code"], "AUTH_REQUIRED")
        self.assertEqual(self._trip_count_count("오사카"), 0)

    def test_the_owner_may_create_on_the_canonical_path(self):
        status, result = self._json(
            "/api/tabs",
            {"starts_on": "2026-11-03", "destination": "오사카",
             "client_request_id": "ca-3"}, "POST", user=OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(self._trip_count_count("오사카"), 1)

    def test_a_viewer_cannot_save_a_row_so_it_cannot_raise_a_conflict(self):
        status, _ = self._json(
            f"/api/rows/{ROW}/save",
            {"expected_revision": 1, "operator_note": "B",
             "change_mode": "exception", "client_request_id": "ca-4"},
            "POST", user=VIEWER)
        self.assertIn(status, (403, 404))
        self.assertIsNone(self.store.row_conflict(ROW))
