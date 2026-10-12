import unittest

from webapp.tests import test_ledger_design_state as state


class LedgerDisplayBrowserTests(unittest.TestCase):
    setUp = state.ViewStateTests.setUp
    tearDown = state.ViewStateTests.tearDown
    _page = state.ViewStateTests._page
    _url = state.ViewStateTests._url

    def test_expense_headers_and_edit_panel_at_desktop_and_mobile_widths(self):
        page = self._page(1440)
        for width in (1440, 390):
            with self.subTest(width=width):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(self._url('?tab=trip-demo-a'))
                self.assertEqual(page.locator('#tbl thead th').count(), 5)
                self.assertEqual(page.locator('#tbl tbody.colhead th').count(), 5)
                self.assertNotIn('메모', page.locator('#tbl thead').inner_text())
                self.assertFalse(page.locator('#previous-trips').evaluate('el=>el.open'))
                self.assertNotIn('Google', page.locator('#trip-income').inner_text())
                row = (".tw tr[data-id='expense-demo-c1']" if width == 1440
                       else ".lst button[data-id='expense-demo-c1']")
                page.locator(row).click()
                page.locator('#f-operator_note').wait_for(state='visible')
                self.assertEqual(page.locator('#panel').count(), 1)
                self.assertLessEqual(
                    page.evaluate('document.documentElement.scrollWidth'), width)
