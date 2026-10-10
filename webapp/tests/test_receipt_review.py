import http.client
import json
import os
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import ledger_board
from webapp.card_flow import CardFlow
from webapp.tests.test_card_flow import CARD

REGIONS = {"regions": [
    {"box": [0, 0, 100, 100], "merchant": "라멘집", "date": "2027-08-03", "currency": "JPY", "total": 1234,
     "payment": "cash", "confidence": 0.95},
    {"box": [110, 0, 210, 100], "merchant": "역 매점", "date": "2027-08-03", "currency": "JPY", "total": 500,
     "payment": "private_card", "confidence": 0.9},
    {"box": [0, 300, 100, 400], "merchant": "흐림", "date": "2027-08-03", "currency": "JPY", "total": 900,
     "payment": "cash", "confidence": 0.4}]}
def make_png():
    """A valid 1x1 PNG built here, so the structural check runs on a real file."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b""))


PNG = make_png()
JPEG = b"\xff\xd8\xff" + b"synthetic jpeg bytes" * 20 + b"\xff\xd9"


def _card_purchase(board, batch_id, transaction_id, merchant, amount_jpy, date):
    board.conn.execute(
        "INSERT INTO transactions(transaction_id, source_hash, batch_id, issuer, card_tail, card_kind,"
        " transaction_direction, transaction_kind, approval_number, original_approval_number, approval_date,"
        " posting_date, merchant, merchant_normalized, amount_krw, foreign_amount, foreign_currency,"
        " description_raw, row_index, raw_row_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (transaction_id, 'hash-' + transaction_id, batch_id, '국민', '1234', 'domestic', 'purchase', 'purchase',
         'AP-' + transaction_id, '', date, date, merchant, merchant, amount_jpy * 10, str(amount_jpy), 'JPY', '',
         9, '{}', '2027-08-03T00:00:00+00:00'))
    board.conn.commit()



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
        self._owner = patch.object(ledger_board, '_receipts_owner_request', return_value=True)
        self._owner.start()
        CardFlow(self.server.card_store)  # creates the card tables the board reads for card links

    def tearDown(self):
        self._owner.stop()
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


    def test_without_owner_every_receipt_route_is_refused(self):
        self._owner.stop()
        self._owner = patch.object(ledger_board, '_receipts_owner_request', return_value=False)
        self._owner.start()
        for method_path in (('GET', '/receipts'), ('GET', '/api/receipts'), ('GET', '/api/receipts/tsv'),
                            ('GET', '/api/receipts/image/' + 'a' * 64)):
            status, body = self.request(method_path[1])
            self.assertEqual(status, 403, method_path)
            self.assertEqual(body['code'], 'OWNER_ONLY', method_path)
        status, body = self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        self.assertEqual((status, body['code']), (403, 'OWNER_ONLY'))
        self.assertFalse(self.store.exists())

    def test_access_enforcement_off_means_no_owner_by_default(self):
        self._owner.stop()
        self._owner = patch.object(ledger_board, 'ACCESS_ENFORCEMENT', False)
        self._owner.start()
        self.assertFalse(ledger_board._receipts_owner_request())

    def test_client_sent_card_rows_are_ignored_and_the_server_decides_the_link(self):
        fake = dict(REGIONS['regions'][0], payment='corporate_card', merchant='카페', total=900, box=[0, 0, 9, 9])
        forged = {'regions': [fake], 'card_rows': [{'transaction_id': 'forged', 'date': '2027-08-03',
                                                    'merchant': '카페', 'original_jpy': 900}]}
        status, body = self.request('/api/receipts/scan', forged, token=self.csrf())
        self.assertEqual(status, 200)
        self.assertEqual(body['added'], 0)
        self.assertEqual({h['reason'] for h in body['holds']}, {'CARD_NOT_FOUND'})

    def test_a_real_card_purchase_in_the_database_is_linked_and_not_repriced(self):
        from webapp.card_flow import CardFlow
        batch = CardFlow(self.server.card_store).pipeline.receive(CARD, 'receipt-link.csv')['batch_id']
        _card_purchase(self.server.card_store, batch, 'card-cafe-1', '카페', 900, '2027-08-03')
        real = dict(REGIONS['regions'][0], payment='corporate_card', merchant='카페', total=900, box=[5, 5, 9, 9])
        status, body = self.request('/api/receipts/scan', {'regions': [real]}, token=self.csrf())
        self.assertEqual(status, 200)
        self.assertEqual(body['added'], 1)
        _, stored = self.request('/api/receipts')
        linked = stored['candidates'][-1]
        self.assertEqual(linked['card_transaction_id'], 'card-cafe-1')
        status, tsv = self.request('/api/receipts/tsv')
        self.assertNotIn('카페', tsv['tsv'])  # the card transaction is the one expense

    def test_forged_photo_bytes_are_refused_with_corrupt_or_type_codes(self):
        png_no_end = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR' + b'\x00' * 13 + b'\x00\x00\x00\x00IDAT'
        self.assertEqual(self.request('/api/receipts/image', token=self.csrf(), raw=png_no_end)[1]['code'],
                         'IMAGE_CORRUPT')
        jpeg_no_end = b'\xff\xd8\xff' + b'pixel data without an end marker'
        self.assertEqual(self.request('/api/receipts/image', token=self.csrf(), raw=jpeg_no_end)[1]['code'],
                         'IMAGE_TYPE_UNSUPPORTED')
        html_with_png_signature = b'\x89PNG\r\n\x1a\n<script>alert(1)</script>'
        self.assertEqual(self.request('/api/receipts/image', token=self.csrf(), raw=html_with_png_signature)[1]['code'],
                         'IMAGE_CORRUPT')

    def test_served_media_type_comes_from_the_bytes(self):
        import urllib.request as ur
        jpeg = b'\xff\xd8\xff' + b'synthetic jpeg' + b'\xff\xd9'
        sha = self.request('/api/receipts/image', token=self.csrf(), raw=jpeg)[1]['sha256']
        with ur.urlopen(self.base + '/api/receipts/image/' + sha) as response:
            self.assertEqual(response.headers.get_content_type(), 'image/jpeg')
            self.assertEqual(response.read(), jpeg)
        sha = self.request('/api/receipts/image', token=self.csrf(), raw=PNG)[1]['sha256']
        with ur.urlopen(self.base + '/api/receipts/image/' + sha) as response:
            self.assertEqual(response.headers.get_content_type(), 'image/png')

    def test_oversized_photo_is_refused_at_the_same_ceiling_as_the_board(self):
        from webapp import receipt_review
        self.assertEqual(receipt_review.IMAGE_LIMIT, 5 * 1024 * 1024)
        too_big = b'\xff\xd8\xff' + b'0' * (5 * 1024 * 1024) + b'\xff\xd9'
        # The board answers 413 before it reads the body, so the client may see the connection close instead.
        try:
            status, body = self.request('/api/receipts/image', token=self.csrf(), raw=too_big)
            self.assertEqual(status, 413)
        except (http.client.RemoteDisconnected, ConnectionError, urllib.error.URLError):
            pass
        with self.assertRaises(ValueError) as raised:
            receipt_review.store_image(self.store, too_big)
        self.assertEqual(str(raised.exception), 'IMAGE_SIZE_INVALID')
