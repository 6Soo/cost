import json
import os
from unittest.mock import patch

from webapp import access_control
from webapp.tests.test_ota_catalog import source_database
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class OtaCatalogBrowserTests(LinkBrowserFixture):
    def test_shared_menu_all_unassigned_search_and_header_filters(self):
        source = self.tmp / 'ota.sqlite'
        source_database(source)
        env = patch.dict(os.environ, {
            'WEBLEDGER_OTA_SOURCES_JSON': json.dumps({'portal_databases': [str(source)], 'mail_directories': []}),
            'WEBLEDGER_REVIEW_CONFIG': '',
        })
        env.start()
        self.addCleanup(env.stop)
        original = source.read_bytes()
        before = self.server.card_store.conn.total_changes
        for width in (390, 1440):
            with self.subTest(width=width):
                context = self.browser.new_context(viewport={'width': width, 'height': 900})
                self.addCleanup(context.close)
                context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
                page = context.new_page()
                page.goto(f'http://127.0.0.1:{self.port}/board')
                if width < 760:
                    page.get_by_role('button', name='전체 메뉴 열기', exact=True).click()
                page.locator('#nav').get_by_role('link', name='OTA 전체 내역', exact=False).click()
                self.assertEqual(page.locator('#nav').count(), 1)
                self.assertIn('전체 3건', page.inner_text('#card-count'))
                self.assertEqual(page.locator('tbody tr').count(), 3)
                page.locator('main').get_by_role('link', name='OTA 미배정 내역', exact=True).click()
                self.assertEqual(page.locator('tbody tr').count(), 2)
                self.assertIn('BOOK-2', page.inner_text('tbody'))
                self.assertIn('취소', page.inner_text('tbody'))
                page.get_by_label('OTA 내역 검색').fill('BOOK-2')
                page.get_by_role('button', name='검색', exact=True).click()
                self.assertEqual(page.locator('tbody tr').count(), 1)
                page.reload()
                self.assertEqual(page.get_by_label('OTA 내역 검색').input_value(), 'BOOK-2')
                self.assertEqual(page.locator('input[name="state"]').input_value(), 'unassigned')
                page.get_by_role('link', name='초기화', exact=True).click()
                page.get_by_role('button', name='이용일', exact=True).click()
                with page.expect_navigation():
                    page.get_by_role('button', name='오름차순 · 이른 이용 먼저', exact=True).click()
                self.assertIn('2026-10-01', page.locator('tbody tr').first.inner_text())
                page.get_by_role('button', name='이용일', exact=True).click()
                with page.expect_navigation():
                    page.get_by_role('button', name='2026-11월', exact=True).click()
                self.assertEqual(page.locator('tbody tr').count(), 1)
                self.assertIn('BOOK-1', page.inner_text('tbody'))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                context.close()
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.server.card_store.conn.total_changes, before)
