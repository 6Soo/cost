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

from app import review
from app.db import StoreError
from webapp import ledger_board
from webapp.card_flow import CardFlow
from webapp.tests.test_card_flow import CARD

TWO_ROWS = CARD + (
    '국민,1234,domestic,purchase,합성상점둘,25000,,,25000,2026-10-02,2026-10-03,A124,,매입\n').encode()


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
        self.trip = self.server.card_store.create_trip(
            starts_on='2026-10-10', ends_on='2026-10-13', destination='합성 여행',
            client_request_id='rule-trip')['tab_id']
        self.batch = self.flow.pipeline.receive(TWO_ROWS, 'rule-review.csv')['batch_id']
        self.rows = self.flow.pipeline.get_batch(self.batch)['rows']
        board = self.server.card_store
        for row in self.rows:
            board.conn.execute("UPDATE transactions SET classification_state='classified', item='', "
                               "trip_id=?, display_tab_id=? WHERE transaction_id=?",
                               (self.trip, self.trip, row['transaction_id']))
        board.conn.commit()
        self.tx = [r['transaction_id'] for r in self.rows]

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

    def items(self):
        rows = self.server.card_store.conn.execute(
            'SELECT transaction_id, item FROM transactions WHERE transaction_id IN (%s)' %
            ','.join('?' * len(self.tx)), self.tx).fetchall()
        return {tid: item for tid, item in rows}

    def propose(self, transaction_id=None, text='이 가맹점은 앞으로 현지잡비로 분류해 줘'):
        _, body = self.post(f'/api/imports/{self.batch}/rule-proposal',
                            {'text': text, 'transaction_id': transaction_id or self.tx[0]},
                            token=ledger_board.CSRF_TOKEN)
        return body

    def approve(self, proposal, request_id, token=ledger_board.CSRF_TOKEN):
        return self.post(f'/api/imports/{self.batch}/rule-proposal/approve',
                         {'text': proposal['text'], 'transaction_id': proposal['transaction_id'],
                          'digest': proposal['digest'], 'approved': True, 'request_id': request_id}, token=token)

    def test_proposal_is_read_only_and_names_the_rows_it_would_change(self):
        body = self.propose()
        self.assertEqual(body['status'], 'proposed')
        # A merchant rule covers that merchant's rows only, so the other row is not in the proposal.
        self.assertEqual({p['transaction_id'] for p in body['payloads']}, {self.tx[0]})
        self.assertEqual(set(self.items().values()), {''})

    def test_unknown_or_original_edit_text_changes_nothing(self):
        for text in ('잘 부탁해', '금액을 9999로 바꿔 줘'):
            body = self.propose(text=text)
            self.assertEqual(body['payloads'], [])
            self.assertIn(body['status'], ('NOT_UNDERSTOOD', 'REJECTED_ORIGINAL_EDIT'))

    def test_proposal_and_approval_need_the_csrf_token(self):
        status, body = self.post(f'/api/imports/{self.batch}/rule-proposal',
                                 {'text': '이 건만 식비로 분류해 줘', 'transaction_id': self.tx[0]})
        self.assertEqual((status, body['code']), (403, 'CSRF_REQUIRED'))
        proposal = self.propose()
        status, body = self.approve(proposal, 'req-no-token', token=None)
        self.assertEqual((status, body['code']), (403, 'CSRF_REQUIRED'))

    def test_approval_applies_every_row_in_one_request(self):
        proposal = self.propose()
        status, body = self.approve(proposal, 'batch-once')
        self.assertEqual(status, 200)
        self.assertEqual(body['applied'], [self.tx[0]])
        self.assertEqual(self.items(), {self.tx[0]: '현지잡비', self.tx[1]: ''})

    def test_stale_proposal_is_refused_and_nothing_changes(self):
        proposal = self.propose()
        self.server.card_store.conn.execute('UPDATE transactions SET amount_krw=amount_krw+1 WHERE transaction_id=?',
                                            (self.tx[0],))
        self.server.card_store.conn.commit()
        status, body = self.approve(proposal, 'stale-1')
        self.assertEqual((status, body['code']), (409, 'STALE_PROPOSAL'))
        self.assertEqual(set(self.items().values()), {''})

    def test_a_failure_in_the_middle_rolls_every_write_back(self):
        store = self.flow.pipeline.store
        revisions = {r['transaction_id']: r['revision'] for r in self.rows}
        decisions = [{'transaction_id': tx, 'revision': revisions[tx], 'item': '현지잡비', 'description': '',
                      'display_tab_id': self.trip, 'trip_id': self.trip, 'note': '', 'reuse_rule': False,
                      'resolve_hold': False} for tx in self.tx]
        real = review.save_decision
        calls = {'n': 0}

        def fail_second(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 2:
                raise StoreError('SYNTHETIC_FAILURE', 'synthetic second write failed')
            return real(*args, **kwargs)

        with patch.object(review, 'save_decision', side_effect=fail_second):
            with self.assertRaises(StoreError) as raised:
                review.save_decisions_atomic(store, decisions, request_id='rollback-1',
                                             tab_validator=self.flow.tab_valid,
                                             trip_validator=self.flow.trip_valid)
        self.assertEqual(raised.exception.code, 'SYNTHETIC_FAILURE')
        self.assertEqual(set(self.items().values()), {''})
        decisions_written = store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]
        self.assertEqual(decisions_written, 0)
        self.assertIsNone(review.batch_result_for(store, 'rollback-1'))

    def test_repeated_request_id_does_not_apply_twice(self):
        proposal = self.propose()
        first = self.approve(proposal, 'twice-1')
        second = self.approve(proposal, 'twice-1')
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        count = self.server.card_store.conn.execute(
            'SELECT COUNT(*) FROM review_decisions WHERE transaction_id=?', (self.tx[0],)).fetchone()[0]
        self.assertEqual(count, 1)

    def _browser_case(self, width, height):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(viewport={'width': width, 'height': height}).new_page()
            page.goto(self.base + '/import')
            page.locator('#rule-focus option').nth(1).wait_for(state='attached')
            chosen = self.tx[1]
            page.select_option('#rule-focus', chosen)
            page.fill('#rule-text', '이 가맹점은 앞으로 현지잡비로 분류해 줘')
            page.click('#rule-propose')
            page.get_by_role('button', name='승인하고 적용').wait_for()
            # Proposing must not reset the chosen row: the list is built once per batch.
            self.assertEqual(page.locator('#rule-focus').input_value(), chosen)
            self.assertEqual(page.evaluate('window.ruleProposal.transaction_id'), chosen)
            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            page.click('#rule-approve')
            page.get_by_text('한 번에 적용했습니다', exact=False).wait_for()
            # Re-query: a fresh load of the page shows the saved item, not just the in-page state.
            page.reload()
            page.locator('#preview').get_by_text('현지잡비').first.wait_for()
            items = self.items()
            self.assertEqual(items[chosen], '현지잡비')
            self.assertEqual(items[self.tx[0]], '')  # the other merchant's row is untouched
            browser.close()

    def test_browser_mobile_390_keeps_the_chosen_row_and_applies_only_it(self):
        self._browser_case(390, 844)

    def test_browser_desktop_1440_keeps_the_chosen_row_and_applies_only_it(self):
        self._browser_case(1440, 900)
