import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
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
    def test_agoda_compound_instruction_previews_category_only_with_trip_warning(self):
        # The screenshot's travel directive conflicts with the existing multiple-trip owner rule.
        # It must be called out, and only the category can be proposed for approval.
        card = CARD.replace('합성상점'.encode(), b'AGODA.COM').replace(b'A123', b'AGODA-TEST')
        batch = self.flow.pipeline.receive(card, 'agoda-compound-synthetic.csv')['batch_id']
        transaction_id = self.flow.pipeline.get_batch(batch)['rows'][0]['transaction_id']
        self.server.card_store.conn.execute(
            'UPDATE transactions SET trip_id=?, display_tab_id=? WHERE transaction_id=?',
            (self.trip, self.trip, transaction_id))
        self.server.card_store.conn.commit()
        original_item = self.server.card_store.conn.execute(
            'SELECT item FROM transactions WHERE transaction_id=?', (transaction_id,)).fetchone()[0]
        instruction = ('아고다 결제는 숙박비로 분류하고, 예약 이용기간으로 여행을 찾아줘. '
                       '여러 여행에 해당하면 미배정으로 남겨.')
        status, preview = self.post(f'/api/imports/{batch}/rule-proposal',
                                    {'text': instruction, 'transaction_id': transaction_id},
                                    token=ledger_board.CSRF_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(preview['status'], 'proposed')
        self.assertEqual(preview['kind'], 'MERCHANT_RULE')
        self.assertEqual(preview['future_rule']['item'], '숙박비')
        self.assertIn('미배정하라는 요청', preview['trip_notice'])
        original_trip = self.server.card_store.conn.execute(
            'SELECT trip_id, display_tab_id, amount_krw FROM transactions WHERE transaction_id=?',
            (transaction_id,)).fetchone()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                page.on('dialog', lambda dialog: dialog.accept())
                self.open_rule_browser(page, batch)
                page.select_option('#rule-focus', transaction_id)
                page.fill('#rule-text', instruction)
                page.click('#rule-propose')
                page.locator('#rule-approve').wait_for()
                self.assertIn('숙박비', page.locator('#rule-result').inner_text())
                self.assertEqual(self.server.card_store.conn.execute(
                    "SELECT COALESCE(item, '') FROM transactions WHERE transaction_id=?",
                    (transaction_id,)).fetchone()[0], original_item)
                self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                page.click('#rule-approve')
                page.locator('#rule-approve').wait_for(state='detached')
                self.assertEqual(self.server.card_store.conn.execute(
                    'SELECT trip_id, display_tab_id, amount_krw FROM transactions WHERE transaction_id=?',
                    (transaction_id,)).fetchone(), original_trip)
                self.assertEqual(self.server.card_store.conn.execute(
                    'SELECT item FROM transactions WHERE transaction_id=?',
                    (transaction_id,)).fetchone()[0], '숙박비')
            finally:
                browser.close()

    def test_cleanup_card_proposal_preview_requires_separate_approval(self):
        unselected = self.pin_unselected_manual_row()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                page.on('dialog', lambda dialog: dialog.accept())
                self.open_rule_browser(page, self.batch)
                page.select_option('#rule-focus', self.tx[0])
                page.fill('#rule-text', '이 건만 숙박비로 분류해 줘')
                page.click('#rule-propose')
                page.locator('#rule-approve').wait_for()
                self.assertEqual(self.items(), {self.tx[0]: '', unselected: '기존 직접 분류'})
                self.assertIn('숙박비', page.locator('#rule-result').inner_text())
                self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                page.click('#rule-approve')
                page.locator('#rule-approve').wait_for(state='detached')
                self.assertEqual(self.items()[self.tx[0]], '숙박비')
                self.assertEqual(self.items()[unselected], '기존 직접 분류')
            finally:
                browser.close()

    def test_same_merchant_proposal_connects_to_existing_future_rule_form(self):
        from app.normalize import normalize_merchant

        with sync_playwright() as api:
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                self.open_rule_browser(page, self.batch)
                page.select_option('#rule-focus', self.tx[0])
                page.fill('#rule-text', '이 가맹점은 앞으로 현지잡비로 분류해 줘')
                page.click('#rule-propose')
                page.locator('#future-rule-draft').click()
                form = page.locator('#ruleform')
                merchant = normalize_merchant(self.rows[0]['merchant'])
                self.assertEqual(form.locator('[name=merchant]').input_value(), merchant)
                self.assertEqual(form.locator('[name=rule_item]').input_value(), '현지잡비')
                self.assertEqual(set(self.items().values()), {''})
                ledger_before = self.server.card_store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
                page.get_by_role('button', name='규칙 저장하고 다시 분류', exact=True).click()
                page.get_by_text('규칙은 저장되고 분류도 다시 계산됐습니다.', exact=False).wait_for()
                self.assertEqual(ledger_before, 0)
                self.assertEqual(self.server.card_store.conn.execute(
                    'SELECT COUNT(*), COUNT(DISTINCT transaction_id) FROM ledger_entries').fetchone(), (2, 2))
                self.assertEqual(self.flow.auto_record(self.batch)['auto_recorded'], 0)
                self.assertTrue(any(r['conditions']['merchant_normalized'] == merchant
                                    and r['effects']['item'] == '현지잡비'
                                    for r in self.flow.pipeline.list_rules()))
                new_card = CARD.replace(b'A123', b'FUTURE-SYNTHETIC')
                batch = self.flow.pipeline.receive(new_card, 'future-synthetic.csv')['batch_id']
                self.flow.classify(batch)
                state = self.flow.state(batch)
                self.assertEqual(state['preview']['rows'][0]['item'], '현지잡비')
            finally:
                browser.close()

    def test_local_ai_browser_proposal_requires_explicit_approval(self):
        """Always exercise the UI with a synthetic adapter; opt in to a real local engine."""
        from app import local_rule_ai
        live_engine = os.environ.get('COST_LOCAL_AI_SMOKE') == '1'
        unselected = self.pin_unselected_manual_row()
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'WEBLEDGER_LOCAL_RULE_AI': '1'}))
            if not live_engine:
                stack.enter_context(patch.object(
                    local_rule_ai, 'interpret', return_value='이 건만 현지잡비로 분류'))
            api = stack.enter_context(sync_playwright())
            browser = api.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                self.open_rule_browser(page, self.batch)
                page.select_option('#rule-focus', self.tx[0])
                page.fill('#rule-text', '이 결제는 식비가 아니라 현지잡비야. 이번만 그렇게 분류해 줘.')
                page.click('#rule-propose')
                page.locator('#rule-approve').wait_for(timeout=25000)
                self.assertEqual(page.locator('#rule-text').input_value(), '이 건만 현지잡비로 분류')
                self.assertEqual(self.items(), {self.tx[0]: '', unselected: '기존 직접 분류'})
                page.click('#rule-approve')
                page.get_by_text('한 번에 적용했습니다', exact=False).wait_for()
                page.goto(self.base + '/import?batch=' + self.batch + '#preview')
                page.locator('[data-review-state="all"]').click()
                page.locator('#preview').get_by_text('현지잡비').first.wait_for()
                self.assertEqual(self.items()[self.tx[0]], '현지잡비')
                self.assertEqual(self.items()[unselected], '기존 직접 분류')
            finally:
                browser.close()

    def test_ai_interpretation_is_reviewed_and_retry_does_not_call_model(self):
        from app import local_rule_ai
        before = self.items()
        with patch.dict(os.environ, {'WEBLEDGER_LOCAL_RULE_AI': '1'}), \
                patch.object(local_rule_ai, 'interpret', return_value='이 건만 현지잡비로 분류') as interpret:
            proposal = self.propose(text='이 결제의 비용 분류를 현지잡비로 정리해 줘')
            self.assertEqual(proposal['interpreted_text'], '이 건만 현지잡비로 분류')
            self.assertEqual(self.items(), before)
            status, result = self.approve(proposal, 'local-ai-approved')
            self.assertEqual(status, 200)
            count = self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]
            status, replay = self.approve(proposal, 'local-ai-approved')
            self.assertEqual(status, 200)
            self.assertEqual(result['applied'], replay['applied'])
            self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], count)
            interpret.assert_called_once()

    def test_ai_unavailable_keeps_proposal_pending_and_database_unchanged(self):
        from app import local_rule_ai
        before = self.items()
        with patch.dict(os.environ, {'WEBLEDGER_LOCAL_RULE_AI': '1'}), \
                patch.object(local_rule_ai, 'interpret', side_effect=local_rule_ai.InterpretationPending):
            result = self.propose(text='이 결제의 비용 분류를 현지잡비로 정리해 줘')
        self.assertEqual(result['status'], 'AI_PENDING')
        self.assertEqual(result['payloads'], [])
        self.assertEqual(self.items(), before)

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

    def open_rule_browser(self, page, batch=None):
        """Select the intended saved batch, then expose its rule controls in the rules tab."""
        page.goto(self.base + '/import')
        if not page.locator('#expense-tab-saved').is_visible():
            page.locator('.expense-tools > summary').click()
        page.locator('#expense-tab-saved').click()
        if batch:
            choice = page.locator(f'#batches [data-batch="{batch}"]')
            choice.wait_for(state='visible')
            choice.click()
            page.wait_for_function('(id) => model && model.batch_id === id', arg=batch)
        else:
            page.wait_for_function('() => Boolean(model && model.batch_id)')
        page.locator('#rule-panel #rule-focus option').first.wait_for(state='attached')
        if not page.locator('#expense-tab-rules').is_visible():
            page.locator('.expense-tools > summary').click()
        page.locator('#expense-tab-rules').click()
        page.locator('#rule-panel #rule-focus').wait_for(state='visible')
        self.assertEqual(page.locator('#expense-tab-rules').get_attribute('aria-selected'), 'true')

    def items(self):
        rows = self.server.card_store.conn.execute(
            'SELECT transaction_id, item FROM transactions WHERE transaction_id IN (%s)' %
            ','.join('?' * len(self.tx)), self.tx).fetchall()
        return {tid: item for tid, item in rows}

    def pin_unselected_manual_row(self, selected_transaction_id=None):
        """Keep automatic batch processing from obscuring the reviewed row boundary."""
        selected = selected_transaction_id or self.tx[0]
        unselected = next(transaction_id for transaction_id in self.tx
                          if transaction_id != selected)
        return self.pin_owner_decision(unselected)

    def pin_owner_decision(self, transaction_id):
        """Represent a real prior owner choice so automatic classification must preserve it."""
        self.server.card_store.conn.execute(
            "UPDATE transactions SET item=?, classification_state='classified', "
            "classification_source='user_decision', classification_basis=?, decided_at=? "
            "WHERE transaction_id=?",
            ('기존 직접 분류', 'OWNER_CONFIRMED: synthetic test fixture',
             '2026-11-02T00:00:00Z', transaction_id))
        self.server.card_store.conn.commit()
        return transaction_id

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

    def test_non_object_json_is_refused_before_rule_or_exclusion_writes(self):
        for suffix in ('rule-proposal', 'rule-proposal/approve', 'company-exclusion'):
            for payload in ([], None, 'invalid', 123):
                with self.subTest(suffix=suffix, payload=payload):
                    status, body = self.post(f'/api/imports/{self.batch}/{suffix}', payload,
                                             token=ledger_board.CSRF_TOKEN)
                    self.assertEqual((status, body['code']), (400, 'INVALID_VALUE'))
        self.assertEqual(set(self.items().values()), {''})
        self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 0)

    def test_approval_applies_selected_row_and_preserves_unselected_owner_decision(self):
        self.pin_unselected_manual_row()
        proposal = self.propose()
        status, body = self.approve(proposal, 'batch-once')
        self.assertEqual(status, 200)
        self.assertEqual(body['applied'], [self.tx[0]])
        self.assertEqual(self.items(), {self.tx[0]: '현지잡비', self.tx[1]: '기존 직접 분류'})
        source = self.server.card_store.conn.execute(
            'SELECT classification_source, classification_basis FROM transactions WHERE transaction_id=?',
            (self.tx[1],)).fetchone()
        self.assertEqual(source, ('user_decision', 'OWNER_CONFIRMED: synthetic test fixture'))

    def test_saved_approval_survives_refresh_failure_and_same_request_retry(self):
        proposal = self.propose()
        with patch.object(CardFlow, 'classify', side_effect=StoreError('REFRESH_FAILED', 'private detail')):
            status, body = self.approve(proposal, 'saved-before-refresh')
        self.assertEqual(status, 200)
        self.assertEqual(body['applied'], [self.tx[0]])
        self.assertTrue(body['refresh_required'])
        self.assertIsNone(body['state'])
        self.assertNotIn('private detail', json.dumps(body))
        self.assertEqual(self.items()[self.tx[0]], '현지잡비')
        count = self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]
        status, replay = self.approve(proposal, 'saved-before-refresh')
        self.assertEqual(status, 200)
        self.assertEqual(replay['applied'], body['applied'])
        self.assertIsNotNone(replay['state'])
        self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], count)

    def test_saved_individual_answer_is_not_reported_as_failed_refresh(self):
        body = dict(transaction_id=self.tx[0], revision=self.rows[0]['revision'], item='식비',
                    display_tab_id=self.trip, request_id='saved-answer-refresh')
        route = f'/api/imports/{self.batch}/decision'
        with patch.object(CardFlow, 'classify', side_effect=StoreError('REFRESH_FAILED', 'private detail')):
            status, result = self.post(route, body, token=ledger_board.CSRF_TOKEN)
        self.assertEqual(status, 200)
        self.assertTrue(result['refresh_required'])
        self.assertTrue(result['saved'])
        self.assertEqual(self.items()[self.tx[0]], '식비')
        status, replay = self.post(route, body, token=ledger_board.CSRF_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(next(r for r in replay['rows'] if r['transaction_id'] == self.tx[0])['item'], '식비')
        self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 1)

    def test_saved_rule_survives_reclassification_failure_and_request_retry(self):
        body = dict(draft=dict(conditions=dict(merchant_normalized='SYNTHETIC-SHOP', transaction_direction='purchase'),
                               optional={}, effects=dict(item='식비')),
                    expected_revision=0, batch_id=self.batch, request_id='rule-refresh-failure')
        with patch.object(CardFlow, 'classify', side_effect=StoreError('REFRESH_FAILED', 'private detail')):
            status, result = self.post('/api/imports/rules', body, token=ledger_board.CSRF_TOKEN)
        self.assertEqual(status, 200)
        self.assertTrue(result['refresh_required'])
        self.assertIsNone(result['rules'])
        status, replay = self.post('/api/imports/rules', body, token=ledger_board.CSRF_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(replay['result'], result['result'])
        saved = [r for r in replay['rules'] if r['rule_id'] == result['result']['rule_id']]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['version'], 1)

    def test_browser_reports_saved_rule_when_followup_state_request_fails(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            self.open_rule_browser(page, self.batch)
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            form = page.locator('#ruleform')
            form.locator('[name="merchant"]').fill('SYNTHETIC-SHOP')
            form.locator('[name="rule_item"]').fill('식비')
            page.route(f'**/api/imports/{self.batch}',
                       lambda route: route.fulfill(status=500, json={'message': 'FOLLOWUP-STATE-FAILED'}))
            form.get_by_role('button', name='규칙 저장하고 다시 분류').click()
            page.get_by_text('화면을 갱신하지 못했습니다.', exact=False).wait_for()
            rule_id = form.locator('[name="rule_id"]').input_value()
            self.assertTrue(rule_id)
            self.assertEqual(form.locator('[name="version"]').input_value(), '1')
            saved = next(r for r in self.flow.pipeline.list_rules() if r['rule_id'] == rule_id)
            self.assertEqual(saved['effects']['item'], '식비')
            browser.close()

    def test_stale_proposal_is_refused_and_nothing_changes(self):
        proposal = self.propose()
        self.server.card_store.conn.execute('UPDATE transactions SET amount_krw=amount_krw+1 WHERE transaction_id=?',
                                            (self.tx[0],))
        self.server.card_store.conn.commit()
        status, body = self.approve(proposal, 'stale-1')
        self.assertEqual((status, body['code']), (409, 'STALE_PROPOSAL'))
        self.assertEqual(set(self.items().values()), {''})

    def test_trip_reassignment_without_decision_revision_invalidates_proposal(self):
        proposal = self.propose()
        other = self.server.card_store.create_trip(starts_on='2027-01-01', ends_on='2027-01-03',
                                                    destination='OTHER-TRIP', client_request_id='other-rule-trip')['tab_id']
        self.server.card_store.conn.execute('UPDATE transactions SET trip_id=?, display_tab_id=? WHERE transaction_id=?',
                                            (other, other, self.tx[0]))
        self.server.card_store.conn.commit()
        status, body = self.approve(proposal, 'stale-trip')
        self.assertEqual((status, body.get('code')), (409, 'STALE_PROPOSAL'))
        self.assertEqual(set(self.items().values()), {''})
        self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 0)

    def test_description_change_without_decision_revision_invalidates_proposal(self):
        proposal = self.propose()
        self.server.card_store.conn.execute('UPDATE transactions SET description=? WHERE transaction_id=?',
                                            ('NEW-AUTHORITY-DESCRIPTION', self.tx[0]))
        self.server.card_store.conn.commit()
        status, body = self.approve(proposal, 'stale-description')
        self.assertEqual((status, body.get('code')), (409, 'STALE_PROPOSAL'))
        self.assertEqual(set(self.items().values()), {''})
        self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 0)

    def test_automatic_classification_changes_invalidate_the_reviewed_before_values(self):
        for column, value in (('item', 'NEW-ITEM'), ('merchant', 'NEW-SHOP')):
            proposal = self.propose()
            self.server.card_store.conn.execute(f'UPDATE transactions SET {column}=? WHERE transaction_id=?',
                                                (value, self.tx[0]))
            self.server.card_store.conn.commit()
            before = self.server.card_store.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
            status, body = self.approve(proposal, 'stale-before-' + column)
            self.assertEqual((status, body.get('code')), (409, 'STALE_PROPOSAL'))
            self.assertEqual(self.server.card_store.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall(), before)
            self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 0)

    def test_assignment_change_after_proposal_check_is_refused_inside_write_transaction(self):
        import sqlite3
        proposal = self.propose()
        other = self.server.card_store.create_trip(starts_on='2027-01-01', ends_on='2027-01-03',
                                                    destination='RACE-TRIP', client_request_id='race-rule-trip')['tab_id']
        real_save = review.save_decisions_atomic
        def change_assignment_then_save(*args, **kwargs):
            connection = sqlite3.connect(Path(self._dir.name) / 'board.sqlite')
            try:
                connection.execute('UPDATE transactions SET trip_id=?, display_tab_id=? WHERE transaction_id=?',
                                   (other, other, self.tx[0]))
                connection.commit()
            finally:
                connection.close()
            return real_save(*args, **kwargs)
        with patch.object(review, 'save_decisions_atomic', side_effect=change_assignment_then_save):
            status, body = self.approve(proposal, 'assignment-race')
        self.assertEqual((status, body.get('code')), (409, 'REVISION_CONFLICT'))
        self.assertEqual(set(self.items().values()), {''})
        self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 0)
        self.assertEqual(self.server.card_store.conn.execute('SELECT trip_id FROM transactions WHERE transaction_id=?',
                                                            (self.tx[0],)).fetchone()[0], other)

    def test_review_state_conflict_on_later_row_rolls_back_earlier_decisions_and_requests(self):
        store = self.flow.pipeline.store
        before = store.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        requests = store.conn.execute('SELECT * FROM requests ORDER BY request_id').fetchall()
        rows = self.flow.state(self.batch)['preview']['rows']
        decisions = []
        for row in rows:
            expected = {key: row.get(key) or '' for key in
                        ('item', 'description', 'display_tab_id', 'trip_id', 'merchant', 'occurred_on')}
            decisions.append(dict(transaction_id=row['transaction_id'], revision=row['revision'], item='현지잡비',
                                  description=row['description'], display_tab_id=self.trip, trip_id=self.trip,
                                  note='', reuse_rule=False, resolve_hold=False,
                                  expected_amount_krw=row['amount_krw'], expected_review_state=expected))
        decisions[1]['expected_review_state']['description'] = 'STALE-DESCRIPTION'
        applied = []
        real_save = review.save_decision
        def record_save(*args, **kwargs):
            result = real_save(*args, **kwargs)
            applied.append(result)
            return result
        with patch.object(review, 'save_decision', side_effect=record_save):
            with self.assertRaises(StoreError) as error:
                review.save_decisions_atomic(store, decisions, request_id='later-state-conflict',
                                              tab_validator=self.flow.tab_valid, trip_validator=self.flow.trip_valid)
        self.assertEqual(error.exception.code, 'REVISION_CONFLICT')
        self.assertEqual(len(applied), 1)
        self.assertEqual(store.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall(), before)
        self.assertEqual(store.conn.execute('SELECT * FROM requests ORDER BY request_id').fetchall(), requests)
        self.assertEqual(store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 0)

    def test_projected_preview_description_is_not_mistaken_for_a_changed_source(self):
        real_state = CardFlow.state
        def projected_state(flow, batch):
            state = real_state(flow, batch)
            # Refund previews can inherit a description without rewriting the original transaction.
            for row in state['preview']['rows']:
                if row['transaction_id'] == self.tx[0]:
                    row['description'] = 'PROJECTED-REFUND-DESCRIPTION'
            return state
        with patch.object(CardFlow, 'state', projected_state):
            proposal = self.propose()
            status, body = self.approve(proposal, 'projected-description')
        self.assertEqual(status, 200, body)
        self.assertEqual(self.server.card_store.conn.execute('SELECT description FROM review_decisions WHERE transaction_id=?',
                                                            (self.tx[0],)).fetchone()[0], 'PROJECTED-REFUND-DESCRIPTION')

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

    def test_replay_when_other_request_finishes_after_first_lookup(self):
        from webapp import rule_review
        proposal = self.propose()
        body = {**proposal, 'approved': True, 'request_id': 'interleaved-approval'}
        lookup = review.batch_result_for
        applied = []
        first_lookup = True

        def concurrent_winner(store, request_id):
            nonlocal first_lookup
            result = lookup(store, request_id)
            if first_lookup:
                first_lookup = False
                applied.append(rule_review.approve(self.flow, self.batch, body))
            return result

        with patch.object(review, 'batch_result_for', side_effect=concurrent_winner):
            replay = rule_review.approve(self.flow, self.batch, body)
        self.assertEqual(replay['applied'], applied[0]['applied'])
        self.assertEqual(self.server.card_store.conn.execute(
            'SELECT COUNT(*) FROM review_decisions').fetchone()[0], 1)

    def test_simultaneous_http_approval_returns_same_result_once(self):
        from concurrent.futures import ThreadPoolExecutor
        self.pin_unselected_manual_row()
        proposal = self.propose()
        barrier = threading.Barrier(2)
        before = self.server.card_store.conn.execute(
            'SELECT source_hash, amount_krw, raw_row_json FROM transactions ORDER BY transaction_id').fetchall()

        def submit():
            barrier.wait(timeout=5)
            return self.approve(proposal, 'simultaneous-http')

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertEqual(results[0][1]['applied'], results[1][1]['applied'])
        conn = self.server.card_store.conn
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 1)
        booked = {row[0] for row in conn.execute('SELECT transaction_id FROM ledger_entries')}
        self.assertEqual(booked, set(self.tx))
        self.assertEqual(len(booked), 2)
        self.assertEqual(self.items(), {self.tx[0]: '현지잡비', self.tx[1]: '기존 직접 분류'})
        self.assertEqual(conn.execute(
            'SELECT classification_source, classification_basis FROM transactions WHERE transaction_id=?',
            (self.tx[1],)).fetchone(),
            ('user_decision', 'OWNER_CONFIRMED: synthetic test fixture'))
        self.assertEqual(conn.execute(
            'SELECT source_hash, amount_krw, raw_row_json FROM transactions ORDER BY transaction_id').fetchall(), before)

    def _browser_case(self, width, height):
        chosen = self.tx[1]
        unselected = self.pin_unselected_manual_row(selected_transaction_id=chosen)
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(viewport={'width': width, 'height': height}).new_page()
            self.open_rule_browser(page, self.batch)
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
            if not page.locator('#expense-tab-saved').is_visible():
                page.locator('.expense-tools > summary').click()
            page.locator('#expense-tab-saved').click()
            page.wait_for_function('(batch) => model && model.batch_id === batch', arg=self.batch)
            page.locator('#preview').wait_for(state='visible')
            items = self.items()
            self.assertEqual(items[chosen], '현지잡비')
            self.assertEqual(items[unselected], '기존 직접 분류')
            browser.close()

    def test_browser_mobile_390_keeps_the_chosen_row_and_applies_only_it(self):
        self._browser_case(390, 844)

    def test_browser_desktop_1440_keeps_the_chosen_row_and_applies_only_it(self):
        self._browser_case(1440, 900)

    def test_browser_discards_delayed_proposal_after_focus_changes(self):
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.route('**/rule-proposal', lambda route: pending.append(route))
            self.open_rule_browser(page, self.batch)
            page.select_option('#rule-focus', self.tx[0])
            page.fill('#rule-text', '이 건만 식비로 분류해 줘')
            with page.expect_request('**/rule-proposal'):
                page.click('#rule-propose')
            page.select_option('#rule-focus', self.tx[1])
            pending.pop().fulfill(json=self.propose(self.tx[0], text='이 건만 식비로 분류해 줘'))
            page.get_by_text('현재 선택이 바뀌었습니다. 다시 제안하세요.', exact=True).wait_for(timeout=5000)
            self.assertEqual(page.locator('#rule-approve').count(), 0)
            self.assertIsNone(page.evaluate('window.ruleProposal ?? null'))
            self.assertEqual(set(self.items().values()), {''})
            browser.close()

    def test_browser_text_edit_invalidates_displayed_approval(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            self.open_rule_browser(page, self.batch)
            page.fill('#rule-text', '이 건만 식비로 분류해 줘')
            page.click('#rule-propose')
            page.locator('#rule-approve').wait_for()
            page.fill('#rule-text', '이 건만 교통비로 분류해 줘')
            self.assertEqual(page.locator('#rule-approve').count(), 0)
            self.assertIsNone(page.evaluate('window.ruleProposal ?? null'))
            self.assertEqual(set(self.items().values()), {''})
            browser.close()

    def test_old_proposal_error_does_not_replace_new_proposal_status(self):
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            self.open_rule_browser(page, self.batch)
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            page.select_option('#rule-focus', self.tx[0])
            page.fill('#rule-text', '이 건만 식비로 분류해 줘')
            page.route('**/rule-proposal', lambda route: pending.append(route))
            with page.expect_request('**/rule-proposal'):
                page.click('#rule-propose')
            page.select_option('#rule-focus', self.tx[1])
            with page.expect_request('**/rule-proposal'):
                page.click('#rule-propose')
            pending[1].fulfill(json=self.propose(self.tx[1], text='이 건만 식비로 분류해 줘'))
            page.locator('#rule-approve').wait_for()
            page.evaluate("document.getElementById('status').textContent='CURRENT-PROPOSAL'")
            with page.expect_response('**/rule-proposal'):
                pending[0].fulfill(status=500, json={'message': 'OLD-PROPOSAL-ERROR'})
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.locator('#status').inner_text(), 'CURRENT-PROPOSAL')
            self.assertEqual(page.evaluate('window.ruleProposal.transaction_id'), self.tx[1])
            self.assertTrue(page.locator('#rule-approve').is_enabled())
            browser.close()

    def test_browser_reports_committed_approval_when_refresh_fails(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            self.open_rule_browser(page, self.batch)
            page.select_option('#rule-focus', self.tx[0])
            page.fill('#rule-text', '이 건만 식비로 분류해 줘')
            page.click('#rule-propose')
            page.locator('#rule-approve').wait_for()
            with patch.object(CardFlow, 'classify', side_effect=RuntimeError('private refresh failure')):
                page.click('#rule-approve')
                page.get_by_text('승인은 저장됐습니다.', exact=False).wait_for()
            self.assertEqual(self.items()[self.tx[0]], '식비')
            self.assertEqual(page.locator('#rule-approve').count(), 0)
            page.reload()
            if not page.locator('#expense-tab-saved').is_visible():
                page.locator('.expense-tools > summary').click()
            page.locator('#expense-tab-saved').click()
            page.wait_for_function('(id)=>model && model.rows.find(r=>r.transaction_id===id)?.item==="식비"', arg=self.tx[0])
            self.assertEqual(page.evaluate('(id)=>model.rows.find(r=>r.transaction_id===id).decided', self.tx[0]), 1)
            browser.close()

    def test_browser_retries_lost_approval_response_with_same_request(self):
        self._lost_approval_response(1280)

    def test_browser_mobile_375_retries_lost_approval_response_with_same_request(self):
        self._lost_approval_response(375)

    def _lost_approval_response(self, width):
        requests = []
        unselected = self.pin_unselected_manual_row()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 812})
            self.open_rule_browser(page, self.batch)
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            page.select_option('#rule-focus', self.tx[0])
            page.fill('#rule-text', '이 건만 식비로 분류해 줘')
            page.click('#rule-propose')
            page.locator('#rule-approve').wait_for()

            def lose_first_response(route):
                body = route.request.post_data_json
                requests.append(body)
                status, result = self.post(f'/api/imports/{self.batch}/rule-proposal/approve', body,
                                           token=ledger_board.CSRF_TOKEN)
                if len(requests) == 1:
                    self.assertEqual(status, 200)
                    route.abort('failed')
                else:
                    route.fulfill(status=status, json=result)

            page.route('**/rule-proposal/approve', lose_first_response)
            page.click('#rule-approve')
            page.get_by_text('서버에 연결하지 못했습니다.', exact=False).wait_for()
            self.assertTrue(page.locator('#rule-approve').is_enabled())
            page.click('#rule-approve')
            page.wait_for_function('document.querySelector("#rule-approve")===null', timeout=5000)
            self.assertEqual(requests[0]['request_id'], requests[1]['request_id'])
            self.assertEqual(self.items()[self.tx[0]], '식비')
            self.assertEqual(self.items()[unselected], '기존 직접 분류')
            self.assertEqual(self.server.card_store.conn.execute(
                'SELECT classification_source, classification_basis FROM transactions WHERE transaction_id=?',
                (unselected,)).fetchone(),
                ('user_decision', 'OWNER_CONFIRMED: synthetic test fixture'))
            self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 1)
            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            page.reload()
            page.wait_for_function('(id)=>model.rows.find(r=>r.transaction_id===id).item==="식비"', arg=self.tx[0])
            self.assertEqual(page.evaluate('(id)=>model.rows.find(r=>r.transaction_id===id).decided', self.tx[0]), 1)
            self.assertEqual(self.server.card_store.conn.execute(
                'SELECT decided_at IS NOT NULL FROM transactions WHERE transaction_id=?', (self.tx[0],)).fetchone()[0], 1)
            browser.close()

    def test_delayed_approval_result_does_not_restore_previous_batch(self):
        second = self.flow.pipeline.receive(CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
        unselected = self.pin_unselected_manual_row()
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            self.open_rule_browser(page, self.batch)
            page.select_option('#rule-focus', self.tx[0])
            page.fill('#rule-text', '이 건만 식비로 분류해 줘')
            page.click('#rule-propose')
            page.locator('#rule-approve').wait_for()
            page.route('**/rule-proposal/approve', lambda route: pending.append(route))
            with page.expect_request('**/rule-proposal/approve'):
                page.click('#rule-approve')
            status, result = self.post(f'/api/imports/{self.batch}/rule-proposal/approve',
                                       pending[0].request.post_data_json, token=ledger_board.CSRF_TOKEN)
            self.assertEqual(status, 200)
            if not page.locator('#expense-tab-saved').is_visible():
                page.locator('.expense-tools > summary').click()
            page.locator('#expense-tab-saved').click()
            page.locator(f'#batches [data-batch="{second}"]').wait_for(state='visible')
            page.locator(f'#batches [data-batch="{second}"]').click()
            page.wait_for_function('(batch)=>model.batch_id===batch', arg=second)
            if not page.locator('#expense-tab-rules').is_visible():
                page.locator('.expense-tools > summary').click()
            page.locator('#expense-tab-rules').click()
            page.locator('#rule-panel #rule-focus').wait_for(state='visible')
            with page.expect_response('**/rule-proposal/approve'):
                pending.pop().fulfill(json=result)
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.evaluate('model.batch_id'), second)
            self.assertEqual(self.items()[self.tx[0]], '식비')
            self.assertEqual(self.items()[unselected], '기존 직접 분류')
            browser.close()

    def test_same_request_id_with_different_approval_is_refused_and_changes_nothing(self):
        self.pin_unselected_manual_row()
        first = self.propose()
        self.assertEqual(self.approve(first, 'reuse-1')[0], 200)
        other = self.propose(text='이 가맹점은 앞으로 교통비로 분류해 줘')
        status, body = self.approve(other, 'reuse-1')
        self.assertEqual((status, body['code']), (409, 'REQUEST_ID_REUSED'))
        self.assertEqual(self.items(), {self.tx[0]: '현지잡비', self.tx[1]: '기존 직접 분류'})
        status, body = self.post(f'/api/imports/{self.batch}/rule-proposal/approve',
                                 {'text': first['text'], 'transaction_id': self.tx[1], 'digest': first['digest'],
                                  'approved': True, 'request_id': 'reuse-1'}, token=ledger_board.CSRF_TOKEN)
        self.assertEqual((status, body['code']), (409, 'REQUEST_ID_REUSED'))
