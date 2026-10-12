import json
import os
from unittest.mock import patch

from webapp import access_control
from webapp.card_flow import CardFlow
from webapp.tests.test_card_flow import CARD, PAIR
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class CardCatalogBrowserTests(LinkBrowserFixture):
    def test_header_buttons_sort_and_filter_without_search_click(self):
        env = patch.dict(os.environ, {'WEBLEDGER_CARD_FLOW': '1', 'WEBLEDGER_UNIFIED_DB': '1'})
        env.start()
        self.addCleanup(env.stop)
        flow = CardFlow(self.server.card_store)
        flow.pipeline.receive(CARD, 'first.csv')
        flow.pipeline.receive(PAIR, 'second.csv')
        conn = self.server.card_store.conn
        ids = [r[0] for r in conn.execute('SELECT transaction_id FROM transactions ORDER BY transaction_id')]
        for txid, date in zip(ids, ['2026-02-20', '2026-01-05', '2026-02-10']):
            conn.execute('UPDATE transactions SET approval_date=? WHERE transaction_id=?', (date, txid))
        conn.commit()
        before = conn.total_changes
        for width in (375, 390, 1440):
            with self.subTest(width=width):
                context = self.browser.new_context(viewport={'width': width, 'height': 900})
                self.addCleanup(context.close)
                context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
                page = context.new_page()
                page.goto(f'http://127.0.0.1:{self.port}/cards')
                self.assertEqual(page.locator('.catalog-actions .catalog-btn').count(), 3)
                self.assertEqual(page.locator('#card-filters button').evaluate(
                    "e=>getComputedStyle(e).backgroundColor"), 'rgb(28, 122, 82)')
                self.assertEqual(page.locator('thead select').count(), 0)
                self.assertTrue(page.get_by_role('button', name='거래일', exact=True).is_visible())
                self.assertEqual(page.locator('tbody tr').first.locator('td').first.inner_text(), '2026-02-20')
                page.get_by_role('button', name='거래일', exact=True).click()
                with page.expect_navigation():
                    page.get_by_role('button', name='오름차순 · 오래된 거래 먼저', exact=True).click()
                self.assertEqual(page.locator('tbody tr').first.locator('td').first.inner_text(), '2026-01-05')
                page.get_by_role('button', name='거래일', exact=True).click()
                with page.expect_navigation():
                    page.get_by_role('button', name='2026년 02월', exact=True).click()
                self.assertEqual(page.locator('tbody tr').count(), 2)
                self.assertEqual(page.locator('tbody tr').first.locator('td').first.inner_text(), '2026-02-10')
                page.get_by_role('button', name='카드', exact=True).click()
                page.keyboard.press('Escape')
                self.assertEqual(page.get_by_role('button', name='카드', exact=True).get_attribute('aria-expanded'), 'false')
                page.get_by_role('button', name='카드', exact=True).click()
                with page.expect_navigation():
                    page.get_by_role('button', name='1234', exact=True).click()
                self.assertEqual(page.locator('input[name="month"]').input_value(), '2026-02')
                page.reload()
                self.assertEqual(page.locator('input[name="sort"]').input_value(), 'asc')
                self.assertEqual(page.locator('input[name="month"]').input_value(), '2026-02')
                page.get_by_role('button', name='거래일', exact=True).click()
                with page.expect_navigation():
                    page.get_by_role('button', name='내림차순 · 최신 거래 먼저', exact=True).click()
                self.assertEqual(page.locator('tbody tr').first.locator('td').first.inner_text(), '2026-02-20')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                page.get_by_label('카드 내역 검색').fill('no match')
                page.get_by_role('button', name='상태', exact=True).click()
                panel = page.locator('#filter-state').bounding_box()
                self.assertGreaterEqual(panel['x'], 0)
                self.assertLessEqual(panel['x'] + panel['width'], width)
                with page.expect_navigation():
                    page.get_by_role('button', name='분류됨', exact=True).click()
                self.assertEqual(page.locator('input[name="state"]').input_value(), 'classified')
                self.assertEqual(page.get_by_label('카드 내역 검색').input_value(), 'no match')
                self.assertEqual(page.locator('input[name="month"]').input_value(), '2026-02')
                self.assertIn('검색 결과 0건', page.inner_text('#card-count'))
                self.assertIn('분류됨', page.get_by_role('button', name='상태', exact=True).inner_text())
                context.close()
        self.assertEqual(conn.total_changes, before)

    def test_menu_search_and_source_review_at_390(self):
        env = patch.dict(os.environ, {'WEBLEDGER_CARD_FLOW': '1', 'WEBLEDGER_UNIFIED_DB': '1'})
        env.start()
        self.addCleanup(env.stop)
        flow = CardFlow(self.server.card_store)
        first = flow.pipeline.receive(CARD, 'first.csv')['batch_id']
        flow.pipeline.receive(PAIR, 'second.csv')
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        script_errors = []
        page.on('pageerror', lambda error: script_errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{self.port}/import')
        page.locator('#site-content').get_by_role('link', name='카드 내역', exact=True).click()
        self.assertIn('전체 3건', page.inner_text('#card-count'))
        self.assertEqual(page.locator('tbody tr').count(), 3)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.get_by_label('카드 내역 검색').fill('no match')
        page.get_by_role('button', name='검색', exact=True).click()
        self.assertIn('검색 결과 0건', page.inner_text('#card-count'))
        page.get_by_role('link', name='초기화', exact=True).click()
        with page.expect_navigation():
            page.locator('tbody tr').filter(has_text='37,000').get_by_role('link', name='자료 검토').click()
        self.assertEqual(script_errors, [])
        page.wait_for_function('model && model.batch_id === ' + json.dumps(first))
        self.assertEqual(page.evaluate('model.batch_id'), first)
