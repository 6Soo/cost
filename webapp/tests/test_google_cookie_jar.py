"""GOOGLE-COOKIE-JAR-001: one cookie, one identity, whatever container holds it.

An owner signed in through Google could open `/reserve-links` and see the owner
screen, while `/board` rendered as a viewer: no owner controls, no `+ 탭 추가`,
and `data-role` reading `읽기 전용`. The same request, the same session, two
different roles on one page.

The cause is a representation bug that reads like an authentication bug.
`Handler._cookies()` returns `http.cookies.SimpleCookie`, which is a dict of
`Morsel` — not a dict of strings. `google_oidc._read_cookie` returned
`cookies.get(name)` unchanged, so a `Morsel` went into `SessionSigner.verify`,
which is not a string, and verification returned `None`. A valid signature read
as no session.

That is why it was missed. Every other caller passed a plain dict or read the raw
`Cookie` header, both of which produce a string and both of which kept working.
The gates passed because they re-read the raw header, while the renderer used the
parsed jar, so one request could clear one gate and fail another.

These tests drive the real `Handler` over a real HTTP connection with a real
`SimpleCookie`, not a synthetic header shortcut, because a synthetic header is
the exact path that was never broken. They assert:

* an owner's `/board` carries the owner controls and is not marked read-only;
* a viewer is shown none of them, and both requests reach the server as one real
  cookie each;
* the write path resolves the same owner through the same parsed jar, so a save
  is not refused by an empty owner id;
* and every existing fence still refuses — expired, tampered, wrong generation,
  wrong secret, unsigned, wrong subject, unknown account.

No real identity, network, credential, or production cookie is used. The
signing secret is a literal in this file and the accounts are synthetic.
"""

from __future__ import annotations

import http.cookies
import json
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webapp import access_control, google_oidc, ledger_board  # noqa: E402
from webapp.tests import test_google_oidc as fixtures  # noqa: E402

OWNER = fixtures.OWNER_SUB
VIEWER = fixtures.STAFF_SUB
#: The signing secret is the existing synthetic fixture's literal. Reusing it
#: keeps one secret in the suite, and a real one is never present here.
FAKE_SECRET = fixtures.FAKE_SESSION_SECRET

#: The owner-only controls that are absent from a viewer board. Listed by id
#: because an id is what the markup binds to, not the wording. The wave3 shell
#: rebuild (8cd0e58b) replaced the old reserve-link/add-trip header controls with
#: the owner-only "더보기" dialog and the manual-expense toolbar button.
OWNER_MARKERS = ("id='site-more-dialog'", "id='add-manual-expense'")
READ_ONLY_MARKER = "data-role='읽기 전용'"


