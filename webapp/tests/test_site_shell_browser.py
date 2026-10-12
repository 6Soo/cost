import os
from unittest.mock import patch

from webapp import access_control, google_ledger_page
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class SiteShellBrowserTests(LinkBrowserFixture):
    def prepare_pages(self, width):
        env = patch.dict(os.environ, {
            'WEBLEDGER_CARD_FLOW': '1', 'WEBLEDGER_RECEIPTS_STORE': str(self.tmp / 'receipts.json'),
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(self.tmp / 'google.json'),
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(self.tmp / 'rows.json'),
        })
        env.start()
        self.addCleanup(env.stop)
        fake = patch.object(google_ledger_page.google_authority, 'load_consistent',
                            return_value=(healthy_snapshot(), rows_doc()['sources']))
        fake.start()
        self.addCleanup(fake.stop)
        context = self.browser.new_context(viewport={'width': width, 'height': 900})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        return context.new_page(), f'http://127.0.0.1:{self.port}'

    def test_same_sidebar_on_all_work_screens_at_desktop(self):
        page, base = self.prepare_pages(1440)
        menu = None
        for path in ('/', '/board', '/import', '/cards', '/receipts', '/google-ledger', '/reserve-links', '/trips', '/access/admin'):
            with self.subTest(path=path):
                response = page.goto(base + path)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator('#nav').count(), 1)
                links = page.locator('#nav a[href]').evaluate_all('(items)=>items.map(a=>a.getAttribute("href"))')
                if menu is None:
                    menu = links
                self.assertEqual(links, menu)
                self.assertEqual(page.locator('#nav').bounding_box()['x'], 0)
                main = page.locator('#site-content') if page.locator('#site-content').count() else page.locator('#main')
                self.assertGreaterEqual(main.bounding_box()['x'], 232)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 1440)

    def test_mobile_menu_navigation_and_input_are_usable(self):
        page, base = self.prepare_pages(390)
        page.goto(base + '/cards')
        page.get_by_label('카드 내역 검색').fill('Synthetic draft')
        page.get_by_role('button', name='전체 메뉴 열기').click()
        self.assertIn('open', page.locator('#nav').get_attribute('class'))
        page.keyboard.press('Escape')
        self.assertNotIn('open', page.locator('#nav').get_attribute('class'))
        self.assertEqual(page.get_by_label('카드 내역 검색').input_value(), 'Synthetic draft')
        page.get_by_role('button', name='전체 메뉴 열기').click()
        page.locator('#nav a[href="/import"]').first.click()
        self.assertEqual(page.url, base + '/import')
        self.assertEqual(page.locator('#nav').count(), 1)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.get_by_role('button', name='전체 메뉴 열기').click()
        page.locator('#nav a[href="/cards"]').click()
        self.assertEqual(page.url, base + '/cards')
        self.assertEqual(page.locator('#nav a[href="/cards"]').get_attribute('aria-current'), 'page')
        page.goto(base + '/board')
        page.get_by_role('button', name='전체 메뉴 열기').click()
        self.assertIn('open', page.locator('#nav').get_attribute('class'))
        page.keyboard.press('Escape')
        self.assertNotIn('open', page.locator('#nav').get_attribute('class'))
