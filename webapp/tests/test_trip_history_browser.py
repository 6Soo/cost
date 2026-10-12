from webapp.tests.test_reserve_link_browser import LinkBrowserFixture
from webapp.tests import test_site_shell_browser as shell_browser


class TripHistoryBrowserTests(LinkBrowserFixture):
    prepare_pages = shell_browser.SiteShellBrowserTests.prepare_pages

    def test_previous_trips_open_and_link_to_existing_ledger_at_both_widths(self):
        old = self.server.card_store.create_trip(
            starts_on="2026-06-25", ends_on="2026-06-28", destination="Synthetic old",
            display_key="Synthetic June 25", client_request_id="synthetic-previous-trip")
        new = self.server.card_store.create_trip(
            starts_on="2026-06-26", destination="Synthetic new",
            display_key="Synthetic June 26", client_request_id="synthetic-current-trip")
        for width in (390, 1440):
            with self.subTest(width=width):
                page, base = self.prepare_pages(width)
                page.goto(base + "/cards")
                if width == 390:
                    page.get_by_role("button", name="전체 메뉴 열기").click()
                history = page.locator("#previous-trips")
                self.assertEqual(history.count(), 1)
                self.assertFalse(history.evaluate("el=>el.open"))
                self.assertEqual(page.locator(f"#trips a[href*='tab={old['tab_id']}']").count(), 0)
                self.assertEqual(page.locator(f"#trips a[href*='tab={new['tab_id']}']").count(), 1)
                history.locator("summary").click()
                self.assertTrue(history.evaluate("el=>el.open"))
                history.locator(f"a[href*='tab={old['tab_id']}']").click()
                page.wait_for_url("**/board?tab=" + old['tab_id'])
                # Default collapsed for any selected/previous trip (new rule);
                # user click opens it.
                self.assertFalse(page.locator("#previous-trips").evaluate("el=>el.open"))
                self.assertEqual(page.locator("#previous-trips a[aria-pressed='true']").count(), 1)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
