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
from webapp.card_flow import CardFlow
from webapp.tests.test_card_flow import CARD


class RuleReviewTests(unittest.TestCase):
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
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.flow = CardFlow(self.server.card_store)
        self.valid = patch.object(CardFlow, 'trip_valid', return_value=True)
        self.valid.start()
        board = self.server.card_store
        self.trip = board.create_trip(starts_on='2026-10-10', ends_on='2026-10-13', destination='합성 여행',
                                      client_request_id='rule-trip')['tab_id']
        self.batch = self.flow.pipeline.receive(CARD, 'rule-review.csv')['batch_id']
        self.row = self.flow.pipeline.get_batch(self.batch)['rows'][0]
        board.conn.execute("UPDATE transactions SET classification_state='classified', item='', "
                           "trip_id=?, display_tab_id=? WHERE transaction_id=?",
                           (self.trip, self.trip, self.row['transaction_id']))
        board.conn.commit()

    def tearDown(self):
        self.valid.stop()
        self.server.shutdown()
        self.server.server_close()
        self.server.card_store.close()
        self.thread.join(timeout=3)
        ledger_board.bind_store(self._previous)
        self._env.stop()
        self._dir.cleanup()

    def post(self, path, body, token=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method='POST')
        req.add_header('Content-Type', 'application/json')
        if token:
            req.add_header('X-CSRF-Token', token)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read().decode('utf-8') or '{}')
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode('utf-8') or '{}')

    def item_now(self):
        return self.server.card_store.conn.execute(
            'SELECT item FROM transactions WHERE transaction_id=?', (self.row['transaction_id'],)).fetchone()[0]

    def test_proposal_is_read_only_and_names_the_rows_it_would_change(self):
        status, body = self.post(f'/api/imports/{self.batch}/rule-proposal',
                                 {'text': '이 건만 현지잡비로 분류해 줘', 'transaction_id': self.row['transaction_id']},
                                 token=ledger_board.CSRF_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], 'proposed')
        self.assertEqual([p['item'] for p in body['payloads']], ['현지잡비'])
        self.assertEqual(self.item_now(), '')  # nothing saved by a proposal

    def test_unknown_or_original_edit_text_changes_nothing(self):
        for text in ('잘 부탁해', '금액을 9999로 바꿔 줘'):
            _, body = self.post(f'/api/imports/{self.batch}/rule-proposal',
                                {'text': text, 'transaction_id': self.row['transaction_id']},
                                token=ledger_board.CSRF_TOKEN)
            self.assertEqual(body['payloads'], [])
            self.assertIn(body['status'], ('NOT_UNDERSTOOD', 'REJECTED_ORIGINAL_EDIT'))

    def test_proposal_needs_the_csrf_token(self):
        status, body = self.post(f'/api/imports/{self.batch}/rule-proposal',
                                 {'text': '이 건만 식비로 분류해 줘', 'transaction_id': self.row['transaction_id']})
        self.assertEqual((status, body['code']), (403, 'CSRF_REQUIRED'))

    def test_browser_proposal_then_approval_saves_through_the_existing_decision_endpoint(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            page = context.new_page()
            page.goto(self.base + '/import')
            page.locator('[data-batch]').first.click() if page.locator('[data-batch]').count() else None
            page.locator('#preview').wait_for()
            page.fill('#rule-text', '이 건만 현지잡비로 분류해 줘')
            page.locator('#rule-focus').wait_for()
            page.click('#rule-propose')
            page.get_by_role('button', name='승인하고 적용').wait_for()
            page.click('#rule-approve')
            page.get_by_text('기존 답변 경로로 적용했습니다', exact=False).wait_for()
            self.assertEqual(self.item_now(), '현지잡비')
            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            browser.close()

    def test_changed_amount_after_the_proposal_refuses_the_approval(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(viewport={'width': 390, 'height': 844}).new_page()
            page.goto(self.base + '/import')
            page.locator('#preview').wait_for()
            page.fill('#rule-text', '이 건만 현지잡비로 분류해 줘')
            page.locator('#rule-focus').wait_for()
            page.click('#rule-propose')
            page.get_by_role('button', name='승인하고 적용').wait_for()
            self.server.card_store.conn.execute('UPDATE transactions SET amount_krw=amount_krw+1 WHERE transaction_id=?',
                                                (self.row['transaction_id'],))
            self.server.card_store.conn.commit()
            page.click('#rule-approve')
            page.get_by_text('거래가 바뀌었습니다', exact=False).wait_for()
            self.assertEqual(self.item_now(), '')
            browser.close()
