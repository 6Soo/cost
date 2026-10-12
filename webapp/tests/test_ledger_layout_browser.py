import unittest
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from webapp import google_ledger_page as google
from webapp.tests import test_ledger_design_state as state
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc


class LedgerLayoutBrowserTests(unittest.TestCase):
    setUp = state.ViewStateTests.setUp
    tearDown = state.ViewStateTests.tearDown
    _page = state.ViewStateTests._page
    _url = state.ViewStateTests._url

    def test_readable_income_and_merchant_order_at_both_widths(self):
        snapshot = healthy_snapshot()
        snapshot['synced_at'] = '2026-10-12T20:00:02.049343+09:00'
        key = snapshot['trips'][0]['key']
        rows = rows_doc()['sources']
        income = rows['main']['trips'][key]['income'][0]
        income['cells'].update(E='420000.0', F='2300000.0', G='-420000.0')
        income['amount'] = 2300000
        snapshot['trips'][0]['copies']['main']['income'].update(
            total=2300000, sheet_total=2300000, row_sum=2300000)
        original = deepcopy(rows)
        row = self.store.get_row('expense-demo-c1')
        row.update(source_merchant='Synthetic merchant', reservation_no='SYN-246',
                   description='Synthetic merchant · 예약 SYN-246')
        self.store.conn.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?',
                                (json.dumps(row), 'expense-demo-c1'))
        self.store.conn.commit()
        with patch.object(google, 'enabled', return_value=True), \
             patch.object(google, '_snapshot_path', return_value=Path(self.tmp) / 'snapshot.json'), \
             patch.object(google, '_rows_path', return_value=Path(self.tmp) / 'rows.json'), \
             patch.object(google, 'caller', return_value=(True, None)), \
             patch.object(google.google_authority, 'load_consistent', return_value=(snapshot, rows)), \
             patch.object(google, 'snapshot_for_display', side_effect=lambda value: value), \
             patch.object(google, 'load_mapping', return_value={key: 'trip-demo-a'}), \
             patch.object(google, 'load_choices', return_value={'choices': {key: 'main'}}):
            page = self._page(1440)
            for width in (1440, 390):
                with self.subTest(width=width):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    page.goto(self._url('?tab=trip-demo-a'))
                    income_table = page.locator('#google-trip-income table')
                    self.assertNotIn('Google', page.locator('main').inner_text())
                    self.assertIn('기록된 거래', page.locator('#live-sum').inner_text())
                    self.assertIn('2026.10.12 20:00', page.locator('#trip-income').inner_text())
                    self.assertNotIn('049343', page.locator('#trip-income').inner_text())
                    self.assertEqual(page.locator('#trip-income time').get_attribute('datetime'),
                                     snapshot['synced_at'])
                    self.assertEqual(page.locator('#ledger-note').count(), 0)
                    self.assertNotIn('행을 누르면 편집', page.locator('main').inner_text())
                    self.assertGreater(page.locator('#trip-income svg').count(), 1)
                    heading = page.locator('main h1').bounding_box()
                    search = page.locator('#q').bounding_box()
                    section = page.locator('#trip-income').bounding_box()
                    if width == 1440:
                        self.assertAlmostEqual(heading['x'], search['x'], delta=1)
                        self.assertAlmostEqual(heading['x'], section['x'], delta=1)
                    self.assertIn('420,000', income_table.inner_text())
                    self.assertIn('2,300,000', income_table.inner_text())
                    self.assertIn('-420,000', income_table.inner_text())
                    self.assertNotIn('420000.0', income_table.inner_text())
                    if width == 1440:
                        party = page.locator("tr[data-id='expense-demo-c1'] .c-party")
                        self.assertEqual(party.locator('.s-main').inner_text(), 'Synthetic merchant')
                        text = party.inner_text()
                        self.assertGreaterEqual(width - page.locator('#tbl').bounding_box()['x']
                                                - page.locator('#tbl').bounding_box()['width'], 24)
                    else:
                        text = page.locator(".lst button[data-id='expense-demo-c1']").inner_text()
                    self.assertLess(text.index('Synthetic merchant'), text.index('SYN-246'))
                    self.assertEqual(text.count('SYN-246'), 1)
                    self.assertEqual(text.count('Synthetic merchant'), 1)
                    self.assertLessEqual(
                        page.evaluate('document.documentElement.scrollWidth'), width)
                    captures = Path('.local-archive/layout-captures')
                    captures.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(captures / f'ledger-{width}.png'), full_page=True)
            page.get_by_role('link', name='수입·지출 원본 상세').click()
            page.wait_for_url('**/google-ledger/rows?**')
            detail_table = page.locator('table').first.inner_text()
            self.assertIn('420,000', detail_table)
            self.assertIn('-420,000', detail_table)
            self.assertNotIn('420000.0', detail_table)
            self.assertEqual(rows, original)
