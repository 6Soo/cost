import json
import os
from unittest.mock import patch

from webapp import access_control
from webapp.card_flow import CardFlow
from webapp.tests.test_card_flow import CARD, PAIR
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class CardCatalogBrowserTests(LinkBrowserFixture):
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
        page.goto(f'http://127.0.0.1:{self.port}/import')
        page.get_by_role('link', name='전체 카드 내역', exact=True).click()
        self.assertIn('전체 3건', page.inner_text('#card-count'))
        self.assertEqual(page.locator('tbody tr').count(), 3)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.get_by_label('카드 내역 검색').fill('no match')
        page.get_by_role('button', name='검색', exact=True).click()
        self.assertIn('검색 결과 0건', page.inner_text('#card-count'))
        page.get_by_role('link', name='초기화', exact=True).click()
        page.locator('tbody tr').filter(has_text='37,000').get_by_role('link', name='자료 검토').click()
        page.wait_for_function('model && model.batch_id === ' + json.dumps(first))
        self.assertEqual(page.evaluate('model.batch_id'), first)
