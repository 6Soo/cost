"""The receipt page as one owner works it: three photos, analysis, review, registration, re-reading, grouping, copy.

Muse is replaced by a fixed answer per photo, so the flow is checked without a model call. Screenshots of each step
are written to WEBLEDGER_FLOW_SHOTS when that variable names a folder.
"""
import os
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp.tests import test_receipt_review as review

WIDTHS = (375, 390, 1280, 1440)


def receipt(merchant, date, amount, currency='JPY', payment='cash'):
    return {'id': 'x', 'merchant': merchant, 'date': date, 'amount': amount, 'currency': currency,
            'payment': payment, 'category_hint': None, 'note': None, 'requires_review': True}


class ReceiptPageFlowTests(review.ReceiptReviewTests):
    setUp = review.ReceiptReviewTests.setUp
    tearDown = review.ReceiptReviewTests.tearDown

    def _answers(self, path, **kwargs):
        """Fixed answers: the first photo has two receipts and a third appears only on re-reading."""
        name = Path(path).stem
        if name == self.photos[0]:
            found = [receipt('SHOP A', '2026-10-10', 820), receipt('FERRY', '2026-10-10', 820, payment=None)]
            if kwargs.get('guidance') and 'Owner feedback' in kwargs['guidance']:
                found.append(receipt('NEW STOP', '2026-10-12', 700, payment='cash'))
            return {'receipts': found, 'label': 'Muse', 'lesson': None}
        if name == self.photos[1]:
            return {'receipts': [receipt('CAFE', '2026-10-11', 12000, currency='KRW')], 'label': 'Muse', 'lesson': None}
        return {'receipts': [], 'label': 'Muse', 'lesson': None}

    def test_three_photos_are_analysed_registered_and_refreshed(self):
        shots = os.environ.get('WEBLEDGER_FLOW_SHOTS')
        self.photos = []
        env = patch.dict(os.environ, {'WEBLEDGER_RECEIPT_VISION': 'opencode-muse-free',
                                      'WEBLEDGER_RECEIPT_LEARNING': str(Path(self._dir.name) / 'learning.jsonl')})
        env.start()
        recognizer = patch('webapp.receipt_review.opencode_receipt_vision.recognize_with_fallback',
                           side_effect=lambda path, **kw: self._answers(path, **kw))
        recognizer.start()
        engine = patch('webapp.receipt_review.opencode_receipt_vision.enabled', return_value=True)
        engine.start()
        try:
            with sync_playwright() as api:
                browser = api.chromium.launch()
                try:
                    for width in WIDTHS:
                        page = browser.new_page(viewport={'width': width, 'height': 900})
                        page.goto(self.base + '/receipts')
                        self.assertEqual(page.locator('h1').inner_text(), '영수증 정리')
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                        if width == 390 and shots:
                            page.screenshot(path=os.path.join(shots, 'p0-start-390.png'), full_page=True)
                        page.close()
                    page = browser.new_page(viewport={'width': 390, 'height': 900})
                    page.goto(self.base + '/receipts')
                    page.select_option('#selected-trip', self.trip)
                    for index, colour in enumerate((b'\xff\x00\x00', b'\x00\xff\x00', b'\x00\x00\xff'), start=1):
                        page.set_input_files('#img-file', files=[{'name': f'p{index}.png', 'mimeType': 'image/png',
                                                                 'buffer': review.make_png(colour)}])
                        with page.expect_navigation():
                            page.click('#img-go')
                        page.wait_for_load_state()
                    self.photos = [s for s in page.eval_on_selector_all('.photo-check', 'els=>els.map(e=>e.value)')]
                    self.assertEqual(len(self.photos), 3)
                    self.assertEqual(page.eval_on_selector_all('.photo-check:checked', 'els=>els.length'), 3)
                    page.click('#vision-go')
                    page.wait_for_function("document.getElementById('status').textContent.includes('분석을 마쳤습니다')",
                                           timeout=240000)
                    self.assertEqual(page.locator('.receipt-card').count(), 3, page.locator('#status').inner_text())
                    self.assertIn('후보', page.locator('.photo-state').first.inner_text())
                    if shots:
                        page.screenshot(path=os.path.join(shots, 'p1-results-390.png'), full_page=True)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    page.locator('.receipt-card').nth(1).locator('select').nth(1).select_option('cash')
                    page.click('#vision-register')
                    page.wait_for_load_state()
                    page.wait_for_selector('#step-review table')
                    candidates = self.request('/api/receipts')[1]['candidates']
                    self.assertEqual(len(candidates), 3)
                    self.assertEqual({candidate['merchant'] for candidate in candidates},
                                     {'SHOP A', 'FERRY', 'CAFE'})
                    self.assertTrue(all(candidate['trip_id'] == self.trip for candidate in candidates))
                    self.assertTrue(all('2026-10-10' <= candidate['date'] <= '2026-10-13'
                                        for candidate in candidates))
                    self.assertEqual(page.locator('#vision-register').count(), 0)
                    self.assertEqual(page.evaluate("JSON.parse(sessionStorage.getItem('cost-receipt-pending')||'[]').length"), 0)
                    self.assertEqual(page.locator('#vision-finish').count(), 0)
                    page.locator('[data-image-sha]').first.click()
                    self.assertIn('사진 1', page.locator('#rescan-target').inner_text())
                    page.fill('#feedback', '6장인데 5장만 찾았어. 작은 승선권 하나 더 찾아')
                    page.click('#rescan-go')
                    page.wait_for_function("document.getElementById('status').textContent.includes('새 후보')",
                                           timeout=240000)
                    self.assertEqual(page.locator('.receipt-card').count(), 1)
                    if shots:
                        page.screenshot(path=os.path.join(shots, 'p2-rescan-390.png'), full_page=True)
                    page.click('#vision-register')
                    page.wait_for_load_state()
                    page.wait_for_selector('#step-review table')
                    candidates = self.request('/api/receipts')[1]['candidates']
                    self.assertEqual(len(candidates), 4)
                    self.assertEqual(sorted(c['merchant'] for c in candidates).count('NEW STOP'), 1)
                    self.assertTrue(all(candidate['trip_id'] == self.trip for candidate in candidates))
                    self.assertTrue(page.locator('#other-methods').count() == 1)
                    page.locator('#other-methods > summary').click()
                    self.assertTrue(page.locator('#r-merchant').is_visible())
                    if shots:
                        page.screenshot(path=os.path.join(shots, 'p3-after-390.png'), full_page=True)
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    page.close()
                finally:
                    browser.close()
        finally:
            recognizer.stop()
            engine.stop()
            env.stop()


# Only this module's own flow runs; the fixture is shared with the review tests, not their cases.
for _name in [n for n in dir(review.ReceiptReviewTests) if n.startswith('test_')]:
    setattr(ReceiptPageFlowTests, _name, None)
