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
        with patch.dict(os.environ, {'WEBLEDGER_CARD_FLOW':'1','WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_REVIEW_FROM':''}):
            flow = CardFlow(self.server.card_store)
            flow.pipeline.receive(CARD, 'first.csv')
            flow.pipeline.receive(PAIR, 'second.csv')
            conn = self.server.card_store.conn
            before = conn.total_changes
            for width in (375,390,1440):
                with self.subTest(width=width):
                    context = self.browser.new_context(viewport={'width':width,'height':900})
                    context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER:OWNER})
                    page = context.new_page()
                    page.goto(f'http://127.0.0.1:{self.port}/cards?year=2026&q=37000')
                    self.assertIn('/cards/all?year=2026&q=37000',page.url)
                    self.assertIn('1건',page.inner_text('#search-heading'))
                    self.assertEqual(page.locator('tr[data-tx-id]').count(),1)
                    page.locator('.card-all-filters input[name=q]').fill('no match')
                    page.get_by_role('button',name='조회',exact=True).click()
                    self.assertIn('0건',page.inner_text('#search-heading'))
                    self.assertEqual(page.locator('tr[data-tx-id]').count(),0)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                    context.close()
            self.assertEqual(conn.total_changes,before)

    def test_menu_search_and_source_review_at_390(self):
        with patch.dict(os.environ, {'WEBLEDGER_CARD_FLOW':'1','WEBLEDGER_UNIFIED_DB':'1'}):
            flow = CardFlow(self.server.card_store)
            first = flow.pipeline.receive(CARD,'first.csv')['batch_id']
            tx = flow.pipeline.get_batch(first)['rows'][0]['transaction_id']
            context = self.browser.new_context(viewport={'width':390,'height':844})
            self.addCleanup(context.close)
            context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER:OWNER})
            page = context.new_page()
            errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{self.port}/import?scope=all')
            self.assertIn('/cards/all',page.url)
            self.assertEqual(page.locator('#nav a[href^="/cards/all"]').count(),1)
            page.goto(f'http://127.0.0.1:{self.port}/import?batch={first}&transaction={tx}')
            page.wait_for_function('model && model.batch_id === '+json.dumps(first))
            self.assertEqual(page.evaluate('model.batch_id'),first)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            self.assertEqual(errors,[])
