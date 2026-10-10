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

    def request(self, path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method='POST' if body is not None else 'GET')
        req.add_header('Content-Type', 'application/json')
        if token:
            req.add_header('X-CSRF-Token', token)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read().decode('utf-8') or '{}')
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode('utf-8') or '{}')

    def csrf(self):
        return ledger_board.CSRF_TOKEN

    def test_upload_of_an_image_is_refused_until_an_engine_is_approved(self):
        status, body = self.request('/api/receipts/upload', {'file': 'x'}, token=self.csrf())
        self.assertEqual((status, body['code']), (501, 'OCR_ENGINE_NOT_APPROVED'))

    def test_scan_holds_unclear_regions_and_adds_nothing_on_a_repeat(self):
        status, first = self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        self.assertEqual(status, 200)
        self.assertEqual(first['added'], 2)
        self.assertEqual({h['reason'] for h in first['holds']}, {'LOW_CONFIDENCE'})
        _, again = self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        self.assertEqual(again['added'], 0)
        _, stored = self.request('/api/receipts')
        self.assertEqual(len(stored['candidates']), 2)

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

    def test_browser_scan_confirm_and_copy_match_the_endpoint(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                          viewport={'width': 390, 'height': 844})
            page = context.new_page()
            page.goto(self.base + '/receipts')
            page.fill('#scan', json.dumps(REGIONS, ensure_ascii=False))
            page.click('#scan-go')
            page.wait_for_load_state()
            page.locator('[data-confirm]').first.wait_for()
            identity = page.locator('[data-confirm]').first.get_attribute('data-confirm')
            page.fill(f'[data-payee="{identity}"]', '라멘집')
            page.fill(f'[data-category="{identity}"]', '식비')
            page.click(f'[data-confirm="{identity}"]')
            page.wait_for_load_state()
            page.click('#copy-tsv')
            page.get_by_text('클립보드에 복사했습니다', exact=False).wait_for()
            clipboard = page.evaluate('navigator.clipboard.readText()').replace(chr(13) + chr(10), chr(10))
            _, tsv = self.request('/api/receipts/tsv')
            self.assertEqual(clipboard, tsv['tsv'])
            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            browser.close()
