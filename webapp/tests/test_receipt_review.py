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
def make_png(rgb=b'\xff\x00\x00'):
    """A valid 1x1 PNG built here, so the structural check runs on a real file."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" + rgb))
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
        self.trip = self.server.card_store.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                                                       destination='합성 여행', client_request_id='receipt-trip')['tab_id']

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

    def test_scan_rejects_malformed_regions_without_writing(self):
        valid = REGIONS['regions'][0]
        invalid = [[], {'regions': ['bad']}, {'regions': [{}]}]
        for box in ([0, 0], [0, 0, 0, 100], [-1, 0, 100, 100], [0, 0, '100', 100]):
            invalid.append({'regions': [{**valid, 'box': box}]})
        for confidence in (float('nan'), float('inf'), -0.1, 1.1, True):
            invalid.append({'regions': [{**valid, 'confidence': confidence}]})
        for payload in invalid:
            with self.subTest(payload=payload):
                status, _ = self.request('/api/receipts/scan', payload, token=self.csrf())
                self.assertEqual(status, 400)
                self.assertFalse(self.store.exists())

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

    def test_a_receipt_joins_a_trip_only_when_the_board_holds_that_trip(self):
        self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        _, stored = self.request('/api/receipts')
        identity = stored['candidates'][0]['identity']
        status, body = self.request('/api/receipts/edit', {'identity': identity, 'trip_id': 'trip-made-up'},
                                    token=self.csrf())
        self.assertEqual((status, body['code']), (400, 'TRIP_UNKNOWN'))
        status, body = self.request('/api/receipts/edit', {'identity': identity, 'trip_id': self.trip},
                                    token=self.csrf())
        self.assertEqual((status, body['trip_id']), (200, self.trip))

    def test_copy_needs_a_trip_and_only_copies_that_trips_confirmed_receipts(self):
        self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        _, stored = self.request('/api/receipts')
        self.assertEqual(self.request('/api/receipts/tsv')[1]['code'], 'TRIP_REQUIRED')
        for candidate in stored['candidates']:
            self.request('/api/receipts/edit', {'identity': candidate['identity'], 'trip_id': self.trip},
                         token=self.csrf())
            self.request('/api/receipts/confirm', {'identity': candidate['identity'],
                                                   'payee': candidate['merchant'], 'category': '식비'},
                         token=self.csrf())
        _, tsv = self.request(f'/api/receipts/tsv?trip={self.trip}')
        self.assertEqual(tsv['row_count'], 2)
        self.assertIn('\t영수증\t12340', tsv['tsv'])
        self.assertTrue(any(h['reason'] == 'LOW_CONFIDENCE' for h in tsv['held']))
        _, other = self.request('/api/receipts/tsv?trip=trip-other')
        self.assertEqual(other['row_count'], 0)

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
            page.select_option(f'[data-trip="{identity}"]', self.trip)
            page.fill(f'[data-total="{identity}"]', '1300')
            page.click(f'[data-edit="{identity}"]')
            page.wait_for_load_state()
            page.locator(f'[data-total="{identity}"]').wait_for()
            self.assertEqual(page.locator(f'[data-total="{identity}"]').input_value(), '1300')
            page.fill(f'[data-payee="{identity}"]', '라멘집')
            page.fill(f'[data-category="{identity}"]', '식비')
            page.click(f'[data-confirm="{identity}"]')
            page.wait_for_load_state()
            page.select_option('#copy-trip', self.trip)
            page.click('#copy-tsv')
            page.get_by_text('클립보드에 복사했습니다', exact=False).wait_for()
            clipboard = page.evaluate('navigator.clipboard.readText()').replace(chr(13) + chr(10), chr(10))
            self.assertIn('\t영수증\t13000', clipboard)
            _, tsv = self.request(f'/api/receipts/tsv?trip={self.trip}')
            self.assertEqual(clipboard, tsv['tsv'])
            self.assertTrue(page.evaluate('(trip)=>Boolean(localStorage.getItem("gcopy-trip:"+trip))', self.trip))
            dialogs = []
            page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
            page.click('#copy-tsv')
            self.assertTrue(any('이미 구글 시트용으로 복사' in message for message in dialogs))
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
        status, tsv = self.request(f'/api/receipts/tsv?trip={self.trip}')
        self.assertNotIn('카페', tsv['tsv'])  # the card transaction is the one expense

    def test_browser_assigns_trip_to_linked_receipt_without_changing_card(self):
        batch = CardFlow(self.server.card_store).pipeline.receive(CARD, 'trip-link.csv')['batch_id']
        _card_purchase(self.server.card_store, batch, 'card-trip-syn', 'SYN-SHOP', 900, '2027-08-03')
        region = dict(REGIONS['regions'][0], payment='corporate_card', merchant='SYN-SHOP', total=900)
        self.request('/api/receipts/scan', {'regions': [region]}, token=self.csrf())
        before = self.server.card_store.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(self.base + '/receipts')
            page.locator('[data-trip]').select_option(self.trip)
            with page.expect_response('**/api/receipts/edit') as answer:
                page.locator('[data-edit]').click()
            self.assertEqual(answer.value.status, 200)
            # The page reloads on save; read persisted state instead of a discarded response body.
            result = self.request('/api/receipts')[1]['candidates'][0]
            self.assertEqual(result['trip_id'], self.trip)
            self.assertEqual(result['card_transaction_id'], 'card-trip-syn')
            self.assertIsNone(result['amount_krw'])
            browser.close()
        self.assertEqual(self.server.card_store.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall(), before)

    def test_browser_selects_earlier_photo_and_keeps_candidate_source(self):
        first = self.request('/api/receipts/image', token=self.csrf(), raw=PNG)[1]['sha256']
        self.request('/api/receipts/image', token=self.csrf(), raw=make_png(b'\x00\xff\x00'))
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(self.base + '/receipts')
            page.locator('[data-image-sha]').first.click()
            self.assertEqual(page.locator('#image-sha').input_value(), first)
            for index, value in enumerate((0, 0, 100, 100), start=1):
                page.fill('#box' + str(index), str(value))
            page.fill('#r-merchant', 'SYN-SHOP')
            page.fill('#r-date', '2027-08-03')
            page.fill('#r-total', '1234')
            with page.expect_response('**/api/receipts/scan') as answer:
                page.locator('#region-go').click()
            self.assertEqual(answer.value.status, 200)
            page.get_by_role('link', name='원본 사진', exact=True).wait_for()
            browser.close()
        candidate, = self.request('/api/receipts')[1]['candidates']
        self.assertEqual(candidate['image_sha'], first)
        self.assertEqual(candidate['box'], [0, 0, 100, 100])

    def test_browser_photo_upload_blocks_double_click_and_recovers_from_error(self):
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.route('**/api/receipts/image', lambda route: pending.append(route))
            page.goto(self.base + '/receipts')
            page.locator('#img-file').set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': PNG})
            with page.expect_request('**/api/receipts/image'):
                page.locator('#img-go').click()
            self.assertTrue(page.locator('#img-go').is_disabled())
            page.locator('#img-go').evaluate('(button)=>{button.click();button.click()}')
            self.assertEqual(len(pending), 1)
            pending.pop().fulfill(status=400, json={'code': 'IMAGE_SIZE_INVALID'})
            page.get_by_text('사진은 비어 있지 않은 5MB 이하 파일이어야 합니다.', exact=True).wait_for()
            self.assertTrue(page.locator('#img-go').is_enabled())
            self.assertFalse(self.store.exists())
            page.unroute('**/api/receipts/image')
            with page.expect_response('**/api/receipts/image') as answer:
                page.locator('#img-go').click()
            self.assertEqual(answer.value.status, 200)
            page.locator("img[alt='등록한 영수증 사진']").wait_for()
            self.assertEqual(len(self.request('/api/receipts')[1]['images']), 1)
            browser.close()

    def test_browser_copy_locks_trip_and_recovers_without_changing_clipboard(self):
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
            page = context.new_page()
            page.route('**/api/receipts/tsv?*', lambda route: pending.append(route))
            page.goto(self.base + '/receipts')
            page.evaluate("navigator.clipboard.writeText('KEEP-CLIPBOARD')")
            with page.expect_request('**/api/receipts/tsv?*'):
                page.click('#copy-tsv')
            self.assertTrue(page.locator('#copy-trip').is_disabled())
            self.assertTrue(page.locator('#copy-tsv').is_disabled())
            page.locator('#copy-tsv').evaluate('(button)=>{button.click();button.click()}')
            self.assertEqual(len(pending), 1)
            pending.pop().fulfill(status=400, json={'code': 'FIELD_MISSING'})
            page.get_by_text('상호·날짜·지급처·내용의 필수 입력을 확인해 주세요.', exact=True).wait_for()
            self.assertTrue(page.locator('#copy-trip').is_enabled())
            self.assertTrue(page.locator('#copy-tsv').is_enabled())
            self.assertEqual(page.evaluate('navigator.clipboard.readText()'), 'KEEP-CLIPBOARD')
            with page.expect_request('**/api/receipts/tsv?*'):
                page.click('#copy-tsv')
            pending.pop().fulfill(json={'row_count': 0, 'held': [], 'tsv': ''})
            page.get_by_text('복사할 확정 영수증이 없습니다. 보류 0건', exact=True).wait_for()
            self.assertTrue(page.locator('#copy-trip').is_enabled())
            self.assertTrue(page.locator('#copy-tsv').is_enabled())
            self.assertEqual(page.evaluate('navigator.clipboard.readText()'), 'KEEP-CLIPBOARD')
            browser.close()

    def test_receipt_copy_success_survives_copy_history_storage_failure(self):
        self.request('/api/receipts/scan', REGIONS, token=self.csrf())
        candidate = self.request('/api/receipts')[1]['candidates'][0]
        self.request('/api/receipts/edit', {'identity': candidate['identity'], 'trip_id': self.trip}, token=self.csrf())
        self.request('/api/receipts/confirm', {'identity': candidate['identity'], 'payee': candidate['merchant'],
                                             'category': '식비'}, token=self.csrf())
        expected = self.request(f'/api/receipts/tsv?trip={self.trip}')[1]['tsv']
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            page.goto(self.base + '/receipts')
            page.evaluate("()=>{Storage.prototype.setItem=()=>{throw new DOMException('storage full','QuotaExceededError')}}")
            page.click('#copy-tsv')
            page.wait_for_function('!document.getElementById("copy-tsv").disabled')
            self.assertIn('클립보드에 복사했습니다', page.locator('#status').inner_text())
            self.assertIn('복사 이력을 저장하지 못했습니다', page.locator('#status').inner_text())
            self.assertEqual(page.evaluate('navigator.clipboard.readText()').replace('\r\n', '\n'), expected)
            self.assertTrue(page.locator('#copy-trip').is_enabled())

    def test_receipt_copy_requires_confirmation_when_history_cannot_be_read(self):
        self._confirmed_cash_receipt()
        expected = self.request(f'/api/receipts/tsv?trip={self.trip}')[1]['tsv']
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            page.goto(self.base + '/receipts')
            page.evaluate("navigator.clipboard.writeText('KEEP')")
            page.evaluate("()=>{Storage.prototype.getItem=()=>{throw new DOMException('blocked','SecurityError')}}")
            dialogs = []
            def dismiss(dialog):
                dialogs.append(dialog.message)
                dialog.dismiss()
            page.on('dialog', dismiss)
            page.click('#copy-tsv')
            self.assertEqual(len(dialogs), 1)
            self.assertEqual(page.evaluate('navigator.clipboard.readText()'), 'KEEP')
            page.remove_listener('dialog', dismiss)
            page.on('dialog', lambda dialog: dialog.accept())
            page.click('#copy-tsv')
            page.wait_for_function("document.getElementById('status').textContent.includes('클립보드에 복사했습니다')")
            self.assertEqual(page.evaluate('navigator.clipboard.readText()').replace('\r\n', '\n'), expected)
            self.assertTrue(page.locator('#copy-tsv').is_enabled())
            browser.close()
            browser.close()

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

    def _confirmed_cash_receipt(self, merchant='라멘집', total=1234):
        region = dict(REGIONS['regions'][0], merchant=merchant, total=total, box=[1, 2, 30, 40])
        self.request('/api/receipts/scan', {'regions': [region]}, token=self.csrf())
        _, stored = self.request('/api/receipts')
        identity = [c for c in stored['candidates'] if c['merchant'] == merchant][-1]['identity']
        self.request('/api/receipts/edit', {'identity': identity, 'trip_id': self.trip}, token=self.csrf())
        self.request('/api/receipts/confirm', {'identity': identity, 'payee': merchant, 'category': '식비'},
                     token=self.csrf())
        return identity

    def test_confirm_refuses_unsaved_amount_or_trip_in_browser(self):
        identity = self._confirmed_cash_receipt()
        before = self.store.read_bytes()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/receipts')
            requests = []
            page.on('request', lambda request: requests.append(request.url)
                    if request.url.endswith('/api/receipts/confirm') else None)
            for selector, value in (('[data-total]', '2000'), ('[data-trip]', '')):
                page.reload()
                if selector == '[data-trip]':
                    page.locator(selector).select_option(value)
                else:
                    page.locator(selector).fill(value)
                page.locator('[data-payee]').fill('NEW-PAYEE')
                page.locator('[data-confirm]').click()
                page.wait_for_function("document.getElementById('status').textContent.includes('수정 버튼')")
                self.assertEqual(requests, [])
                self.assertEqual(self.store.read_bytes(), before)
                self.assertEqual(page.locator('[data-total]').input_value(), value if selector == '[data-total]' else '1234')
            browser.close()

    def test_receipt_copy_refuses_unsaved_review_changes(self):
        self._confirmed_cash_receipt()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            requests = []
            page.on('request', lambda request: requests.append(request.url)
                    if '/api/receipts/tsv?' in request.url else None)
            for selector, value in (('[data-total]', '2500'), ('[data-payee]', 'UNSAVED-PAYEE'),
                                    ('[data-category]', 'UNSAVED-CATEGORY'), ('[data-trip]', '')):
                page.goto(self.base + '/receipts')
                page.evaluate("navigator.clipboard.writeText('KEEP')")
                if selector == '[data-trip]':
                    page.locator(selector).select_option(value)
                else:
                    page.locator(selector).fill(value)
                page.click('#copy-tsv')
                page.wait_for_function('!receiptBusy')
                self.assertEqual(requests, [])
                self.assertIn('저장하지 않은 변경', page.locator('#status').inner_text())
                self.assertEqual(page.evaluate('navigator.clipboard.readText()'), 'KEEP')
            browser.close()

    def test_receipt_copy_keeps_other_trips_unsaved_changes_separate(self):
        self._confirmed_cash_receipt()
        other = self._confirmed_cash_receipt(merchant='OTHER-SHOP', total=500)
        other_trip = self.server.card_store.create_trip(starts_on='2027-01-01', ends_on='2027-01-03',
                                                        destination='OTHER-TRIP', client_request_id='other-trip')['tab_id']
        self.request('/api/receipts/edit', {'identity': other, 'trip_id': other_trip}, token=self.csrf())
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            page.goto(self.base + '/receipts')
            page.locator('[data-total="' + other + '"]').fill('700')
            page.locator('#copy-trip').select_option(self.trip)
            page.click('#copy-tsv')
            page.wait_for_function("document.getElementById('status').textContent.includes('클립보드에 복사했습니다')")
            self.assertEqual(page.locator('[data-total="' + other + '"]').input_value(), '700')
            self.assertNotIn('OTHER-SHOP', page.evaluate('navigator.clipboard.readText()'))
            browser.close()

    def test_old_receipt_page_cannot_confirm_a_new_amount(self):
        identity = self._confirmed_cash_receipt()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/receipts')
            self.request('/api/receipts/edit', {'identity': identity, 'total_jpy': 2000}, token=self.csrf())
            before = self.store.read_bytes()
            page.locator('[data-payee]').fill('OLD-PAGE-PAYEE')
            with page.expect_response('**/api/receipts/confirm') as response:
                page.locator('[data-confirm]').click()
            self.assertEqual(response.value.status, 409)
            self.assertEqual(response.value.json()['code'], 'STALE_CANDIDATE')
            self.assertEqual(self.store.read_bytes(), before)
            self.assertFalse(page.locator('[data-confirm]').is_disabled())
            browser.close()

    def test_old_receipt_page_cannot_overwrite_a_new_confirmation(self):
        identity = self._confirmed_cash_receipt()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/receipts')
            self.request('/api/receipts/confirm', {'identity': identity, 'payee': 'NEW-PAYEE',
                                                  'category': 'NEW-CATEGORY'}, token=self.csrf())
            before = self.store.read_bytes()
            page.locator('[data-total]').fill('2100')
            with page.expect_response('**/api/receipts/edit') as response:
                page.locator('[data-edit]').click()
            self.assertEqual(response.value.status, 409)
            self.assertEqual(response.value.json()['code'], 'STALE_CANDIDATE')
            self.assertEqual(self.store.read_bytes(), before)
            browser.close()

    def test_receipt_save_locks_controls_and_restores_inputs_after_error(self):
        self._confirmed_cash_receipt()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/receipts')
            pending = []
            page.route('**/api/receipts/edit', lambda route: pending.append(route))
            page.locator('[data-total]').fill('2300')
            with page.expect_request('**/api/receipts/edit'):
                page.locator('[data-edit]').click()
            for selector in ('[data-edit]', '[data-confirm]', '[data-total]', '#region-go', '#copy-tsv', '#img-go'):
                self.assertTrue(page.locator(selector).is_disabled(), selector)
            page.locator('[data-edit]').evaluate('(button)=>{button.click();button.click()}')
            self.assertEqual(len(pending), 1)
            pending.pop().fulfill(status=500, json={'message': 'RETRY-SAVE'})
            page.get_by_text('RETRY-SAVE', exact=True).wait_for()
            self.assertEqual(page.locator('[data-total]').input_value(), '2300')
            self.assertTrue(page.locator('[data-edit]').is_enabled())
            self.assertTrue(page.locator('[data-confirm]').is_enabled())
            page.unroute('**/api/receipts/edit')
            with page.expect_response('**/api/receipts/edit') as response:
                page.locator('[data-edit]').click()
            self.assertEqual(response.value.status, 200)
            page.wait_for_function("document.querySelector('[data-total]').value==='2300' && !document.querySelector('[data-edit]').disabled")
            self.assertEqual(self.request('/api/receipts')[1]['candidates'][0]['total_jpy'], 2300)
            browser.close()

    def test_receipt_save_retry_after_lost_response_preserves_one_history_entry(self):
        self._confirmed_cash_receipt()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            for operation in ('edit', 'confirm'):
                page.goto(self.base + '/receipts')
                if operation == 'edit':
                    page.locator('[data-total]').fill('2400')
                else:
                    page.locator('[data-payee]').fill('LOST-RESPONSE-PAYEE')
                    page.locator('[data-category]').fill('FOOD')
                requests = []
                def lose_first_response(route):
                    requests.append(route.request.post_data_json)
                    response = route.fetch()
                    if len(requests) == 1:
                        self.assertEqual(response.status, 200)
                        route.abort('failed')
                    else:
                        route.fulfill(response=response)
                pattern = '**/api/receipts/' + operation
                page.route(pattern, lose_first_response)
                page.locator('[data-' + operation + ']').click()
                page.wait_for_function("document.getElementById('status').textContent.includes('연결하지 못했습니다')")
                saved = self.store.read_bytes()
                with page.expect_response(pattern) as retry:
                    page.locator('[data-' + operation + ']').click()
                self.assertEqual(retry.value.status, 200)
                self.assertEqual(requests[0], requests[1])
                self.assertEqual(self.store.read_bytes(), saved)
                page.unroute(pattern)
            browser.close()

    def test_saving_one_receipt_preserves_other_receipts_unsaved_inputs(self):
        first = self._confirmed_cash_receipt()
        other = self._confirmed_cash_receipt(merchant='OTHER-SHOP', total=500)
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/receipts')
            page.locator(f'[data-total="{other}"]').fill('900')
            page.locator(f'[data-payee="{other}"]').fill('UNSAVED-PAYEE')
            page.locator('#r-merchant').fill('UNSAVED-REGION')
            page.locator(f'[data-total="{first}"]').fill('2600')
            with page.expect_response('**/api/receipts/edit'):
                page.locator(f'[data-edit="{first}"]').click()
            page.wait_for_load_state('networkidle')
            self.assertEqual(page.locator(f'[data-total="{other}"]').input_value(), '900')
            self.assertEqual(page.locator(f'[data-payee="{other}"]').input_value(), 'UNSAVED-PAYEE')
            self.assertEqual(page.locator('#r-merchant').input_value(), 'UNSAVED-REGION')
            self.assertEqual(page.locator(f'[data-payee="{first}"]').input_value(), '')
            self.assertIn('26,000', page.locator(f'[data-edit="{first}"]').locator('xpath=ancestor::tr').inner_text())
            page.locator(f'[data-payee="{first}"]').fill('SAVED-PAYEE')
            page.locator(f'[data-category="{first}"]').fill('FOOD')
            with page.expect_response('**/api/receipts/confirm') as confirmation:
                page.locator(f'[data-confirm="{first}"]').click()
            self.assertEqual(confirmation.value.status, 200)
            page.wait_for_function('!receiptBusy')
            self.assertEqual(page.locator(f'[data-total="{other}"]').input_value(), '900')
            saved = {row['identity']: row for row in self.request('/api/receipts')[1]['candidates']}
            self.assertEqual(saved[first]['total_jpy'], 2600)
            self.assertEqual(saved[first]['payee'], 'SAVED-PAYEE')
            self.assertEqual(saved[other]['total_jpy'], 500)
            browser.close()

    def test_non_json_receipt_failures_show_safe_recovery_messages(self):
        self._confirmed_cash_receipt()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            for status, expected in ((401, '다시 로그인'), (500, '저장 여부를 확인')):
                page.goto(self.base + '/receipts')
                page.locator('[data-total]').fill('2700')
                def fail_response(route):
                    route.fulfill(status=status, content_type='text/html', body='<h1>PRIVATE-SERVER-DETAILS</h1>')
                page.route('**/api/receipts/edit', fail_response)
                with page.expect_response('**/api/receipts/edit'):
                    page.locator('[data-edit]').click()
                page.wait_for_function('!receiptBusy')
                message = page.locator('#status').inner_text()
                self.assertIn(expected, message)
                self.assertNotIn('PRIVATE', message)
                self.assertEqual(page.locator('[data-total]').input_value(), '2700')
                self.assertTrue(page.locator('[data-edit]').is_enabled())
                page.unroute('**/api/receipts/edit')
            browser.close()

    def test_new_region_registration_does_not_discard_unsaved_receipt_review(self):
        self._confirmed_cash_receipt()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/receipts')
            page.locator('[data-total]').fill('2800')
            for selector, value in (('#box3', '100'), ('#box4', '100'), ('#r-merchant', 'NEW-SHOP'),
                                    ('#r-date', '2027-08-03'), ('#r-total', '700')):
                page.locator(selector).fill(value)
            requests = []
            page.on('request', lambda request: requests.append(request.url)
                    if request.url.endswith('/api/receipts/scan') else None)
            page.click('#region-go')
            page.wait_for_load_state('networkidle')
            self.assertEqual(requests, [])
            self.assertEqual(page.locator('[data-total]').input_value(), '2800')
            self.assertEqual(page.locator('#r-merchant').input_value(), 'NEW-SHOP')
            self.assertIn('먼저 저장', page.locator('#status').inner_text())
            with page.expect_response('**/api/receipts/edit'):
                page.locator('[data-edit]').click()
            page.wait_for_function('!receiptBusy')
            with page.expect_response('**/api/receipts/scan') as scan:
                page.click('#region-go')
            self.assertEqual(scan.value.status, 200)
            # Registration reloads the page; inspect the durable result after that response is discarded.
            stored = self.request('/api/receipts')[1]['candidates']
            self.assertEqual(len([candidate for candidate in stored if candidate['merchant'] == 'NEW-SHOP']), 1)
            browser.close()

    def test_switching_to_corporate_without_a_card_match_keeps_the_cash_amount_out_of_the_copy(self):
        identity = self._confirmed_cash_receipt()
        _, before = self.request(f'/api/receipts/tsv?trip={self.trip}')
        self.assertIn('\t영수증\t12340', before['tsv'])
        status, body = self.request('/api/receipts/edit', {'identity': identity, 'payment': 'corporate_card'},
                                    token=self.csrf())
        self.assertEqual(status, 200, body)
        _, after = self.request(f'/api/receipts/tsv?trip={self.trip}')
        self.assertNotIn('라멘집', after['tsv'])
        self.assertIn('CARD_NOT_FOUND', {h['reason'] for h in after['held']})

    def test_switching_to_corporate_links_the_one_matching_card_purchase_and_drops_the_cash_price(self):
        from webapp.card_flow import CardFlow
        identity = self._confirmed_cash_receipt(merchant='카페', total=900)
        batch = CardFlow(self.server.card_store).pipeline.receive(CARD, 'switch-link.csv')['batch_id']
        _card_purchase(self.server.card_store, batch, 'card-switch-1', '카페', 900, '2027-08-03')
        status, body = self.request('/api/receipts/edit', {'identity': identity, 'payment': 'corporate_card'},
                                    token=self.csrf())
        self.assertEqual(status, 200, body)
        self.assertEqual(body['card_transaction_id'], 'card-switch-1')
        self.assertIsNone(body['amount_krw'])
        _, after = self.request(f'/api/receipts/tsv?trip={self.trip}')
        self.assertNotIn('카페', after['tsv'])

    def test_a_linked_receipt_cannot_be_unlinked_into_a_second_cost(self):
        from webapp.card_flow import CardFlow
        region = dict(REGIONS['regions'][0], payment='corporate_card', merchant='카페', total=900, box=[5, 5, 9, 9])
        batch = CardFlow(self.server.card_store).pipeline.receive(CARD, 'unlink.csv')['batch_id']
        _card_purchase(self.server.card_store, batch, 'card-unlink-1', '카페', 900, '2027-08-03')
        self.request('/api/receipts/scan', {'regions': [region]}, token=self.csrf())
        _, stored = self.request('/api/receipts')
        identity = stored['candidates'][-1]['identity']
        self.assertEqual(stored['candidates'][-1]['card_transaction_id'], 'card-unlink-1')
        status, body = self.request('/api/receipts/edit', {'identity': identity, 'payment': 'cash'}, token=self.csrf())
        self.assertEqual((status, body['code']), (400, 'CARD_LINKED_NOT_EDITABLE'))

    def test_the_same_receipt_rescanned_or_resubmitted_is_one_cost(self):
        region = dict(REGIONS['regions'][0], merchant='라멘집', total=1234, box=[1, 2, 30, 40])
        self.request('/api/receipts/scan', {'regions': [region]}, token=self.csrf())
        self.request('/api/receipts/scan', {'regions': [region]}, token=self.csrf())
        _, stored = self.request('/api/receipts')
        self.assertEqual(len(stored['candidates']), 1)

    def test_the_same_content_from_a_second_photo_is_held_not_added_as_a_second_cost(self):
        first = dict(REGIONS['regions'][0], merchant='라멘집', total=1234, box=[1, 2, 30, 40])
        second = dict(first, box=[500, 500, 530, 540])  # a second photo of the same slip, another position
        self.request('/api/receipts/scan', {'regions': [first]}, token=self.csrf())
        _, body = self.request('/api/receipts/scan', {'regions': [second]}, token=self.csrf())
        self.assertEqual(body['added'], 0)
        self.assertIn('DUPLICATE_CONTENT', {h['reason'] for h in body['holds']})
        _, stored = self.request('/api/receipts')
        self.assertEqual(len(stored['candidates']), 1)
