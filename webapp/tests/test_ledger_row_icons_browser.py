import json
import unittest

from webapp.tests import test_ledger_design_state as state


class LedgerRowIconsBrowserTests(unittest.TestCase):
    setUp = state.ViewStateTests.setUp
    tearDown = state.ViewStateTests.tearDown
    _page = state.ViewStateTests._page
    _url = state.ViewStateTests._url

    def test_local_ota_icons_and_category_icons_keep_rows_usable(self):
        row = self.store.get_row('expense-demo-c1')
        row.update(source_merchant='AGODA.COM EN RESORT', item='숙박비')
        self.store.conn.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?',
                                (json.dumps(row), row['row_id']))
        self.store.conn.commit()
        page = self._page(1440)
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        for width in (1440, 390):
            with self.subTest(width=width):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(self._url('?tab=trip-demo-a'))
                selector = "tr[data-id='expense-demo-c1']" if width == 1440 else ".lst button[data-id='expense-demo-c1']"
                entry = page.locator(selector)
                image = entry.locator('img.ota-icon')
                image.scroll_into_view_if_needed()
                page.wait_for_function("el => el.complete && el.naturalWidth > 0", arg=image.element_handle())
                self.assertEqual(image.get_attribute('src'), '/assets/ota/agoda.png')
                self.assertEqual(image.get_attribute('alt'), '')
                self.assertEqual(entry.locator('.category-line svg').count(), 1)
                self.assertIn('AGODA.COM EN RESORT', entry.inner_text())
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                entry.click()
                page.wait_for_url('**row=expense-demo-c1**')
                self.assertEqual(self.store.get_row(row['row_id']), row)
        response = page.request.get(f'http://127.0.0.1:{self.port}/assets/ota/trip.png')
        self.assertEqual(response.status, 200)
        self.assertTrue(response.headers['content-type'].startswith('image/png'))
        self.assertTrue(response.body().startswith(b'\x89PNG'))
        self.assertTrue(all(url.startswith(f'http://127.0.0.1:{self.port}/') for url in requests))
