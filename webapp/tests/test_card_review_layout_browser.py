import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from webapp import ledger_board
from webapp.card_flow import CardFlow
from tests.card_pipeline.fixtures import make_csv, domestic_row


class CardReviewLayoutBrowserTests(unittest.TestCase):
    def test_review_filters_icons_and_edit_keep_original_transactions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1', 'WEBLEDGER_REVIEW_FROM': ''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            flow = CardFlow(server.card_store)
            batch = flow.pipeline.receive(make_csv([
                domestic_row(merchant='AGODA.COM', amount=123000, approval='UI001', date='2026-07-12'),
                domestic_row(merchant='TRIP.COM', amount=45600, approval='UI002', date='2026-06-03'),
                domestic_row(merchant='합성 미확정 상점', amount=9900, approval='UI003', date='2026-07-20'),
            ]), 'review-layout.csv')['batch_id']
            originals = flow.pipeline.get_batch(batch)['rows']
            for row in originals[:2]:
                flow.pipeline.save_decision(row['transaction_id'], row['revision'],
                    item='숙박비', display_tab_id='unclassified', tab_validator=flow.tab_valid,
                    request_id='ui-confirm-'+row['transaction_id'])
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as api:
                    browser = api.chromium.launch()
                    for width in (390, 1440):
                        with self.subTest(width=width):
                            page = browser.new_page(viewport={'width': width, 'height': 950})
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(f'http://127.0.0.1:{server.server_address[1]}/import?batch={batch}')
                            page.locator('#preview tbody tr').first.wait_for()
                            self.assertEqual(page.locator('#preview tbody tr').count(), 2)
                            self.assertEqual(page.locator('#review-sort').input_value(), 'date-asc')
                            self.assertIn('TRIP.COM', page.locator('#preview tbody tr').first.inner_text())
                            self.assertFalse(page.locator('#saved-materials').evaluate('el => el.open'))
                            self.assertEqual(page.locator('#nav').count(), 1)
                            self.assertEqual(page.locator('#review-metrics [data-review-state]').count(), 4)
                            self.assertEqual(page.locator('#preview .ota-icon').count(), 2)
                            page.get_by_role('button', name='거래일 정렬 및 월 선택').click()
                            page.locator('#review-sort').select_option('date-asc')
                            self.assertIn('TRIP.COM', page.locator('#preview tbody tr').first.inner_text())
                            page.locator('#review-month').select_option('2026-07')
                            self.assertEqual(page.locator('#preview tbody tr').count(), 1)
                            self.assertTrue(page.locator('#commit').is_disabled())
                            page.locator('#review-search').fill('TRIP')
                            self.assertEqual(page.locator('#preview tbody tr').count(), 0)
                            self.assertTrue(page.locator('#review-empty').is_visible())
                            page.get_by_role('button', name='조회 조건 초기화').click()
                            self.assertEqual(page.locator('#review-sort').input_value(), 'date-asc')
                            self.assertFalse(page.locator('#commit').is_disabled())
                            page.locator('[data-review-state="all"]').click()
                            self.assertEqual(page.locator('#preview tbody tr').count(), 3)
                            self.assertIn('확인 필요', page.locator('#preview tbody').inner_text())
                            page.locator('#review-search').fill('AGODA')
                            page.locator('#preview [data-edit]').click()
                            page.locator('form[data-index] input[name=item]').first.fill('현지경비')
                            page.locator('form[data-index] button').first.click()
                            page.get_by_text('답변을 적용했습니다.', exact=False).wait_for()
                            self.assertEqual(page.locator('#review-search').input_value(), 'AGODA')
                            self.assertIn('현지경비', page.locator('#preview tbody').inner_text())
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                            self.assertEqual(errors, [])
                            page.close()
                    browser.close()
                updated = {row['transaction_id']: row for row in flow.pipeline.get_batch(batch)['rows']}
                for original in originals:
                    for field in ('transaction_id', 'source_hash', 'amount_krw', 'approval_date', 'merchant'):
                        self.assertEqual(updated[original['transaction_id']][field], original[field])
                self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 0)
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)
