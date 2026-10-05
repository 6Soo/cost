"""Two real browser pages, one real server: does a save in one show up in the other?

This is the behavioural half of the cross-screen refresh. `test_live_sync.py`
covers the server: the token, its scope, its refusals. This file covers the
promise a user actually makes about the product: save in one browser, look at the
other one, and the row, the totals and the trip rail are already right.

Every test here drives two Chromium pages against one running `ledger_board`
server over real HTTP. Nothing is asserted by reading the source of the script:
each test waits for the screen to change and reads the rendered DOM, because a
script that is present but never runs, or runs against a region that is not the
one on screen, would pass a source check and fail a user.

The two pages are the point. A single page cannot show a refresh at all, because
it has nothing new to notice. Two pages against the same server is the smallest
thing that can show one.

Synthetic accounts only: `syn-owner-O` is the owner on both pages, and
`syn-staff-V1` / `syn-staff-V2` are the viewers. No real Google login, no
customer data, and no database file from a deployment is used here.

The interval is the production one (about two seconds), so each wait is a real
wait rather than a shortened one. A refresh that only worked at a 50 ms interval
would be a refresh that does not work.
"""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp import live_sync
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-O"
V1 = "syn-staff-V1"
V2 = "syn-staff-V2"
TRIP_A = "trip-demo-a"
TRIP_B = "trip-demo-b"
ROW_A = "expense-demo-c1"
ROW_A2 = "expense-demo-c2"
# The screen is allowed to be up to `live_sync.POLL_INTERVAL_MS` late, and the
# contract is about five seconds. The wait allows a little more than the contract
# so a slow machine fails the test instead of passing it by luck.
SETTLE_SECONDS = live_sync.POLL_INTERVAL_MS / 1000.0 + 5.0


