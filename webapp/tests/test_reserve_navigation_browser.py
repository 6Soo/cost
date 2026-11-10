"""RESERVE-NAVIGATION-001, through a real browser: the way in and the way out.

The static tests already pin that the header carries the link and that the
linking document carries the two return links. This file walks the path the way
an owner does, because the thing that was broken was not the markup. It was that
nobody could get there without typing an address.

Two flows, both against synthetic data:

* an owner opens the ledger, finds the entry link, follows it, and gets the
  linking screen. Then the screen's own return links are followed, and each one
  answers with a document rather than a 404.
* a viewer opens the same ledger and is shown no entry link at all, and asking
  for the address directly is still refused.

The return link to the real-source comparison is followed and asserted to answer
with a served document, which may be the unconfigured page. That is the honest
check: the link must not be a dead one, and a 503 that explains the review is not
configured is a better answer than a 404 that looks like a broken button.

Nothing here reads a real roster.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webapp import access_control  # noqa: E402
from webapp.tests.test_reserve_link import OWNER  # noqa: E402
from webapp.tests.test_reserve_link_browser import (  # noqa: E402
    LinkBrowserFixture, sync_playwright)
from webapp.tests.test_real_review_browser import SETTLE_MS  # noqa: E402


class NavigationBrowserFixture(LinkBrowserFixture):
    """The linking server, plus a ledger page that links to it."""

    def setUp(self):
        super().setUp()
        from webapp import ledger_board
        trip = ledger_board._active_store().create_trip(
            starts_on='2026-10-01', ends_on='2026-10-03', destination='Synthetic',
            client_request_id='navigation-trip')
        self.trip_id = trip['tab_id']
        self.served.conn.execute('INSERT INTO trip_tabs(tab_id, display_key) VALUES (?, ?)',
                                 (self.trip_id, 'Synthetic'))

    def board_page(self, user=OWNER):
        context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.addCleanup(context.close)
        context.set_extra_http_headers(
            {access_control.SyntheticSessionAdapter.HEADER: user})
        page = context.new_page()
        suffix = '?tab=' + self.trip_id if user == OWNER else ''
        response = page.goto(f"http://127.0.0.1:{self.port}/board" + suffix)
        return response, page

    def wait_ready(self, page):
        page.wait_for_function(
            "() => document.readyState === 'complete'", timeout=SETTLE_MS)
        return page


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class OwnerNavigationTests(NavigationBrowserFixture):
    def test_trip_filter_save_keeps_other_trips_and_allows_unlinked_search(self):
        from webapp import reserve_link
        plan = reserve_link.build_plan(self.served, self.snapshot)
        reserve_link.save_links(self.served, self.snapshot, {
            'request_id': 'seed-navigation', 'source_binding': self.bind(),
            'link_revision': plan['link_revision'], 'unlinks': [],
            'links': [{'source_event_key': 'reservation:cafeParse:ALFA', 'target_tab_id': self.trip_id},
                      {'source_event_key': 'reservation:cafeParse:BRAVO', 'target_tab_id': 'COST-TRIP-BRAVO'}],
        }, owner_id=OWNER)
        _, page = self.board_page()
        page.get_by_role('tab', name='예약 연결').click()
        page.locator('#trip-reservations > summary').click()
        frame = page.frame_locator('#trip-reservations iframe')
        frame.locator('#linkFilter').wait_for()
        self.assertEqual(frame.locator('.linktable tbody tr:not(.is-hidden)').count(), 1)
        frame.locator('select[data-source="reservation:cafeParse:ALFA"]').select_option([self.trip_id, 'COST-TRIP-ALFA'])
        frame.locator('#saveBtn').click()
        frame.locator('#state').filter(has_text='연결을 저장했어요').wait_for()
        after = reserve_link.build_plan(self.served, self.snapshot)
        self.assertEqual(after['per_identifier']['reservation:cafeParse:BRAVO'], ['COST-TRIP-BRAVO'])
        self.assertEqual(set(after['per_identifier']['reservation:cafeParse:ALFA']), {self.trip_id, 'COST-TRIP-ALFA'})
        frame.locator('#linkFilter').select_option('unlinked')
        self.assertEqual(frame.locator('.linktable tbody tr:not(.is-hidden)').count(), 0)
        self.assertIn('조건에 맞는 예약 건이 없습니다', frame.locator('#emptyFilter').inner_text())

    def test_the_owner_finds_the_link_and_follows_it_to_the_linking_screen(self):
        """The whole point: no address typed, no bookmark needed."""
        response, page = self.board_page()
        self.wait_ready(page)
        self.assertEqual(response.status, 200)
        link = page.get_by_role('tab', name='예약 연결')
        self.assertTrue(link.is_visible(), "the owner ledger carries no reservation tab")
        link.click()
        page.locator('#trip-reservations > summary').click()
        frame = page.frame_locator('#trip-reservations iframe')
        frame.locator('#linkFilter').wait_for()
        self.assertEqual(frame.locator('#linkFilter').input_value(), 'trip')
        self.assertIn('#trip-reservations', page.url)
        self.assertEqual(page.locator('#trip-reservations').get_attribute('open'), '')
        self.assertIn('전체 명단 작업', frame.locator('body').inner_text())

    def test_the_linking_screen_reaches_the_ledger_and_the_review_screen(self):
        """A screen with no way out is a screen an owner opens once."""
        _response, page = self.board_page()
        self.wait_ready(page)
        page.goto(f"http://127.0.0.1:{self.port}/reserve-links?trip={self.trip_id}")
        page.wait_for_function("() => window.__reserveLink !== undefined",
                               timeout=SETTLE_MS)

        board = page.query_selector("#back-board")
        review = page.query_selector("#back-review")
        self.assertIsNotNone(board, "no return link to the ledger")
        self.assertIsNotNone(review, "no return link to the source review")
        self.assertEqual(board.get_attribute("href"), "/board?tab=" + self.trip_id)
        self.assertEqual(review.get_attribute("href"), "/review")
        self.assertIn("장부", board.inner_text())
        self.assertIn("실제 자료", review.inner_text())

        # The ledger really answers. A link that 404s reads as a broken button.
        board.click()
        page.wait_for_function(
            "() => document.readyState === 'complete'", timeout=SETTLE_MS)
        self.assertIn("/board", page.url)

    def test_the_review_return_link_answers_with_a_document(self):
        """Not a 404.

        The comparison is unconfigured in this environment, so the answer is the
        unconfigured page rather than the comparison itself. Either is a served
        document; a 404 would mean the link names an address that does not exist.
        """
        _response, page = self.board_page()
        self.wait_ready(page)
        page.goto(f"http://127.0.0.1:{self.port}/reserve-links?trip={self.trip_id}")
        page.wait_for_function("() => window.__reserveLink !== undefined",
                               timeout=SETTLE_MS)
        page.click("#back-review")
        page.wait_for_function(
            "() => document.readyState === 'complete'", timeout=SETTLE_MS)
        body = page.inner_text("body")
        self.assertNotIn("Not Found", body)
        self.assertTrue(body.strip(), "the review route returned an empty body")

    def test_the_return_links_survive_the_configuration_required_state(self):
        """The links are in the document, not added by the fetch.

        When the source is not configured the screen says so and refuses to do
        anything. That is the state an owner is most likely to land in first, so
        it is the state where being unable to get back out would matter most.
        """
        import os

        from webapp import reserve_link
        saved = os.environ.pop(reserve_link.CONFIG_ENV, None)
        try:
            context = self.browser.new_context()
            self.addCleanup(context.close)
            context.set_extra_http_headers(
                {access_control.SyntheticSessionAdapter.HEADER: OWNER})
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{self.port}/reserve-links")
            page.wait_for_function(
                "() => window.__reserveLink !== undefined", timeout=SETTLE_MS)
            self.assertIsNotNone(page.query_selector("#back-board"))
            self.assertIsNotNone(page.query_selector("#back-review"))
            # The state line names the configuration-required code, and the
            # screen invents no source to avoid saying it. The code is asserted
            # rather than the sentence: the wording is a copy decision and the
            # fixed code is what a caller branches on.
            state = page.locator("#state").get_attribute("data-code")
            self.assertIn(reserve_link.CODE_CONFIG_REQUIRED, state)
            self.assertIn("예약 명단 연결 대기", page.inner_text("#state"))
            self.assertEqual(page.query_selector("#saveBtn").is_disabled(), True)
            self.assertEqual(page.query_selector("#applyBtn").is_disabled(), True)
        finally:
            if saved is not None:
                os.environ[reserve_link.CONFIG_ENV] = saved


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class ViewerNavigationTests(NavigationBrowserFixture):
    """A viewer must not be shown the entry, and must still be refused at it.

    The viewer here is the one the fixture already grants. `LinkBrowserFixture`
    creates and approves that account in its own setUp, so granting it a second
    time is refused by the store for a good reason: a person may hold one
    active application, and this is the same person.
    """

    VIEWER = "syn-staff-1"

    def test_a_viewer_is_shown_no_entry_link(self):
        """A viewer must not be shown a link to a screen that refuses them."""
        response, page = self.board_page(self.VIEWER)
        self.wait_ready(page)
        self.assertEqual(response.status, 200)
        self.assertIsNone(page.query_selector("#reserve-link"))
        self.assertEqual(page.locator('a[href^="/reserve-links"], #trip-reservations iframe').count(), 0)

    def test_a_viewer_asking_for_the_address_directly_is_still_refused(self):
        """The link is a convenience; the server gate is the decision.

        Withholding the markup must not be the only thing standing between a
        viewer and the screen, so the route is asked for by address here.
        """
        page = self.open_screen(self.VIEWER, expect_refused=True)
        self.assertNotIn("<select", page.content())


if __name__ == "__main__":
    unittest.main()
