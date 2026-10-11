import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import ledger_board
from webapp.card_flow import CardFlow
from webapp.tests.test_card_flow import CARD


class CardGoogleCopyTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1',
                                            'WEBLEDGER_REVIEW_FROM': ''})
        self._env.start()
        self._previous = ledger_board._STORE
        ledger_board.bind_access(None)
        self.server = ledger_board.serve(port=0, db_path=Path(self._dir.name) / 'board.sqlite',
                                         with_worker=False, seed_demo=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.flow = CardFlow(self.server.card_store)
        self.valid = patch.object(CardFlow, 'trip_valid', return_value=True)
        self.valid.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.valid.stop()
        self.server.shutdown(); self.server.server_close(); self.server.card_store.close()
        self.thread.join(timeout=3)
        ledger_board.bind_store(self._previous)
        self._env.stop()
        self._dir.cleanup()

    def assign(self, *, trip, merchant_row_index=0):
        board = self.server.card_store
        batch = self.flow.pipeline.receive(CARD, 'google-copy.csv')['batch_id']
        row = self.flow.pipeline.get_batch(batch)['rows'][merchant_row_index]
        board.conn.execute("UPDATE transactions SET classification_state='classified', item='숙박비', "
                           "trip_id=?, display_tab_id=? WHERE transaction_id=?",
                           (trip, trip, row['transaction_id']))
        board.conn.commit()
        return batch

    def make_trip(self):
        return self.server.card_store.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                                                  destination='합성 여행', client_request_id='gc-trip')['tab_id']

    def test_http_endpoint_returns_the_seven_columns_for_the_trip(self):
        import urllib.request
        trip = self.make_trip()
        batch = self.assign(trip=trip)
        with urllib.request.urlopen(f'{self.base}/api/imports/{batch}/google-tsv?tab={trip}') as response:
            body = json.loads(response.read().decode('utf-8'))
        fields = body['tsv'].rstrip('\n').split('\t')
        self.assertEqual(len(fields), 7)
        self.assertEqual(fields[1], '합성상점')
        self.assertEqual(fields[2], '숙박비')
        self.assertEqual(fields[5], '카드')
        self.assertEqual(body['row_count'], 1)

    def test_browser_copies_the_exact_tsv_and_warns_on_a_second_copy(self):
        self._copy_flow(390, 844)

    def test_browser_desktop_1440_copies_the_exact_tsv(self):
        self._copy_flow(1440, 900)

    def test_delayed_batch_response_does_not_replace_latest_selection(self):
        self._delayed_response_case(poll=False)

    def test_delayed_poll_response_does_not_restore_previous_batch(self):
        self._delayed_response_case(poll=True)

    def _delayed_response_case(self, *, poll):
        first = self.assign(trip=self.make_trip())
        second = self.flow.pipeline.receive(CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import')
            page.wait_for_function('typeof model !== "undefined"')
            page.locator(f'[data-batch="{first}"]').click()
            page.wait_for_function('(batch)=>model.batch_id===batch', arg=first)
            page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true,get:()=>true})")
            pending = []
            for batch in (first, second):
                page.route(f'**/api/imports/{batch}', lambda route: pending.append(route))
                with page.expect_request(f'**/api/imports/{batch}'):
                    if poll and batch == first:
                        page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true,get:()=>false});void pollCard()")
                    else:
                        page.locator(f'[data-batch="{batch}"]').click()
                page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true,get:()=>true})")
            pending[1].fulfill(json=self.flow.state(second))
            page.wait_for_function('(batch)=>model.batch_id===batch', arg=second)
            with page.expect_response(f'**/api/imports/{first}'):
                pending[0].fulfill(json=self.flow.state(first))
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.evaluate('model.batch_id'), second)
            page.locator('#summary details summary').click()
            self.assertEqual(page.locator('#summary details p').inner_text(), 'second.csv')
            browser.close()

    def _copy_flow(self, width, height):
        trip = self.make_trip()
        batch = self.assign(trip=trip)
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                          viewport={'width': width, 'height': height})
            page = context.new_page()
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.accept()))
            page.goto(self.base + '/import')
            page.locator('[data-batch]').first.click() if page.locator('[data-batch]').count() else None
            button = page.locator(f'[data-google-copy="{trip}"]')
            button.wait_for()
            button.click()
            page.get_by_text('클립보드에 복사했습니다', exact=False).wait_for()
            # The OS clipboard turns newlines into CRLF; the paste into a sheet reads both.
            clipboard = page.evaluate('navigator.clipboard.readText()')
            # The OS clipboard turns newlines into CRLF; the paste into a sheet reads both.
            clipboard = clipboard.replace(chr(13) + chr(10), chr(10))
            expected = json.loads(page.request.get(f'{self.base}/api/imports/{batch}/google-tsv?tab={trip}').text())['tsv']
            self.assertEqual(clipboard, expected)
            self.assertTrue(page.evaluate('(trip)=>Boolean(localStorage.getItem("gcopy-trip:"+trip))', trip))
            self.assertIn('장부를 바꾸지 않습니다', page.locator('#status').inner_text())
            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            button.click()  # a second copy of the same trip asks first
            page.wait_for_timeout(300)
            self.assertTrue(any('이미 구글 시트용으로 복사' in message for message in dialogs))
            browser.close()

    def test_held_rows_are_listed_and_never_pasted(self):
        trip = self.make_trip()
        batch = self.assign(trip=trip)
        board = self.server.card_store
        board.conn.execute("UPDATE transactions SET item='' WHERE display_tab_id=?", (trip,))
        board.conn.commit()
        import urllib.request
        with urllib.request.urlopen(f'{self.base}/api/imports/{batch}/google-tsv?tab={trip}') as response:
            body = json.loads(response.read().decode('utf-8'))
        self.assertEqual(body['row_count'], 0)
        self.assertTrue(body['held'])
