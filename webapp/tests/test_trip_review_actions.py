"""Trip actions exercise real disclosures, refresh replacement and source protection."""
import json
import unittest

from webapp.tests import test_ledger_design as fixture


class TripReviewActionsTests(unittest.TestCase):
    setUp = fixture.DesignScreenTests.setUp
    tearDown = fixture.DesignScreenTests.tearDown
    _page = fixture.DesignScreenTests._page
    _board = fixture.DesignScreenTests._board

    def test_trip_actions_and_stay_layout(self):
        row = self.store.get_row('expense-demo-c1')
        row.update(item='숙박비', service_period='2026-09-22~2026-09-23')
        self.store.conn.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?',
                                (json.dumps(row), row['row_id']))
        self.store.conn.commit()
        page = self._page(1280)
        for width in (320, 390, 760, 1024, 1440):
            with self.subTest(width=width):
                page.set_viewport_size({'width': width, 'height': 900})
                self._board(page, '?tab=trip-demo-a')
                actions = page.locator('.trip-actions')
                self.assertEqual(actions.locator(':scope > a').count(), 4)
                self.assertTrue(actions.locator(':scope > a').evaluate_all(
                    'els=>els.every(el=>el.getBoundingClientRect().height>=44)'))
                self.assertEqual(page.locator('.trip-header .act').inner_text().strip(), 'XLSX 출력')
                page.locator('.trip-actions [data-trip-panel="trip-review-panel"]').click()
                self.assertTrue(page.locator('#trip-review-panel').evaluate('el=>el.open'))
                self.assertIn('비교할 수 없습니다', page.locator('#trip-review-panel').inner_text())
                page.locator('#trip-review-panel [data-trip-panel]').click()
                self.assertTrue(page.locator('#participant-trip-panel').evaluate('el=>el.open'))
                self.assertFalse(page.locator('#trip-review-panel').evaluate('el=>el.open'))
                self.assertEqual(actions.locator('[data-trip-panel="participant-trip-panel"]').get_attribute('aria-expanded'), 'true')
                actions.locator('[data-trip-panel="trip-review-panel"]').click()
                page.evaluate("document.querySelector('#live-rows').innerHTML=document.querySelector('#live-rows').innerHTML")
                page.wait_for_function("document.querySelector('#trip-review-panel').open")
                actions.locator('[data-trip-panel="trip-review-panel"]').focus()
                page.keyboard.press('Space')
                self.assertFalse(page.locator('#trip-review-panel').evaluate('el=>el.open'))
                actions.locator('[data-manual-open]').click()
                self.assertTrue(page.locator('#manual-expense-dialog').evaluate('el=>el.open'))
                self.assertEqual(page.input_value('#mx-tab'), 'trip-demo-a')
                page.keyboard.press('Escape')
                if width >= 760:
                    cell = page.locator('tr[data-id="expense-demo-c1"] .c-stay')
                    self.assertEqual(cell.inner_text(), '09.22–09.23 · 1박')
                    self.assertIn('9월 22일', cell.get_attribute('title'))
                    self.assertEqual(cell.evaluate('el=>getComputedStyle(el).whiteSpace'), 'nowrap')
                    self.assertLessEqual(cell.evaluate('el=>el.scrollWidth-el.clientWidth'), 1)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth-innerWidth'), 0)
