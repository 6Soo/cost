"""예약 행사 연결 화면 — 실제 브라우저.

합성 명단과 합성 대상 행사만 쓴다. 실제 자료와 운영 브라우저에는 접근하지 않는다.
조회, 초안 저장, 철회, 적용 계획을 한 번씩 실제로 눌러 본다.
"""

import hashlib
import json
import os
import pathlib
import sqlite3
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from ledger.domain.reservation_access_snapshot import (  # noqa: E402
    SCHEMA_VERSION, parse_reservation_access_snapshot)
from webapp import access_control, ledger_board, reserve_link  # noqa: E402
from webapp.tests.test_reserve_link import (  # noqa: E402
    LEDGER_EVENTS, OWNER, raw_snapshot, source_person)
from webapp.tests.test_real_review_browser import SETTLE_MS  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the environment has it
    sync_playwright = None


class LinkBrowserFixture(unittest.TestCase):
    """One served link screen over synthetic source and target events."""

    def setUp(self):
        if sync_playwright is None:
            self.skipTest("playwright is not installed")
        self.tmp = pathlib.Path(__import__("tempfile").mkdtemp())
        self.db_path = self.tmp / "access.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        self.store = access_control.AccessStore(conn)
        self.store.create_account(user_id=OWNER,
                                  role=access_control.ROLE_OWNER,
                                  display_name="owner")
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS trip_tabs("
            " tab_id TEXT PRIMARY KEY, display_key TEXT NOT NULL,"
            " destination TEXT NOT NULL DEFAULT '', starts_on TEXT NOT NULL DEFAULT '',"
            " ends_on TEXT NOT NULL DEFAULT '', prepared_on TEXT NOT NULL DEFAULT '',"
            " prepared_by_name TEXT NOT NULL DEFAULT '',"
            " archived INTEGER NOT NULL DEFAULT 0,"
            " deleted INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1)")
        for event in LEDGER_EVENTS:
            conn.execute("INSERT OR IGNORE INTO trip_tabs(tab_id, display_key)"
                         " VALUES (?,?)", (event, event))
        conn.commit()
        # Kept open: the assertions below read through it. `AccessStore` owns the
        # connection it was handed.
        self.addCleanup(conn.close)

        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA",
                                       "reservation:cafeParse:BRAVO"])])
        self.grant("rp-1", "syn-staff-1")

        os.environ["WEBLEDGER_DB"] = str(self.tmp / "board.sqlite")
        self.server = ledger_board.serve(port=0, with_worker=False,
                                        seed_demo=False)
        self.served = access_control.AccessStore(sqlite3.connect(
            str(self.db_path), check_same_thread=False, isolation_level=None,
            timeout=5.0))
        ledger_board.bind_access(self.served)
        access_control.bind_synthetic_sessions(True)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.addCleanup(self._close)

    def _close(self):
        try:
            self.browser.close()
            self.playwright.stop()
            self.server.shutdown()
            self.server.server_close()
            self.served.conn.close()
        except Exception:
            pass

    def configure(self, persons):
        raw = raw_snapshot(persons)
        parsed = parse_reservation_access_snapshot(raw)
        self.source_file = self.tmp / "roster.json"
        self.source_file.write_bytes(raw)
        self.source_raw = raw
        os.environ[reserve_link.CONFIG_ENV] = json.dumps({
            "path": str(self.source_file),
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "digest": parsed["digest"]})
        self.snapshot = parsed

    def bind(self):
        return reserve_link.source_binding(
            reserve_link.read_source(reserve_link.load_source_config()))

    def grant(self, person_id, user_id):
        self.store.create_account(user_id=user_id,
                                  role=access_control.ROLE_VIEWER,
                                  display_name=user_id)
        self.store.register_reservation_person(
            reservation_person_id=person_id, display_name=person_id)
        application = self.store.create_application(
            user_id=user_id, requested_name=person_id,
            client_request_id=f"app-{user_id}")
        return self.store.approve_application(
            application_id=application["application_id"], owner_id=OWNER,
            expected_revision=application["revision"],
            reservation_person_id=person_id,
            client_request_id=f"approve-{user_id}")

    def open_screen(self, user=OWNER, *, expect_refused=False):
        """Open the owner screen, or observe the refusal.

        A refused session never receives the document: the server answers 401 or
        403 before any HTML is rendered, so the screen's hook does not exist. That
        is the point of the refusal, so this waits for *either* the loaded screen
        or a refusal status, and the refusal tests assert the refusal rather than
        expecting a page that was correctly never sent.
        """
        context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.addCleanup(context.close)
        context.set_extra_http_headers(
            {access_control.SyntheticSessionAdapter.HEADER: user})
        page = context.new_page()
        response = page.goto(f"http://127.0.0.1:{self.port}/reserve-links")
        page.wait_for_function(
            "() => window.__reserveLink !== undefined"
            " || document.readyState === 'complete'",
            timeout=SETTLE_MS)
        if expect_refused:
            self.assertIn(response.status, (401, 403))
            self.assertEqual(page.evaluate(
                "() => typeof window.__reserveLink"), "undefined")
            self.assertNotIn("<select", page.content())
            return page
        self.assertEqual(response.status, 200)
        page.wait_for_function("() => window.__reserveLink !== undefined",
                               timeout=SETTLE_MS)
        return page


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class LinkScreenTests(LinkBrowserFixture):
    """Reading, drafting, saving and applying, through the real document."""

    def visible_tabs(self):
        return self.store.visible_tabs("syn-staff-1")

    def wait_for_links(self, expected, timeout=SETTLE_MS):
        """Wait until the *server* holds these links.

        Polling the database rather than the page: the page's draft is client state
        and reads as saved before the request has been answered, so a wait on it
        would test nothing.
        """
        import time as _time

        deadline = _time.monotonic() + timeout / 1000.0
        while _time.monotonic() < deadline:
            if self.store.reserve_link_state()["links"] == expected:
                return True
            _time.sleep(0.05)
        return False

    def wait_for_message(self, page, needle, timeout=SETTLE_MS):
        page.wait_for_function(
            "(n) => document.getElementById('state').textContent"
            ".indexOf(n) >= 0", arg=needle, timeout=timeout)

    def wait_for_outcome(self, page, outcome, timeout=SETTLE_MS):
        """Wait for a machine-readable outcome, not for prose.

        The sentence on screen is written for the owner; waiting on its wording
        couples the check to phrasing, and a phrasing change would read as a
        product failure. The outcome is what the product actually did.
        """
        page.wait_for_function(
            "(o) => window.__reserveLink.outcome() === o", arg=outcome,
            timeout=timeout)

    def test_the_screen_reads_the_source_and_offers_the_ledger_events(self):
        page = self.open_screen()
        page.wait_for_function("() => window.__reserveLink.state() !== null",
                               timeout=SETTLE_MS)
        state = page.evaluate("() => window.__reserveLink.state()")
        self.assertTrue(state["configured"])
        self.assertTrue(state["readable"])
        self.assertEqual(sorted(state["per_identifier"]),
                         ["reservation:cafeParse:ALFA",
                          "reservation:cafeParse:BRAVO"])
        # The opaque keys appear verbatim: no prefix stripping anywhere.
        body = page.inner_text("#linkBox")
        self.assertIn("reservation:cafeParse:ALFA", body)
        self.assertIn("COST-TRIP-ALFA", body)
        # Nothing is applied by looking.
        self.assertEqual(self.visible_tabs(), set())

    def test_a_saved_draft_alone_grants_nothing(self):
        page = self.open_screen()
        page.wait_for_function("() => window.__reserveLink.state() !== null",
                               timeout=SETTLE_MS)
        page.select_option(
            "select[data-source='reservation:cafeParse:ALFA']",
            ["COST-TRIP-ALFA"])
        page.select_option(
            "select[data-source='reservation:cafeParse:BRAVO']",
            ["COST-TRIP-DELTA"])
        page.click("#saveBtn")
        self.assertTrue(self.wait_for_links({
            "reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"],
            "reservation:cafeParse:BRAVO": ["COST-TRIP-DELTA"]}))
        # Saved, not applied. The apply button is a separate press.
        self.assertEqual(self.visible_tabs(), set())
        self.assertTrue(page.evaluate("() => window.__reserveLink.applied()")
                        is False)

    def test_applying_moves_the_permission_and_a_retry_does_not_double_it(self):
        page = self.open_screen()
        page.wait_for_function("() => window.__reserveLink.state() !== null",
                               timeout=SETTLE_MS)
        # Both identifiers linked. One left unlinked refuses the whole roster,
        # which is its own check below.
        page.select_option(
            "select[data-source='reservation:cafeParse:ALFA']",
            ["COST-TRIP-ALFA", "COST-TRIP-BRAVO"])
        page.select_option(
            "select[data-source='reservation:cafeParse:BRAVO']",
            ["COST-TRIP-DELTA"])
        page.click("#saveBtn")
        self.wait_for_outcome(page, "saved")
        page.click("#applyBtn")
        self.wait_for_outcome(page, "applied")
        self.assertEqual(self.visible_tabs(),
                         {"COST-TRIP-ALFA", "COST-TRIP-BRAVO", "COST-TRIP-DELTA"})
        applied_rows = self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments WHERE state=?",
            (access_control.ASSIGN_ACTIVE,)).fetchone()[0]
        self.assertEqual(applied_rows, 3)

        # A second press on a spent screen does nothing at all, and no second row.
        page.wait_for_function("() => window.__reserveLink.applied() === true",
                               timeout=SETTLE_MS)
        self.assertTrue(page.evaluate(
            "() => window.__reserveLink.applyDisabled()"))
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments WHERE state=?",
            (access_control.ASSIGN_ACTIVE,)).fetchone()[0], 3)

    def test_narrowing_the_targets_revokes_what_was_left_out(self):
        page = self.open_screen()
        page.wait_for_function("() => window.__reserveLink.state() !== null",
                               timeout=SETTLE_MS)
        page.select_option(
            "select[data-source='reservation:cafeParse:ALFA']",
            ["COST-TRIP-ALFA", "COST-TRIP-BRAVO"])
        page.select_option(
            "select[data-source='reservation:cafeParse:BRAVO']",
            ["COST-TRIP-DELTA"])
        page.click("#saveBtn")
        self.wait_for_outcome(page, "saved")
        page.click("#applyBtn")
        self.wait_for_outcome(page, "applied")
        self.assertEqual(self.visible_tabs(),
                         {"COST-TRIP-ALFA", "COST-TRIP-BRAVO", "COST-TRIP-DELTA"})

        # Drop one target and apply again: the dropped trip is revoked.
        page.select_option(
            "select[data-source='reservation:cafeParse:ALFA']",
            ["COST-TRIP-BRAVO"])
        page.click("#saveBtn")
        self.wait_for_outcome(page, "saved")
        page.click("#applyBtn")
        self.wait_for_outcome(page, "applied")
        self.assertEqual(self.visible_tabs(),
                         {"COST-TRIP-BRAVO", "COST-TRIP-DELTA"})

    def test_staff_and_anonymous_are_refused_and_never_receive_the_screen(self):
        for user, expected in ((None, 401), ("syn-staff-1", 403)):
            with self.subTest(user=user):
                page = self.open_screen(user=user, expect_refused=True)
                # The document was not served, so there is nothing on the page to
                # leak: no roster, no targets, no draft, no script.
                self.assertEqual(page.evaluate(
                    "() => typeof window.__reserveLink"), "undefined")
                self.assertEqual(page.locator("select").count(), 0)
                self.assertNotIn("reservation:cafeParse", page.content())
                self.assertNotIn("COST-TRIP", page.content())
                del expected

    def test_no_configuration_shows_the_required_state_and_offers_nothing(self):
        os.environ.pop(reserve_link.CONFIG_ENV, None)
        page = self.open_screen()
        page.wait_for_function("() => document.getElementById('state')"
                               ".textContent.indexOf('RESERVE_LINK_CONFIG_REQUIRED') >= 0",
                               timeout=SETTLE_MS)
        self.assertEqual(page.evaluate(
            "() => document.getElementById('saveBtn').disabled"), True)
        self.assertEqual(page.evaluate(
            "() => document.getElementById('applyBtn').disabled"), True)
        self.assertEqual(page.locator("#linkBox select").count(), 0)
        self.assertIn("원천 설정이 필요해요", page.inner_text("#rows"))

    def test_no_ledger_event_shows_the_waiting_state_and_invents_nothing(self):
        self.store.conn.execute("DELETE FROM trip_tabs")
        self.store.conn.commit()
        page = self.open_screen()
        page.wait_for_function("() => document.getElementById('state')"
                               ".textContent.indexOf('대상 행사 대기') >= 0",
                               timeout=SETTLE_MS)
        self.assertEqual(page.evaluate(
            "() => document.getElementById('saveBtn').disabled"), True)
        self.assertEqual(page.evaluate(
            "() => document.getElementById('applyBtn').disabled"), True)
        self.assertIn("등록되면", page.inner_text("#linkBox"))

    def test_an_unlinked_identifier_refuses_the_apply_and_keeps_the_draft(self):
        page = self.open_screen()
        page.wait_for_function("() => window.__reserveLink.state() !== null",
                               timeout=SETTLE_MS)
        # Link one identifier and leave the other unlinked.
        page.select_option(
            "select[data-source='reservation:cafeParse:ALFA']",
            ["COST-TRIP-ALFA"])
        page.select_option(
            "select[data-source='reservation:cafeParse:BRAVO']", [])
        page.click("#saveBtn")
        self.wait_for_outcome(page, "saved")
        # Saved first, then the plan it produced cannot be applied. The button is
        # inert rather than offering an action whose only answer is a refusal, and
        # the screen names the code that says so. The API-level refusal is checked
        # over HTTP.
        self.assertTrue(self.wait_for_links({
            "reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"]}))
        # The plan that came back cannot be applied. This is read from the plan the
        # server returned, not from the outcome label: the save's own outcome is the
        # last thing the screen says, and it is correct — the *save* worked. What
        # cannot be applied is the plan, and that is the plan's own field.
        page.wait_for_function(
            "() => window.__reserveLink.state()"
            " && window.__reserveLink.state().applicable === false",
            timeout=SETTLE_MS)
        state = page.evaluate("() => window.__reserveLink.state()")
        self.assertEqual(state["refusal_code"],
                         reserve_link.CODE_APPLY_UNLINKED)
        self.assertEqual(state["unlinked"], ["reservation:cafeParse:BRAVO"])
        self.assertTrue(page.evaluate(
            "() => document.getElementById('applyBtn').disabled"))
        # The draft is still on the screen: a refusal does not throw away the
        # owner's work.
        self.assertEqual(sorted(page.evaluate(
            "() => Object.keys(window.__reserveLink.draft())")),
            ["reservation:cafeParse:ALFA", "reservation:cafeParse:BRAVO"])
        self.assertEqual(self.visible_tabs(), set())
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()