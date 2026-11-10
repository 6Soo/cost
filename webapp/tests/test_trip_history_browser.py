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
                page.goto(base + "/trips?state=previous")
                self.assertEqual(page.locator(f"#manage-{old['tab_id']}").count(), 1)
                self.assertEqual(page.locator(f"#manage-{new['tab_id']}").count(), 0)
                old_link = page.locator(f"#manage-{old['tab_id']} h3 a")
                self.assertTrue(old_link.is_visible())
                old_link.click()
                page.wait_for_url("**/board?tab=" + old['tab_id'])
                self.assertEqual(page.locator("#previous-trips, #archived").count(), 0)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