class JarFixture(unittest.TestCase):
    """One served board, reached with a real parsed cookie jar."""

    def setUp(self):
        import os
        import sqlite3
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        # One connection, opened with `check_same_thread=False`, because the
        # adapter the server calls lives on the serving thread while the fixture
        # seeds it from this one. Two connections would be two answers to the
        # same question; this is the same shape the existing server fixtures use.
        self.conn = sqlite3.connect(str(self.tmp / "access.sqlite"),
                                    check_same_thread=False,
                                    isolation_level=None, timeout=5.0)
        self.store = access_control.AccessStore(self.conn)
        self.addCleanup(self.conn.close)
        self.store.create_account(user_id=OWNER, role=access_control.ROLE_OWNER,
                                  display_name="owner")
        self.store.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER,
                                  display_name="viewer")
        # The ledger schema the board's own queries read, created here because
        # this fixture seeds the board from an empty file. The owner pages list
        # trips, and without the table the handler answers 500 — which is a
        # fixture gap, not the behaviour under test.
        self.conn.executescript(
            "CREATE TABLE IF NOT EXISTS trip_tabs("
            " tab_id TEXT PRIMARY KEY, display_key TEXT NOT NULL,"
            " destination TEXT NOT NULL DEFAULT '',"
            " starts_on TEXT NOT NULL DEFAULT '',"
            " ends_on TEXT NOT NULL DEFAULT '',"
            " prepared_on TEXT NOT NULL DEFAULT '',"
            " prepared_by_name TEXT NOT NULL DEFAULT '',"
            " archived INTEGER NOT NULL DEFAULT 0,"
            " deleted INTEGER NOT NULL DEFAULT 0,"
            " revision INTEGER NOT NULL DEFAULT 1)")
        self.conn.commit()

        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(self.tmp / "board.sqlite")

        self.server = ledger_board.serve(port=0, with_worker=False, seed_demo=False)
        ledger_board.bind_access(self.store)
        # The synthetic-header adapter must be off: these tests exist to prove
        # the real cookie works, and a synthetic header would answer instead.
        access_control.bind_synthetic_sessions(False)
        self.flow = fixtures.make_flow(self.store)
        ledger_board.bind_oidc(self.flow)
        self.port = self.server.server_address[1]
        import threading
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        import os

        self.server.shutdown()
        self.server.server_close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def signed(self, subject=OWNER, *, secret=FAKE_SECRET, exp_delta=600,
               generation=None, **extra):
        payload = {
            "sub": subject,
            "exp": int(time.time()) + exp_delta,
            "gen": (self.store.session_generation(subject)
                    if generation is None else generation),
        }
        payload.update(extra)
        return google_oidc.SessionSigner(secret).sign(payload)

    def jar_for(self, value):
        """A real parsed jar, the way `Handler._cookies()` builds one."""
        jar = http.cookies.SimpleCookie()
        jar.load(google_oidc.COOKIE_NAME + "=" + value)
        return jar

    def get(self, path, cookie_value, *, raw=False):
        """One real GET, carrying the cookie as the browser would."""
        url = f"http://127.0.0.1:{self.port}{path}"
        headers = {}
        if cookie_value:
            headers["Cookie"] = (google_oidc.COOKIE_NAME + "="
                                 + (cookie_value if raw else _quote(cookie_value)))
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def csrf(self, cookie_value):
        """The token as the screen received it.

        It arrives as a substituted placeholder in the document's own script,
        not in a form field, so it is read from where it actually is rather than
        from a form this screen does not have.
        """
        status, body = self.get("/reserve-links", cookie_value)
        self.assertEqual(status, 200, "the linking screen refused the owner")
        marker = 'var csrfToken = "'
        start = body.index(marker) + len(marker)
        return body[start:body.index('"', start)]

    def post(self, path, cookie_value, payload, *, origin_ok=True, token=None):
        """One real POST, so the jar is parsed by the server, not supplied here."""
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Cookie": google_oidc.COOKIE_NAME + "=" + cookie_value,
        }
        if origin_ok:
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
            # A refused caller never receives a token, so the token is fetched
            # once as the owner and replayed by whoever the write is made as.
            headers["X-CSRF-Token"] = (
                token if token is not None else self.csrf(cookie_value))
        request = urllib.request.Request(url, data=body, headers=headers,
                                         method="POST")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")


def _quote(value):
    return value


class RepresentationTests(JarFixture):
    """One cookie, one identity, in every shape the caller may hand over."""

    def test_a_parsed_jar_resolves_the_same_session_as_a_raw_header(self):
        value = self.signed()
        headers = {"Cookie": google_oidc.COOKIE_NAME + "=" + value}
        from_jar = self.flow.adapter.session_for(headers, self.jar_for(value))
        from_dict = self.flow.adapter.session_for(
            headers, {google_oidc.COOKIE_NAME: value})
        from_raw = self.flow.adapter.session_for(headers, None)
        self.assertIsNotNone(from_jar)
        for other in (from_dict, from_raw):
            self.assertIsNotNone(other)
            # `Session` carries no role; the account table does. So the subject
            # and the generation are what must agree, and the role is asserted
            # where it is actually decided: on the served page.
            self.assertEqual(from_jar.user_id, other.user_id)
            self.assertEqual(from_jar.session_generation,
                             other.session_generation)
            self.assertEqual(from_jar.is_synthetic, other.is_synthetic)

    def test_the_value_taken_from_a_morsel_is_the_signed_string(self):
        """The fix is where it claims to be: `.value`, and only `.value`.

        A `Morsel` carries the decoded value plus attributes. Reading `.value` is
        what makes the parsed-jar path agree with the raw-header path, and
        reading anything else would let the attributes into the verifier.
        """
        morsel = self.jar_for(self.signed())[google_oidc.COOKIE_NAME]
        self.assertIsInstance(morsel, http.cookies.Morsel)
        read = google_oidc._read_cookie({}, self.jar_for(self.signed()),
                                        google_oidc.COOKIE_NAME)
        self.assertIsInstance(read, str)
        self.assertEqual(read, morsel.value)
        # And it is the same string the raw header yields, not a variant.
        headers = {"Cookie": google_oidc.COOKIE_NAME + "=" + morsel.value}
        self.assertEqual(
            read,
            google_oidc._read_cookie(headers, None, google_oidc.COOKIE_NAME))


