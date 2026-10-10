import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import ledger_board

REGIONS = {"regions": [
    {"box": [0, 0, 100, 100], "merchant": "라멘집", "date": "2027-08-03", "currency": "JPY", "total": 1234,
     "payment": "cash", "confidence": 0.95},
    {"box": [110, 0, 210, 100], "merchant": "역 매점", "date": "2027-08-03", "currency": "JPY", "total": 500,
     "payment": "private_card", "confidence": 0.9},
    {"box": [0, 300, 100, 400], "merchant": "흐림", "date": "2027-08-03", "currency": "JPY", "total": 900,
     "payment": "cash", "confidence": 0.4}]}
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic receipt photo bytes" * 20
JPEG = b"\xff\xd8\xff" + b"synthetic jpeg bytes" * 20


class ReceiptReviewTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = Path(self._dir.name) / 'receipts.json'
        self._env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1',
                                            'WEBLEDGER_REVIEW_FROM': '',
                                            'WEBLEDGER_RECEIPTS_STORE': str(self.store)})
        self._env.start()
        self._previous = ledger_board._STORE
        ledger_board.bind_access(None)
        self.server = ledger_board.serve(port=0, db_path=Path(self._dir.name) / 'board.sqlite',
                                         with_worker=False, seed_demo=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.card_store.close()
        self.thread.join(timeout=3)
        ledger_board.bind_store(self._previous)
        self._env.stop()
        self._dir.cleanup()

    def request(self, path, body=None, token=None, raw=None, method=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data,
                                     method=method or ('POST' if data is not None else 'GET'))
        req.add_header('Content-Type', 'application/json' if raw is None else 'application/octet-stream')
        if token:
            req.add_header('X-CSRF-Token', token)
        try:
            with urllib.request.urlopen(req) as response:
                payload = response.read()
                return response.status, (json.loads(payload.decode('utf-8')) if response.headers.get_content_type()
                                         == 'application/json' else payload)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode('utf-8') or '{}')

    def csrf(self):
        return ledger_board.CSRF_TOKEN

    def test_upload_of_an_image_is_refused_until_an_engine_is_approved(self):
        status, body = self.request('/api/receipts/upload', {'file': 'x'}, token=self.csrf())
        self.assertEqual((status, body['code']), (501, 'OCR_ENGINE_NOT_APPROVED'))

    def test_registered_photo_is_stored_by_content_and_served_back(self):
        status, body = self.request('/api/receipts/image', token=self.csrf(), raw=PNG)
        self.assertEqual(status, 200)
        sha = body['sha256']
        again = self.request('/api/receipts/image', token=self.csrf(), raw=PNG)[1]
        self.assertEqual(again['sha256'], sha)
        status, served = self.request(f'/api/receipts/image/{sha}')
        self.assertEqual((status, served), (200, PNG))

    def test_only_png_or_jpeg_bytes_are_accepted(self):
        status, body = self.request('/api/receipts/image', token=self.csrf(), raw=b'<html>not a photo</html>')
        self.assertEqual((status, body['code']), (400, 'IMAGE_TYPE_UNSUPPORTED'))
        self.assertEqual(self.request('/api/receipts/image', token=self.csrf(), raw=JPEG)[0], 200)

    def test_scan_holds_unclear_regions_and_adds_nothing_on_a_repeat(self):
        status, first = self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        self.assertEqual(status, 200)
        self.assertEqual(first['added'], 2)
        self.assertEqual({h['reason'] for h in first['holds']}, {'LOW_CONFIDENCE'})
        _, again = self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        self.assertEqual(again['added'], 0)
        _, stored = self.request('/api/receipts')
        self.assertEqual(len(stored['candidates']), 2)

    def test_scan_on_an_unknown_photo_is_refused(self):
        status, body = self.request('/api/receipts/scan', {'image': 'f' * 64, 'regions': REGIONS['regions'][:1]},
                                    token=self.csrf())
        self.assertEqual(status, 404)

    def test_manual_edit_reprices_cash_and_keeps_history(self):
        self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        _, stored = self.request('/api/receipts')
        identity = stored['candidates'][0]['identity']
        status, body = self.request('/api/receipts/edit', {'identity': identity, 'total_jpy': 1300}, token=self.csrf())
        self.assertEqual(status, 200)
        self.assertEqual(body['amount_krw'], 13000)
        self.assertEqual(body['history'][-1]['edit'], {'total_jpy': 1234})
        status, body = self.request('/api/receipts/edit', {'identity': identity, 'category': '식비'}, token=self.csrf())
        self.assertEqual((status, body['code']), (400, 'FIELD_NOT_EDITABLE'))

    def test_writes_need_the_csrf_token(self):
        status, body = self.request('/api/receipts/scan', REGIONS)
        self.assertEqual((status, body['code']), (403, 'CSRF_REQUIRED'))

    def test_confirm_needs_payee_and_category_and_keeps_history(self):
        self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        _, stored = self.request('/api/receipts')
        identity = stored['candidates'][0]['identity']
        status, _ = self.request('/api/receipts/confirm',
                                 {'identity': identity, 'payee': '', 'category': '식비'}, token=self.csrf())
        self.assertEqual(status, 400)
        status, body = self.request('/api/receipts/confirm',
                                    {'identity': identity, 'payee': '라멘집', 'category': '식비'}, token=self.csrf())
        self.assertEqual(status, 200)
        self.assertEqual(body['history'][0]['to'], {'payee': '라멘집', 'category': '식비'})

    def test_tsv_has_confirmed_receipts_only_and_lists_holds(self):
        self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        _, stored = self.request('/api/receipts')
        for candidate in stored['candidates']:
            self.request('/api/receipts/confirm', {'identity': candidate['identity'],
                                                   'payee': candidate['merchant'], 'category': '식비'},
                         token=self.csrf())
        _, tsv = self.request('/api/receipts/tsv')
        self.assertEqual(tsv['row_count'], 2)
        self.assertIn('\t영수증\t12340', tsv['tsv'])
        self.assertTrue(any(h['reason'] == 'LOW_CONFIDENCE' for h in tsv['held']))

    def _browser_flow(self, width, height):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                          viewport={'width': width, 'height': height})
            page = context.new_page()
            page.goto(self.base + '/receipts')
            page.set_input_files('#img-file', files=[{'name': 'receipt.png', 'mimeType': 'image/png',
                                                      'buffer': PNG}])
            page.click('#img-go')
            # The page reloads after a registration, so the registered photo itself is the signal.
            page.locator("img[src*='/api/receipts/image/']").first.wait_for()
            page.wait_for_load_state()
            page.fill('#box1', '0'); page.fill('#box2', '0'); page.fill('#box3', '100'); page.fill('#box4', '100')
            page.fill('#r-merchant', '라멘집'); page.fill('#r-date', '2027-08-03'); page.fill('#r-total', '1234')
            page.click('#region-go')
            page.wait_for_load_state()
            page.locator('[data-confirm]').first.wait_for()
            identity = page.locator('[data-confirm]').first.get_attribute('data-confirm')
            page.fill(f'[data-total="{identity}"]', '1300')
            page.click(f'[data-edit="{identity}"]')
            page.wait_for_load_state()
            page.locator(f'[data-total="{identity}"]').wait_for()
            self.assertEqual(page.locator(f'[data-total="{identity}"]').input_value(), '1300')
            page.fill(f'[data-payee="{identity}"]', '라멘집')
            page.fill(f'[data-category="{identity}"]', '식비')
            page.click(f'[data-confirm="{identity}"]')
            page.wait_for_load_state()
            page.click('#copy-tsv')
            page.get_by_text('클립보드에 복사했습니다', exact=False).wait_for()
            clipboard = page.evaluate('navigator.clipboard.readText()').replace(chr(13) + chr(10), chr(10))
            self.assertIn('\t영수증\t13000', clipboard)
            _, tsv = self.request('/api/receipts/tsv')
            self.assertEqual(clipboard, tsv['tsv'])
            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            browser.close()

    def test_browser_mobile_390_photo_region_edit_confirm_and_copy(self):
        self._browser_flow(390, 844)

    def test_browser_desktop_1440_photo_region_edit_confirm_and_copy(self):
        self._browser_flow(1440, 900)
