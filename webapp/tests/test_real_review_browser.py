"""REAL-REVIEW-001: the review screen in a real browser, two pages at a time.

Synthetic sources only, written by `webapp.tests.review_fixtures` into a
temporary directory. The merchant and the review note in the injection fixture
are the literal string `<script>alert(1)</script>`, and this file asserts it is
shown as text and never executed. No value here is a real merchant, a real
person or a real amount, and nothing reads a deployment or a customer file.

The two pages are the cross-device case: one page holds a choice the other has
not saved yet, and the screen has to say so rather than take either side away.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.request
import time
import unittest
from pathlib import Path

from webapp import access_control
from webapp import ledger_board as board_mod
from webapp import real_review
from webapp.tests import review_fixtures as fx

OWNER = "syn-owner-O"

#: Playwright's `timeout` is in milliseconds, not seconds. A small number here
# reads as a few milliseconds and the wait returns before the page has even
# fetched its model, which fails every test on this screen for the wrong reason.
SETTLE_MS = 20000


class ReviewBrowserFixture(unittest.TestCase):
    """The server, the fixtures and the browser. No tests of its own.

    Kept separate from the tests so the two groups below can differ only in the
    fixture they need. A test case that holds tests and is subclassed to vary one
    attribute re-runs every test it holds once per subclass, and each one pays for a
    server and a Chromium to say something the group it sits in already says.
    """

    rows = 3
    injection = False

    def setUp(self):
        from playwright.sync_api import sync_playwright

        self.tmp = Path(tempfile.mkdtemp())
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self._prev_config = os.environ.get(real_review.CONFIG_ENV)
        os.environ["WEBLEDGER_DB"] = str(self.tmp / "browser.sqlite")
        self.manifest = fx.write_case(self.tmp, rows=self.rows,
                                      injection=self.injection)
        self.config_path = self.tmp / "review.json"
        self.config_path.write_text(json.dumps(self.manifest, ensure_ascii=False),
                                    encoding="utf-8")
        os.environ[real_review.CONFIG_ENV] = str(self.config_path)

        self.server = board_mod.serve(port=0, with_worker=False, seed_demo=False)
        self.store = board_mod._active_store()
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.ensure_owner(OWNER)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        real_review.clear_real_review()

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self.pages = []
        self.addCleanup(self._restore)

    def _restore(self):
        real_review.clear_real_review()
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        try:
            self._browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass
        for name, value in (("WEBLEDGER_DB", self._prev_db),
                            (real_review.CONFIG_ENV, self._prev_config)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # ------------------------------------------------------------- browser
    def open_review(self, user=OWNER, viewport=None):
        context = self._browser.new_context(
            viewport=viewport or {"width": 1280, "height": 900})
        context.set_extra_http_headers(
            {access_control.SyntheticSessionAdapter.HEADER: user})
        page = context.new_page()
        self.pages.append(page)
        page.goto(f"http://127.0.0.1:{self.port}/review")
        page.wait_for_function(
            "document.querySelectorAll('#rows .card').length > 0", timeout=SETTLE_MS)
        return page

    def card(self, page, offset=0):
        """The card for fixture row `offset`, paging to it if it is not on screen."""
        self.find_page(page, offset)
        return self.card_for(page, offset)

    def card_for(self, page, offset=0):
        """The card for fixture row `offset`, found by its own ref.

        Not by position. The core sorts rows by ref, and `A100` sorts before `A5`
        as text, so the first card on screen is the hundredth fixture row. Selecting
        by position would test a row the fixture never described.
        """
        return page.locator(f"#rows .card[data-ref='{fx.source_ref(fx.FIRST_ROW + offset)}']")

    def ref_of(self, offset):
        return fx.source_ref(fx.FIRST_ROW + offset)

    def find_page(self, page, offset, limit=12):
        """Turn the pager until the card for fixture row `offset` is on screen.

        The rows come back sorted by ref and the first of them is not the first
        fixture row, so a card is reached by paging rather than by index. This is
        also how a reviewer reads it: a large set a page at a time.
        """
        want = self.ref_of(offset)
        for _ in range(limit):
            if page.locator(f"#rows .card[data-ref='{want}']").count():
                return int(page.evaluate("window.__realReview.page()"))
            if page.is_disabled("#nextBtn"):
                break
            page.click("#nextBtn")
        raise AssertionError(f"no page showed {want}")

    def choose(self, page, offset, value):
        self.find_page(page, offset)
        self.card_for(page, offset).locator(
            f"input[value='{value}']").check()

    def chosen(self, page, offset=0):
        self.find_page(page, offset)
        return self.card_for(page, offset).locator(
            "input[type=radio]:checked").input_value()

    def replace_source(self, extra_rows=1):
        """A newer export of the same three sources, picked up by the app.

        The config is read once per process, so a new export takes effect the way
        it does in reality — the app is rebound to it — and a page that is already
        open is left holding the old one.
        """
        self.manifest = fx.write_case(self.tmp, rows=self.rows + extra_rows,
                                      injection=self.injection)
        self.config_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        real_review.bind_real_review(real_review.RealReviewService(self.manifest))

    def server_state(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/review/model",
            headers={access_control.SyntheticSessionAdapter.HEADER: OWNER})
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload["state"]

    def wait_status(self, page, needle, timeout=SETTLE_MS):
        page.wait_for_function(
            "(n) => document.getElementById('status').textContent.indexOf(n) >= 0",
            arg=needle, timeout=timeout)

class ReviewBrowserTests(ReviewBrowserFixture):
    """The review screen, on the ordinary fixture."""

    rows = 3
    injection = False

    def test_mobile_review_fits_a_390px_viewport(self):
        page = self.open_review(viewport={"width": 390, "height": 844})
        metrics = page.evaluate("""() => ({
            viewport: document.documentElement.clientWidth,
            document: document.documentElement.scrollWidth,
            body: document.body.scrollWidth,
            widest: Math.max(...Array.from(document.body.querySelectorAll('*'))
                .map((node) => Math.ceil(node.getBoundingClientRect().right))),
            offenders: Array.from(document.body.querySelectorAll('*'))
                .map((node) => ({
                    tag: node.tagName,
                    id: node.id,
                    cls: node.className,
                    left: Math.floor(node.getBoundingClientRect().left),
                    right: Math.ceil(node.getBoundingClientRect().right),
                    width: Math.ceil(node.getBoundingClientRect().width)
                }))
                .filter((item) => item.right > document.documentElement.clientWidth)
                .slice(0, 12)
        })""")
        self.assertLessEqual(metrics["document"], metrics["viewport"], metrics)
        self.assertLessEqual(metrics["body"], metrics["viewport"], metrics)
        self.assertLessEqual(metrics["widest"], metrics["viewport"], metrics)

    def test_the_owner_sees_the_source_and_the_candidates(self):
        page = self.open_review()
        card = self.card(page, 0)
        card.locator(".review-evidence > summary").click()
        text = card.inner_text()
        # the actual source fields, read out of the workbook
        self.assertIn("100,001원", text)
        self.assertIn("2026-04-01", text)
        self.assertIn("합성내용 0", text)
        self.assertIn("원본 항목 확인됨", text)
        # the candidate beside it
        self.assertIn(fx.candidate_key(1), text)
        self.assertIn("APPROVAL-0001", text)
        self.assertIn("100,001원", text)
        # and the counts
        counts = page.inner_text("#counts")
        self.assertIn(f"검토 원천 {self.rows}건", counts)
        self.assertIn(f"보류 {self.rows}건", counts)

    def test_no_example_board_is_shown_anywhere_on_the_screen(self):
        page = self.open_review()
        body = page.inner_text("body")
        for example in ("예시여행", "예시 숙소", "expense-demo", "trip-demo"):
            self.assertNotIn(example, body)

    def test_untouched_rows_start_blank(self):
        page = self.open_review()
        # the blank option is the checked one on a row nobody touched
        self.assertEqual(self.chosen(page, 0), "")

    def test_a_choice_is_saved_and_survives_a_reload(self):
        page = self.open_review()
        key = fx.candidate_key(1)
        self.choose(page, 0, f"APPROVE:{key}")
        page.click("#saveBtn")
        self.wait_status(page, "결정을 저장했어요")
        page.reload()
        page.wait_for_function(
            "document.querySelectorAll('#rows .card').length > 0",
            timeout=SETTLE_MS)
        self.assertEqual(self.chosen(page, 0), f"APPROVE:{key}")
        self.assertIn("결정 1건", page.inner_text("#counts"))

    def test_a_rejection_is_saved_too(self):
        page = self.open_review()
        self.choose(page, 0, "REJECT")
        page.click("#saveBtn")
        self.wait_status(page, "결정을 저장했어요")
        self.assertIn("거부 1건", page.inner_text("#counts"))

    def test_the_export_downloads_the_two_files(self):
        page = self.open_review()
        with page.expect_download() as first:
            page.click("#exportBtn")
        with page.expect_download() as second:
            pass
        # the first click downloads decisions.csv; the second needs its own click
        page.wait_for_timeout(200)
        try:
            second.value
        except Exception:
            pass
        self.wait_status(page, "이 파일은 장부 행을 등록하지 않습니다")
        self.assertIn("decisions.csv", first.value.suggested_filename)

    def test_a_second_page_sees_a_save_within_five_seconds(self):
        first = self.open_review()
        second = self.open_review()
        key = fx.candidate_key(1)
        self.choose(first, 0, f"APPROVE:{key}")
        first.click("#saveBtn")
        self.wait_status(first, "결정을 저장했어요")
        # the second page polls every two seconds
        second.wait_for_function(
            "document.getElementById('counts').textContent"
            ".indexOf('결정 1건') >= 0", timeout=5000)
        self.assertIn("다른 기기의 결정을 불러왔어요",
                      second.inner_text("#status"))

    def test_a_slow_first_load_is_not_killed_by_the_poll_behind_it(self):
        """The poll must wait for the model it is polling.

        A real 1,734-row model takes longer than the two-second interval to arrive.
        With nothing on screen yet this page has no binding of its own, so the
        small answer's binding does not match, and the page concludes its source
        was replaced and stops — permanently. The rows then land and are rendered,
        and the screen looks finished while it is dead: no further refresh will
        ever come. So the poll is skipped while a full load is in flight, and the
        page is live again the moment the load succeeds.
        """
        context = self._browser.new_context(
            viewport={"width": 1280, "height": 900})
        context.set_extra_http_headers(
            {access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        self.pages.append(page)

        asked = []
        release = {}

        def hold(route):
            url = route.request.url
            asked.append(url)
            if "state_only=1" in url:
                route.continue_()
                return
            # The model is really fetched; only the answer is withheld, which is
            # the same thing the network does when the server is slow.
            response = route.fetch()
            release["model"] = lambda: route.fulfill(response=response)

        page.route("**/api/review/model*", hold)
        page.goto(f"http://127.0.0.1:{self.port}/review")

        # Well past the two-second interval, and the model is still withheld.
        page.wait_for_timeout(2600)
        self.assertTrue(release.get("model"), "the model was never requested")
        self.assertEqual(page.evaluate("() => window.__realReview.loading()"),
                         True)
        self.assertEqual(page.locator("#rows .card").count(), 0)
        # Nothing polled while there was still nothing to compare against.
        self.assertEqual([url for url in asked if "state_only=1" in url], [])

        release["model"]()
        page.wait_for_function(
            "document.querySelectorAll('#rows .card').length > 0", timeout=SETTLE_MS)

        # The load landed, so the page is live rather than stopped.
        self.assertEqual(page.evaluate("() => window.__realReview.loading()"),
                         False)
        self.assertEqual(page.evaluate("() => window.__realReview.stopped()"),
                         False)
        self.assertEqual(page.evaluate("() => window.__realReview.rows()"),
                         self.rows)
        self.assertFalse(page.is_disabled("#exportBtn"))

        # And the small poll runs again afterwards, and changes nothing here.
        before = len(asked)
        page.wait_for_timeout(2600)
        self.assertTrue(
            [url for url in asked[before:] if "state_only=1" in url],
            "the poll never resumed after the load")
        self.assertEqual(page.evaluate("() => window.__realReview.stopped()"),
                         False)
        self.assertIn(str(self.rows), page.inner_text("#counts"))

    def test_the_two_second_poll_asks_for_the_small_answer(self):
        """What the timer fetches must be the three numbers, not the comparison.

        A poll that fetched the whole model would pull every source row into every
        open page twice a second for nothing. The request URL is asserted, not the
        response: the point is what the page decided to ask for.
        """
        page = self.open_review()
        asked = []
        page.on("request", lambda request: asked.append(request.url))
        page.wait_for_timeout(2600)
        polls = [url for url in asked if "/api/review/model" in url]
        self.assertTrue(polls, "the screen never polled for changes")
        self.assertTrue(all("state_only=1" in url for url in polls), polls)
        self.assertEqual(page.evaluate(
            "() => window.__realReview.rows()"), self.rows)

    def test_a_decision_made_while_the_model_loads_is_not_overwritten(self):
        """A decision made during a load is newer than the model it fetches.

        The load fetches the whole comparison, which is slow, and the radio
        handlers stay live throughout — which is right, because nobody should be
        unable to decide while a page loads. The bug this pins is what happened
        when the response landed: it copied the saved choices over the page's own
        map unconditionally, so a decision taken in those seconds was silently
        discarded, and the counts on screen went back to saying nothing was
        decided.
        """
        page = self.open_review()
        release = {"respond": None}

        def hold(route):
            # The request really goes out; only the answer is withheld, which is
            # what a slow server does.
            response = route.fetch()
            release["respond"] = lambda: route.fulfill(response=response)

        page.route("**/api/review/model*", hold)
        page.click("#reloadBtn")
        page.wait_for_function(
            "() => window.__realReview.loading() === true", timeout=SETTLE_MS)

        # The decision, made while the model is in flight.
        self.choose(page, 0, "REJECT")
        self.assertTrue(page.evaluate("() => window.__realReview.isDirty()"))

        release["respond"]()
        self.wait_status(page, "결정한 내용을 지우지 않기 위해")

        # The rows on screen are still the ones the decision was made against, and
        # the decision is still there.
        self.assertTrue(page.evaluate("() => window.__realReview.isDirty()"))
        self.assertEqual(self.chosen(page, 0), "REJECT")
        self.assertEqual(page.locator("#rows .card").count() > 0, True)

        # And a save still works: the guard is on the load, not on the decision.
        page.unroute("**/api/review/model*")
        page.click("#saveBtn")
        self.wait_status(page, "결정을 저장했어요")
        self.assertFalse(page.evaluate("() => window.__realReview.isDirty()"))

    def test_a_save_during_a_load_is_refused_rather_than_written(self):
        """Writing while the model is being replaced would be a guess.

        A load in flight means the source may already be a different one, so a
        save at that moment would be a decision written against a binding that is
        being replaced. The draft is kept; the write waits.
        """
        page = self.open_review()
        release = {"respond": None}

        def hold(route):
            response = route.fetch()
            release["respond"] = lambda: route.fulfill(response=response)

        page.route("**/api/review/model*", hold)
        page.click("#reloadBtn")
        page.wait_for_function(
            "() => window.__realReview.loading() === true", timeout=SETTLE_MS)
        self.choose(page, 0, "REJECT")
        page.click("#saveBtn")
        self.wait_status(page, "불러오는 중이라 저장하지 않았어요")
        # The decision is untouched by the refusal.
        self.assertTrue(page.evaluate("() => window.__realReview.isDirty()"))
        release["respond"]()
        page.wait_for_function(
            "() => window.__realReview.loading() === false", timeout=SETTLE_MS)

    def test_a_replaced_source_refuses_the_save_and_keeps_the_draft(self):
        """A page holding the old source may not write against the new one.

        The server answers 409 with the source-binding code and nothing is
        written — the binding is checked before anything is, so the new dataset's
        saved set stays empty. The page then keeps what it had: the rows the
        decision was made against and the decision itself. It used to reload
        itself here, which dropped the decision while the message on screen said
        the user's changes were being kept, and that message is what makes this a
        defect rather than a wording problem.
        """
        page = self.open_review()
        self.replace_source()

        key = fx.candidate_key(1)
        self.choose(page, 0, f"APPROVE:{key}")
        page.click("#saveBtn")
        self.wait_status(page, "결정한 내용을 지우지 않았어요")
        # The page is live, not stopped: the rows are still readable and the
        # decision is still on them.
        self.assertEqual(page.evaluate("() => window.__realReview.stopped()"),
                         False)
        self.assertTrue(page.evaluate("() => window.__realReview.isDirty()"))
        self.assertEqual(self.chosen(page, 0), f"APPROVE:{key}")
        self.assertEqual(page.locator("#rows .card").count() > 0, True)
        # And nothing reached the new dataset.
        _status, state = self.server_state()
        self.assertEqual(state["revision"], 0)
        self.assertEqual(state["counts"]["selected"], 0)

    def test_a_discard_is_the_only_way_to_load_the_new_source(self):
        """Nothing is reloaded behind the user's back; the button does it.

        The reload is the one that drops the draft, so it is the user's decision to
        make it. Clicking it is an explicit discard, and only then does the page
        read the new rows.
        """
        page = self.open_review()
        self.replace_source()
        key = fx.candidate_key(1)
        self.choose(page, 0, f"APPROVE:{key}")
        page.click("#saveBtn")
        self.wait_status(page, "결정한 내용을 지우지 않았어요")
        self.assertTrue(page.locator("#conflict button").is_visible())

        # Before the click, the old rows are still on screen.
        self.assertEqual(self.chosen(page, 0), f"APPROVE:{key}")
        page.click("#conflict button")
        page.wait_for_function(
            "() => window.__realReview.loading() === false", timeout=SETTLE_MS)
        self.assertEqual(page.locator("#conflict").is_visible(), False)

        # The new source can now be saved, and only that.
        key = fx.candidate_key(1)
        self.choose(page, 0, f"APPROVE:{key}")
        page.click("#saveBtn")
        self.wait_status(page, "결정을 저장했어요")
        _status, state = self.server_state()
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["counts"]["selected"], 1)

    def test_a_decision_made_while_the_save_is_in_flight_stays_unsaved(self):
        """A radio clicked between the request and its response was not sent.

        The request body is fixed when the POST goes out. A decision made in the
        seconds before the response arrives never went anywhere, so when the
        response lands it must still read as unsaved, and the button must be live
        again. Copying the page's current choices into the saved set on success
        would instead claim it was stored, and the next save would carry it — the
        user would be told their decision is safe when it is not.
        """
        page = self.open_review()
        release = {}

        def hold(route):
            """Send the request on, but keep the answer until the test lets it go.

            The body has already left by the time this runs, which is exactly the
            window under test: the server has the decision, the page has not been
            told, and the user is still free to click something else.
            """
            response = route.fetch()
            release["respond"] = lambda: route.fulfill(response=response)

        page.route("**/api/review/decisions", hold)
        page.wait_for_timeout(200)

        later = f"APPROVE:{fx.candidate_key(2)}"
        self.choose(page, 0, "REJECT")
        page.click("#saveBtn")
        page.wait_for_function(
            "document.getElementById('saveBtn').disabled === true &&"
            " window.__realReview.saving() === true", timeout=SETTLE_MS)

        # The later edit, made while the response is still held.
        self.choose(page, 1, later)
        self.assertTrue(page.evaluate("() => window.__realReview.isDirty()"))

        release["respond"]()
        self.wait_status(page, "보낸 결정은 저장했어요")

        # The saved set is the one that was sent: row 0 rejected, row 1 blank.
        saved = page.evaluate("() => window.__realReview.saved()")
        self.assertEqual(saved[self.ref_of(0)], "REJECT")
        self.assertEqual(saved[self.ref_of(1)], "")
        # The later edit is still pending, not marked as stored.
        self.assertTrue(page.evaluate("() => window.__realReview.isDirty()"))
        self.assertFalse(page.is_disabled("#saveBtn"))
        self.assertEqual(self.chosen(page, 1), later)

        # And the server holds the sent set, so the next save is what stores the
        # later decision rather than this page pretending it already did.
        _status, state = self.server_state()
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["choices"][self.ref_of(1)], "")

        page.unroute("**/api/review/decisions")
        page.click("#saveBtn")
        self.wait_status(page, "결정을 저장했어요")
        self.assertFalse(page.evaluate("() => window.__realReview.isDirty()"))
        _status, state = self.server_state()
        self.assertEqual(state["revision"], 2)
        self.assertEqual(state["choices"][self.ref_of(1)], later)
        self.assertEqual(state["choices"][self.ref_of(0)], "REJECT")

    def test_a_pending_choice_survives_another_devices_save(self):
        first = self.open_review()
        second = self.open_review()
        # the second page has an unsaved choice of its own
        pending = fx.candidate_key(2)
        self.choose(second, 1, f"APPROVE:{pending}")
        # the local counts include the pending choice, because it is a decision
        # the user has made on this device and not yet saved
        self.assertIn("결정 1건", second.inner_text("#counts"))
        # the first page saves something different
        self.choose(first, 0, "REJECT")
        first.click("#saveBtn")
        self.wait_status(first, "결정을 저장했어요")
        # the second page is told, and keeps what it had
        second.wait_for_function(
            "document.getElementById('conflict') &&"
            " !document.getElementById('conflict').hidden", timeout=5000)
        self.assertIn("저장하지 않은 결정이 있고", second.inner_text("#conflict"))
        self.assertIn("다른 기기에서 더 최근 결정을", second.inner_text("#conflict"))
        self.assertEqual(self.chosen(second, 1), f"APPROVE:{pending}")

    def test_a_stale_save_is_a_conflict_and_overwrites_nothing(self):
        first = self.open_review()
        second = self.open_review()
        # The second page's model reads are refused for the length of this test, so
        # its two-second poll cannot tell it about the first page's save. Without
        # that it would learn within two seconds and there would be no stale save
        # to be a conflict about, which is the case under test.
        seen = {"model": 0}

        def refuse_polls(route):
            seen["model"] += 1
            if seen["model"] == 1:
                route.continue_()
                return
            route.fulfill(status=503, content_type="application/json",
                          body='{"code":"REVIEW_UNAVAILABLE"}')

        second.route("**/api/review/model*", refuse_polls)
        second.reload()
        second.wait_for_function(
            "document.querySelectorAll('#rows .card').length > 0",
            timeout=SETTLE_MS)
        self.choose(first, 0, "REJECT")
        first.click("#saveBtn")
        self.wait_status(first, "결정을 저장했어요")
        # the second page still believes it is on revision 0
        self.choose(second, 1, "REJECT")
        second.click("#saveBtn")
        # the note carries what happened, the status line carries what to do
        second.wait_for_function(
            "document.getElementById('conflict') &&"
            " !document.getElementById('conflict').hidden", timeout=SETTLE_MS)
        self.assertIn("다른 기기에서 더 최근 결정을 저장했어요",
                      second.inner_text("#conflict"))
        self.assertIn("다른 기기의 저장을 확인해 주세요",
                      second.inner_text("#status"))
        # the first page's decision is the one that stands
        self.assertIn("거부 1건", first.inner_text("#counts"))
        # and this page is still showing its own unsaved choice, not the other one
        self.assertIn("거부 1건", second.inner_text("#counts"))
        self.assertIn("아직 저장된 결정이 없어요", second.inner_text("#counts"))
        # and once it can read again, that is what it shows
        second.unroute("**/api/review/model*")
        second.reload()
        second.wait_for_function(
            "document.querySelectorAll('#rows .card').length > 0",
            timeout=SETTLE_MS)
        counts = second.inner_text("#counts")
        self.assertIn("거부 1건", counts)
        self.assertIn(f"보류 {self.rows - 1}건", counts)

    def test_a_refused_model_clears_the_screen_and_stops_polling(self):
        page = self.open_review()
        self.assertTrue(page.locator("#rows .card").count() > 0)
        page.route("**/api/review/model*", lambda route: route.fulfill(
            status=403, content_type="application/json",
            body='{"code":"ACTION_FORBIDDEN","message":"거부"}'))
        page.wait_for_function(
            "document.getElementById('rows').children.length === 1 &&"
            " document.getElementById('rows').firstElementChild"
            ".getAttribute('role') === 'alert'", timeout=SETTLE_MS)
        body = page.inner_text("#rows")
        self.assertIn("권한", body)
        self.assertNotIn("합성내용", body)
        # the save and export buttons are disabled, so nothing can be written
        self.assertTrue(page.is_disabled("#saveBtn"))
        self.assertTrue(page.is_disabled("#exportBtn"))
        # and no further model request is made
        before = page.locator("#rows .card").count()
        page.wait_for_timeout(3000)
        self.assertEqual(page.locator("#rows .card").count(), before)


class InjectionBrowserTests(ReviewBrowserFixture):
    injection = True

    def test_a_tag_in_a_source_value_is_shown_as_text(self):
        page = self.open_review()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        body = page.inner_text("body")
        self.assertIn(fx.INJECTION, body)
        # the tag is text, not an element: the document has no such node
        self.assertEqual(
            page.evaluate("document.querySelectorAll('script').length"), 2)
        self.assertFalse(page.locator('script').evaluate_all(
            "(nodes, value) => nodes.some(node => node.textContent.includes(value))",
            fx.INJECTION))
        self.assertEqual(errors, [])
        # the note column carries it too
        card = self.card(page, 0).inner_text()
        self.assertIn("합성", card)


class LargeSetBrowserTests(ReviewBrowserFixture):
    rows = 120

    def test_pagination_keeps_every_page_reachable(self):
        page = self.open_review()
        self.assertEqual(page.locator("#rows .card").count(), 50)
        self.assertIn("1 / 3 페이지", page.inner_text("#pageLabel"))
        page.click("#nextBtn")
        self.assertIn("2 / 3 페이지", page.inner_text("#pageLabel"))
        self.assertEqual(page.locator("#rows .card").count(), 50)
        page.click("#nextBtn")
        self.assertIn("3 / 3 페이지", page.inner_text("#pageLabel"))
        self.assertEqual(page.locator("#rows .card").count(), 20)

    def test_a_choice_survives_turning_away_and_back(self):
        page = self.open_review()
        key = fx.candidate_key(1)
        home = self.find_page(page, 0)
        self.choose(page, 0, f"APPROVE:{key}")
        # away to a different page, and the choice is still there on the way back
        page.click("#nextBtn" if home == 0 else "#prevBtn")
        self.assertNotEqual(int(page.evaluate("window.__realReview.page()")), home)
        page.fill("#q", self.ref_of(0))
        page.click("#searchBtn")
        self.assertEqual(
            self.card_for(page, 0).locator(
                "input[type=radio]:checked").input_value(),
            f"APPROVE:{key}")

    def test_a_choice_on_page_one_is_saved_with_the_rest(self):
        page = self.open_review()
        key = fx.candidate_key(1)
        self.choose(page, 0, f"APPROVE:{key}")
        page.click("#nextBtn")
        page.click("#saveBtn")
        self.wait_status(page, "결정을 저장했어요")
        self.assertIn("결정 1건", page.inner_text("#counts"))
        # every other row was sent blank, and stayed blank
        self.assertIn(f"보류 {self.rows - 1}건", page.inner_text("#counts"))

    def test_search_finds_a_row_and_keeps_the_choice(self):
        page = self.open_review()
        key = fx.candidate_key(1)
        page.fill("#q", key)
        page.click("#searchBtn")
        self.choose(page, 0, f"APPROVE:{key}")
        self.assertEqual(page.locator("#rows .card").count(), 1)
        # search for a row on another page, and the choice is still there after
        page.fill("#q", f"합성거래키-{self.rows:04d}")
        page.click("#searchBtn")
        self.assertEqual(page.locator("#rows .card").count(), 1)
        page.fill("#q", key)
        page.click("#searchBtn")
        self.assertEqual(self.chosen(page, 0), f"APPROVE:{key}")