class HandlerRoleTests(JarFixture):
    """The real board, over a real cookie, for both roles."""

    def board(self, subject):
        status, body = self.get(f"/board?tab=unclassified", self.signed(subject))
        self.assertEqual(status, 200, body[:400])
        return body

    def test_an_owner_board_shows_the_owner_controls(self):
        """The failure this fixes, asserted as a page rather than a session.

        The session resolved correctly and the gates passed; what was wrong was
        the rendered role. So the check is the markup an owner sees.
        """
        body = self.board(OWNER)
        self.assertIn("id='site-more-dialog'", body)
        self.assertIn("id='add-manual-expense'", body)
        self.assertNotIn(READ_ONLY_MARKER, body)

    def test_a_viewer_board_shows_none_of_them(self):
        """No `tab` is asked for, because a viewer's tab list is separate.

        A viewer's rail is built from its own allowlist and `/board?tab=…` runs
        the tab permission check, which is a different subject with its own
        fixture. What matters here is only that the owner controls are absent
        from what a viewer is served.
        """
        status, body = self.get("/board", self.signed(VIEWER))
        self.assertEqual(status, 200, body[:400])
        for marker in OWNER_MARKERS:
            self.assertNotIn(marker, body)

    def test_one_request_resolves_one_role_everywhere_in_it(self):
        """The gate and the renderer must not disagree.

        This is the actual defect: one request, two roles. So the same response
        is asked whether its own gate thought it was an owner.
        """
        status, me = self.get("/access/me", self.signed(OWNER))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(me)["role"], "owner")
        body = self.board(OWNER)
        self.assertIn('"role": "owner"', body)  # the live-config the page runs on
        self.assertNotIn(READ_ONLY_MARKER, body)

    def test_the_owner_control_does_not_depend_on_the_url_shape(self):
        """Unclassified is the quietest board; a trip board must agree."""
        _status, body = self.get("/board", self.signed(OWNER))
        self.assertIn("id='site-more-dialog'", body)


class WritePathTests(JarFixture):
    """The write path resolves its owner through the same parsed jar.

    `_reserve_owner_id` calls `current_session(self.headers, self._cookies())`,
    so it reads the same jar that made the read path wrong. If the jar were
    still mishandled, the owner id would be empty and the save refused.

    So these save real links against a real synthetic roster and a real target,
    and read the owner back out of the store's own record. A refusal for a
    missing source configuration would prove nothing here: that refusal happens
    before the owner id is ever used, so it would pass whether the id was correct
    or empty.
    """

    #: One opaque source key. Prefixed on purpose: the parser must not strip it.
    SOURCE_KEY = "reservation:cafeParse:ALFA"
    TARGET = "COST-TRIP-ALFA"

    def setUp(self):
        super().setUp()
        import os

        from webapp import reserve_link
        from webapp.tests.test_reserve_link import raw_snapshot, source_person

        self.tmp.mkdir(exist_ok=True)
        self.source_file = self.tmp / "roster.json"
        raw = raw_snapshot([source_person("rp-1", "owner",
                                          [self.SOURCE_KEY])])
        self.source_file.write_bytes(raw)
        # The real parser, so the digest and the identifiers are the ones the
        # product itself would produce from this file.
        from ledger.domain.reservation_access_snapshot import (
            parse_reservation_access_snapshot)
        parsed = parse_reservation_access_snapshot(raw)
        os.environ[reserve_link.CONFIG_ENV] = json.dumps({
            "path": str(self.source_file),
            "file_sha256": __import__("hashlib").sha256(raw).hexdigest(),
            "digest": parsed["digest"]})
        self.addCleanup(lambda: os.environ.pop(reserve_link.CONFIG_ENV, None))
        self.conn.execute(
            "INSERT OR IGNORE INTO trip_tabs(tab_id, display_key) VALUES (?,?)",
            (self.TARGET, self.TARGET))
        self.conn.commit()

    def owner_csrf(self):
        return self.csrf(self.signed(OWNER))

    def save_payload(self, token, request_id="jar-save-1"):
        """A `save_links` request built to the product's own contract."""
        state = self.link_state()
        return {
            "csrf": token,
            "request_id": request_id,
            "source_binding": self.binding(),
            "link_revision": state["revision"],
            "links": [{"source_event_key": self.SOURCE_KEY,
                       "target_tab_id": self.TARGET}],
            "unlinks": [],
        }

    def link_state(self):
        return self.store.reserve_link_state()

    def link_rows(self):
        """The saved links, read straight from the table.

        `reserve_event_links.linked_by` is the column that records who saved a
        link, so it is the evidence that the owner id resolved on the write path.
        """
        columns = [row[1] for row in self.conn.execute(
            "PRAGMA table_info(reserve_event_links)")]
        rows = self.conn.execute(
            "SELECT * FROM reserve_event_links ORDER BY rowid").fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def binding(self):
        from webapp import reserve_link
        return reserve_link.source_binding(
            reserve_link.read_source(reserve_link.load_source_config()))

    def test_a_save_through_the_parsed_cookie_records_the_signed_owner(self):
        """The proof that `_reserve_owner_id` resolved, over real HTTP.

        The link is saved and the account that saved it is the Google subject of
        the cookie. An empty owner id cannot save a link at all, so the recorded
        `linked_by` is itself the evidence — no synthetic header, no shortcut.
        """
        token = self.owner_csrf()
        status, answer = self.post("/api/reserve-link/links", self.signed(OWNER),
                                   self.save_payload(token), token=token)
        self.assertEqual(status, 200, answer[:600])
        result = json.loads(answer)
        self.assertEqual(result["linked"], [{"source_event_key": self.SOURCE_KEY,
                                             "target_tab_id": self.TARGET}])

        state = self.link_state()
        # `links` is a map of one source key to every target it names, which is
        # what lets one source own several ledger events.
        self.assertEqual(state["links"],
                         {self.SOURCE_KEY: [self.TARGET]})
        rows = self.link_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["linked_by"], OWNER)
        self.assertNotEqual(rows[0]["linked_by"], "")
        self.assertNotIn("syn", rows[0]["linked_by"])

    def test_the_link_revision_moved_so_a_later_apply_is_not_a_silent_no_op(self):
        """The save bumped the link version, as the owner contract requires.

        Checked here because this is the write the cookie authorises, so it is
        the write that has to carry its consequences.
        """
        before = self.link_state()["revision"]
        token = self.owner_csrf()
        self.post("/api/reserve-link/links", self.signed(OWNER),
                  self.save_payload(token), token=token)
        self.assertGreater(self.link_state()["revision"], before)

    def test_the_opaque_source_key_survives_the_cookie_round_trip(self):
        """The prefix is not stripped anywhere along this path."""
        token = self.owner_csrf()
        status, _answer = self.post("/api/reserve-link/links", self.signed(OWNER),
                                    self.save_payload(token), token=token)
        self.assertEqual(status, 200)
        stored = self.link_rows()[0]["source_event_key"]
        self.assertEqual(stored, self.SOURCE_KEY)
        self.assertTrue(stored.startswith("reservation:"))

    def test_a_viewer_save_is_refused_before_the_source_is_even_read(self):
        token = self.owner_csrf()
        status, answer = self.post("/api/reserve-link/links", self.signed(VIEWER),
                                   self.save_payload(token, "jar-save-v"),
                                   token=token)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(answer)["code"], "ACTION_FORBIDDEN")
        # And nothing was written by the refused request.
        self.assertEqual(self.link_rows(), [])


