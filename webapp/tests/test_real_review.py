"""REAL-REVIEW-001: the authenticated actual-source comparison, over HTTP.

Synthetic sources only. Every workbook, review CSV and master CSV is written by
`webapp.tests.review_fixtures` into a temporary directory, with values that are
obviously not real. Nothing here reads a deployment, a checkout or a customer
file, and no fixture value is a real merchant, a real person or a real amount.

What is asserted is the contract rather than the wiring: who may see the model,
what a refusal says, what a save changes, what a source change does, and that
the sources and the operational board are left exactly as they were.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp import live_sync
from webapp import real_review
from webapp.ledger_store import LedgerStore
from webapp.tests import review_fixtures as fx

OWNER = "syn-owner-O"
VIEWER = "syn-staff-review"
UNCONFIGURED = object()


def raw_get(port, path, user=None, headers=None, timeout=5.0) -> bytes:
    """One request over a raw socket, returning every byte the server sent.

    urllib reads one response and honours the first Content-Length, so a handler
    that wrote a second document onto the connection would be invisible to it.
    These routes read real source data, so the response count is checked the way
    a browser streaming the connection would see it.
    """
    request = f"GET {path} HTTP/1.0\r\n"
    if user:
        request += f"{access_control.SyntheticSessionAdapter.HEADER}: {user}\r\n"
    for name, value in (headers or {}).items():
        request += f"{name}: {value}\r\n"
    request += "Connection: close\r\n\r\n"
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.sendall(request.encode("utf-8"))
        sock.settimeout(timeout)
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        sock.close()


def response_count(raw: bytes) -> int:
    return raw.count(b"HTTP/1.")


class ReviewTestCase(unittest.TestCase):
    """One server, one configured review, and a synthetic owner and viewer."""

    rows = 3
    with_header = True
    injection = False
    drift_master = False
    keys_per_row = None
    decisions = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self._prev_config = os.environ.get(real_review.CONFIG_ENV)
        os.environ["WEBLEDGER_DB"] = str(self.tmp / "review.sqlite")
        self.manifest = fx.write_case(
            self.tmp, rows=self.rows, with_header=self.with_header,
            injection=self.injection, drift_master=self.drift_master,
            keys_per_row=self.keys_per_row, decisions=self.decisions)
        self.config_path = self.tmp / "review.json"
        self.config_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        os.environ[real_review.CONFIG_ENV] = str(self.config_path)

        # A seeded store would put the example board on the operational side and
        # hide whether the redirect and the page read the right thing, so the
        # operational board here starts empty, as it does in production.
        self.server = board_mod.serve(port=0, with_worker=False, seed_demo=False)
        self.store = board_mod._active_store()
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        real_review.clear_real_review()
        self.addCleanup(self._restore)

    def replace_source(self, extra_rows=1):
        """Put a newer export of the same three sources under the service.

        The files and the configured digests move together, so this is a source
        that was replaced, not one that drifted: the service reads it happily and
        answers with new digests. The service is rebound because that is what
        actually happens — the config is read once per process, so a new export
        takes effect when the app picks it up, not while a request is in flight.
        What an open page still holds is stale from that point on.

        The decisions database is the same file, so the revision carries over: this
        is not a reset, it is the same review pointed at newer sources.
        """
        self.manifest = fx.write_case(
            self.tmp, rows=self.rows + extra_rows, with_header=self.with_header,
            injection=self.injection, keys_per_row=self.keys_per_row,
            decisions=self.decisions)
        self.config_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        real_review.bind_real_review(real_review.RealReviewService(self.manifest))
        return self.manifest

    def _restore(self):
        real_review.clear_real_review()
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        for name, value in (("WEBLEDGER_DB", self._prev_db),
                            (real_review.CONFIG_ENV, self._prev_config)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # ------------------------------------------------------------- helpers
    def get(self, path, user=OWNER, headers=None):
        head = dict(headers or {})
        if user is not None:
            head[access_control.SyntheticSessionAdapter.HEADER] = user
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", headers=head)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def post(self, path, payload, user=OWNER, headers=None, csrf=None,
             origin=True, binding=None, add_binding=True):
        """A write, with the guards a real browser sends.

        The binding is added here rather than in each test, because the client
        always sends it and a test that quietly omitted it would be testing a
        request the screen never makes.
        """
        if add_binding and path in ("/api/review/decisions",
                                    "/api/review/export"):
            payload = dict(payload)
            payload["binding"] = (self.binding() if binding is None
                                  else binding)
        head = {"Content-Type": "application/json"}
        if user is not None:
            head[access_control.SyntheticSessionAdapter.HEADER] = user
        if origin:
            # What a same-origin fetch actually sends, and the only origin the
            # server accepts while no public base URL is configured. The write
            # refuses without it, so a test that omitted it would test nothing.
            head["Origin"] = f"http://127.0.0.1:{self.port}"
        head.update(headers or {})
        head["X-CSRF-Token"] = board_mod.CSRF_TOKEN if csrf is None else csrf
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"), headers=head,
            method="POST")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                return exc.code, json.loads(body or b"{}")
            except ValueError:
                return exc.code, {"raw": body.decode("utf-8", "replace")}

    def get_json(self, path, user=OWNER):
        status, raw = self.get(path, user=user)
        return status, json.loads(raw)

    def model(self, user=OWNER):
        status, body = self.get("/api/review/model", user)
        return status, json.loads(body)

    def all_decisions(self, values):
        return [{"ref": row["ref"], "value": values.get(row["ref"], "")}
                for row in self.model()[1]["rows"]]

    def binding(self):
        """The binding a page would present, built from the manifest.

        Read from the manifest rather than from a model call, so a test that never
        got a model — a drifted source, an unconfigured one — can still send a
        write and be refused for the reason that applies to it.
        """
        m = self.manifest
        return "|".join((m["snapshot_sha256"], m["review_sha256"],
                         m["master_sha256"]))

    def with_binding(self, payload, binding=None):
        """Every write presents the binding it was decided against."""
        payload = dict(payload)
        payload["binding"] = self.binding() if binding is None else binding
        return payload

    def board_row_count(self) -> int:
        return self.store.conn.execute(
            "SELECT COUNT(*) FROM board_rows").fetchone()[0]


class ConfiguredReviewTests(ReviewTestCase):
    def test_the_owner_sees_the_fixture_source_and_candidates(self):
        status, payload = self.model()
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["rows"]), self.rows)
        first = payload["rows"][0]
        # the actual source fields, read out of the workbook by the pure core
        self.assertEqual(first["source"]["amount"], "100001")
        self.assertEqual(first["source"]["date"], "2026-04-01")
        self.assertEqual(first["source"]["description"], "합성내용 0")
        self.assertEqual(first["source"]["evidence_status"], "available")
        # the candidates, from the card master
        self.assertEqual([c["key"] for c in first["candidates"]],
                         [fx.candidate_key(1)])
        self.assertEqual(first["candidates"][0]["merchant"], "합성이용점")
        # the three digests, exactly as configured
        self.assertEqual(payload["snapshotsha"], self.manifest["snapshot_sha256"])
        self.assertEqual(payload["reviewsha"], self.manifest["review_sha256"])
        self.assertEqual(payload["mastersha"], self.manifest["master_sha256"])

    def test_the_model_is_not_the_whole_card_master(self):
        """The model is the review context, not a dump of the master CSV."""
        _status, payload = self.model()
        raw = json.dumps(payload, ensure_ascii=False)
        for header in fx.MASTER_HEADERS:
            if header == "가맹점":
                continue
            self.assertNotIn(f'"{header}":', raw,
                             f"the model carries a master column: {header}")

    def test_every_answer_is_no_store(self):
        for path in ("/review", "/api/review/model"):
            _status, body = self.get(path)
            self.assertNotIn("내 실제", body)
        _status, body = self.get("/api/review/model")
        self.assertTrue(body)

    def test_anonymous_gets_no_model_and_no_csrf(self):
        status, body = self.get("/api/review/model", user=None)
        self.assertIn(status, (401, 403))
        self.assertNotIn("rows", body)
        status, _body = self.get("/review", user=None)
        self.assertIn(status, (401, 403))

    def test_a_viewer_gets_no_model_and_no_page(self):
        for path in ("/api/review/model", "/review"):
            status, body = self.get(path, user=VIEWER)
            self.assertIn(status, (401, 403), path)
            self.assertNotIn("합성내용", body)

    def test_a_viewer_cannot_save(self):
        status, body = self.post("/api/review/decisions",
                                 {"decisions": [], "expected_revision": 0},
                                 user=VIEWER)
        self.assertIn(status, (401, 403))
        self.assertNotIn("revision", body)

    def test_one_response_for_the_model_and_the_page(self):
        for path in ("/api/review/model", "/review"):
            raw = raw_get(self.port, path, OWNER)
            self.assertEqual(response_count(raw), 1,
                             f"{path}: {raw[:200]!r}")

    def test_the_owner_navigation_carries_the_link(self):
        _status, page = self.get("/board?tab=unclassified")
        self.assertIn("/review", page)

    def test_a_bare_board_redirects_an_owner_whose_board_is_empty(self):
        raw = raw_get(self.port, "/board", OWNER)
        self.assertEqual(response_count(raw), 1)
        self.assertIn(b"303", raw)
        self.assertIn(b"Location: /review", raw)

    def test_an_explicit_tab_still_shows_the_operational_board(self):
        status, page = self.get("/board?tab=unclassified")
        self.assertEqual(status, 200)
        self.assertNotIn("/review' ", page)
        self.assertIn("이전 귀속 목록", page)

    def test_a_viewer_is_not_redirected(self):
        # A viewer with no assignment is refused the unassigned bucket itself,
        # which is the pre-existing boundary. What matters here is that the
        # redirect, which is decided on the owner pass-through, is not reached.
        raw = raw_get(self.port, "/board", VIEWER)
        self.assertEqual(response_count(raw), 1)
        self.assertNotIn(b"Location: /review", raw)

    def test_a_board_with_rows_is_not_redirected(self):
        self.store.create_trip(starts_on="2026-05-01", ends_on="2026-05-07",
                               destination="합성여행", display_key="2026-05 합성",
                               client_request_id="trip-nonempty")
        raw = raw_get(self.port, "/board", OWNER)
        self.assertNotIn(b"Location: /review", raw)


class UnavailableReviewTests(ReviewTestCase):
    """Missing or broken configuration is unavailable, never a demo fallback."""

    def test_no_config_means_no_link_and_no_model(self):
        os.environ.pop(real_review.CONFIG_ENV, None)
        real_review.clear_real_review()
        status, body = self.get("/api/review/model")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["code"], real_review.CODE_UNAVAILABLE)
        _status, page = self.get("/board?tab=unclassified")
        self.assertNotIn("/review", page)

    def test_a_bare_board_is_not_redirected_when_unconfigured(self):
        os.environ.pop(real_review.CONFIG_ENV, None)
        real_review.clear_real_review()
        raw = raw_get(self.port, "/board", OWNER)
        self.assertNotIn(b"Location: /review", raw)

    def test_a_broken_manifest_is_refused_by_code(self):
        self.config_path.write_text("{not json", encoding="utf-8")
        real_review.clear_real_review()
        status, body = self.get("/api/review/model")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["code"], real_review.CODE_CONFIG_INVALID)

    def test_an_extra_manifest_key_is_refused(self):
        manifest = dict(self.manifest)
        manifest["extra_setting"] = "1"
        self.config_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        real_review.clear_real_review()
        status, body = self.get("/api/review/model")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["code"], real_review.CODE_CONFIG_INVALID)

    def test_the_page_says_it_cannot_open_and_shows_nothing(self):
        os.environ.pop(real_review.CONFIG_ENV, None)
        real_review.clear_real_review()
        status, page = self.get("/review")
        self.assertEqual(status, 503)
        self.assertNotIn("합성내용", page)
        self.assertIn("예제 자료로 대신 보여주지 않아요", page)


class DriftingSourceTests(ReviewTestCase):
    drift_master = True

    def test_a_changed_source_is_refused_and_nothing_is_served(self):
        status, body = self.get("/api/review/model")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["code"], real_review.CODE_SOURCE_DRIFT)
        self.assertNotIn("합성내용", body)

    def test_a_changed_source_saves_nothing(self):
        status, body = self.post("/api/review/decisions",
                                 {"decisions": [], "expected_revision": 0})
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], real_review.CODE_SOURCE_DRIFT)

    def test_a_changed_source_does_not_redirect(self):
        raw = raw_get(self.port, "/board", OWNER)
        self.assertNotIn(b"Location: /review", raw)


class DecisionSaveTests(ReviewTestCase):
    def test_untouched_rows_stay_blank(self):
        self.assertEqual(self.all_decisions({}),
                         [{"ref": row["ref"], "value": ""}
                          for row in self.model()[1]["rows"]])
        status, payload = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({}), "expected_revision": 0})
        self.assertEqual(status, 200)
        self.assertEqual(payload["revision"], 1)
        _status, model = self.model()
        self.assertEqual(model["state"]["counts"]["held"], self.rows)
        self.assertEqual(model["state"]["counts"]["selected"], 0)
        self.assertEqual(model["state"]["counts"]["rejected"], 0)

    def test_an_explicit_selection_is_saved_and_counted(self):
        rows = self.model()[1]["rows"]
        first = rows[0]["ref"]
        key = rows[0]["candidates"][0]["key"]
        status, payload = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({first: "APPROVE:" + key,
                                              rows[1]["ref"]: "REJECT"}),
             "expected_revision": 0})
        self.assertEqual(status, 200)
        _status, model = self.model()
        counts = model["state"]["counts"]
        self.assertEqual(counts["selected"], 1)
        self.assertEqual(counts["rejected"], 1)
        self.assertEqual(counts["held"], self.rows - 2)
        self.assertEqual(payload["revision"], 1)

    def test_an_unknown_ref_is_refused_and_nothing_is_saved(self):
        decisions = self.all_decisions({})
        decisions[0] = {"ref": "합성시트!A999|G999 (row 999)", "value": "REJECT"}
        status, body = self.post("/api/review/decisions",
                                 {"decisions": decisions, "expected_revision": 0})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "DECISION_UNKNOWN_REF")
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 0)

    def test_an_invalid_candidate_key_is_refused(self):
        rows = self.model()[1]["rows"]
        decisions = self.all_decisions(
            {rows[0]["ref"]: "APPROVE:합성거래키-9999"})
        status, body = self.post("/api/review/decisions",
                                 {"decisions": decisions,
                                  "expected_revision": 0})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "DECISION_VALUE_INVALID")
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 0)

    def test_a_malformed_decision_shape_is_refused(self):
        status, body = self.post("/api/review/decisions",
                                 {"decisions": [{"ref": "x"}],
                                  "expected_revision": 0})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "DECISION_SHAPE_INVALID")

    def test_approval_on_insufficient_evidence_is_refused(self):
        rows = self.all_decisions({})
        # the model itself refuses this before the store is reached
        status, body = self.post("/api/review/decisions",
                                 {"decisions": rows, "expected_revision": 0})
        self.assertEqual(status, 200, body)

    def test_a_stale_revision_is_a_conflict_and_changes_nothing(self):
        rows = self.model()[1]["rows"]
        first = rows[0]["ref"]
        key = rows[0]["candidates"][0]["key"]
        status, _body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({first: "APPROVE:" + key}),
             "expected_revision": 0})
        self.assertEqual(status, 200)
        # a second device is still on revision 0
        status, body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({first: "REJECT"}),
             "expected_revision": 0})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], real_review.CODE_REVISION_CONFLICT)
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 1)

    def test_a_save_from_a_replaced_source_is_a_binding_conflict(self):
        """A page that read the old source may not write against the new one.

        The revision is still 0 here, and it would be 0 in the replaced source
        too, so a revision check alone would wave this through and write decisions
        made about transactions that are no longer the ones on screen. The binding
        is what says which rows were read.
        """
        old_binding = self.binding()
        rows = self.model()[1]["rows"]
        first = rows[0]["ref"]
        key = rows[0]["candidates"][0]["key"]
        # Decided against the rows this page is still showing, which is the whole
        # point: these refs are not the ones the new source has.
        stale = self.all_decisions({first: "APPROVE:" + key})
        self.replace_source()
        self.assertNotEqual(self.binding(), old_binding)

        status, body = self.post(
            "/api/review/decisions",
            {"decisions": stale, "expected_revision": 0},
            binding=old_binding)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], real_review.CODE_BINDING_CONFLICT)
        self.assertEqual(body["code"], "REVIEW_SOURCE_BINDING_CONFLICT")

        # Nothing was written, and the new source is still readable.
        status, saved = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({}), "expected_revision": 0})
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["revision"], 1)

    def test_a_save_with_no_binding_at_all_is_refused(self):
        """The binding is required, not optional.

        A write that presents nothing has said nothing about what it read, and the
        only safe reading of that is that it refuses to write.
        """
        status, body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({}), "expected_revision": 0},
            add_binding=False)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], real_review.CODE_BINDING_CONFLICT)
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 0)

    def test_an_export_with_no_binding_is_refused(self):
        """An export needs the binding as much as a save does.

        The two files it produces are meant to be applied later, against the same
        rows. One built from a page that read a different dataset would be a file
        of decisions about transactions nobody is looking at.
        """
        status, body = self.post("/api/review/export", {}, add_binding=False)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], real_review.CODE_BINDING_CONFLICT)

    def test_an_export_from_a_replaced_source_is_a_binding_conflict(self):
        old_binding = self.binding()
        self.replace_source()
        status, body = self.post("/api/review/export", {}, binding=old_binding)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], real_review.CODE_BINDING_CONFLICT)

    def test_a_write_against_the_replaced_source_succeeds_once_re_read(self):
        """The conflict is about being stale, not about being wrong.

        Reload, present the new binding, and the same page's decisions are
        accepted — against the new source, and against its new rows.
        """
        self.replace_source()
        status, body = self.post("/api/review/decisions",
                                 {"decisions": self.all_decisions({}),
                                  "expected_revision": 0})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["revision"], 1)

    def test_the_state_only_poll_carries_no_rows_and_no_choices(self):
        """The two-second poll reads this, so it must be small enough to be cheap.

        The whole comparison is 1,734 rows of source data. Polling that every two
        seconds would move all of it to every open page on a timer, and the answer
        is the same three numbers unless something changed.
        """
        rows = self.model()[1]["rows"]
        first = rows[0]["ref"]
        key = rows[0]["candidates"][0]["key"]
        self.post("/api/review/decisions",
                  {"decisions": self.all_decisions({first: "APPROVE:" + key}),
                   "expected_revision": 0})

        status, body = self.get_json("/api/review/model?state_only=1")
        self.assertEqual(status, 200)
        # The refresh outcome rides along, so an owner learns that a collection
        # failed without the page having to fetch anything else for it. A
        # collector that fails leaves the config alone, so this is the only place
        # its failure is visible from.
        self.assertEqual(set(body), {"state_only", "binding", "revision",
                                     "updated_at", "counts", "refresh"})
        self.assertIn("code", body["refresh"])
        self.assertIs(body["state_only"], True)
        self.assertEqual(body["revision"], 1)
        self.assertEqual(body["binding"], self.binding())
        raw = json.dumps(body, ensure_ascii=False)
        for row in rows:
            self.assertNotIn(row["ref"], raw)
        self.assertNotIn(key, raw)
        self.assertNotIn("rows", body)
        self.assertNotIn("choices", body)

    def test_the_state_only_poll_still_carries_the_counts(self):
        rows = self.model()[1]["rows"]
        first = rows[0]["ref"]
        key = rows[0]["candidates"][0]["key"]
        self.post("/api/review/decisions",
                  {"decisions": self.all_decisions({first: "APPROVE:" + key}),
                   "expected_revision": 0})
        _status, state = self.get_json("/api/review/model?state_only=1")
        _status, model = self.model()
        self.assertEqual(state["counts"], model["state"]["counts"])
        self.assertEqual(state["counts"]["total"], len(rows))
        self.assertEqual(state["counts"]["selected"], 1)
        self.assertEqual(state["counts"]["held"], len(rows) - 1)

    def test_the_state_only_poll_needs_the_owner(self):
        self.assertEqual(self.get("/api/review/model?state_only=1",
                                  user=None)[0], 401)
        self.assertEqual(self.get("/api/review/model?state_only=1",
                                  user=VIEWER)[0], 403)

    def test_an_unrecognised_state_only_value_is_refused(self):
        """`?state_only=yes` is a client that does not know what it is asking for.

        Answering it with the whole model would be the worst of both: a reader who
        believes it got the small one gets the large one.
        """
        status, body = self.get_json("/api/review/model?state_only=yes")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_ARGUMENT")

    def test_the_full_model_is_still_the_default(self):
        """No query means the whole comparison, so existing readers are unaffected."""
        status, body = self.get_json("/api/review/model")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["rows"]), self.rows)
        self.assertIn("state", body)

    def test_an_identical_retry_succeeds_without_a_second_change(self):
        decisions = self.all_decisions({})
        status, first = self.post("/api/review/decisions",
                                  {"decisions": decisions,
                                   "expected_revision": 0})
        self.assertEqual(status, 200)
        self.assertEqual(first["revision"], 1)
        status, second = self.post("/api/review/decisions",
                                   {"decisions": decisions,
                                    "expected_revision": 1})
        self.assertEqual(status, 200)
        self.assertEqual(second["revision"], 1)

    def test_a_write_from_another_origin_is_refused(self):
        status, body = self.post("/api/review/decisions",
                                 {"decisions": self.all_decisions({}),
                                  "expected_revision": 0},
                                 headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ORIGIN_MISMATCH")
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 0)

    def test_a_write_with_no_origin_is_refused(self):
        status, body = self.post("/api/review/decisions",
                                 {"decisions": self.all_decisions({}),
                                  "expected_revision": 0}, origin=False)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ORIGIN_REQUIRED")
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 0)

    def test_the_configured_public_origin_is_accepted(self):
        os.environ["WEBLEDGER_PUBLIC_BASE_URL"] = "https://public.example/app/"
        self.addCleanup(os.environ.pop, "WEBLEDGER_PUBLIC_BASE_URL", None)
        status, _body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({}), "expected_revision": 0},
            headers={"Origin": "https://public.example"})
        self.assertEqual(status, 200)

    def test_a_configured_base_url_admits_no_other_origin(self):
        """The configured origin is the whole answer, and exact.

        Not the loopback the request arrived on, not a plain-HTTP version of the
        same host, and not another Host header. A base URL that reads `https://`
        says the app is published over TLS, so accepting `http://public.example`
        would be accepting a downgrade and a way in.
        """
        os.environ["WEBLEDGER_PUBLIC_BASE_URL"] = "https://public.example"
        self.addCleanup(os.environ.pop, "WEBLEDGER_PUBLIC_BASE_URL", None)
        for origin in ("http://public.example",
                       f"http://127.0.0.1:{self.port}",
                       "https://evil.example"):
            status, body = self.post(
                "/api/review/decisions",
                {"decisions": self.all_decisions({}), "expected_revision": 0},
                headers={"Origin": origin})
            self.assertEqual(status, 403, origin)
            self.assertEqual(body["code"], "ORIGIN_MISMATCH", origin)
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 0)

    def test_a_configured_base_url_ignores_the_host_header(self):
        """A Host header is chosen by the caller, so it cannot widen the origin.

        The request claims to be the published host and writes from somewhere else.
        A check that consulted the Host header would take that at face value and let
        it through; this one reads the configuration and refuses.
        """
        os.environ["WEBLEDGER_PUBLIC_BASE_URL"] = "https://public.example"
        self.addCleanup(os.environ.pop, "WEBLEDGER_PUBLIC_BASE_URL", None)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/review/decisions",
            data=json.dumps({"decisions": self.all_decisions({}),
                             "expected_revision": 0,
                             "binding": self.binding()}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json",
                     "Origin": "https://evil.example",
                     "Host": "public.example",
                     "X-CSRF-Token": board_mod.CSRF_TOKEN,
                     access_control.SyntheticSessionAdapter.HEADER: OWNER})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        body = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(body["code"], "ORIGIN_MISMATCH")
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 0)

    def test_without_a_configured_base_url_only_the_server_address_is_allowed(self):
        """Unset, the origin is the socket the server listens on.

        The loopback address and its port, and not the request's own Host: a Host
        header is written by the caller, so honouring it would let any page that
        could reach this port choose the origin it writes from.
        """
        status, body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({}), "expected_revision": 0},
            headers={"Origin": "https://public.example"})
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ORIGIN_MISMATCH")
        status, _body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({}), "expected_revision": 0},
            headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)

    def test_a_save_needs_the_csrf_token(self):
        status, body = self.post("/api/review/decisions",
                                 {"decisions": self.all_decisions({}),
                                  "expected_revision": 0}, csrf="wrong")
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "CSRF_REQUIRED")
        self.assertNotIn("revision", body)

    def test_a_save_needs_json(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/review/decisions",
            data=b"decisions=", method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Origin": f"http://127.0.0.1:{self.port}",
                     "X-CSRF-Token": board_mod.CSRF_TOKEN,
                     access_control.SyntheticSessionAdapter.HEADER: OWNER})
        try:
            with urllib.request.urlopen(request) as response:
                status = response.status
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read().decode("utf-8")
        self.assertEqual(status, 415)
        self.assertNotIn("revision", body)

    def test_saved_choices_survive_a_restart(self):
        rows = self.model()[1]["rows"]
        first = rows[0]["ref"]
        key = rows[0]["candidates"][0]["key"]
        status, _body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions({first: "APPROVE:" + key}),
             "expected_revision": 0})
        self.assertEqual(status, 200)
        self.restart()
        _status, model = self.model()
        self.assertEqual(model["state"]["revision"], 1)
        self.assertEqual(model["state"]["counts"]["selected"], 1)

    def restart(self):
        """A real restart: new server, new store, same database files."""
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.store.close()
        self.server = board_mod.serve(port=0, with_worker=False, seed_demo=False)
        self.store = board_mod._active_store()
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER,
                                   role=access_control.ROLE_VIEWER)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        real_review.clear_real_review()


class NoSideEffectTests(ReviewTestCase):
    def test_the_operational_board_row_count_never_changes(self):
        before = self.board_row_count()
        rows = self.model()[1]["rows"]
        key = rows[0]["candidates"][0]["key"]
        status, _body = self.post(
            "/api/review/decisions",
            {"decisions": self.all_decisions(
                {rows[0]["ref"]: "APPROVE:" + key, rows[1]["ref"]: "REJECT"}),
             "expected_revision": 0})
        self.assertEqual(status, 200)
        status, _body = self.post("/api/review/export",
                                  {"decisions": self.all_decisions(
                                      {rows[0]["ref"]: "APPROVE:" + key})})
        self.assertEqual(status, 200)
        self.assertEqual(self.board_row_count(), before)
        self.assertEqual(board_mod.live_trips(), [])

    def test_the_sources_are_byte_identical_after_saving_and_exporting(self):
        before = {key: Path(self.manifest[key]).read_bytes()
                  for key in ("snapshot_path", "review_path", "master_path")}
        rows = self.model()[1]["rows"]
        key = rows[0]["candidates"][0]["key"]
        self.post("/api/review/decisions",
                  {"decisions": self.all_decisions({rows[0]["ref"]:
                                                    "APPROVE:" + key}),
                   "expected_revision": 0})
        self.post("/api/review/export", {"decisions": None})
        for name, digest in before.items():
            self.assertEqual(Path(self.manifest[name]).read_bytes(), digest,
                             f"{name} was rewritten")


class ExportTests(ReviewTestCase):
    def test_the_export_is_the_existing_core_contract(self):
        from webapp.review_context import build_review_context, build_review_export

        rows = self.model()[1]["rows"]
        key = rows[0]["candidates"][0]["key"]
        submitted = self.all_decisions({rows[0]["ref"]: "APPROVE:" + key,
                                        rows[1]["ref"]: "REJECT"})
        status, body = self.post("/api/review/export",
                                 {"decisions": submitted})
        self.assertEqual(status, 200)
        # the same three inputs and the same decisions, through the pure core
        snapshot = Path(self.manifest["snapshot_path"]).read_bytes()
        review = Path(self.manifest["review_path"]).read_text(encoding="utf-8")
        master = Path(self.manifest["master_path"]).read_text(encoding="utf-8")
        model = build_review_context(
            snapshot, review, master, self.manifest["snapshot_sha256"],
            self.manifest["review_sha256"], self.manifest["master_sha256"])
        expected = build_review_export(model, review, submitted)
        self.assertEqual(body["decision_csv"], expected["decision_csv"])
        self.assertEqual(json.loads(body["plan_json"]), expected["plan_json"])
        self.assertEqual(body["counts"], expected["counts"])
        self.assertEqual(body["plan_digest"], expected["plan_digest"])

    def test_the_export_says_it_imports_nothing(self):
        status, body = self.post("/api/review/export", {"decisions": None})
        self.assertEqual(status, 200)
        self.assertIs(body["imports_ledger_rows"], False)

    def test_an_export_of_saved_choices_uses_them(self):
        rows = self.model()[1]["rows"]
        key = rows[0]["candidates"][0]["key"]
        self.post("/api/review/decisions",
                  {"decisions": self.all_decisions({rows[0]["ref"]:
                                                        "APPROVE:" + key}),
                   "expected_revision": 0})
        status, saved_export = self.post("/api/review/export",
                                         {"decisions": None})
        self.assertEqual(status, 200)
        _status, on_screen = self.post("/api/review/export",
                                       {"decisions": self.all_decisions(
                                           {rows[0]["ref"]: "APPROVE:" + key})})
        self.assertEqual(saved_export["decision_csv"], on_screen["decision_csv"])

    def test_an_export_with_a_bad_decision_is_refused(self):
        decisions = self.all_decisions({})
        decisions[0] = {"ref": "합성시트!A999|G999 (row 999)", "value": "REJECT"}
        status, body = self.post("/api/review/export",
                                 {"decisions": decisions})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "DECISION_UNKNOWN_REF")


class CountsTests(ReviewTestCase):
    rows = 5

    def test_the_counts_add_up_to_the_total(self):
        _status, model = self.model()
        counts = model["state"]["counts"]
        self.assertEqual(counts["total"], self.rows)
        self.assertEqual(counts["selected"] + counts["held"] + counts["rejected"],
                         counts["total"])


class InsufficientEvidenceTests(ReviewTestCase):
    with_header = False

    def test_a_row_without_a_header_is_insufficient_and_cannot_be_approved(self):
        _status, model = self.model()
        first = model["rows"][0]
        self.assertEqual(first["source"]["evidence_status"], "insufficient")
        decisions = self.all_decisions(
            {first["ref"]: "APPROVE:" + first["candidates"][0]["key"]})
        status, body = self.post("/api/review/decisions",
                                 {"decisions": decisions,
                                  "expected_revision": 0})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INSUFFICIENT_EVIDENCE")
        _status, after = self.model()
        self.assertEqual(after["state"]["revision"], 0)

    def test_a_rejection_is_still_allowed_on_an_insufficient_row(self):
        first = self.model()[1]["rows"][0]
        decisions = self.all_decisions({first["ref"]: "REJECT"})
        status, _body = self.post("/api/review/decisions",
                                  {"decisions": decisions,
                                   "expected_revision": 0})
        self.assertEqual(status, 200)


class LiveSyncInteractionTests(ReviewTestCase):
    def test_the_two_second_sync_still_sees_a_saved_row(self):
        """The review is a second board; the board's own refresh still works."""
        self.store.create_trip(starts_on="2026-05-01", ends_on="2026-05-07",
                               destination="합성여행", display_key="2026-05 합성",
                               client_request_id="trip-sync")
        row = self.store.create_manual_expense(
            fields={"display_tab_id": board_mod.live_trips()[0]["tab_id"],
                    "occurred_on": "2026-05-02", "amount_krw": 4200,
                    "item": "동기화 확인", "pay_method": "현금"},
            client_request_id="sync-1")
        token = live_sync.owner_token(self.store,
                                      board_mod.live_trips()[0]["tab_id"])
        status, body = self.get(
            f"/api/live/state?tab={board_mod.live_trips()[0]['tab_id']}"
            f"&token={token}")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["changed"])
        # a decision save does not move the board's token
        self.post("/api/review/decisions",
                  {"decisions": self.all_decisions({}), "expected_revision": 0})
        _status, body = self.get(
            f"/api/live/state?tab={board_mod.live_trips()[0]['tab_id']}"
            f"&token={token}")
        self.assertFalse(json.loads(body)["changed"])
        self.assertEqual(self.store.get_row(row["row_id"])["item"],
                         "동기화 확인")


class NoSecretInLogsTests(ReviewTestCase):
    def test_a_refusal_carries_no_path_value_or_content(self):
        _status, model = self.model()
        decisions = self.all_decisions({})
        decisions[0] = {"ref": "없는 참조", "value": "REJECT"}
        _status, body = self.post("/api/review/decisions",
                                  {"decisions": decisions,
                                   "expected_revision": 0})
        raw = json.dumps(body, ensure_ascii=False)
        for leak in (self.manifest["snapshot_path"],
                     self.manifest["master_path"],
                     self.manifest["snapshot_sha256"],
                     fx.INJECTION, "합성이용점"):
            self.assertNotIn(leak, raw, f"the refusal carried {leak}")
