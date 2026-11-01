"""Synthetic owner-filter interaction against the disposable product test server."""
import unittest
from webapp.tests import test_ledger_design_state as state

class AndreFilterBrowserTests(unittest.TestCase):
    setUp = state.ViewStateTests.setUp
    tearDown = state.ViewStateTests.tearDown
    _page = state.ViewStateTests._page
    _url = state.ViewStateTests._url

    def test_owner_filter_url_keyboard_and_responsive_layout(self):
        for owner in ('aslan','andre'):
            self.store.create_trip(starts_on='2026-10-22',ends_on='2026-10-23',destination='합성 필터',
                display_key='andre::2026::1022_합성 필터' if owner=='andre' else '1022_합성 필터',
                client_request_id='filter-'+owner,actor='google-sync')
        before=list(self.store.conn.iterdump())
        for width in (1440,390):
            with self.subTest(width=width):
                page=self._page(width)
                page.goto(f'http://127.0.0.1:{self.port}/trips?owner=andre')
                selector=page.locator('#trip-management-owner')
                self.assertEqual(selector.input_value(),'andre')
                self.assertEqual(page.locator('.trip-management-row:visible').count(),1)
                self.assertEqual(page.locator('.trip-management-row:visible').get_attribute('data-owner'),'andre')
                self.assertNotIn('andre::2026::',page.locator('.trip-management-row:visible h3').inner_text())
                selector.focus();selector.press('Home');selector.press('ArrowDown');selector.press('Enter')
                self.assertEqual(selector.input_value(),'aslan')
                self.assertIn('owner=aslan',page.url)
                self.assertEqual(page.locator(".trip-management-row[data-owner='andre']:visible").count(),0)
                selector.select_option('andre')
                page.reload()
                self.assertEqual(page.locator('#trip-management-owner').input_value(),'andre')
                self.assertEqual(page.locator('.trip-management-row:visible').count(),1)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.close()
        self.assertEqual(list(self.store.conn.iterdump()),before)
