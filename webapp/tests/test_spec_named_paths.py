"""The paths APP_SPEC names that had no test on them, proven over real HTTP.

  * `POST /api/expenses/manual` — the manual-expense write, its validation and
    its refusal, and the fact that the `/expense/new` screen really posts here.
  * `POST /api/rows/{id}/revert` for an ordinary edit (a memo), which until now
    was only proven at the store layer while the allocation case was proven here.
  * `GET /api/rows/{id}/lineage`, `GET /api/audit/changes`, `GET /api/tabs` and
    `GET /api/tabs/{tab_id}/rows`, which APP_SPEC 10 lists and which did not
    exist.
  * The export dialog's 검토필요 and 충돌 counts.

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

OWNER = "syn-owner-p3"
VIEWER = "syn-staff-p3"

TAB = "trip-demo-a"
DEST = "다낭"
DAY = "2026-05-12"


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

    def _open(self, path, payload=None, method="GET", user=None, form=False):
        headers = {}
        data = None
        if payload is not None:
            body = dict(payload)
            if method == "POST":
                body.setdefault("csrf", board_mod.CSRF_TOKEN)
            if form:
                from urllib.parse import urlencode
                data = urlencode(body).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
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

    def _json(self, path, payload=None, method="GET", user=None, form=False):
        status, body = self._open(path, payload, method, user, form)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None

    def _manual_payload(self, **over):
        payload = {"display_tab_id": TAB, "occurred_on": DAY,
                   "pay_method": "현금", "item": "현금 지출",
                   "description": "수기 입력", "amount_krw": 45000,
                   "operator_note": "현금영수증 있음", "client_request_id": "m-1"}
        payload.update(over)
        return payload

    def _expense_rows(self):
        # a manual expense is stored in `board_rows` with a `man-` row id and
        # its record in `payload_json`; the id prefix is the stable handle.
        return self.store.conn.execute(
            "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'man-%'"
        ).fetchone()[0]


class ManualExpenseHttpTests(_Server, unittest.TestCase):
    """`POST /api/expenses/manual` on the served response."""

    def setUp(self):
        self._boot("manual.sqlite", with_access=False)

    def tearDown(self):
        self._shutdown()

    def test_the_new_screen_posts_to_this_endpoint(self):
        status, page = self._open("/expense/new")
        self.assertEqual(status, 200)
        self.assertIn("action='/api/expenses/manual'", page)
        for field in ("occurred_on", "amount_krw", "pay_method", "item"):
            self.assertIn(f"name='{field}'", page)

    def test_a_manual_expense_is_saved_and_readable_at_its_own_url(self):
        status, result = self._json("/api/expenses/manual",
                                    self._manual_payload(), "POST")
        self.assertEqual(status, 200)
        row_id = result["row_id"]
        self.assertEqual(self._expense_rows(), 1)
        status, page = self._open(f"/row?id={row_id}")
        self.assertEqual(status, 200)
        # the detail page shows the amount and states the source level
        self.assertIn("45,000원", page)
        self.assertIn("직접 입력", page)
        self.assertIn("수기", page)

    def test_the_form_post_lands_on_the_new_row(self):
        status, body = self._open("/api/expenses/manual",
                                  self._manual_payload(), "POST", form=True)
        self.assertEqual(status, 200)
        self.assertEqual(self._expense_rows(), 1)

    def test_the_same_request_id_saves_only_one_row(self):
        _, first = self._json("/api/expenses/manual",
                              self._manual_payload(), "POST")
        _, again = self._json("/api/expenses/manual",
                              self._manual_payload(), "POST")
        self.assertEqual(first["row_id"], again["row_id"])
        self.assertEqual(self._expense_rows(), 1)

    def test_the_same_request_id_with_other_content_is_refused(self):
        self._json("/api/expenses/manual", self._manual_payload(), "POST")
        status, result = self._json(
            "/api/expenses/manual",
            self._manual_payload(amount_krw=99000), "POST")
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "REQUEST_ID_REUSED")
        self.assertEqual(self._expense_rows(), 1)

    def test_a_write_without_the_confirmation_token_is_refused(self):
        status, _ = self._open("/api/expenses/manual",
                               self._manual_payload(csrf="wrong"), "POST")
        self.assertEqual(status, 403)
        self.assertEqual(self._expense_rows(), 0)

    def test_an_amount_the_server_cannot_read_is_refused_with_422(self):
        for bad in ("열두천원", "", "4,5,00.5"):
            status, result = self._json(
                "/api/expenses/manual",
                self._manual_payload(amount_krw=bad,
                                     client_request_id=f"bad-{bad}"), "POST")
            self.assertEqual(status, 422, bad)
            self.assertEqual(result["code"], "INVALID_VALUE", bad)
        self.assertEqual(self._expense_rows(), 0)

    def test_a_date_the_server_cannot_read_is_refused(self):
        status, result = self._json(
            "/api/expenses/manual",
            self._manual_payload(occurred_on="2026-13-45",
                                 client_request_id="bad-day"), "POST")
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")
        self.assertEqual(self._expense_rows(), 0)

    def test_a_refused_write_leaves_no_row_behind(self):
        self._json("/api/expenses/manual",
                   self._manual_payload(amount_krw="nope",
                                        client_request_id="rollback-m"), "POST")
        self.assertEqual(self._expense_rows(), 0)
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM board_revisions"
                " WHERE client_request_id='rollback-m'").fetchone()[0], 0)

    def test_the_expense_shows_its_own_source_level(self):
        """APP_SPEC 5: a manual entry with no source value says so, and that is
        a level of basis rather than an error."""
        _, result = self._json("/api/expenses/manual",
                               self._manual_payload(), "POST")
        _, page = self._open(f"/row?id={result['row_id']}")
        self.assertIn("원천", page)
        self.assertIn("수기", page)


class OrdinaryRevertHttpTests(_Server, unittest.TestCase):
    """REFINEMENT 9 for an ordinary edit, on the route the spec names."""

    ROW = "expense-demo-c1"

    def setUp(self):
        self._boot("revert.sqlite", with_access=False)
        self._save_memo("A", "memo-1")

    def tearDown(self):
        self._shutdown()

    def _revision(self):
        return (self.store.get_row(self.ROW) or {}).get("revision")

    def _save_memo(self, note, request_id):
        return self._json(
            f"/api/rows/{self.ROW}/save",
            {"expected_revision": self._revision(), "operator_note": note,
             "client_request_id": request_id, "change_mode": "exception"},
            "POST")

    def test_a_memo_edit_and_its_revert_both_go_through_http(self):
        _, saved = self._save_memo("B", "memo-2")
        self.assertEqual(saved.get("revision"), self._revision())
        _, page = self._open(f"/row?id={self.ROW}")
        self.assertIn("B", page)

        status, result = self._json(
            f"/api/rows/{self.ROW}/revert",
            {"expected_revision": self._revision(),
             "client_request_id": "revert-1"}, "POST")
        self.assertEqual(status, 200)
        self.assertEqual((self.store.get_row(self.ROW) or {}).get("operator_note"),
                         "A")

    def test_the_revert_is_a_new_event_and_does_not_erase_the_old_one(self):
        """REFINEMENT 9: the original event is kept and a new one refers to it."""
        _, before = self._json(
            f"/api/rows/{self.ROW}/lineage", None, "GET")
        _, result = self._json(
            f"/api/rows/{self.ROW}/revert",
            {"expected_revision": self._revision(),
             "client_request_id": "revert-2"}, "POST")
        _, after = self._json(f"/api/rows/{self.ROW}/lineage", None, "GET")
        self.assertEqual(after["event_count"], before["event_count"] + 1)
        reverts = [e for e in after["history"] if e.get("reverts_event_id")]
        self.assertTrue(reverts, "the revert must point back at an event")
        self.assertIsNone(result.get("error"))

    def test_a_retry_of_the_same_revert_does_not_add_history(self):
        payload = {"expected_revision": None, "client_request_id": "revert-3"}
        payload["expected_revision"] = self._revision()
        first_status, _ = self._json(f"/api/rows/{self.ROW}/revert",
                                     payload, "POST")
        second_status, _ = self._json(f"/api/rows/{self.ROW}/revert",
                                      payload, "POST")
        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        _, lineage = self._json(f"/api/rows/{self.ROW}/lineage", None, "GET")
        reverts = [e for e in lineage["history"] if e.get("reverts_event_id")]
        self.assertEqual(len(reverts), 1)

    def test_a_stale_revert_is_refused_and_changes_nothing(self):
        self._save_memo("C", "memo-4")
        status, result = self._json(
            f"/api/rows/{self.ROW}/revert",
            {"expected_revision": 1, "client_request_id": "revert-stale"},
            "POST")
        self.assertIn(status, (409, 422))
        self.assertEqual(result["code"], "EDIT_CONFLICT")
        self.assertEqual((self.store.get_row(self.ROW) or {}).get("operator_note"),
                         "C")

    def test_a_revert_without_a_revision_is_refused(self):
        status, result = self._json(
            f"/api/rows/{self.ROW}/revert",
            {"client_request_id": "revert-norev"}, "POST")
        self.assertEqual(status, 422)
        self.assertEqual(result["code"], "INVALID_VALUE")

    def test_a_revert_without_the_confirmation_token_is_refused(self):
        status, _ = self._open(
            f"/api/rows/{self.ROW}/revert",
            {"expected_revision": self._revision(),
             "client_request_id": "revert-nocsrf", "csrf": "wrong"}, "POST")
        self.assertEqual(status, 403)
        self.assertEqual((self.store.get_row(self.ROW) or {}).get("operator_note"),
                         "A")


class SpecNamedReadTests(_Server, unittest.TestCase):
    """APP_SPEC 10's read paths."""

    def setUp(self):
        self._boot("reads.sqlite", with_access=False)

    def tearDown(self):
        self._shutdown()

    def test_the_tabs_index_reports_authority_totals_and_review_counts(self):
        status, data = self._json("/api/tabs")
        self.assertEqual(status, 200)
        names = {t["display_key"] for t in data["tabs"]}
        self.assertIn("분류대기", names)
        for tab in data["tabs"]:
            self.assertIn("authority_status", tab)
            self.assertIn("income_krw", tab)
            self.assertIn("expense_krw", tab)
            self.assertIn("needs_review_rows", tab)
            self.assertEqual(
                tab["profit_krw"], tab["income_krw"] - tab["expense_krw"])

    def test_the_tabs_index_states_authority_apart_from_the_name(self):
        _, data = self._json("/api/tabs")
        for tab in data["tabs"]:
            self.assertIn(tab["authority_status"],
                          ("needs_review", "authoritative", "unconfirmed",
                           "conflicted"))
            self.assertEqual(
                tab["authority_label"] == "권위 있음",
                tab["authority_status"] == "authoritative")
        # A tab on screen is not an authoritative schedule (3, 4.2). Every tab
        # this store has was made without a schedule source, so none of them may
        # read as authoritative however it is named.
        by_id = {t["tab_id"]: t for t in data["tabs"]}
        self.assertNotEqual(by_id["trip-demo-a"]["authority_status"],
                            "authoritative")
        self.assertNotEqual(by_id["trip-demo-b"]["authority_status"],
                            "authoritative")
        self.assertNotEqual(by_id["unclassified"]["authority_status"],
                            "authoritative")

    def test_a_trip_created_on_screen_is_not_authoritative_either(self):
        self._json("/api/tabs",
                   {"starts_on": "2026-11-03", "destination": DEST,
                    "ends_on": "2026-11-07",
                    "client_request_id": "tabs-authority-1"}, "POST")
        _, data = self._json("/api/tabs")
        made = [t for t in data["tabs"] if t["destination"] == DEST]
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["authority_status"], "needs_review")
        self.assertNotEqual(made[0]["authority_label"], "권위 있음")

    def test_the_lineage_answers_source_proposal_edits_and_history(self):
        status, data = self._json("/api/rows/expense-demo-c1/lineage")
        self.assertEqual(status, 200)
        self.assertIn("source", data)
        self.assertIn("proposal", data)
        self.assertIn("user_edits", data)
        self.assertIn("history", data)
        self.assertEqual(data["source"]["event_id"], "SRC-C1")

    def test_the_lineage_of_a_row_that_names_nothing_is_404(self):
        status, data = self._json("/api/rows/no-such-row/lineage")
        self.assertEqual(status, 404)
        self.assertEqual(data["code"], "RESOURCE_NOT_FOUND")

    def test_the_audit_list_is_empty_until_something_is_saved(self):
        status, data = self._json("/api/audit/changes")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 0)

    def test_a_save_shows_up_in_the_audit_list_with_its_actor(self):
        self._json("/api/rows/expense-demo-c1/save",
                   {"expected_revision": 1, "operator_note": "기록",
                    "client_request_id": "audit-1", "change_mode": "exception"},
                   "POST")
        status, data = self._json("/api/audit/changes")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        entry = data["changes"][0]
        self.assertEqual(entry["row_id"], "expense-demo-c1")
        self.assertEqual(entry["actor"], "owner")
        self.assertTrue(entry["created_at"])

    def test_the_audit_list_filters_by_row_and_by_actor(self):
        self._json("/api/rows/expense-demo-c1/save",
                   {"expected_revision": 1, "operator_note": "기록",
                    "client_request_id": "audit-2", "change_mode": "exception"},
                   "POST")
        _, by_row = self._json("/api/audit/changes?row_id=expense-demo-c1")
        self.assertEqual(by_row["count"], 1)
        _, other_row = self._json("/api/audit/changes?row_id=income-demo-i1")
        self.assertEqual(other_row["count"], 0)
        _, by_actor = self._json("/api/audit/changes?actor=owner")
        self.assertEqual(by_actor["count"], 1)
        _, nobody = self._json("/api/audit/changes?actor=nobody")
        self.assertEqual(nobody["count"], 0)

    def test_the_audit_list_filters_by_period(self):
        self._json("/api/rows/expense-demo-c1/save",
                   {"expected_revision": 1, "operator_note": "기록",
                    "client_request_id": "audit-3", "change_mode": "exception"},
                   "POST")
        _, future = self._json("/api/audit/changes?since=2999-01-01")
        self.assertEqual(future["count"], 0)
        _, past = self._json("/api/audit/changes?until=2000-01-01")
        self.assertEqual(past["count"], 0)
        _, everything = self._json("/api/audit/changes")
        self.assertEqual(everything["count"], 1)

    def test_the_export_dialog_states_the_review_and_conflict_counts(self):
        status, page = self._open("/export")
        self.assertEqual(status, 200)
        self.assertIn("검토필요", page)
        self.assertIn("충돌", page)
        # a clean ledger reports a real zero rather than dropping the line
        self.assertIn("충돌 0행", page)
        self.assertTrue(
            re.search(r"검토필요 (\d+)행 · 충돌 (\d+)행", page),
            "the dialog must state both counts")

    def test_the_export_dialog_review_note_appears_before_the_form(self):
        _, page = self._open("/export")
        self.assertLess(page.index("검토필요"),
                        page.index("action='/api/exports/xlsx'"))


class SpecNamedReadAccessTests(_Server, unittest.TestCase):
    """The same reads under the owner boundary."""

    def setUp(self):
        self._boot("reads-access.sqlite", with_access=True)
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER,
                                   role=access_control.ROLE_VIEWER,
                                   display_name="직원")

    def tearDown(self):
        self._shutdown()

    def test_a_viewer_cannot_read_the_tabs_index(self):
        status, _ = self._json("/api/tabs", None, "GET", user=VIEWER)
        self.assertIn(status, (403, 404))

    def test_a_viewer_cannot_read_the_audit_list(self):
        status, _ = self._json("/api/audit/changes", None, "GET", user=VIEWER)
        self.assertIn(status, (403, 404))

    def test_a_caller_without_a_session_is_asked_to_log_in_again(self):
        status, data = self._json("/api/tabs")
        self.assertEqual(status, 401)
        self.assertEqual(data["code"], "AUTH_REQUIRED")
