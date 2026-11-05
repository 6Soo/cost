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


def receipt(merchant, date, amount, currency='JPY', payment='cash', box=None):
    return {'id': 'x', 'merchant': merchant, 'date': date, 'amount': amount, 'currency': currency,
            'payment': payment, 'category_hint': None, 'note': None, 'requires_review': True, 'box': box}


class ReceiptPageFlowTests(review.ReceiptReviewTests):
    setUp = review.ReceiptReviewTests.setUp
    tearDown = review.ReceiptReviewTests.tearDown

    def test_selected_files_survive_cancelled_trip_change(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.set_input_files('#img-file', {'name': 'receipt.png', 'mimeType': 'image/png', 'buffer': review.PNG})
                page.select_option('#selected-trip', '')
                self.assertEqual(page.locator('#selected-trip').input_value(), self.trip)
                self.assertIn('먼저 처리', page.locator('#status').inner_text())
                self.assertEqual(page.locator('#selected-files li').count(), 1)
                page.get_by_role('button', name='receipt.png 선택 제거').click()
                self.assertEqual(page.locator('#selected-files li').count(), 0)
            finally:
                browser.close()

    def test_blank_mime_uses_browser_image_conversion(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.set_input_files('#img-file', {'name': 'photo.heic', 'mimeType': '', 'buffer': review.PNG})
                page.click('#img-go')
                page.locator('#upload-results img').wait_for()
                data = self.request('/api/receipts')[1]
                image = self.request('/api/receipts/image/' + data['images'][0])[1]
                self.assertTrue(image.startswith(b'\xff\xd8\xff'))
                self.assertEqual(data['uploads'][0]['name'], 'photo.heic')
            finally:
                browser.close()

    def test_unsaved_manual_input_keeps_its_original_image(self):
        first = self.request('/api/receipts/image', token=self.csrf(), raw=review.PNG)[1]['sha256']
        second = self.request('/api/receipts/image', token=self.csrf(), raw=review.make_png(b'\x00\xff\x00'))[1]['sha256']
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.locator(f'[data-image-sha="{first}"]').click()
                page.locator('#other-methods').evaluate('(el)=>el.open=true')
                page.fill('#r-merchant', 'SYNTHETIC')
                page.locator(f'[data-image-sha="{second}"]').click()
                self.assertEqual(page.locator('#image-sha').input_value(), first)
                self.assertIn(first, page.locator('#manual-preview').get_attribute('src'))
                page.set_input_files('#img-file', {'name': 'new.png', 'mimeType': 'image/png', 'buffer': review.PNG})
                page.click('#img-go')
                self.assertEqual(page.locator('#selected-files li').count(), 1)
                self.assertEqual(page.locator('#image-sha').input_value(), first)
            finally:
                browser.close()

    def test_manual_currency_or_payment_alone_blocks_source_and_trip_change(self):
        first = self.request('/api/receipts/image', token=self.csrf(), raw=review.PNG)[1]['sha256']
        second = self.request('/api/receipts/image', token=self.csrf(), raw=review.make_png(b'\x00\xff\x00'))[1]['sha256']
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                for field, value in (('r-currency', 'KRW'), ('r-payment', 'private_card')):
                    page = browser.new_page(viewport={'width': 390, 'height': 900})
                    page.goto(self.base + '/receipts?trip=' + self.trip)
                    page.locator(f'[data-image-sha="{first}"]').click()
                    page.locator('#other-methods').evaluate('(el)=>el.open=true')
                    page.select_option('#' + field, value)
                    page.locator(f'[data-image-sha="{second}"]').click()
                    self.assertEqual(page.locator('#image-sha').input_value(), first)
                    page.select_option('#selected-trip', '')
                    self.assertEqual(page.locator('#selected-trip').input_value(), self.trip)
                    self.assertTrue(page.evaluate("() => {const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented}"))
                    page.close()
            finally:
                browser.close()

    def test_mixed_upload_failure_retry_and_pdf_page_recovery(self):
        from app import local_receipt_ocr
        rendered = {'pages': [
            {'image': review.PNG, 'text': '', 'suggestions': {}},
            {'image': review.PNG, 'text': '', 'suggestions': {}},
        ]}
        with patch.object(local_receipt_ocr, 'recognize_pdf', return_value=rendered), sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.set_input_files('#img-file', [
                    {'name': 'receipt.png', 'mimeType': 'image/png', 'buffer': review.PNG},
                    {'name': 'receipt.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF-1.7 synthetic'},
                    {'name': 'bad.png', 'mimeType': 'image/png', 'buffer': b'invalid'},
                ])
                self.assertEqual(page.locator('#selected-files li').count(), 3)
                page.click('#img-go')
                page.get_by_role('button', name='다시 시도').wait_for()
                self.assertEqual(page.locator('#upload-results p').count(), 3)
                self.assertEqual(len(self.request('/api/receipts')[1]['pdfs']), 1)
                self.assertIn('원본 저장됨', page.locator('#upload-results p').nth(0).inner_text())
                self.assertIn('2페이지', page.locator('#upload-results p').nth(1).inner_text())
                page.get_by_role('button', name='다시 시도').click()
                page.get_by_role('button', name='다시 시도').wait_for()
                self.assertEqual(page.locator('#upload-results p').count(), 3)
                self.assertEqual(len(self.request('/api/receipts')[1]['pdfs']), 1)
                page.get_by_role('button', name='실패 파일 제거').click()
                page.reload()
                pdf = page.locator('section[aria-label="저장된 파일"] > ul > li').filter(has_text='receipt.pdf')
                pdf_pages = pdf.locator('[data-manual-image]')
                self.assertEqual(pdf_pages.count(), 2)
                pdf_pages.first.click()
                self.assertTrue(page.locator('#r-merchant').is_visible())
                self.assertEqual(page.locator('#image-sha').input_value(),
                                 self.request('/api/receipts')[1]['pdfs'][0]['pages'][0])
            finally:
                browser.close()

    def _answers(self, path, **kwargs):
        """Fixed answers: the first photo has two receipts and a third appears only on re-reading."""
        name = Path(path).stem
        if name == self.photos[0]:
            found = [receipt('SHOP A', '2026-10-10', 820, box=[0.1, 0.1, 0.4, 0.4]),
                     receipt('FERRY', '2026-10-10', 820, payment=None, box=[0.6, 0.1, 0.9, 0.4])]
            if kwargs.get('guidance') and 'Owner feedback' in kwargs['guidance']:
                found.append(receipt('NEW STOP', '2026-10-12', 700, payment='cash'))
            return {'receipts': found, 'label': 'Muse', 'lesson': None}
        if name == self.photos[1]:
            return {'receipts': [receipt('CAFE', '2026-10-11', 12000, currency='KRW')], 'label': 'Muse', 'lesson': None}
        return {'receipts': [], 'label': 'Muse', 'lesson': None}

    def test_three_photos_are_analysed_registered_and_refreshed(self):
        from webapp import receipt_vision_jobs
        with receipt_vision_jobs._LOCK:
            receipt_vision_jobs._JOBS.clear()
            receipt_vision_jobs._BY_IMAGE.clear()
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
                        self.assertEqual(page.locator('h1').inner_text(), '영수증 처리')
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
                        page.click('#img-go')
                        page.wait_for_function("document.querySelectorAll('#upload-results p').length >= " + str(index))
                        page.wait_for_function("[...document.querySelectorAll('#upload-results p')].every(p=>p.textContent.includes('원본 저장됨'))")
                    self.photos = [s for s in page.eval_on_selector_all('.photo-check', 'els=>els.map(e=>e.value)')]
                    self.assertEqual(len(self.photos), 3)
                    self.assertEqual(page.eval_on_selector_all('.photo-check:checked', 'els=>els.length'), 3)
                    page.click('#vision-go')
                    page.wait_for_function("document.getElementById('status').textContent.includes('분석을 마쳤습니다')",
                                           timeout=240000)
                    self.assertEqual(page.locator('.receipt-card').count(), 3, page.locator('#status').inner_text())
                    self.assertEqual(page.locator('.receipt-region-box:not([hidden])').count(), 2)
                    self.assertEqual(page.get_by_text('영역 미확인', exact=False).count(), 1)
                    self.assertIn('후보', page.locator('.photo-state').first.inner_text())
                    self.assertIn('후보 2건', page.locator(f'[data-upload-page="{self.photos[0]}"]').first.inner_text())
                    if shots:
                        page.screenshot(path=os.path.join(shots, 'p1-results-390.png'), full_page=True)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    cards = page.locator('.receipt-card')
                    ferry = next(cards.nth(index) for index in range(cards.count())
                                 if cards.nth(index).get_by_role('textbox', name='상호', exact=True).input_value() == 'FERRY')
                    ferry.get_by_role('combobox', name='결제수단', exact=True).select_option('cash')
                    with page.expect_navigation():
                        page.click('#vision-register')
                    page.wait_for_selector('#step-review table')
                    candidates = self.request('/api/receipts')[1]['candidates']
                    self.assertEqual(len(candidates), 3)
                    self.assertEqual({candidate['merchant'] for candidate in candidates},
                                     {'SHOP A', 'FERRY', 'CAFE'})
                    self.assertIn('등록된 영수증 2건', page.locator(f'[data-upload-page="{self.photos[0]}"]').first.inner_text())
                    self.assertIn('trip=' + self.trip, page.locator('[data-receipt-link]').first.get_attribute('href'))
                    self.assertEqual({c['merchant']: c['box'] for c in candidates},
                                     {'SHOP A': [0.1, 0.1, 0.4, 0.4], 'FERRY': [0.6, 0.1, 0.9, 0.4], 'CAFE': None})
                    self.assertTrue(all(candidate['trip_id'] == self.trip for candidate in candidates))
                    self.assertTrue(all('2026-10-10' <= candidate['date'] <= '2026-10-13'
                                        for candidate in candidates))
                    self.assertEqual(page.locator('#vision-register').count(), 0)
                    self.assertEqual(page.evaluate("JSON.parse(sessionStorage.getItem('cost-receipt-pending')||'[]').length"), 0)
                    self.assertEqual(page.locator('#vision-finish').count(), 0)
                    page.locator('[data-image-sha]').first.click()
                    page.wait_for_function("document.getElementById('rescan-target').textContent.includes('사진 1')")
                    self.assertIn('사진 1', page.locator('#rescan-target').text_content())
                    page.locator('details.rescan > summary').click()
                    page.fill('#feedback', '6장인데 5장만 찾았어. 작은 승선권 하나 더 찾아')
                    page.click('#rescan-go')
                    page.wait_for_function("document.getElementById('status').textContent.includes('새 후보')",
                                           timeout=240000)
                    self.assertEqual(page.locator('.receipt-card').count(), 1)
                    if shots:
                        page.screenshot(path=os.path.join(shots, 'p2-rescan-390.png'), full_page=True)
                    with page.expect_navigation():
                        page.click('#vision-register')
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
