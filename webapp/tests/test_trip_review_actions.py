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
                steps = page.locator('.settlement-steps')
                self.assertEqual(steps.locator('li').count(), 5)
                self.assertTrue(steps.locator('a').evaluate_all(
                    'els=>els.every(el=>el.getBoundingClientRect().height>=44)'))
                menu = page.locator('#trip-settings > summary')
                self.assertEqual(menu.get_attribute('aria-label'), '여행 작업')
                self.assertEqual(menu.get_attribute('aria-haspopup'), 'menu')
                menu.click()
                self.assertTrue(page.locator('#trip-settings').evaluate('el=>el.open'))
                self.assertEqual(page.locator('#trip-settings .trip-more-menu a[href^="/export?"]').count(), 1)
                menu.click()
                page.locator('#add-manual-expense').click()
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
