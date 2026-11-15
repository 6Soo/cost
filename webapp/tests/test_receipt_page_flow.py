"""The receipt page as one owner works it: three photos, analysis, review, registration, re-reading, grouping, copy.

The reading model is replaced by a fixed answer per photo, so the flow is checked without a model call. Screenshots of each step
are written to WEBLEDGER_FLOW_SHOTS when that variable names a folder.
"""
import hashlib
import json
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

    def test_upload_timeout_reports_unknown_storage_and_keeps_retry(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.evaluate("""() => {
                  const real = window.setTimeout;
                  window.setTimeout = (fn, ms, ...args) => real(fn, ms === 120000 ? 20 : ms, ...args);
                }""")
                page.route('**/api/receipts/image', lambda route: None)
                page.set_input_files('#img-file', {'name': 'timeout.png', 'mimeType': 'image/png', 'buffer': review.PNG})
                page.click('#img-go')
                page.get_by_role('button', name='다시 시도').wait_for()
                self.assertIn('저장 여부를 확인해 주세요', page.locator('#upload-results').inner_text())
                self.assertIn('응답 시간이 초과', page.locator('#upload-results').inner_text())
                self.assertTrue(page.evaluate("() => {const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented}"))
            finally:
                browser.close()

    def test_lost_upload_response_recovers_committed_original_without_retry(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)

                # Lose the first response after its real body has arrived. Browser
                # route.abort can race fetch's response/body completion on Windows.
                # Keep the actual upload, storage lookup and recovery UI in the test.
                page.evaluate("""() => {
                  const realFetch = window.fetch.bind(window);
                  window.uploadPosts = 0;
                  window.fetch = async (url, options) => {
                    const response = await realFetch(url, options);
                    if (url === '/api/receipts/image' && options?.method === 'POST'
                        && ++window.uploadPosts === 1) {
                      if (!response.ok) throw new Error('Synthetic upload did not commit');
                      await response.json();
                      throw new TypeError('Failed to fetch');
                    }
                    return response;
                  };
                }""")
                page.set_input_files('#img-file', {
                    'name': 'response-lost.png', 'mimeType': 'image/png', 'buffer': review.PNG,
                })
                page.click('#img-go')
                page.get_by_text('저장 결과 복구됨', exact=False).wait_for(timeout=30000)
                self.assertEqual(page.get_by_role('button', name='다시 시도').count(), 0)
                self.assertEqual(len(self.request('/api/receipts')[1]['images']), 1)
                self.assertEqual(page.evaluate('window.uploadPosts'), 1)
                self.assertIsNone(page.locator('#manual-preview').get_attribute('hidden'))
                page.reload()
                self.assertIn('response-lost.png', page.locator('section[aria-label="저장된 파일"]').inner_text())
            finally:
                browser.close()

    def test_lost_pdf_response_recovers_all_pages_and_continues_batch(self):
        from app import local_receipt_ocr
        rendered = {'pages': [
            {'image': review.PNG, 'text': '', 'suggestions': {}},
            {'image': review.make_png(b'\x00\xff\x00'), 'text': '', 'suggestions': {}},
        ]}
        with patch.object(local_receipt_ocr, 'recognize_pdf', return_value=rendered), sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)

                page.evaluate("""() => {
                  const realFetch = window.fetch.bind(window);
                  window.pdfPosts = 0;
                  window.fetch = async (url, options) => {
                    const response = await realFetch(url, options);
                    if (url === '/api/receipts/pdf' && options?.method === 'POST'
                        && ++window.pdfPosts === 1) {
                      if (!response.ok) throw new Error('Synthetic PDF did not commit');
                      await response.json();
                      throw new TypeError('Failed to fetch');
                    }
                    return response;
                  };
                }""")
                page.set_input_files('#img-file', [
                    {'name': 'lost.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF-1.7 synthetic'},
                    {'name': 'next.png', 'mimeType': 'image/png', 'buffer': review.PNG},
                ])
                page.click('#img-go')
                page.get_by_text('저장 결과 복구됨', exact=False).wait_for()
                page.locator('#upload-results p').filter(has_text='next.png').locator('img').wait_for()
                self.assertEqual(page.locator('#upload-results [data-manual-image]').count(), 3)
                self.assertEqual(page.get_by_role('button', name='다시 시도').count(), 0)
                data = self.request('/api/receipts')[1]
                self.assertEqual(len(data['pdfs']), 1)
                self.assertEqual(len(data['images']), 2)
                self.assertEqual(len(data['uploads']), 2)
                self.assertEqual(page.evaluate('window.pdfPosts'), 1)
                page.reload()
                self.assertIn('lost.pdf', page.locator('section[aria-label="저장된 파일"]').inner_text())
            finally:
                browser.close()

    def test_safari_network_error_recovers_normalized_image_bytes(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.evaluate("""() => {
                    const fetch = window.fetch.bind(window);
                    window.fetch = async (url, options) => {
                        const result = await fetch(url, options);
                        if (url === '/api/receipts/image' && options?.method === 'POST')
                            throw new TypeError('Load failed');
                        return result;
                    };
                }""")
                page.set_input_files('#img-file', {
                    'name': 'converted.heic', 'mimeType': '', 'buffer': review.PNG,
                })
                page.click('#img-go')
                page.get_by_text('저장 결과 복구됨', exact=False).wait_for()
                data = self.request('/api/receipts')[1]
                self.assertEqual(len(data['images']), 1)
                self.assertNotEqual(data['images'][0], hashlib.sha256(review.PNG).hexdigest())
                self.assertEqual(page.get_by_role('button', name='다시 시도').count(), 0)
            finally:
                browser.close()

    def test_committed_upload_recovers_truncated_or_stalled_response_body(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                for stalled in (False, True):
                    with self.subTest(stalled=stalled):
                        page = browser.new_page(viewport={'width': 390, 'height': 900})
                        page.goto(self.base + '/receipts?trip=' + self.trip)
                        page.evaluate("""stalled => {
                            const fetch = window.fetch.bind(window), timer = window.setTimeout;
                            window.setTimeout = (fn, ms, ...args) => timer(fn, ms === 120000 ? 100 : ms, ...args);
                            window.fetch = async (url, options) => {
                                const result = await fetch(url, options);
                                if (url !== '/api/receipts/image' || options?.method !== 'POST') return result;
                                window.uploadHeadersReceived = true;
                                if (!stalled) return new Response('{', {status: 200});
                                return new Response(new ReadableStream({start(controller) {
                                    options.signal.addEventListener('abort', () =>
                                        controller.error(new DOMException('Timed out', 'AbortError')));
                                }}), {status: 200});
                            };
                        }""", stalled)
                        page.set_input_files('#img-file', {
                            'name': 'lost-body.png', 'mimeType': 'image/png', 'buffer': review.PNG,
                        })
                        page.click('#img-go')
                        page.get_by_text('저장 결과 복구됨', exact=False).wait_for()
                        self.assertTrue(page.evaluate('window.uploadHeadersReceived'))
                        self.assertEqual(page.get_by_role('button', name='다시 시도').count(), 0)
                        self.assertEqual(len(self.request('/api/receipts')[1]['images']), 1)
                        page.close()
            finally:
                browser.close()

    def test_failed_storage_lookup_keeps_retry_and_processes_next_file(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.route('**/api/receipts/image', lambda route: route.abort(), times=1)
                page.evaluate("""() => {
                    const fetch = window.fetch.bind(window);
                    window.fetch = (url, options) => url === '/api/receipts'
                        ? Promise.resolve(new Response('{}', {status: 503})) : fetch(url, options);
                }""")
                page.set_input_files('#img-file', [
                    {'name': 'unsaved.png', 'mimeType': 'image/png', 'buffer': review.PNG},
                    {'name': 'saved.png', 'mimeType': 'image/png', 'buffer': review.make_png(b'\x00\xff\x00')},
                ])
                page.click('#img-go')
                page.get_by_role('button', name='다시 시도').wait_for()
                page.wait_for_function("document.querySelector('[data-upload-recovery]').disabled === false")
                self.assertIn('저장 여부를 확인해 주세요', page.locator('#upload-results').inner_text())
                self.assertEqual(len(self.request('/api/receipts')[1]['images']), 1)
                page.get_by_role('button', name='다시 시도').click()
                page.locator('#upload-results p').filter(has_text='unsaved.png').locator('img').wait_for()
                self.assertEqual(len(self.request('/api/receipts')[1]['images']), 2)
            finally:
                browser.close()

    def test_analysis_drafts_and_zero_results_recover_without_session_or_job_memory(self):
        from webapp import receipt_vision_jobs
        answer = {'receipts': [receipt('SYNTHETIC', '2026-10-12', 100)], 'label': 'fixture', 'lesson': None}
        first_sha = hashlib.sha256(review.PNG).hexdigest()
        with receipt_vision_jobs._LOCK:
            receipt_vision_jobs._JOBS.clear()
            receipt_vision_jobs._BY_IMAGE.clear()
        with patch('webapp.receipt_review.receipt_vision.enabled', return_value=True), \
             patch('webapp.receipt_review.receipt_vision.recognize_with_fallback',
                   side_effect=lambda path, **kw: answer if Path(path).stem == first_sha else {'receipts': []}), \
             sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                first = browser.new_context(viewport={'width': 390, 'height': 900})
                page = first.new_page()
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.set_input_files('#img-file', [
                    {'name': 'photo.png', 'mimeType': 'image/png', 'buffer': review.PNG},
                    {'name': 'empty.png', 'mimeType': 'image/png', 'buffer': review.make_png(b'\x00\xff\x00')},
                ])
                page.click('#img-go')
                page.wait_for_function("document.querySelectorAll('#upload-results img').length === 2")
                page.click('#vision-go')
                page.locator('.receipt-card').wait_for(timeout=30000)
                page.get_by_text('영수증 후보 0건 · 원본 저장됨').wait_for(timeout=30000)
                with page.expect_response(lambda response: '/api/receipts/drafts' in response.url and response.request.method == 'POST'):
                    page.get_by_role('textbox', name='상호', exact=True).fill('EDITED SYNTHETIC')
                page.wait_for_function("""async () => {
                  const response=await fetch('/api/receipts/drafts',{headers:{'X-CSRF-Token':csrf}});
                  const data=await response.json();
                  return data.drafts.some(d=>d.groups.some(g=>g.receipts.some(r=>r.merchant==='EDITED SYNTHETIC')));
                }""")
                first.close()
                with receipt_vision_jobs._LOCK:
                    receipt_vision_jobs._JOBS.clear()
                    receipt_vision_jobs._BY_IMAGE.clear()
                second = browser.new_context(viewport={'width': 390, 'height': 900})
                reopened = second.new_page()
                reopened.goto(self.base + '/receipts?trip=' + self.trip)
                reopened.locator('#draft-recovery button').first.click()
                self.assertEqual(reopened.get_by_role('textbox', name='상호', exact=True).input_value(), 'EDITED SYNTHETIC')
                self.assertTrue(reopened.get_by_text('영수증 후보 0건 · 원본 저장됨').is_visible())
                self.assertEqual(reopened.locator('#selected-trip').input_value(), self.trip)
                second.close()
            finally:
                browser.close()

    def test_two_tabs_keep_local_edit_when_draft_revision_conflicts(self):
        sha = self.request('/api/receipts/image', token=self.csrf(), raw=review.PNG)[1]['sha256']
        import uuid
        draft = {'draft_id': uuid.uuid4().hex, 'expected_revision': 0, 'trip_id': self.trip,
                 'groups': [{'sha': sha, 'kind': 'analysis', 'jobId': None,
                             'receipts': [{'merchant': 'SYNTHETIC', 'date': '2026-10-12', 'amount': 100,
                                           'currency': 'JPY', 'payment': 'cash', 'include': True}]}]}
        self.assertEqual(self.request('/api/receipts/drafts', draft, token=self.csrf())[0], 200)
        with patch('webapp.receipt_review.receipt_vision.enabled', return_value=True), sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                contexts = [browser.new_context(), browser.new_context()]
                pages = [context.new_page() for context in contexts]
                for page in pages:
                    page.goto(self.base + '/receipts?trip=' + self.trip)
                    page.locator('#draft-recovery button').first.click()
                pages[0].get_by_role('textbox', name='상호', exact=True).fill('FIRST')
                pages[0].wait_for_function("document.getElementById('draft-status').textContent.includes('저장됨')")
                pages[1].get_by_role('textbox', name='상호', exact=True).fill('SECOND')
                pages[1].get_by_role('button', name='현재 입력을 새 초안으로 보관').wait_for(timeout=30000)
                self.assertEqual(pages[1].get_by_role('textbox', name='상호', exact=True).input_value(), 'SECOND')
                saved = self.request('/api/receipts/drafts', token=self.csrf())[1]['drafts']
                self.assertEqual(saved[0]['groups'][0]['receipts'][0]['merchant'], 'FIRST')
                pages[1].get_by_role('button', name='현재 입력을 새 초안으로 보관').click()
                pages[1].wait_for_function("document.getElementById('draft-status').textContent.includes('저장됨')")
                saved = self.request('/api/receipts/drafts', token=self.csrf())[1]['drafts']
                assert {draft['groups'][0]['receipts'][0]['merchant'] for draft in saved} == {'FIRST', 'SECOND'}
                for context in contexts:
                    context.close()
            finally:
                browser.close()

    def test_lost_analysis_response_recovers_unknown_without_automatic_resubmit(self):
        with patch('webapp.receipt_review.receipt_vision.enabled', return_value=True), sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                first = browser.new_context()
                page = first.new_page()
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.set_input_files('#img-file', {'name': 'photo.png', 'mimeType': 'image/png', 'buffer': review.PNG})
                page.click('#img-go')
                page.locator('#upload-results img').wait_for()
                page.route('**/api/receipts/vision', lambda route: route.abort())
                page.click('#vision-go')
                page.get_by_text('분석 완료 여부를 확인하지 못했습니다.', exact=False).wait_for(timeout=30000)
                page.wait_for_function("document.getElementById('draft-status').textContent.includes('저장됨')")
                saved = self.request('/api/receipts/drafts', token=self.csrf())[1]['drafts']
                self.assertEqual(saved[0]['groups'][0]['status'], 'unknown')
                first.close()
                second = browser.new_context()
                reopened = second.new_page()
                calls = []
                reopened.on('request', lambda request: calls.append(request.url)
                            if request.method == 'POST' and request.url.endswith('/api/receipts/vision') else None)
                reopened.goto(self.base + '/receipts?trip=' + self.trip)
                reopened.locator('#draft-recovery button').first.click()
                self.assertTrue(reopened.get_by_text('분석 완료 여부를 확인하지 못했습니다.', exact=False).is_visible())
                self.assertEqual(calls, [])
                second.close()
            finally:
                browser.close()

    def test_lost_registration_response_recovers_committed_result_without_duplicate(self):
        import uuid
        sha = self.request('/api/receipts/image', token=self.csrf(), raw=review.PNG)[1]['sha256']
        draft = {'draft_id': uuid.uuid4().hex, 'expected_revision': 0, 'trip_id': self.trip,
                 'groups': [{'sha': sha, 'kind': 'analysis', 'jobId': None,
                             'receipts': [{'merchant': 'SYNTHETIC', 'date': '2026-10-12', 'amount': 100,
                                           'currency': 'JPY', 'payment': 'cash', 'include': True}]}]}
        self.assertEqual(self.request('/api/receipts/drafts', draft, token=self.csrf())[0], 200)
        with patch('webapp.receipt_review.receipt_vision.enabled', return_value=True), sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.locator('#draft-recovery button').first.click()
                def lose_response(route):
                    route.fetch()
                    route.abort()
                page.route('**/api/receipts/scan', lose_response, times=1)
                page.click('#vision-register')
                page.get_by_role('button', name='현재 입력을 새 초안으로 보관').wait_for(timeout=30000)
                self.assertEqual(len(self.request('/api/receipts')[1]['candidates']), 1)
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='저장된 분석 결과 열기', exact=False).click()
                page.get_by_role('link', name='화면을 다시 열어 등록 내역 확인').click()
                page.locator('[data-version]').first.wait_for()
                self.assertEqual(len(self.request('/api/receipts')[1]['candidates']), 1)
            finally:
                browser.close()

    def test_failed_file_recovery_waits_for_the_remaining_upload(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                pending = []
                def hold_second_file(route):
                    if 'waiting.png' in route.request.headers.get('x-receipt-filename', ''):
                        pending.append(route)
                    else:
                        route.continue_()
                page.route('**/api/receipts/image', hold_second_file)
                page.set_input_files('#img-file', [
                    {'name': 'bad.png', 'mimeType': 'image/png', 'buffer': b'invalid'},
                    {'name': 'waiting.png', 'mimeType': 'image/png', 'buffer': review.PNG},
                ])
                page.click('#img-go')
                retry = page.get_by_role('button', name='다시 시도', exact=True)
                remove = page.get_by_role('button', name='실패 파일 제거', exact=True)
                retry.wait_for()
                page.wait_for_function("document.querySelectorAll('#upload-results p').length===2")
                self.assertTrue(retry.is_disabled())
                self.assertTrue(remove.is_disabled())
                self.assertEqual(len(pending), 1)
                pending[0].continue_()
                page.wait_for_function("document.querySelectorAll('#upload-results p')[1].textContent.includes('원본 저장됨')")
                page.wait_for_function("[...document.querySelectorAll('#upload-results button')].filter(b=>b.dataset.uploadRecovery).every(b=>!b.disabled)")
                remove.click()
                self.assertEqual(page.locator('#upload-results p').count(), 1)
                self.assertEqual(len(self.request('/api/receipts')[1]['images']), 1)
            finally:
                browser.close()

    def test_failed_uploads_are_compact_cards_with_bulk_actions_at_375px(self):
        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 375, 'height': 800})
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.set_input_files('#img-file', [
                    {'name': '20261012_161558_a_very_long_receipt_file_name_from_phone.jpg', 'mimeType': 'image/jpeg', 'buffer': b'\xff\xd8\xffbroken'},
                    {'name': 'bad.png', 'mimeType': 'image/png', 'buffer': b'invalid'},
                ])
                page.click('#img-go')
                bulk = page.locator('#upload-bulk')
                bulk.wait_for()
                self.assertIn('실패 2개', bulk.inner_text())
                self.assertEqual(page.locator('#upload-results .is-fail').count(), 2)
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth<=375"))
                box = page.locator('#upload-results .upload-name').first.bounding_box()
                self.assertLess(box['height'], 30)
                page.get_by_role('button', name='모두 제거').click()
                self.assertEqual(page.locator('#upload-results .is-fail').count(), 0)
                self.assertTrue(bulk.is_hidden())
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
            return {'receipts': found, 'label': 'Claude opus', 'lesson': None}
        if name == self.photos[1]:
            return {'receipts': [receipt('CAFE', '2026-10-11', 12000, currency='KRW')], 'label': 'Claude opus', 'lesson': None}
        return {'receipts': [], 'label': 'Claude opus', 'lesson': None}

    def test_rescan_retry_uses_rescan_for_failed_group_and_keeps_original_candidate(self):
        analysis_calls = []
        rescan_payloads = []
        original = receipt('ORIGINAL SHOP', '2026-10-11', 12000)
        retried = receipt('RESCAN SHOP', '2026-10-12', 900)

        def analysis_route(route):
            if route.request.method != 'POST':
                route.continue_()
                return
            analysis_calls.append(route.request.method)
            route.fulfill(status=202, content_type='application/json', body=json.dumps({
                'job_id': 'a' * 32, 'status': 'done', 'result': {'receipts': [original]},
            }))

        def rescan_route(route):
            rescan_payloads.append(json.loads(route.request.post_data or '{}'))
            if len(rescan_payloads) == 1:
                state = {'job_id': 'b' * 32, 'status': 'failed',
                         'code': 'VISION_ALL_MODELS_UNAVAILABLE'}
            else:
                state = {'job_id': 'c' * 32, 'status': 'done',
                         'result': {'engine': 'windows_ocr'}}
            route.fulfill(status=202, content_type='application/json', body=json.dumps(state))

        def new_route(route):
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'new': [retried]}))

        with patch('webapp.receipt_review.receipt_vision.enabled', return_value=True), sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.route('**/api/receipts/vision', analysis_route)
                page.route('**/api/receipts/vision/rescan', rescan_route)
                page.route('**/api/receipts/vision/new', new_route)
                page.goto(self.base + '/receipts?trip=' + self.trip)
                page.set_input_files('#img-file', {
                    'name': 'synthetic-rescan.png', 'mimeType': 'image/png', 'buffer': review.PNG,
                })
                page.click('#img-go')
                page.locator('[data-image-sha]').first.wait_for()
                page.click('#vision-go')
                page.wait_for_function(
                    "document.getElementById('vision-summary').textContent.includes('후보 1건')"
                )

                page.locator('[data-image-sha]').first.click()
                page.locator('details.rescan > summary').click()
                page.fill('#feedback', '누락 영수증 한 장을 더 찾아')
                page.click('#rescan-go')
                page.wait_for_function(
                    "document.getElementById('vision-summary').textContent.includes('영수증 다시 분석에 실패했습니다.')"
                )
                self.assertNotIn('새 후보 0건', page.locator('#vision-results').inner_text())
                page.locator('#vision-results').get_by_role(
                    'button', name='이 사진 다시 분석'
                ).click()
                page.locator('#vision-results .result-group h4').filter(
                    has_text='새 후보 1건'
                ).wait_for(timeout=15000)

                self.assertEqual(len(analysis_calls), 1)
                self.assertEqual(len(rescan_payloads), 2)
                self.assertEqual([payload['feedback'] for payload in rescan_payloads],
                                 ['누락 영수증 한 장을 더 찾아'] * 2)
                self.assertIn('Windows OCR 참고값을 사용한 사진 1장입니다.',
                              page.locator('#vision-summary').inner_text())
                merchants = [
                    page.locator('.receipt-card').nth(index)
                    .get_by_role('textbox', name='상호', exact=True).input_value()
                    for index in range(page.locator('.receipt-card').count())
                ]
                self.assertEqual(merchants, ['ORIGINAL SHOP', 'RESCAN SHOP'])

                page.reload()
                page.get_by_text(
                    'AI 판독을 완료하지 못해 Windows OCR 참고값을 사용했습니다. 내용을 확인해 주세요.',
                    exact=True,
                ).wait_for()
                self.assertEqual(page.locator('.receipt-card').count(), 2)
            finally:
                browser.close()

    def test_three_photos_are_analysed_registered_and_refreshed(self):
        from webapp import receipt_vision_jobs
        with receipt_vision_jobs._LOCK:
            receipt_vision_jobs._JOBS.clear()
            receipt_vision_jobs._BY_IMAGE.clear()
        shots = os.environ.get('WEBLEDGER_FLOW_SHOTS')
        self.photos = []
        env = patch.dict(os.environ, {'WEBLEDGER_RECEIPT_VISION': 'claude-opus',
                                      'WEBLEDGER_RECEIPT_LEARNING': str(Path(self._dir.name) / 'learning.jsonl')})
        env.start()
        recognizer = patch('webapp.receipt_review.receipt_vision.recognize_with_fallback',
                           side_effect=lambda path, **kw: self._answers(path, **kw))
        recognizer.start()
        engine = patch('webapp.receipt_review.receipt_vision.enabled', return_value=True)
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
                    self.assertEqual(page.evaluate("JSON.parse(sessionStorage.getItem('cost-receipt-pending')||'[]').filter(g=>g.empty).length"), 1)
                    self.assertTrue(page.get_by_text('영수증 후보 0건 · 원본 저장됨').is_visible())
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