class TwoPageBoardTests(unittest.TestCase):
    """The fixture: one server, one store, one access store, two pages."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "live-browser.sqlite")
        self._start_server()
        self.seed()
        self._pw = None
        self._browser = None
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            try:
                page.close()
            except Exception:  # noqa: BLE001 - a closed page is not a failure
                pass
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self._stop_server()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def _start_server(self):
        self.store = LedgerStore(os.environ["WEBLEDGER_DB"])
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)

    def _stop_server(self):
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()

    def _hold_saves(self):
        """A gate that stalls this browser's own save answer until released.

        The guard is supposed to hold the screen still while a save is on the wire.
        A save that answers instantly never gives the refresh a chance to arrive in
        the middle of one, so a test that only clicks save proves the guard works
        when there was nothing to guard against.

        The request is captured and *not* answered, rather than answered late from
        inside the handler. Playwright runs a route handler on the driver's own
        thread, so a handler that sleeps there also stops the test from observing
        the page — the very window this needs to look at. Leaving the request
        un-answered stalls it in the browser while the test stays in control, and
        `release()` lets it finish when the test says so.
        """
        held: list = []

        def handler(route):
            held.append(route)

        def release():
            # A test that fails while a request is held must not leave the
            # cleanup answering it: the page is being torn down, and continuing a
            # route on a closed browser raises out of the cleanup and hides the
            # real failure.
            for route in list(held):
                try:
                    route.continue_()
                except Exception:  # noqa: BLE001 - the page is already gone
                    pass
            held.clear()

        self.addCleanup(release)
        return handler, release

    def _slow_state_route(self, route):
        """Every state-endpoint request is delayed a little.

        Used where the question is about requests overlapping. A delay long enough
        to be visible and short enough not to eat the test's own time budget.
        """
        time.sleep(0.35)
        route.continue_()

    def _wait_for_held(self, page, held, message, timeout=SETTLE_SECONDS):
        """Wait until the page has a fragment fetch in flight.

        The page is asked something on every pass as well as being waited on. An
        intercepted request is only handed to this test once the driver is pumping,
        and `wait_for_timeout` on its own does not reliably get there: the fragment
        arrives late, or not at all, and the test then reports a fetch that never
        happened when the request was simply still queued behind the driver. A round
        trip to the page pumps the driver, so the handler runs and `held` fills.
        """
        deadline = time.time() + timeout
        while time.time() < deadline and not held:
            page.evaluate("1")
            page.wait_for_timeout(50)
        self.assertTrue(held, message)

    def _is_fragment_request(self, route) -> bool:
        """Is this the fragment fetch rather than the token poll?

        The two go to the same URL and differ only by the part header, so a route
        that cannot tell them apart would hold or fail both. Playwright reports
        header names in lower case, which is the detail that makes this check easy
        to get wrong.
        """
        return "x-part" in {str(name).lower()
                            for name in route.request.headers}

    def seed(self):
        self.access.ensure_owner(OWNER)
        for user in (V1, V2):
            self.access.create_account(user_id=user,
                                       role=access_control.ROLE_VIEWER)
        for index, (user, tab, person) in enumerate((
                (V1, TRIP_A, "rp-br-1"), (V2, TRIP_B, "rp-br-2")), start=1):
            self.access.register_reservation_person(
                reservation_person_id=person,
                display_name=f"합성 담당자 {index}")
            application = self.access.create_application(
                user_id=user, requested_name=f"합성 담당자 {index}",
                nickname=f"담당 {index}", description="합성 링크",
                client_request_id=f"app-br-{index}")
            self.access.approve_application(
                application_id=application["application_id"], owner_id=OWNER,
                expected_revision=1, reservation_person_id=person,
                client_request_id=f"dec-br-{index}")
            self.access.apply_assignment_snapshot(
                user_id=user,
                items=[{"tab_id": tab, "snapshot_revision": 1,
                        "state": access_control.ASSIGN_ACTIVE}],
                source_version="src-br", complete=False)

    # ------------------------------------------------------------- browser
    def _open(self, query="", user=OWNER, width=1440, height=900):
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
        context = self._browser.new_context(
            viewport={"width": width, "height": height})
        # The synthetic session is a request header, which is the test seam the
        # access store already provides. It selects an account that must exist
        # with a role; it is not a credential, and the server still decides the
        # role from the account every request.
        context.set_extra_http_headers(
            {access_control.SyntheticSessionAdapter.HEADER: user})
        page = context.new_page()

        def answer(dialog):
            # `beforeunload` is the native leave-confirm Playwright does not
            # answer on its own, and `confirm` is the Escape guard asking whether
            # to drop an unsaved edit. Both are answered the way a user pressing
            # the button would, so a test that cancels a draft is not blocked by a
            # dialog nobody answered.
            dialog.accept()
        page.on("dialog", answer)
        self.pages.append(page)
        page.goto(f"http://127.0.0.1:{self.port}/board{query}")
        # `attached`, not `visible`: the config is a JSON script element, which is
        # never rendered. What matters is that it is in the document, because that
        # is what the refresh script reads.
        page.wait_for_selector("#live-config", state="attached")
        return page

    def _save_through_the_api(self, row_id, user=OWNER, **changes):
        """A save from outside the browser, as another machine would make it.

        The point of the feature is that the watching page was not involved in
        the save at all, so the save is made over HTTP rather than by driving
        another page's form. It is a real save through the real endpoint; it just
        isolates the change from any UI state on the watching page.
        """
        row = self.store.get_row(row_id)
        self.assertIsNotNone(row, row_id)
        payload = {"csrf": board_mod.CSRF_TOKEN,
                   "expected_revision": row["revision"],
                   "client_request_id": f"browser-{row_id}-{time.time_ns()}",
                   "change_mode": "exception"}
        payload.update(changes)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/rows/{row_id}/save",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     access_control.SyntheticSessionAdapter.HEADER: user},
            method="POST")
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    # ------------------------------------------------------------- waiting
    def _wait_for(self, page, expression, message, timeout=SETTLE_SECONDS):
        """Wait for a rendered condition, and fail with the DOM if it never comes.

        Polling the live DOM rather than sleeping a fixed time is what makes this
        a test of the feature: a page that never refreshes has to fail here, and
        a page that refreshes slowly still passes without the wait being tuned to
        whichever it happened to be.
        """
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = page.evaluate(expression)
            if last:
                return last
            page.wait_for_timeout(100)
        summary = page.evaluate(
            "(document.getElementById('live-sum')||{}).innerText")
        notice = page.evaluate(
            "(document.getElementById('live-status')||{}).textContent")
        rows = page.evaluate(
            "(document.getElementById('live-rows')||{}).innerText")
        self.fail(f"{message}\n"
                  f"  마지막 확인 값: {last!r}\n"
                  f"  합계: {summary!r}\n"
                  f"  상태 안내: {notice!r}\n"
                  f"  행 목록: {(rows or '')[:400]!r}")

    def _row_text(self, page, row_id=ROW_A):
        return page.evaluate(
            "(id) => { const r = document.querySelector"
            "(\"tr[data-id='\" + id + \"']\");"
            " return r ? r.innerText : ''; }", row_id)

    def _rail(self, page):
        return page.evaluate(
            "document.getElementById('live-nav').innerText")

    def _rail_entry(self, page, display_key):
        """One trip's rail entry as rendered: its name and its income badge.

        Read from the rail rather than from the page source, so this is what a
        user is looking at.
        """
        return page.evaluate(
            "(key) => { const all = Array.from("
            "document.querySelectorAll('#live-nav .nv'));"
            " const hit = all.filter(a => a.innerText.indexOf(key) >= 0)[0];"
            " return hit ? hit.innerText : ''; }", display_key)

    def _summary(self, page):
        return page.evaluate(
            "document.getElementById('live-sum').innerText")

    # ---------------------------------------------------------- the promise
    def test_a_save_in_one_browser_is_in_the_other_within_the_budget(self):
        """The core promise, end to end, on two real pages.

        The watching page is never touched after it loads: no reload, no click, no
        scripted call into the refresh. If the row and the totals are right, the
        refresh found the change by itself.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        before_row = self._row_text(watcher)
        self.assertNotIn("브라우저 B에서 본 값", before_row)

        self._save_through_the_api(ROW_A, description="브라우저 B에서 본 값")

        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('브라우저 B에서 본 값')",
            "the watching page did not pick up a save made elsewhere")
        self.assertIn("브라우저 B에서 본 값", self._row_text(watcher))
        # the page refreshed rather than reloaded: a reload would have replaced
        # the document, and a document identity check is what tells the two apart
        self.assertEqual(
            watcher.evaluate("document.getElementById('live-rows')"
                             ".closest('.app') !== null"), True)

    def _region_counts(self, page):
        # Hyphenated ids need quoting in a JavaScript object literal, so the keys
        # are quoted rather than bare.
        return page.evaluate(
            "({'live-nav': document.querySelectorAll('#live-nav').length,"
            "  'live-sum': document.querySelectorAll('#live-sum').length,"
            "  'live-rows': document.querySelectorAll('#live-rows').length,"
            "  'nav-mask': document.querySelectorAll('#nav-mask').length,"
            "  nav: document.querySelectorAll('#nav').length,"
            "  navft: document.querySelectorAll('.nav-ft').length,"
            "  tripq: document.querySelectorAll('#tripq').length})")

    def _assert_sidebar_intact(self, page, context=""):
        """One of each region, and one of each piece of sidebar chrome.

        A bundle that nested its own wrapper inside the region it replaces, or that
        carried the rail's footer and mask along with it, would leave a second copy
        on the page after the first refresh. `getElementById` then finds the stale
        one, so the screen quietly stops updating from the second refresh onwards.
        """
        counts = self._region_counts(page)
        for name in ("live-nav", "live-sum", "live-rows"):
            self.assertEqual(counts[name], 1, f"{context}{name}: {counts[name]}")
        for name in ("nav-mask", "nav", "navft", "tripq"):
            self.assertEqual(counts[name], 1, f"{context}{name}: {counts[name]}")

    def test_two_changes_in_a_row_are_both_seen(self):
        """A refresh must not be a one-shot.

        A region is swapped in by looking it up by its own id. If the swapped-in
        copy lost that id, the first refresh would still look right and the second
        would silently find nothing to replace — a screen that updates once and
        then goes quiet, with no error anywhere. Two changes in a row is what tells
        the two apart.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        self._assert_sidebar_intact(watcher, "on load: ")
        self._save_through_the_api(ROW_A, description="첫 번째 변경")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('첫 번째 변경')",
            "the first refresh did not happen")
        # the regions are still findable by the id they are swapped by
        for region in ("live-nav", "live-sum", "live-rows"):
            self.assertTrue(
                watcher.evaluate(
                    "(id) => !!document.getElementById(id)", region),
                f"{region} lost its id after being swapped in")
        self._assert_sidebar_intact(watcher, "after one refresh: ")

        self._save_through_the_api(ROW_A2, description="두 번째 변경")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('두 번째 변경')",
            "the second refresh did not happen")
        self._assert_sidebar_intact(watcher, "after two refreshes: ")

    def test_repeated_refreshes_leave_one_of_everything(self):
        """Several changes in a row, with the DOM checked after each one.

        A wrapper that nests, or a fragment that carries the rail's footer, shows
        up as a growing count. One change would not always show it and three in a
        row always will, because each refresh adds one.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        for index in range(1, 4):
            self._save_through_the_api(ROW_A if index % 2 else ROW_A2,
                                       description=f"{index}번째 연속 변경")
            self._wait_for(
                watcher,
                f"document.getElementById('live-rows').innerText"
                f".includes('{index}번째 연속 변경')",
                f"refresh {index} did not happen")
            self._assert_sidebar_intact(watcher, f"after refresh {index}: ")
        # and the rail is still a working rail, not a stack of copies
        rail = watcher.evaluate(
            "document.getElementById('nav').innerText")
        self.assertIn("여행 목록", rail)
        self.assertIn("분류대기", rail)

    def test_a_change_that_moves_money_also_moves_the_totals(self):
        """The totals are part of the same refresh, not a separate one.

        A description edit does not change an amount, so it cannot show this. A
        row that moves out of the tab does: the trip's expense total has to fall
        on the page that was already open, not only after a manual reload.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        before_sum = self._summary(watcher)
        self.assertIn("180,000", before_sum)

        self._save_through_the_api(ROW_A, display_tab_id=TRIP_B)

        self._wait_for(
            watcher,
            "(function(){var s=document.getElementById('live-sum');"
            "return s && !s.innerText.includes('180,000');})()",
            "the totals did not follow a change that moved money",
            timeout=SETTLE_SECONDS + 2)
        after_sum = self._summary(watcher)
        self.assertNotEqual(after_sum, before_sum)
        # the moved row is gone from this tab, in the same refresh
        self.assertNotIn(ROW_A, watcher.evaluate(
            "document.getElementById('live-rows').innerHTML"))

    def test_the_trip_rail_shows_a_change_made_in_a_trip_not_being_viewed(self):
        """A save in trip B is noticed while trip A is on screen.

        The rail shows an income total for every trip, so a save anywhere is a
        change to this screen. Watching only the open tab would miss it. The row
        is moved into trip B and given a memo, which changes trip B's rail entry
        without changing trip A's rows at all.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        # the rail text before the change, kept in the page so the wait compares
        # against what was actually on screen rather than against a rebuilt copy
        watcher.evaluate("window.__railBefore ="
                         " document.getElementById('live-nav').innerText")
        # trip A is on screen, and trip B starts with nothing in it
        self.assertIn(TRIP_A, watcher.content())
        self.assertEqual(self._rail_entry(watcher, "예시여행B"), "0420_예시여행B\n0원")

        # an income row moves from trip A to trip B. The rail badge is the income
        # total, so this is the change the badge has to show: an expense move
        # would not touch it and would prove nothing about the badge.
        income = self.store.get_row("income-demo-i1")
        self.store.save(row_id="income-demo-i1",
                        expected_revision=income["revision"],
                        client_request_id="rail-b-income", change_mode="exception",
                        changes={"display_tab_id": TRIP_B})

        self._wait_for(
            watcher,
            "document.getElementById('live-nav').innerText"
            " !== window.__railBefore",
            "the trip rail did not refresh")
        # trip A is still on screen, and the trip that changed now carries the
        # income that arrived in it
        self.assertIn(TRIP_A, watcher.content())
        self.assertNotEqual(self._rail_entry(watcher, "예시여행B"),
                            "0420_예시여행B\n0원",
                            "trip B's rail total should have moved")

    def test_two_pages_each_see_the_other_s_save(self):
        """Both directions, so this is not one page watching a privileged one.

        Page A saves, page B updates; then B saves, A updates. A feature that only
        worked in one direction would still pass a single-direction test.
        """
        page_a = self._open(f"?tab={TRIP_A}")
        page_b = self._open(f"?tab={TRIP_A}")

        self._save_through_the_api(ROW_A, description="A 가 저장한 값")
        self._wait_for(page_b,
                       "document.getElementById('live-rows').innerText"
                       ".includes('A 가 저장한 값')",
                       "page B did not see the save")

        self._save_through_the_api(ROW_A2, description="B 가 저장한 값")
        self._wait_for(page_a,
                       "document.getElementById('live-rows').innerText"
                       ".includes('B 가 저장한 값')",
                       "page A did not see the second save")

    # ------------------------------------------------------ the draft guard
    def test_an_unsaved_draft_is_never_overwritten_and_is_said_to_be_waiting(self):
        """The guard, on a real page, with real typing.

        A draft in progress is the user's own work. A change arriving while it is
        open must not replace the screen under it, and the user must be told
        something changed rather than left looking at a stale list.
        """
        watcher = self._open(f"?tab={TRIP_A}&row={ROW_A}")
        watcher.wait_for_selector("#f-description")
        draft = "아직 저장하지 않은 입력"
        watcher.fill("#f-description", draft)
        # the board's own dirty mark, which the refresh reads
        self.assertEqual(
            watcher.evaluate("document.querySelector("
                             "'form[data-js-save]').getAttribute('data-dirty')"),
            "1")

        self._save_through_the_api(ROW_A2, description="다른 곳에서 저장한 값")

        # wait long enough for several polls to have happened
        time.sleep(live_sync.POLL_INTERVAL_MS / 1000.0 + 1.0)
        self.assertEqual(
            watcher.input_value("#f-description"), draft,
            "a refresh overwrote an unsaved draft")
        # and the user was told
        notice = watcher.evaluate(
            "document.getElementById('live-status').textContent")
        self.assertIn("바뀌었어요", notice)
        # the change is recorded, not lost
        self.assertTrue(watcher.evaluate(
            "window.__ledgerLiveSync &&"
            " window.__ledgerLiveSync.pendingToken()"))

    def test_the_deferred_change_is_applied_after_the_draft_is_saved(self):
        """Save first, then the held change lands. Nothing is left stale."""
        watcher = self._open(f"?tab={TRIP_A}&row={ROW_A}")
        watcher.wait_for_selector("#f-description")
        watcher.fill("#f-description", "이 브라우저가 저장한 값")
        self._save_through_the_api(ROW_A2, description="다른 곳에서 저장한 값")
        time.sleep(live_sync.POLL_INTERVAL_MS / 1000.0 + 1.0)
        self.assertTrue(watcher.evaluate(
            "window.__ledgerLiveSync.pendingToken()"))

        # the user saves their own edit through the panel form
        watcher.click("#panel form[data-js-save] button[type=submit]")
        watcher.wait_for_function(
            "document.querySelector('form[data-js-save]')"
            ".getAttribute('data-dirty') !== '1'")
        # the save is real
        self.assertEqual(self.store.get_row(ROW_A)["description"].replace(" ", ""),
                         "이브라우저가저장한값")
        # and the change that was held back is now on screen
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('다른 곳에서 저장한 값')",
            "the deferred change was not applied after the save")

    def test_the_deferred_change_is_applied_after_the_draft_is_cancelled(self):
        """Escape discards the draft, and the latest state replaces it.

        A cancel is a decision, so the screen that comes back is the current one
        rather than the one the draft was typed against.
        """
        watcher = self._open(f"?tab={TRIP_A}&row={ROW_A}")
        watcher.wait_for_selector("#f-description")
        watcher.fill("#f-description", "버릴 입력")
        self._save_through_the_api(ROW_A, description="다른 곳에서 저장한 값")
        time.sleep(live_sync.POLL_INTERVAL_MS / 1000.0 + 1.0)
        self.assertTrue(watcher.evaluate(
            "window.__ledgerLiveSync.pendingToken()"))

        watcher.press("#f-description", "Escape")
        watcher.wait_for_selector("#live-rows")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('다른 곳에서 저장한 값')",
            "the deferred change was not applied after the cancel")
        # the store has the other browser's value, not the discarded draft
        self.assertEqual(self.store.get_row(ROW_A)["description"],
                         "다른 곳에서 저장한 값")

    def test_a_save_in_flight_is_not_raced_by_a_refresh(self):
        """While this browser's own save is on the wire, the screen holds still.

        A refresh landing between the request and the answer would replace the form
        the user is looking at, which is how a save ends up written against a row
        that is no longer the one on screen.

        The save's answer is held on purpose here, and an outside change is made
        while it is held. Without the delay the answer comes back before the
        refresh has a chance to notice anything, so the guard would never be asked
        the question this test is about.
        """
        watcher = self._open(f"?tab={TRIP_A}&row={ROW_A}")
        watcher.wait_for_selector("#f-description")
        watcher.fill("#f-description", "한 번에 저장")
        # hold this browser's own save answer, and let the polls through
        handler, release = self._hold_saves()
        watcher.route("**/api/rows/*/save", handler)
        # the revision the form is about to save against, read before the click
        revision_before = watcher.evaluate(
            "document.querySelector('input[name=expected_revision]').value")
        self.assertEqual(revision_before,
                         str(self.store.get_row(ROW_A)["revision"]))
        watcher.click("#panel form[data-js-save] button[type=submit]")
        # the form is marked as saving while the request is on the wire
        watcher.wait_for_function(
            "document.querySelector('form[data-js-save]')"
            ".getAttribute('data-saving') === '1'")
        # a change lands from outside while the save is still waiting
        self._save_through_the_api(ROW_A2, description="저장 중에 다른 곳에서 저장")
        # let several polls and a fragment fetch happen inside that window
        time.sleep(live_sync.POLL_INTERVAL_MS / 1000.0 + 1.5)
        # the form is untouched: the typed value is still typed, and the panel is
        # still the same panel rather than one rebuilt underneath the save
        self.assertEqual(watcher.input_value("#f-description"), "한 번에 저장")
        self.assertEqual(
            watcher.evaluate("document.querySelector("
                             "'form[data-js-save]')"
                             ".getAttribute('data-saving')"), "1",
            "the save finished early, so the window under test never happened")
        self.assertEqual(
            watcher.evaluate("document.querySelector("
                             "'input[name=expected_revision]').value"),
            revision_before,
            "the form was replaced while a save was in flight")
        # and the save itself went through, once the held answer is let go
        release()
        watcher.wait_for_function(
            "document.querySelector('form[data-js-save]')"
            ".getAttribute('data-dirty') !== '1'", timeout=15000)
        self.assertEqual(self.store.get_row(ROW_A)["description"].replace(" ", ""),
                         "한번에저장")
        self.assertEqual(watcher.evaluate(
            "document.getElementById('panel') !== null"), True)
        # the change that arrived mid-save is applied afterwards, not lost
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('저장 중에 다른 곳에서 저장')",
            "the change that arrived during the save was lost")

    def test_a_draft_started_mid_fragment_fetch_is_not_replaced(self):
        """The guard is asked again after the fragments arrive, not only before.

        A draft can start while the fragments are in flight: the user opens a row
        and starts typing in the time the fetch takes. Swapping them in then would
        replace the list under a form the user is about to save from, and the token
        would be committed over a screen that does not show it.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        # stall the fragment answer, so a draft can be started while it is in flight
        held: list = []
        watcher.route("**/api/live/state*", lambda route: (
            held.append(route) if self._is_fragment_request(route)
            else route.continue_()))
        self._save_through_the_api(ROW_A, description="조각을 기다리는 변경")
        watcher.wait_for_function(
            "window.__ledgerLiveSync.pendingToken() !== '' || "
            "window.__ledgerLiveSync.isBusy()")
        # a draft starts now, while the fragment fetch is still unanswered
        watcher.click(f"tr[data-id='{ROW_A2}']")
        watcher.wait_for_selector("#f-description")
        watcher.fill("#f-description", "조각이 오는 동안 입력")
        self.assertEqual(
            watcher.evaluate("document.querySelector('form[data-js-save]')"
                             ".getAttribute('data-dirty')"), "1")
        # now let the fragments arrive, with the draft open
        for route in held:
            route.continue_()
        held.clear()
        # and let the later fetches through, so the recovery below is a real one
        watcher.unroute("**/api/live/state*")
        time.sleep(live_sync.POLL_INTERVAL_MS / 1000.0 + 1.0)
        self.assertEqual(watcher.input_value("#f-description"),
                         "조각이 오는 동안 입력",
                         "a refresh replaced a form typed into mid-fetch")
        # the token was not committed either, so the change is still pending
        self.assertTrue(watcher.evaluate(
            "window.__ledgerLiveSync.pendingToken()"),
            "the token was committed over a screen that does not show it")
        # and once the draft is saved the change is applied. The save itself
        # reloads nothing, so anything that appears now came from the refresh.
        watcher.click("#panel form[data-js-save] button[type=submit]")
        watcher.wait_for_function(
            "document.querySelector('form[data-js-save]')"
            ".getAttribute('data-dirty') !== '1'", timeout=15000)
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('조각을 기다리는 변경')",
            "the change was lost after the draft was saved",
            timeout=SETTLE_SECONDS + 5)

    def test_a_failed_fragment_fetch_does_not_commit_the_token(self):
        """A fragment answer that fails must leave the change pending.

        Committing the token on a fetch that failed would make the next poll report
        "no change" over a screen that never received the new data. The token is
        read directly for that reason: the change does eventually arrive on a later
        pass, so watching the screen would not tell a committed token from a
        correctly held one.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        watcher.route("**/api/live/state*", lambda route: (
            route.abort("connectionfailed") if self._is_fragment_request(route)
            else route.continue_()))
        # the token the page was rendered from, and the one it is asking with
        rendered = watcher.evaluate("window.__ledgerLiveSync.token()")
        self._save_through_the_api(ROW_A, description="조각이 실패하는 변경")
        # wait for the failure to be reported rather than for a fixed time: the
        # report is the thing under test, so a sleep could pass without it
        self._wait_for(
            watcher,
            "document.getElementById('live-status').textContent"
            ".includes('못했어요')",
            "a failed fragment fetch was not reported")
        # the screen is unchanged, the token is the one it was rendered from, and
        # the change is still outstanding
        self.assertNotIn("조각이 실패하는 변경", watcher.evaluate(
            "document.getElementById('live-rows').innerText"))
        self.assertEqual(watcher.evaluate("window.__ledgerLiveSync.token()"),
                         rendered,
                         "a failed fetch committed a token the screen does not "
                         "show")
        self.assertTrue(watcher.evaluate(
            "window.__ledgerLiveSync.pendingToken()"),
            "a failed fetch lost the change")
        # once the transport is back, the change arrives
        watcher.unroute("**/api/live/state*")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('조각이 실패하는 변경')",
            "the change was lost after the transport came back")

    def test_a_fragment_bundle_that_replaces_nothing_commits_no_token(self):
        """If no region was replaced, the token must not move.

        A bundle can come back with regions this page does not have — the wrong
        bundle for the screen, or a page whose regions were replaced by something
        else. Committing the token then would make the next poll report "no change"
        over a screen that never received the data, and the change would be lost
        with nothing on screen to say so.

        The regions are removed from the live page rather than a bundle faked, so
        this goes through the real fetch and the real swap.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        rendered = watcher.evaluate("window.__ledgerLiveSync.token()")
        # the page is showing something the fragments cannot replace
        watcher.evaluate(
            "['live-nav','live-sum','live-rows'].forEach(function(id){"
            "  var el=document.getElementById(id);"
            "  if(el&&el.parentNode) el.parentNode.removeChild(el); });"
            "document.getElementById('live-status').textContent='';")
        self._save_through_the_api(ROW_A, description="영역이 없는 페이지")
        # the fetch happens and the change is found, but nothing can be replaced
        self._wait_for(
            watcher,
            "window.__ledgerLiveSync.pendingToken() !== ''",
            "the change was never even found")
        self._wait_for(
            watcher,
            "document.getElementById('live-status').textContent"
            ".includes('못했어요')",
            "a bundle that replaced nothing was not reported",
            timeout=SETTLE_SECONDS)
        self.assertEqual(watcher.evaluate("window.__ledgerLiveSync.token()"),
                         rendered,
                         "the token was committed over a screen that shows "
                         "none of it")
        self.assertTrue(watcher.evaluate(
            "window.__ledgerLiveSync.pendingToken()"),
            "the change was dropped instead of being held")

    def test_a_failing_fragment_fetch_backs_off_instead_of_looping(self):
        """Repeated fragment failures must not become a tight retry loop.

        The first version retried the fragment as soon as it failed, which is two
        requests a second against a server already in trouble, forever. The bound
        is what separates a screen that recovers from one that hammers.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        asked = []
        watcher.route("**/api/live/state*", lambda route: (
            asked.append(time.time()) if self._is_fragment_request(route)
            else route.continue_(),
            route.abort("connectionfailed") if self._is_fragment_request(route)
            else None))
        self._save_through_the_api(ROW_A, description="계속 실패하는 변경")
        self._wait_for(
            watcher,
            "document.getElementById('live-status').textContent"
            ".includes('못했어요')",
            "the fragment failure was not reported")
        # Read straight away: a later poll that succeeds releases the backoff again,
        # so this is the only moment the grown delay is visible.
        after_failure = watcher.evaluate("window.__ledgerLiveSync.delay()")
        self.assertGreaterEqual(
            after_failure, 2 * live_sync.POLL_INTERVAL_MS,
            "a failed fragment fetch did not grow the wait: "
            f"{after_failure}ms")
        self.assertLessEqual(after_failure, live_sync.BACKOFF_CEILING_MS,
                             "the fragment backoff is not bounded")
        # The second ask is what shows the retry happened at all, and where it
        # lands depends on the machine, so it is waited for rather than assumed to
        # fall inside a fixed sleep. A tight loop gets here in well under a second.
        # The waits go through the driver, not `time.sleep`: while a route is
        # intercepted nothing is answered until the driver is pumped, so a plain
        # sleep would hold the very requests this is counting still.
        deadline = time.time() + SETTLE_SECONDS
        while time.time() < deadline and len(asked) < 2:
            watcher.wait_for_timeout(100)
        self.assertGreaterEqual(
            len(asked), 2, "the failed fragment fetch was never retried")
        at_two = len(asked)
        first_gap = round(asked[1] - asked[0], 2)
        self.assertGreaterEqual(
            first_gap, 1.5, f"the retries did not back off: {asked}")
        # and then it must stay slow: a loop would add dozens in this window
        watcher.wait_for_timeout(6000)
        self.assertLess(
            len(asked) - at_two, 4,
            f"the fragment fetch is looping: {len(asked)} asks in 6s")
        # a poll that comes back releases the backoff, and only that does
        watcher.unroute("**/api/live/state*")
        self._wait_for(
            watcher,
            "window.__ledgerLiveSync.delay() === %d"
            % live_sync.POLL_INTERVAL_MS,
            "a working poll did not release the fragment backoff",
            timeout=SETTLE_SECONDS)
        self.assertLessEqual(
            watcher.evaluate("window.__ledgerLiveSync.delay()"),
            live_sync.BACKOFF_CEILING_MS,
            "the fragment backoff is not bounded")

    def test_a_poll_refusal_takes_the_ledger_off_the_screen(self):
        """A refusal on the poll itself must clear the ledger, not just stop it.

        A page whose permission was withdrawn still has the rows it was showing.
        Stopping the polling and leaving them up would be showing data the server
        has taken back, and the user would have no indication that anything
        changed — the screen would simply stop moving.
        """
        watcher = self._open(f"?tab={TRIP_A}", user=V1)
        self.assertIn(TRIP_A, watcher.content())
        # withdrawn with no change outstanding, so the refusal lands on the poll
        # rather than on a fragment fetch
        self.access.apply_assignment_snapshot(
            user_id=V1, items=[{"tab_id": TRIP_A, "snapshot_revision": 2,
                                "state": access_control.ASSIGN_REVOKED}],
            source_version="src-br-clear-poll", complete=False)
        self._wait_for(
            watcher,
            "window.__ledgerLiveSync.isStopped() === true",
            "the page kept polling after its permission was revoked")
        for region in ("live-viewer", "live-nav", "live-sum", "live-rows"):
            inner = watcher.evaluate(
                "(id) => { const el = document.getElementById(id);"
                " return el ? el.innerHTML : ''; }", region)
            self.assertNotIn(TRIP_A, inner, f"{region} still holds ledger data")
        self.assertNotIn(TRIP_A, watcher.evaluate(
            "document.getElementById('main').innerText"))
        self.assertIn("권한", watcher.evaluate(
            "document.getElementById('main').innerText"))

    def test_one_request_at_a_time_when_a_poll_and_a_fragment_overlap(self):
        """A request in flight must not be joined by a second one.

        Two in flight can land out of order, and the older answer landing last
        would leave the screen showing a state the next comparison does not expect.

        The overlap is measured from inside the page, by wrapping `fetch` and
        recording how many state-endpoint requests are open at each moment. That
        is the only place both halves are visible: a route handler would see them
        one at a time, because Playwright dispatches route handlers serially, and
        the count has to be taken while a request is still open.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        watcher.evaluate(
            "window.__overlap = {open: 0, max: 0, log: []};"
            "(function(){"
            "  var real = window.fetch;"
            "  window.fetch = function(url, opts){"
            "    var u = String(url && url.url ? url.url : url);"
            "    if (u.indexOf('/api/live/state') < 0) {"
            "      return real.apply(window, arguments); }"
            "    var kind = (opts && opts.headers &&"
            "      Object.keys(opts.headers).some(function(k){"
            "        return k.toLowerCase() === 'x-part'; })) ? 'frag' : 'poll';"
            "    window.__overlap.open++;"
            "    if (window.__overlap.open > window.__overlap.max){"
            "      window.__overlap.max = window.__overlap.open;"
            "      window.__overlap.log.push(kind + ' into ' +"
            "        window.__overlap.open); }"
            "    return real.apply(window, arguments).then(function(r){"
            "      window.__overlap.open--; return r; }, function(e){"
            "      window.__overlap.open--; throw e; });"
            "  };"
            "})()")
        # A fragment that comes back straight away cannot overlap anything: it is
        # answered long before the next poll is due, so the guard is never asked a
        # question. The fragment is therefore held for longer than one poll
        # interval, which is the only window in which two requests could be in
        # flight at once.
        held: list = []

        def hold_fragment(route):
            if not self._is_fragment_request(route):
                route.continue_()
                return
            held.append(route)

        watcher.route("**/api/live/state*", hold_fragment)
        self._save_through_the_api(ROW_A, description="겹침 확인용 변경")
        self._wait_for(
            watcher, "window.__overlap.max >= 1",
            "no state request was ever made", timeout=SETTLE_SECONDS)
        # outlives several poll intervals, so a second request would have to be
        # started by the timer if the guard were not there. The wait goes through
        # the driver: an intercepted poll is not dispatched until then, and a plain
        # sleep would leave the network quiet for reasons that have nothing to do
        # with the guard.
        stalled = live_sync.POLL_INTERVAL_MS / 1000.0 * 2 + 0.5
        deadline = time.time() + stalled
        while time.time() < deadline:
            watcher.wait_for_timeout(100)
        overlap = watcher.evaluate("window.__overlap")
        for route in list(held):
            route.continue_()
        held.clear()
        watcher.unroute("**/api/live/state*")
        self.assertGreaterEqual(len(overlap["log"]), 1,
                                f"no state request was ever made: {overlap}")
        self.assertEqual(
            overlap["max"], 1,
            f"two requests were in flight at once: {overlap['log']}")
        # the held change still lands, so the overlap was not faked by a stall
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('겹침 확인용 변경')",
            "the screen did not settle on the newest state")

    def test_a_revoked_page_takes_the_ledger_off_the_screen(self):
        """A refusal clears the ledger, not just the polling.

        Rows already on screen are the caller's only while the server says so. When
        the session or the permission is withdrawn, leaving them up would be showing
        data the server has taken back, so the regions are emptied and the refusal
        is shown in their place.
        """
        watcher = self._open(f"?tab={TRIP_A}", user=V1)
        content = watcher.content()
        self.assertIn(TRIP_A, content, "the viewer page showed no trip to clear")
        self.access.apply_assignment_snapshot(
            user_id=V1, items=[{"tab_id": TRIP_A, "snapshot_revision": 2,
                                "state": access_control.ASSIGN_REVOKED}],
            source_version="src-br-clear", complete=False)
        self._wait_for(
            watcher,
            "window.__ledgerLiveSync.isStopped() === true",
            "the page kept polling after its permission was revoked")
        # the ledger is gone from the page
        for region in ("live-viewer", "live-nav", "live-sum", "live-rows"):
            inner = watcher.evaluate(
                "(id) => { const el = document.getElementById(id);"
                " return el ? el.innerHTML : ''; }", region)
            self.assertNotIn(TRIP_A, inner, f"{region} still holds ledger data")
        self.assertNotIn(TRIP_A, watcher.evaluate(
            "document.getElementById('main').innerText"))
        # and the reason is on screen
        main_text = watcher.evaluate("document.getElementById('main').innerText")
        self.assertIn("권한", main_text)

    def test_a_revoked_page_that_is_mid_change_takes_the_ledger_off_the_screen(
            self):
        """The same, for a refusal that lands on the fragment fetch instead.

        A page that is holding a change when the permission goes has a fetch in
        flight, so its refusal arrives on the fragment, not on the poll. That is a
        different branch, and it has to clear the regions for the same reason: the
        rows on screen are the caller's only while the server says so.

        The fragment is held by leaving it unanswered rather than by sleeping in the
        handler. Playwright runs a handler on the driver's own thread, so a handler
        that sleeps there also stops the test from revoking anything.
        """
        watcher = self._open(f"?tab={TRIP_A}", user=V1)
        self.assertIn(TRIP_A, watcher.content())
        held: list = []
        answered = {"polls": False}

        def isolate_the_fragment(route):
            # A poll answered here with "no change" never reaches the server, so
            # it never refuses and never clears anything. That is what makes this a
            # test of the fragment branch: the poll branch cannot be what stops the
            # page, so if the page does stop, the fragment's own refusal did it.
            if self._is_fragment_request(route):
                held.append(route)
                return
            if answered["polls"]:
                token = watcher.evaluate("window.__ledgerLiveSync.token()")
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(
                                  {"token": token, "changed": False,
                                   "role": "owner", "state": "closed"}))
                return
            route.continue_()

        watcher.route("**/api/live/state*", isolate_the_fragment)
        # a change the page will find and go to fetch
        self._save_through_the_api(ROW_A, description="철회 중에 되찾는 중")
        # The fragment, not just any request, has to be the one in flight. The wait
        # goes through the driver, because an intercepted request is not dispatched
        # until then, and a plain sleep would see nothing arrive.
        self._wait_for_held(watcher, held, "the fragment fetch was never in flight")
        # withdrawn while that fetch is in flight, and from here on the poll can
        # no longer be the thing that notices
        self.access.apply_assignment_snapshot(
            user_id=V1, items=[{"tab_id": TRIP_A, "snapshot_revision": 2,
                                "state": access_control.ASSIGN_REVOKED}],
            source_version="src-br-clear-fragment", complete=False)
        answered["polls"] = True
        for route in list(held):
            route.continue_()
        held.clear()
        watcher.unroute("**/api/live/state*")
        self._wait_for(
            watcher,
            "window.__ledgerLiveSync.isStopped() === true",
            "the fragment's refusal did not stop the page")
        for region in ("live-viewer", "live-nav", "live-sum", "live-rows"):
            inner = watcher.evaluate(
                "(id) => { const el = document.getElementById(id);"
                " return el ? el.innerHTML : ''; }", region)
            self.assertNotIn(TRIP_A, inner, f"{region} still holds ledger data")
        self.assertNotIn(TRIP_A, watcher.evaluate(
            "document.getElementById('main').innerText"))
        self.assertIn("권한", watcher.evaluate(
            "document.getElementById('main').innerText"))

    def test_a_stale_revision_is_still_refused_and_the_draft_is_kept(self):
        """The existing conflict path is untouched by the refresh.

        Two browsers, same row. The second save is refused on `expected_revision`,
        the typed value stays in the form, and the screen says why. A refresh that
        quietly replaced the form would turn a refusal into a lost edit.
        """
        watcher = self._open(f"?tab={TRIP_A}&row={ROW_A}")
        watcher.wait_for_selector("#f-description")
        watcher.fill("#f-description", "내 입력")
        # another browser saves first
        self._save_through_the_api(ROW_A, description="먼저 저장된 값")
        # wait for the refresh to find it and then try to save
        time.sleep(live_sync.POLL_INTERVAL_MS / 1000.0 + 1.0)
        watcher.click("#panel form[data-js-save] button[type=submit]")
        watcher.wait_for_selector("#panel .f-msg.err")
        message = watcher.text_content("#panel .f-msg.err")
        self.assertIn("EDIT_CONFLICT", message)
        self.assertEqual(watcher.input_value("#f-description"), "내 입력")
        # the store kept the other browser's value
        self.assertEqual(self.store.get_row(ROW_A)["description"],
                         "먼저 저장된 값")

    def test_focus_and_scroll_survive_a_refresh(self):
        """A refresh must not move what the user was looking at.

        The board's scroller is the `main` element rather than the window, so the
        position that has to survive is that one. A short viewport is used so the
        list is genuinely taller than the frame, and a non-zero scroll is read
        back before the change is made, so a test that asserted a position the
        layout never allowed would not pass by accident.
        """
        watcher = self._open(f"?tab={TRIP_A}", width=900, height=420)
        scrollable = watcher.evaluate(
            "(function(){var m=document.getElementById('main');"
            "return m.scrollHeight - m.clientHeight;})()")
        self.assertGreater(scrollable, 0,
                           "this viewport has nothing to scroll, so the test "
                           "would prove nothing")
        watcher.evaluate("document.getElementById('main').scrollTop = 80")
        scrolled = watcher.evaluate(
            "document.getElementById('main').scrollTop")
        self.assertGreater(scrolled, 0, "the board did not scroll where asked")
        watcher.evaluate("document.getElementById('tripq').focus()")

        self._save_through_the_api(ROW_A2, description="스크롤 확인용 저장")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('스크롤 확인용 저장')",
            "the refresh never happened, so nothing was protected")

        self.assertEqual(watcher.evaluate(
            "document.getElementById('main').scrollTop"), scrolled,
            "the refresh moved the scroll position")
        self.assertEqual(watcher.evaluate("document.activeElement.id"), "tripq",
                         "the refresh moved the keyboard focus")

    def test_scrolling_during_a_held_fragment_keeps_the_new_position(self):
        """The position to keep is the one at the swap, not the one at the request.

        The earlier version read the scroll position before the fragment fetch and
        put that back afterwards. A held fetch is a window in which the user
        scrolls, and restoring the value from before the fetch undid that: the page
        jumped back to where they had been when the request went out. Measured on
        this synthetic page, `main.scrollTop` 40, scrolled to 100 while the fragment
        was held, and the refresh landed back on 40.

        So the position is read immediately before the DOM is replaced, and the
        change is made while the fragment is genuinely still in flight.
        """
        watcher = self._open(f"?tab={TRIP_A}", width=900, height=420)
        scrollable = watcher.evaluate(
            "(function(){var m=document.getElementById('main');"
            "return m.scrollHeight - m.clientHeight;})()")
        self.assertGreater(scrollable, 150,
                           "this viewport cannot scroll far enough for the test "
                           "to mean anything")
        held: list = []

        def hold_fragment(route):
            if self._is_fragment_request(route):
                held.append(route)
            else:
                route.continue_()

        watcher.route("**/api/live/state*", hold_fragment)
        watcher.evaluate("document.getElementById('main').scrollTop = 40")
        self.assertEqual(watcher.evaluate(
            "document.getElementById('main').scrollTop"), 40,
            "the board did not start where asked")
        self._save_through_the_api(ROW_A2, description="스크롤 도중 저장")
        # the fragment is now in flight and the page is live underneath it
        self._wait_for_held(watcher, held, "the fragment fetch was never in flight")
        # the user scrolls while it is held, which is the whole point
        watcher.evaluate("document.getElementById('main').scrollTop = 100")
        self.assertEqual(watcher.evaluate(
            "document.getElementById('main').scrollTop"), 100,
            "the board did not move where asked mid-fetch")
        for route in list(held):
            route.continue_()
        held.clear()
        watcher.unroute("**/api/live/state*")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('스크롤 도중 저장')",
            "the held refresh never landed")
        self.assertEqual(
            watcher.evaluate("document.getElementById('main').scrollTop"), 100,
            "the refresh moved the scroll position back to where it was before "
            "the fetch, undoing the scroll the user made while waiting")

    def test_focus_moved_during_a_held_fragment_stays_moved(self):
        """The same for the keyboard: what is focused at the swap is what stays.

        A refresh that restored the element focused before the fetch would take the
        caret out of a field the user has moved it into, which is the same
        regression as the scroll and would break typing.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        # the search box, then a row link. Neither is a text field inside a panel,
        # so neither makes the page treat an edit as in progress: the fragment is
        # fetched, which is the case under test.
        watcher.evaluate("document.getElementById('tripq').focus()")
        before = watcher.evaluate("document.activeElement.id")
        held: list = []

        def hold_fragment(route):
            if self._is_fragment_request(route):
                held.append(route)
            else:
                route.continue_()

        watcher.route("**/api/live/state*", hold_fragment)
        self._save_through_the_api(ROW_A, description="포커스 도중 저장")
        self._wait_for_held(watcher, held, "the fragment fetch was never in flight")
        # the user moves the focus elsewhere while the fetch is held
        watcher.evaluate(
            "(function(){var a=document.querySelector('#live-rows a');"
            "if(a) a.focus();})()")
        after = watcher.evaluate("document.activeElement.tagName")
        self.assertNotEqual(after, "INPUT",
                            "the focus never left the search box, so the test "
                            "would pass without the refresh doing anything")
        for route in list(held):
            route.continue_()
        held.clear()
        watcher.unroute("**/api/live/state*")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('포커스 도중 저장')",
            "the held refresh never landed")
        self.assertEqual(watcher.evaluate("document.activeElement.tagName"),
                         after,
                         f"the refresh moved the keyboard focus back to "
                         f"{before}, the element focused before the fetch")

    def test_a_draft_started_during_a_held_fragment_keeps_the_caret(self):
        """A draft that began while the fragment was in flight keeps the caret.

        The other test with a draft mid-fetch checks that the form is not replaced.
        This one is about the focus: with the old code the remembered state was
        restored in a `finally`-style step after the fetch, whether or not anything
        had been replaced, so a draft that started during the fetch had the caret
        pulled out of the field being typed into and put back on whatever had been
        focused before the request went out.

        The draft is started after the fetch is in flight, not before. A draft open
        before the change is found means the fetch is never made at all, which is
        the deferral rule and not the case under test.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        # Something is focused before the fetch, so there is a remembered focus that
        # a later restore could wrongly put back. Focusing nothing would make the
        # test pass against the old code for the wrong reason: with nothing to
        # restore, the caret stays in the field whatever the code does.
        watcher.evaluate("document.getElementById('tripq').focus()")
        held: list = []

        def hold_fragment(route):
            if self._is_fragment_request(route):
                held.append(route)
            else:
                route.continue_()

        watcher.route("**/api/live/state*", hold_fragment)
        # nothing is being edited yet, so the change is fetched
        self._save_through_the_api(ROW_A, description="작성 중 조각 확인")
        self._wait_for_held(watcher, held, "the fragment fetch was never in flight")
        # the user opens a row and starts typing while the fetch is held
        watcher.click(f"tr[data-id='{ROW_A2}']")
        watcher.wait_for_selector("#f-description")
        watcher.click("#f-description")
        watcher.fill("#f-description", "조각 기다리는 중 입력")
        self.assertEqual(watcher.evaluate("document.activeElement.id"),
                         "f-description",
                         "the caret was never in the field, so the test would "
                         "pass without the refresh doing anything")
        for route in list(held):
            route.continue_()
        held.clear()
        watcher.unroute("**/api/live/state*")
        # the change is held rather than applied, because a draft is in progress
        self._wait_for(
            watcher,
            "document.getElementById('live-status').innerText"
            ".includes('저장하거나 닫으면')",
            "the change was not held for the draft")
        self.assertEqual(watcher.input_value("#f-description"),
                         "조각 기다리는 중 입력",
                         "the draft was disturbed by a refresh it never got")
        self.assertEqual(watcher.evaluate("document.activeElement.id"),
                         "f-description",
                         "the caret left the field being typed in")

    # ---------------------------------------------------- the viewer scope
    def test_a_viewer_page_sees_its_own_trip_and_never_the_other(self):
        watcher = self._open(f"?tab={TRIP_A}", user=V1)
        content = watcher.content()
        # its own trip is on the screen
        self.assertIn(TRIP_A, content)
        # the trip it has no assignment to is nowhere in the document, not even
        # as a link the viewer could follow
        self.assertNotIn(TRIP_B, content)
        self.assertNotIn("예시여행B", content)

    def test_a_viewer_page_refreshes_and_still_cannot_see_the_other_trip(self):
        """A viewer's refresh is bounded by the same allowlist as its first load."""
        watcher = self._open(f"?tab={TRIP_A}", user=V1)
        self._save_through_the_api(ROW_A, description="담당자 화면 갱신")
        self._wait_for(
            watcher,
            "document.getElementById('live-viewer').innerText"
            ".includes('담당 여행') || "
            "document.body.innerText.includes('담당 여행')",
            "the viewer page never refreshed")
        time.sleep(live_sync.POLL_INTERVAL_MS / 1000.0)
        # after the refresh, still nothing about the other trip
        self.assertNotIn("예시여행B", watcher.content())
        self.assertNotIn(TRIP_B, watcher.content())

    def test_a_viewer_poll_stops_when_the_assignment_is_revoked(self):
        """A revoked viewer's open page stops asking and says so.

        The refresh is a read, so a revocation must reach it. The page is told
        rather than left polling a refusal, and the ledger it already shows is
        left alone: nothing new is fetched and nothing is invented.
        """
        watcher = self._open(f"?tab={TRIP_A}", user=V1)
        self.assertEqual(watcher.evaluate("window.__ledgerLiveSync.isStopped()"),
                         False)
        self.access.apply_assignment_snapshot(
            user_id=V1, items=[{"tab_id": TRIP_A, "snapshot_revision": 2,
                                "state": access_control.ASSIGN_REVOKED}],
            source_version="src-br-revoke", complete=False)
        self._wait_for(
            watcher,
            "window.__ledgerLiveSync.isStopped() === true",
            "the page kept polling after its permission was revoked")
        self.assertIn("열 수 없어요", watcher.evaluate(
            "document.getElementById('live-status').textContent"))

    def test_a_page_with_no_session_never_gets_a_token(self):
        """No session, no token. The login path answers, as it already did."""
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/live/state?tab={TRIP_A}")
        try:
            with urllib.request.urlopen(request) as response:
                self.fail(f"expected a refusal, got {response.status}")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 401)

    # ------------------------------------------------------------ the tab
    def test_a_background_tab_is_not_asked_and_catches_up_when_shown(self):
        """A tab that is not visible does not poll; on return it checks at once.

        Background polling would keep asking the server for a screen nobody is
        looking at, and the cost is paid on every open tab.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        # a second page is backgrounded, which is what a real user has
        watcher.evaluate("document.dispatchEvent("
                         "new Event('visibilitychange'))")
        # the page reads as hidden: force the state the browser would set
        watcher.evaluate(
            "Object.defineProperty(document,'hidden',{value:true,"
            "configurable:true});"
            "Object.defineProperty(document,'visibilityState',{value:'hidden',"
            "configurable:true});")
        # Count what the page actually asks for while it reads as hidden, rather
        # than reading the delay back: a delay of the right size with requests
        # still going out would pass a check on the delay alone.
        asked = []
        watcher.route("**/api/live/state*",
                      lambda route: (asked.append(1), route.continue_()))
        watcher.evaluate("window.__ledgerLiveSync.check()")
        time.sleep(1.0)
        watcher.evaluate("window.__ledgerLiveSync.check()")
        time.sleep(1.0)
        self.assertEqual(asked, [],
                         "a hidden tab asked the server anyway")
        self.assertEqual(watcher.evaluate("window.__ledgerLiveSync.delay()"),
                         live_sync.POLL_INTERVAL_MS,
                         "a hidden tab should wait the normal interval")
        watcher.unroute("**/api/live/state*")
        # a change made while hidden is picked up on the way back, not lost
        self._save_through_the_api(ROW_A2, description="숨김 동안 저장")
        watcher.evaluate(
            "Object.defineProperty(document,'hidden',{value:false,"
            "configurable:true});"
            "Object.defineProperty(document,'visibilityState',{value:'visible',"
            "configurable:true});"
            "document.dispatchEvent(new Event('visibilitychange'));")
        self._wait_for(
            watcher,
            "document.getElementById('live-rows').innerText"
            ".includes('숨김 동안 저장')",
            "a change made while the tab was hidden was lost")

    def test_a_dropped_connection_backs_off_and_says_so(self):
        """A transport failure backs off inside a bound and tells the user.

        The bound matters in both directions: an unbounded backoff would look
        like a working screen that never updates, and no backoff at all would
        hammer a server that is down.
        """
        watcher = self._open(f"?tab={TRIP_A}")
        # fail the next polls at the transport level, the way a lost connection
        # does, without changing any status code
        watcher.route("**/api/live/state*",
                      lambda route: route.abort("connectionfailed"))
        watcher.evaluate("window.dispatchEvent(new Event('ledger:saved'))")
        self._wait_for(
            watcher,
            "document.getElementById('live-status').textContent"
            ".includes('연결')",
            "a dropped connection was not reported to the user")
        time.sleep(0.5)
        delay = watcher.evaluate("window.__ledgerLiveSync.delay()")
        self.assertGreater(delay, live_sync.POLL_INTERVAL_MS,
                           "the interval did not back off")
        self.assertLessEqual(delay, live_sync.BACKOFF_CEILING_MS,
                             "the backoff is not bounded")
        self.assertEqual(watcher.evaluate("window.__ledgerLiveSync.isStopped()"),
                         False, "a transport failure is not a refusal")
        # and the backoff grows rather than staying at one value, while staying
        # inside the bound: a fixed longer delay would satisfy the two checks above
        watcher.evaluate("window.__ledgerLiveSync.check()")
        self._wait_for(
            watcher,
            f"window.__ledgerLiveSync.delay() > {delay}",
            "the backoff did not grow on a second failure",
            timeout=SETTLE_SECONDS)
        # a recovered connection returns to the normal interval
        watcher.unroute("**/api/live/state*")
        watcher.evaluate("window.dispatchEvent(new Event('online'))")
        self._wait_for(
            watcher,
            f"window.__ledgerLiveSync.delay() === {live_sync.POLL_INTERVAL_MS}",
            "the interval did not return to normal after the connection came back",
            timeout=SETTLE_SECONDS)


class LiveSyncBrowserHtmlTests(unittest.TestCase):
    """What the server sends, checked without a browser.

    The headers matter on their own: a cached poll or a cached fragment would make
    a screen report a stale ledger as current, which no DOM assertion can catch.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "live-headers.sqlite")
        self.store = LedgerStore(os.environ["WEBLEDGER_DB"])
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        self.access.ensure_owner(OWNER)

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

    def _get(self, path, user=OWNER, headers=None):
        head = dict(headers or {})
        if user:
            head[access_control.SyntheticSessionAdapter.HEADER] = user
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", headers=head)
        with urllib.request.urlopen(request) as response:
            return response.status, response.read(), dict(response.headers)

    def test_the_board_page_and_both_poll_shapes_are_no_store(self):
        for path, headers in (
                (f"/board?tab={TRIP_A}", None),
                (f"/api/live/state?tab={TRIP_A}", None),
                (f"/api/live/state?tab={TRIP_A}", {"X-Part": "live-state"}),
                (f"/healthz", None)):
            status, _body, response_headers = self._get(path, OWNER, headers)
            self.assertEqual(status, 200, path)
            self.assertEqual(response_headers.get("Cache-Control"), "no-store",
                             path)

    def test_the_single_operator_server_also_answers_the_poll(self):
        """The board with no access store bound still has two browsers.

        A local single-operator board is the same product on loopback, so its
        pages have to refresh too. With no access store there is no session to
        check, and the refusal path must not be reached by accident.
        """
        board_mod.bind_access(None)
        try:
            status, body, headers = self._get(f"/api/live/state?tab={TRIP_A}",
                                             user=None)
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Cache-Control"), "no-store")
            state = json.loads(body.decode("utf-8"))
            self.assertEqual(state["role"], "owner")
            self.assertTrue(state["token"])
            # and the page carries a config the script can use
            _status, page, _ = self._get(f"/board?tab={TRIP_A}", user=None)
            self.assertIn(b"id='live-config'", page)
        finally:
            board_mod.bind_access(self.access)


if __name__ == "__main__":
    unittest.main()