class FenceTests(JarFixture):
    """Every fence that was already there must still refuse.

    Taking `.value` must not loosen anything: a `Morsel` carries the same signed
    bytes the raw header would have produced, so the signature, expiry and
    generation checks run on identical input.
    """

    def assert_refused(self, value, why):
        for representation in (self.jar_for(value),
                               {google_oidc.COOKIE_NAME: value}):
            with self.subTest(why=why,
                              shape=type(representation).__name__):
                session = self.flow.adapter.session_for({}, representation)
                self.assertIsNone(session, f"{why} was accepted")
        status, _body = self.get("/board", value)
        self.assertEqual(status, 401, f"{why} was served a board")

    def test_an_expired_cookie_is_refused(self):
        self.assert_refused(self.signed(exp_delta=-5), "expired")

    def test_a_tampered_cookie_is_refused(self):
        self.assert_refused(self.signed() + "tampered", "tampered")

    def test_a_stale_generation_is_refused(self):
        """A revoked session: the generation moved past the one in the cookie."""
        current = self.store.session_generation(OWNER)
        self.assert_refused(self.signed(generation=current - 1), "stale generation")

    def test_a_cookie_signed_with_another_secret_is_refused(self):
        """Another signing key must not produce a session.

        The wrong secret has to be strong enough to be *accepted as a key* and
        still fail the signature check, or this would be testing the key
        strength rule twice instead of the signature.
        """
        other = "Qb3Tz9Xp5Lr1Kv7Wm4Nc8Sd2Fg6Hj0Ya1Ub5Xe9Ic3Po"
        self.assertNotEqual(other, FAKE_SECRET)
        self.assert_refused(self.signed(secret=other), "wrong secret")

    def test_a_cookie_with_no_signature_is_refused(self):
        import json as _json

        forged = _json.dumps({"sub": OWNER, "exp": int(time.time()) + 600,
                              "gen": self.store.session_generation(OWNER)})
        self.assert_refused(forged, "unsigned")

    def test_a_cookie_for_an_unknown_account_is_refused(self):
        self.assert_refused(self.signed(subject="sub-nobody"), "unknown subject")

    def test_an_absent_cookie_is_refused(self):
        status, _body = self.get("/board", "")
        self.assertEqual(status, 401)

    def test_a_cookie_naming_another_cookie_is_not_read_as_this_one(self):
        jar = http.cookies.SimpleCookie()
        jar.load("unrelated=" + self.signed())
        self.assertIsNone(self.flow.adapter.session_for({}, jar))
        self.assertEqual(google_oidc._read_cookie({}, jar, google_oidc.COOKIE_NAME),
                         "")

    def test_a_morsel_with_a_blank_value_reads_as_absent(self):
        """A present cookie with an empty value is not a session.

        `_cookie_value` must not turn a blank into something truthy, or a cleared
        cookie would read as a malformed-but-present one instead of absent.
        """
        jar = http.cookies.SimpleCookie()
        jar[google_oidc.COOKIE_NAME] = ""
        self.assertEqual(
            google_oidc._read_cookie({}, jar, google_oidc.COOKIE_NAME), "")


class ReadCookieShapeTests(unittest.TestCase):
    """`_read_cookie` accepts every container it may be handed."""

    def test_a_plain_string_is_returned_unchanged(self):
        self.assertEqual(
            google_oidc._read_cookie({}, {"c": "abc"}, "c"), "abc")

    def test_a_morsel_is_reduced_to_its_value(self):
        jar = http.cookies.SimpleCookie()
        jar.load("c=abc")
        self.assertEqual(google_oidc._read_cookie({}, jar, "c"), "abc")

    def test_a_missing_name_is_empty_in_every_shape(self):
        jar = http.cookies.SimpleCookie()
        jar.load("other=abc")
        for cookies in (None, {}, jar):
            self.assertEqual(
                google_oidc._read_cookie({}, cookies, "c"), "")

    def test_a_non_mapping_container_falls_through_to_the_header(self):
        """An object with no usable `.get` must not raise.

        The header is the second source, so a caller that passes something
        unexpected still gets the real cookie from the raw header rather than a
        `TypeError` out of the session lookup.
        """
        headers = {"Cookie": "c=from-header"}
        self.assertEqual(
            google_oidc._read_cookie(headers, object(), "c"), "from-header")

    def test_a_quoted_header_value_is_unwrapped(self):
        headers = {"Cookie": 'c="quoted"'}
        self.assertEqual(google_oidc._read_cookie(headers, None, "c"), "quoted")


class RejectedShapeTests(unittest.TestCase):
    """Only a `Morsel` and a `str` are supported; the rest read as absent.

    The contract names those two shapes because they are the only two a caller
    can produce. Anything else being *coerced* would be a different contract:
    it would accept a container this code never builds and hand its text to the
    verifier. Reading those as absent keeps the boundary where it is.
    """

    class _Duck:
        """Carries a `.value`, but is not a Morsel."""

        def __init__(self, value):
            self.value = value

    def test_an_object_with_a_value_attribute_is_not_accepted(self):
        """The shape that duck-typing would have accepted, and must not."""
        found = self._Duck("looks-like-a-session-value")
        self.assertEqual(google_oidc._cookie_value(found), "")

    def test_an_integer_or_none_is_not_coerced_to_a_string(self):
        for value in (0, 1, None, True, ["a"], {"a": 1}, b"bytes"):
            with self.subTest(value=value):
                self.assertEqual(google_oidc._cookie_value(value), "")

    def test_a_morsel_is_accepted(self):
        jar = http.cookies.SimpleCookie()
        jar.load("c=the-signed-value")
        found = jar["c"]
        self.assertIsInstance(found, http.cookies.Morsel)
        self.assertEqual(google_oidc._cookie_value(found), "the-signed-value")

    def test_a_string_is_returned_unchanged(self):
        self.assertEqual(google_oidc._cookie_value("plain"), "plain")

    def test_a_rejected_shape_does_not_stop_the_header_being_read(self):
        """Absent from the jar still means the raw header is consulted.

        Rejecting an unknown shape must not turn into refusing a request that
        carries a perfectly good cookie in its header.
        """
        headers = {"Cookie": "c=from-header"}
        self.assertEqual(
            google_oidc._read_cookie(headers, {"c": self._Duck("x")}, "c"),
            "from-header")


if __name__ == "__main__":
    unittest.main()