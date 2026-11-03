import json
import datetime as dt
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import ledger_board
from webapp.card_flow import CardFlow
from webapp.tests.test_card_flow import CARD
from app import google_authority as ga
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp import access_control
from webapp.tests.test_reserve_link import OWNER


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

    def save_browser_classification(self, page, batch, row, *, trip, item, request_id):
        response = page.request.post(
            f'{self.base}/api/imports/{batch}/decision',
            data={'transaction_id': row['transaction_id'], 'revision': row['revision'],
                  'item': item, 'description': 'SYNTHETIC-CLASSIFICATION',
                  'display_tab_id': trip, 'note': '', 'request_id': request_id},
            headers={'X-CSRF-Token': ledger_board.CSRF_TOKEN})
        self.assertEqual(response.status, 200, response.text())
        return response.json()

    @contextmanager
    def owner_copy_auth(self, context):
        previous_access = ledger_board._ACCESS
        previous_sessions = access_control.session_adapter()
        connection = sqlite3.connect(str(Path(self._dir.name) / 'copy-access.sqlite'),
                                     check_same_thread=False, isolation_level=None)
        access_store = access_control.AccessStore(connection)
        access_store.create_account(user_id=OWNER, role=access_control.ROLE_OWNER,
                                    display_name='합성 소유자')
        access_control.bind_sessions(access_control.SyntheticSessionAdapter(
            allow_synthetic=True, access_store=access_store))
        ledger_board.bind_access(access_store)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        try:
            yield
        finally:
            ledger_board.bind_access(previous_access)
            access_control.bind_sessions(previous_sessions)
            connection.close()

    @contextmanager
    def quarter_copy_fixture(self):
        from tests.card_pipeline.fixtures import domestic_row, make_csv

        snapshot = healthy_snapshot()
        stamp = dt.datetime.now(ga.KST).isoformat()
        snapshot['synced_at'] = stamp
        for source in snapshot['sources'].values():
            source.update(last_ok_at=stamp, checked_at=stamp)
        quarter = snapshot['trips'][0]
        quarter.update(key='3분기_기타비용', kind='quarter', quarter=3, ledger_year=2026)
        quarter['copies']['archive'] = None
        quarter['copies']['main'].update(sheet='3분기_기타비용', kind='quarter', ledger_year=2026)
        snapshot_path = Path(self._dir.name) / 'snapshot.json'
        rows_path = Path(self._dir.name) / 'rows.json'
        snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
        batch = self.flow.pipeline.receive(make_csv([
            domestic_row(merchant='Synthetic quarter payee', amount=12000,
                         approval='Q1', date='2026-09-30')]), 'quarter.csv')['batch_id']
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        self.flow.pipeline.save_decision(row['transaction_id'], row['revision'], item='분기 기타비용',
                                         display_tab_id='unclassified', tab_validator=self.flow.tab_valid,
                                         request_id='quarter-' + row['transaction_id'])
        with patch.dict(os.environ, {'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(snapshot_path),
                                     'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(rows_path)}):
            yield batch, 'quarter:2026:3'

    def test_http_endpoint_returns_the_seven_columns_for_the_trip(self):
        from webapp.tests.test_trip_expense_copy_button import install_canonical_source

        trip = self.make_trip()
        batch = self.flow.pipeline.receive(CARD, 'google-copy.csv')['batch_id']
        install_canonical_source(self, trip)
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            with self.owner_copy_auth(context):
                row = self.flow.pipeline.get_batch(batch)['rows'][0]
                saved = self.save_browser_classification(
                    page, batch, row, trip=trip, item='숙박비',
                    request_id='seven-column-trip-classification')
                self.assertEqual(saved['ledger_recording']['status'], 'recorded')
                preview_response = page.request.get(
                    f'{self.base}/api/google-ledger/expense-reconciliation?trip={trip}')
                self.assertEqual(preview_response.status, 200, preview_response.text())
                preview = preview_response.json()
                response = page.request.post(
                    f'{self.base}/api/google-ledger/expense-reconciliation',
                    data={'action': 'export', 'scope': 'board', 'trip_id': trip,
                          'expected_revision': preview['links_revision'],
                          'preview_digest': preview['preview_digest'],
                          'request_id': 'export:seven-column-trip'},
                    headers={'X-CSRF-Token': ledger_board.CSRF_TOKEN})
                self.assertEqual(response.status, 200, response.text())
                body = response.json()
            browser.close()

        fields = body['tsv'].rstrip('\n').split('\t')
        self.assertEqual(len(fields), 7)
        self.assertEqual(fields[1], '합성상점')
        self.assertEqual(fields[2], '숙박비')
        self.assertEqual(fields[5], '카드')
        self.assertEqual(body['row_count'], 1)
        self.assertEqual(body['total_krw'], 37000)
        self.assertEqual(fields[6], '37000')

    def test_browser_copies_the_exact_tsv_and_warns_on_a_second_copy(self):
        self._copy_flow(390, 844)

    def test_browser_desktop_1440_copies_the_exact_tsv(self):
        self._copy_flow(1440, 900)

    def test_browser_mobile_375_upload_assign_confirm_and_copy(self):
        from webapp.tests.test_trip_expense_copy_button import install_canonical_source

        trip = self.make_trip()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                          viewport={'width': 375, 'height': 812})
            page = context.new_page()
            page.goto(self.base + '/import#newupload')
            page.locator('#file').set_input_files({'name': 'synthetic.csv', 'mimeType': 'text/csv', 'buffer': CARD})
            page.get_by_role('button', name='카드 사용내역 업로드하고 분류').click()
            page.locator('#upload-results a').first.wait_for()
            page.locator('[data-review-state="all"]').click()
            page.locator('#preview [data-edit]').first.click()
            form = page.locator('#questions form[data-index]').first
            form.locator('select[name=display_tab_id]').select_option(trip)
            form.locator('input[name=item]').fill('숙박비')
            with page.expect_response('**/decision') as decision:
                form.get_by_role('button', name='저장하고 자동 반영').click()
            self.assertEqual(decision.value.status, 200)
            self.assertEqual(decision.value.json()['ledger_recording']['status'], 'recorded')
            saved = self.server.card_store.conn.execute(
                'SELECT amount_krw,item,display_tab_id,decided_at IS NOT NULL FROM transactions').fetchone()
            self.assertEqual(saved, (37000, '숙박비', trip, 1))
            install_canonical_source(self, trip)
            self.assertEqual(self.server.card_store.conn.execute(
                'SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries').fetchone(), (1, 37000))
            with self.owner_copy_auth(context):
                page.goto(f'{self.base}/board?tab={trip}')
                button = page.locator('#copy-trip-expenses')
                button.wait_for()
                self.assertTrue(button.is_enabled(), page.locator('.trip-copy-desc').inner_text())
                button.click()
                page.wait_for_function("['success','err'].some(c=>document.getElementById('copy-status')?.classList.contains(c))")
                self.assertIn('success', page.locator('#copy-status').get_attribute('class'),
                              page.locator('#copy-status').inner_text())
                clipboard = page.evaluate('navigator.clipboard.readText()').replace('\r\n', '\n')
                self.assertEqual(len(clipboard.rstrip('\n').split('\t')), 7)
                fields = clipboard.rstrip('\n').split('\t')
                self.assertEqual(fields[1], '합성상점')
                self.assertEqual(fields[2], '숙박비')
                self.assertEqual(fields[-1], '37000')
                self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            browser.close()

    def test_delayed_batch_response_does_not_replace_latest_selection(self):
        self._delayed_response_case(poll=False)

    def test_browser_mobile_375_partial_refund_reupload_books_exact_net_and_copies(self):
        from tests.card_pipeline.fixtures import make_xlsx
        from tests.card_pipeline.test_actual_layouts import HAN
        from webapp.tests.test_trip_expense_copy_button import install_canonical_source
        row = [1, '2026-04-08', '', '****1234', '7777', 1000000, 700000,
               'SYN-REFUND', '', '', '', '\uad6d\ub0b4', '', '', 300000, '',
               '2026-04-10', '\uc815\uc0c1', 0, '']
        # Hana's actual export is headerless and has a five-row preamble.
        # Keep the upload fixture on that parser path so both purchase and
        # cancellation rows (and their linked refund group) are present.
        content = make_xlsx([[''] * len(HAN) for _ in range(5)] + [HAN, row],
                            headers=[], headered=False)
        trip = self.make_trip()
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                          viewport={'width': 375, 'height': 812})
            page = context.new_page()
            page.goto(self.base + '/import#newupload')
            page.locator('#file').set_input_files({'name': 'refund.xlsx',
                'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': content})
            page.click('#upload')
            page.wait_for_function('typeof model !== "undefined" && model.rows.some(r=>r.transaction_direction==="purchase")')
            batch = page.evaluate('model.batch_id')
            uploaded_rows = self.flow.pipeline.get_batch(batch)['rows']
            purchase = next(r for r in uploaded_rows if r['transaction_direction'] == 'purchase')
            cancellation = next(r for r in uploaded_rows if r['transaction_direction'] == 'cancellation')
            self.save_browser_classification(page, batch, purchase, trip=trip,
                                             item='\ud56d\uacf5\ub8cc',
                                             request_id='mobile-refund-classification-purchase')
            self.save_browser_classification(page, batch, cancellation, trip=trip,
                                             item='\ud56d\uacf5\ub8cc',
                                             request_id='mobile-refund-classification-cancellation')
            page.goto(f'{self.base}/import?batch={batch}#saved-materials')
            page.wait_for_function('(id) => typeof model !== "undefined" && model.batch_id === id', arg=batch)
            page.locator('[data-group-commit]').wait_for()
            group = page.evaluate('model.refund_groups[0]')
            before = self.server.card_store.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
            page.goto(self.base + '/import#newupload')
            page.locator('#file').set_input_files({'name': 'refund.xlsx',
                'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': content})
            with page.expect_response('**/api/imports') as reupload_response:
                page.click('#upload')
            self.assertLess(reupload_response.value.status, 400)
            reuploaded_batch = reupload_response.value.json()['batch_id']
            page.wait_for_function('!document.getElementById("upload").disabled')
            self.assertEqual(self.server.card_store.conn.execute(
                'SELECT * FROM transactions ORDER BY transaction_id').fetchall(), before)
            self.assertEqual(reuploaded_batch, batch)
            self.assertEqual((group['gross_krw'], group['refund_krw'], group['net_krw']),
                             (1000000, -700000, 300000))
            page.locator('[data-group-commit]').click()
            page.wait_for_function("document.getElementById('status').textContent.includes('환불 쌍을 장부에 기록했습니다.')")
            self.assertEqual(self.server.card_store.conn.execute(
                'SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries').fetchone(), (2, 300000))
            install_canonical_source(self, trip)
            with self.owner_copy_auth(context):
                page.goto(f'{self.base}/board?tab={trip}')
                page.locator('#copy-trip-expenses').wait_for()
                page.locator('#copy-trip-expenses').click()
                page.wait_for_function("['success','err'].some(c=>document.getElementById('copy-status')?.classList.contains(c))")
                self.assertIn('success', page.locator('#copy-status').get_attribute('class'),
                              page.locator('#copy-status').inner_text())
                clipboard = page.evaluate('navigator.clipboard.readText()').replace('\r\n', '\n')
                rows = [line.split('\t') for line in clipboard.strip().split('\n')]
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(len(row) == 7 for row in rows))
                self.assertEqual(sorted(int(row[6]) for row in rows), [-700000, 1000000])
                self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            browser.close()

    def test_copy_blocks_duplicate_requests_and_recovers_from_error(self):
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            with self.quarter_copy_fixture() as (batch, quarter_id):
                page.route('**/google-tsv?*', lambda route: pending.append(route))
                page.goto(f'{self.base}/import?batch={batch}')
                button = page.locator(f'[data-google-copy="{quarter_id}"]')
                button.wait_for()
                page.evaluate("navigator.clipboard.writeText('KEEP-CLIPBOARD')")
                with page.expect_request('**/google-tsv?*'):
                    button.click()
                self.assertTrue(button.is_disabled())
                button.evaluate('(button)=>{button.click();button.click()}')
                self.assertEqual(len(pending), 1)
                pending.pop().fulfill(status=400, json={'code': 'SYNTHETIC_FAILURE'})
                page.get_by_text('SYNTHETIC_FAILURE', exact=True).wait_for()
                self.assertTrue(button.is_enabled())
                self.assertEqual(page.evaluate('navigator.clipboard.readText()'), 'KEEP-CLIPBOARD')
                browser.close()

    def test_delayed_copy_from_previous_batch_does_not_change_clipboard(self):
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            with self.quarter_copy_fixture() as (first, quarter_id):
                second = self.flow.pipeline.receive(CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
                page.goto(f'{self.base}/import?batch={first}')
                page.wait_for_function('(batch)=>model.batch_id===batch', arg=first)
                button = page.locator(f'[data-google-copy="{quarter_id}"]')
                button.wait_for()
                page.evaluate("navigator.clipboard.writeText('KEEP-CLIPBOARD')")
                expected = page.request.get(
                    f'{self.base}/api/imports/{first}/google-tsv?tab={quarter_id}').json()
                self.assertEqual(expected['row_count'], 1)
                page.route('**/google-tsv?*', lambda route: pending.append(route))
                with page.expect_request('**/google-tsv?*'):
                    button.click()
                page.locator(f'.batch-choice[data-batch="{second}"]').click()
                page.wait_for_function('(batch)=>model.batch_id===batch', arg=second)
                pending.pop().fulfill(json=expected)
                page.get_by_text('자료가 바뀌었습니다. 현재 자료에서 다시 복사해 주세요.', exact=True).wait_for()
                self.assertEqual(page.evaluate('navigator.clipboard.readText()'), 'KEEP-CLIPBOARD')
                self.assertIsNone(page.evaluate(
                    '(trip)=>localStorage.getItem("gcopy-trip:"+trip)', quarter_id))
                browser.close()

    def test_delayed_decision_result_keeps_latest_batch_and_saved_answer(self):
        first = self.assign(trip=self.make_trip())
        row = self.flow.pipeline.get_batch(first)['rows'][0]
        second = self.flow.pipeline.receive(CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#saved-materials')
            page.locator(f'.batch-choice[data-batch="{first}"]').click()
            page.locator(f'[data-edit="{row["transaction_id"]}"]').click()
            form = page.locator('form[data-index]').first
            form.locator('[name="item"]').fill('식비')
            page.route('**/decision', lambda route: pending.append(route))
            with page.expect_request('**/decision'):
                form.locator('button').click()
            response = page.request.post(pending[0].request.url,
                                         data=pending[0].request.post_data_json,
                                         headers={'X-CSRF-Token': ledger_board.CSRF_TOKEN})
            self.assertEqual(response.status, 200)
            result = response.json()
            page.locator(f'.batch-choice[data-batch="{second}"]').click()
            page.wait_for_function('(batch)=>model.batch_id===batch', arg=second)
            with page.expect_response('**/decision'):
                pending.pop().fulfill(json=result)
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.evaluate('model.batch_id'), second)
            saved = self.server.card_store.conn.execute(
                'SELECT item,decided_at IS NOT NULL FROM transactions WHERE transaction_id=?',
                (row['transaction_id'],)).fetchone()
            self.assertEqual(saved, ('식비', 1))
            browser.close()

    def test_delayed_decision_cannot_replace_a_newer_answer_in_the_same_batch(self):
        batch = self.assign(trip=self.make_trip())
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#saved-materials')
            page.locator(f'[data-edit="{row["transaction_id"]}"]').click()
            form = page.locator('form[data-index]').first
            form.locator('[name="item"]').fill('식비')
            page.route('**/decision', lambda route: pending.append(route))
            with page.expect_request('**/decision'):
                form.locator('button').click()
            body = pending[0].request.post_data_json
            headers = {'X-CSRF-Token': ledger_board.CSRF_TOKEN}
            first = page.request.post(pending[0].request.url, data=body, headers=headers)
            self.assertEqual(first.status, 200)
            old = first.json()
            fresh_row = next(r for r in old['rows'] if r['transaction_id'] == row['transaction_id'])
            second = page.request.post(pending[0].request.url, headers=headers,
                                       data={**body, 'revision': fresh_row['revision'],
                                             'item': '교통비', 'request_id': 'another-device-answer'})
            self.assertEqual(second.status, 200)
            page.evaluate('document.activeElement.blur();void pollCard()')
            page.wait_for_function('(id)=>model.rows.find(r=>r.transaction_id===id).item==="교통비"',
                                   arg=row['transaction_id'])
            with page.expect_response('**/decision'):
                pending.pop().fulfill(json=old)
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            shown = page.evaluate('(id)=>model.rows.find(r=>r.transaction_id===id)', row['transaction_id'])
            self.assertEqual(shown['item'], '교통비')
            self.assertEqual(shown['revision'], fresh_row['revision'] + 1)
            self.assertEqual(self.server.card_store.conn.execute(
                'SELECT item FROM transactions WHERE transaction_id=?',
                (row['transaction_id'],)).fetchone()[0], '교통비')
            browser.close()

    def test_delayed_poll_response_does_not_restore_previous_batch(self):
        self._delayed_response_case(poll=True)

    def test_superseded_load_and_poll_errors_keep_current_status(self):
        first = self.assign(trip=self.make_trip())
        second = self.flow.pipeline.receive(CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            for poll in (False, True):
                for status in (401, 500):
                    with self.subTest(poll=poll, status=status):
                        page = browser.new_page()
                        page.goto(self.base + '/import#saved-materials')
                        page.wait_for_function('typeof model !== "undefined"')
                        page.locator(f'.batch-choice[data-batch="{first}"]').click()
                        page.wait_for_function('(batch)=>model.batch_id===batch', arg=first)
                        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
                        pending = []
                        page.route(f'**/api/imports/{first}', lambda route: pending.append(route))
                        with page.expect_request(f'**/api/imports/{first}'):
                            if poll:
                                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});void pollCard()")
                            else:
                                page.locator(f'.batch-choice[data-batch="{first}"]').click()
                        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
                        page.locator(f'.batch-choice[data-batch="{second}"]').click()
                        page.wait_for_function('(batch)=>model.batch_id===batch', arg=second)
                        page.evaluate("document.getElementById('status').textContent='CURRENT-SELECTION'")
                        with page.expect_response(f'**/api/imports/{first}'):
                            pending.pop().fulfill(status=status, json={'message': 'OLD-REQUEST-FAILED'})
                        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                        self.assertEqual(page.locator('#status').inner_text(), 'CURRENT-SELECTION')
                        self.assertEqual(page.evaluate('model.batch_id'), second)
                        page.close()
            browser.close()

    def test_upload_failure_after_batch_switch_keeps_current_status_and_unlocks_button(self):
        batch = self.assign(trip=self.make_trip())
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#newupload')
            page.wait_for_function('typeof model !== "undefined"')
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            page.locator('#newupload').evaluate('(node)=>node.open=true')
            page.locator('#file').set_input_files(dict(name='delayed.csv', mimeType='text/csv', buffer=CARD))
            page.route('**/api/imports', lambda route: pending.append(route))
            with page.expect_request('**/api/imports'):
                page.click('#upload')
            self.assertTrue(page.locator('#upload').is_disabled())
            if not page.locator('#expense-tab-saved').is_visible():
                page.locator('.expense-tools > summary').click()
            page.locator('#expense-tab-saved').click()
            page.locator(f'.batch-choice[data-batch="{batch}"]').click()
            page.wait_for_function('(id)=>model.batch_id===id', arg=batch)
            page.evaluate("document.getElementById('status').textContent='CURRENT-SELECTION'")
            with page.expect_response('**/api/imports'):
                pending.pop().fulfill(status=500, json={'message': 'OLD-UPLOAD-ERROR'})
            page.wait_for_function('!document.getElementById("upload").disabled')
            self.assertEqual(page.locator('#status').inner_text(), 'CURRENT-SELECTION')
            self.assertEqual(page.evaluate('model.batch_id'), batch)
            browser.close()

    def test_committed_ledger_write_survives_state_failure_and_same_request_retry(self):
        from app.db import StoreError
        batch = self.assign(trip=self.make_trip())
        body = dict(digest=self.flow.state(batch)['preview']['digest'], request_id='ledger-refresh-failure')
        with sync_playwright() as api:
            context = api.request.new_context(base_url=self.base,
                                             extra_http_headers={'X-CSRF-Token': ledger_board.CSRF_TOKEN})
            with patch.object(CardFlow, 'state', side_effect=StoreError('REFRESH_FAILED', 'private detail')):
                response = context.post(f'/api/imports/{batch}/commit', data=body)
            self.assertEqual(response.status, 200)
            result = response.json()
            self.assertTrue(result['refresh_required'])
            self.assertTrue(result['saved'])
            count = self.server.card_store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
            self.assertEqual(count, 1)
            replay = context.post(f'/api/imports/{batch}/commit', data=body)
            self.assertEqual(replay.status, 200)
            self.assertEqual(replay.json()['result'], result['result'])
            self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], count)
            context.dispose()

    def test_answer_retry_after_lost_response_reuses_request_and_restores_button(self):
        batch = self.assign(trip=self.make_trip())
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        requests = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#saved-materials')
            page.locator(f'.batch-choice[data-batch="{batch}"]').click()
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            page.locator(f'[data-edit="{row["transaction_id"]}"]').click()
            form = page.locator('form[data-index]').first
            form.locator('[name="item"]').fill('식비')

            def lose_first_response(route):
                body = route.request.post_data_json
                requests.append(body)
                response = page.request.post(route.request.url, data=body,
                                              headers={'X-CSRF-Token': ledger_board.CSRF_TOKEN})
                if len(requests) == 1:
                    self.assertEqual(response.status, 200)
                    route.abort('failed')
                else:
                    route.fulfill(status=response.status, json=response.json())

            page.route('**/decision', lose_first_response)
            form.locator('button').click()
            page.get_by_text('서버에 연결하지 못했습니다.', exact=False).wait_for()
            self.assertTrue(form.locator('button').is_enabled())
            with page.expect_response('**/decision'):
                form.locator('button').click()
            self.assertEqual(requests[0]['request_id'], requests[1]['request_id'])
            page.wait_for_function('(id)=>model.rows.find(r=>r.transaction_id===id).item==="식비"', arg=row['transaction_id'])
            self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0], 1)
            browser.close()

    def test_clipboard_success_is_preserved_when_copy_history_storage_fails(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            with self.quarter_copy_fixture() as (batch, quarter_id):
                page.goto(f'{self.base}/import?batch={batch}')
                button = page.locator(f'[data-google-copy="{quarter_id}"]')
                button.wait_for()
                page.evaluate("()=>{Storage.prototype.setItem=()=>{throw new DOMException('storage full','QuotaExceededError')}}")
                button.click()
                page.wait_for_function('!googleCopyPending')
                self.assertIn('클립보드에 복사했습니다', page.locator('#status').inner_text())
                self.assertIn('복사 이력을 저장하지 못했습니다', page.locator('#status').inner_text())
                expected = page.request.get(
                    f'{self.base}/api/imports/{batch}/google-tsv?tab={quarter_id}').json()['tsv']
                self.assertEqual(page.evaluate('navigator.clipboard.readText()').replace('\r\n', '\n'), expected)
                self.assertTrue(button.is_enabled())
                browser.close()

    def test_card_copy_requires_confirmation_when_history_cannot_be_read(self):
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_context(permissions=['clipboard-read', 'clipboard-write']).new_page()
            with self.quarter_copy_fixture() as (batch, quarter_id):
                page.goto(f'{self.base}/import?batch={batch}')
                button = page.locator(f'[data-google-copy="{quarter_id}"]')
                button.wait_for()
                page.evaluate("navigator.clipboard.writeText('KEEP')")
                page.evaluate("()=>{Storage.prototype.getItem=()=>{throw new DOMException('blocked','SecurityError')}}")
                dialogs = []
                def dismiss(dialog):
                    dialogs.append(dialog.message)
                    dialog.dismiss()
                page.on('dialog', dismiss)
                button.click()
                self.assertEqual(len(dialogs), 1)
                self.assertEqual(page.evaluate('navigator.clipboard.readText()'), 'KEEP')
                page.remove_listener('dialog', dismiss)
                page.on('dialog', lambda dialog: dialog.accept())
                button.click()
                page.wait_for_function("document.getElementById('status').textContent.includes('클립보드에 복사했습니다')")
                expected = page.request.get(
                    f'{self.base}/api/imports/{batch}/google-tsv?tab={quarter_id}').json()['tsv']
                self.assertEqual(page.evaluate('navigator.clipboard.readText()').replace('\r\n', '\n'), expected)
                self.assertTrue(button.is_enabled())
                browser.close()

    def test_commit_failure_for_previous_batch_keeps_current_status(self):
        trip = self.make_trip()
        first = self.flow.pipeline.receive(CARD, 'first.csv')['batch_id']
        second = self.flow.pipeline.receive(CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
        row = self.flow.pipeline.get_batch(first)['rows'][0]
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#saved-materials')
            page.locator(f'.batch-choice[data-batch="{first}"]').click()
            page.wait_for_function('(id)=>model.batch_id===id', arg=first)
            page.locator(f'[data-edit="{row["transaction_id"]}"]').click()
            form = page.locator('form[data-index]')
            form.locator('[name="item"]').fill('숙박비')
            form.locator('[name="display_tab_id"]').select_option(trip)
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            page.route(f'**/api/imports/{first}/decision', lambda route: pending.append(route))
            with page.expect_request(f'**/api/imports/{first}/decision'):
                form.locator('button').click()
            page.locator(f'.batch-choice[data-batch="{second}"]').click()
            page.wait_for_function('(id)=>model.batch_id===id', arg=second)
            page.evaluate("document.getElementById('status').textContent='CURRENT-SELECTION'")
            with page.expect_response(f'**/api/imports/{first}/decision'):
                pending.pop().fulfill(status=500, json={'message': 'OLD-COMMIT-FAILED'})
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.locator('#status').inner_text(), 'CURRENT-SELECTION')
            self.assertEqual(page.evaluate('model.batch_id'), second)
            self.assertEqual(self.server.card_store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], 0)
            browser.close()

    def test_refund_group_failure_after_batch_switch_keeps_current_status(self):
        from webapp.tests.test_refund_group_commit import CSV
        first = self.flow.pipeline.receive(CSV, 'refund.csv')['batch_id']
        conn = self.server.card_store.conn
        conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-700000,"
                     "original_approval_number='100' WHERE approval_number='200'")
        conn.commit()
        self.flow.pipeline.classify_batch(first)
        row = next(r for r in self.flow.pipeline.get_batch(first)['rows'] if r['approval_number'] == '100')
        self.flow.pipeline.save_decision(row['transaction_id'], row['revision'], item='항공료',
                                         display_tab_id='unclassified', tab_validator=lambda _: True,
                                         request_id='refund-browser-answer')
        self.assertTrue(self.flow.state(first)['refund_groups'][0]['recordable'])
        second = self.flow.pipeline.receive(CARD, 'second.csv')['batch_id']
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#saved-materials')
            page.locator(f'.batch-choice[data-batch="{first}"]').click()
            page.locator('[data-group-commit]').wait_for()
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            page.route('**/refund-groups/*/commit', lambda route: pending.append(route))
            with page.expect_request('**/refund-groups/*/commit'):
                page.locator('[data-group-commit]').click()
            page.locator(f'.batch-choice[data-batch="{second}"]').click()
            page.wait_for_function('(id)=>model.batch_id===id', arg=second)
            page.evaluate("document.getElementById('status').textContent='CURRENT-SELECTION'")
            with page.expect_response('**/refund-groups/*/commit'):
                pending.pop().fulfill(status=500, json={'message': 'OLD-REFUND-ERROR'})
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.locator('#status').inner_text(), 'CURRENT-SELECTION')
            self.assertEqual(page.evaluate('model.batch_id'), second)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], 0)
            browser.close()

    def test_old_poll_error_cannot_replace_a_saved_answer_status_in_same_batch(self):
        batch = self.assign(trip=self.make_trip())
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        pending = []
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#saved-materials')
            page.locator(f'.batch-choice[data-batch="{batch}"]').click()
            page.wait_for_function('(id)=>model.batch_id===id', arg=batch)
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            page.locator(f'[data-edit="{row["transaction_id"]}"]').click()
            form = page.locator('form[data-index]').first
            form.locator('[name="item"]').fill('식비')
            page.route(f'**/api/imports/{batch}', lambda route: pending.append(route))
            with page.expect_request(f'**/api/imports/{batch}'):
                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});void pollCard()")
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
            form.locator('button').click()
            page.wait_for_function("document.getElementById('status').textContent.includes('저장했습니다.')")
            status = page.locator('#status').inner_text()
            with page.expect_response(f'**/api/imports/{batch}'):
                pending.pop().fulfill(status=500, json={'message': 'OLD-POLL-FAILED'})
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.locator('#status').inner_text(), status)
            self.assertEqual(page.evaluate('(id)=>model.rows.find(r=>r.transaction_id===id).item', row['transaction_id']), '식비')
            self.assertEqual(self.server.card_store.conn.execute('SELECT item,decided_at IS NOT NULL FROM transactions WHERE transaction_id=?',
                                                                (row['transaction_id'],)).fetchone(), ('식비', 1))
            browser.close()

    def _delayed_response_case(self, *, poll):
        first = self.assign(trip=self.make_trip())
        second = self.flow.pipeline.receive(CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/import#saved-materials')
            page.wait_for_function('typeof model !== "undefined"')
            page.locator(f'.batch-choice[data-batch="{first}"]').click()
            page.wait_for_function('(batch)=>model.batch_id===batch', arg=first)
            page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true,get:()=>true})")
            pending = []
            for batch in (first, second):
                page.route(f'**/api/imports/{batch}', lambda route: pending.append(route))
                with page.expect_request(f'**/api/imports/{batch}'):
                    if poll and batch == first:
                        page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true,get:()=>false});void pollCard()")
                    else:
                        page.locator(f'.batch-choice[data-batch="{batch}"]').click()
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
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                          viewport={'width': width, 'height': height})
            page = context.new_page()
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.accept()))
            with self.quarter_copy_fixture() as (batch, quarter_id):
                page.goto(f'{self.base}/import?batch={batch}')
                page.wait_for_function('(id) => typeof model !== "undefined" && model.batch_id === id', arg=batch)
                button = page.locator(f'[data-google-copy="{quarter_id}"]')
                button.wait_for()
                button.click()
                page.get_by_text('클립보드에 복사했습니다', exact=False).wait_for()
                clipboard = page.evaluate('navigator.clipboard.readText()').replace(chr(13) + chr(10), chr(10))
                expected = json.loads(page.request.get(
                    f'{self.base}/api/imports/{batch}/google-tsv?tab={quarter_id}').text())['tsv']
                self.assertEqual(clipboard, expected)
                self.assertEqual(len(clipboard.rstrip('\n').split('\t')), 7)
                self.assertTrue(page.evaluate(
                    '(trip)=>Boolean(localStorage.getItem("gcopy-trip:"+trip))', quarter_id))
                self.assertIn('장부를 바꾸지 않습니다', page.locator('#status').inner_text())
                self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                button.click()
                page.wait_for_timeout(300)
                self.assertTrue(any('이미 구글 시트용으로 복사' in message for message in dialogs))
                browser.close()

    def test_held_rows_are_listed_and_never_pasted(self):
        from webapp.tests.test_trip_expense_copy_button import install_canonical_source

        trip = self.make_trip()
        batch = self.assign(trip=trip)
        board = self.server.card_store
        board.conn.execute("UPDATE transactions SET item='' WHERE display_tab_id=?", (trip,))
        board.conn.commit()
        install_canonical_source(self, trip)

        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            with self.owner_copy_auth(context):
                preview_response = page.request.get(
                    f'{self.base}/api/google-ledger/expense-reconciliation?trip={trip}')
                self.assertEqual(preview_response.status, 200, preview_response.text())
                preview = preview_response.json()
                response = page.request.post(
                    f'{self.base}/api/google-ledger/expense-reconciliation',
                    data={'action': 'export', 'scope': 'batch', 'batch_id': batch,
                          'trip_id': trip, 'expected_revision': preview['links_revision'],
                          'preview_digest': preview['preview_digest'],
                          'request_id': 'export:held-card-row'},
                    headers={'X-CSRF-Token': ledger_board.CSRF_TOKEN})
                self.assertEqual(response.status, 200, response.text())
                body = response.json()
            browser.close()

        self.assertEqual(body['row_count'], 0)
        held_ids = {entry['transaction_id'] for entry in body['held']}
        transaction_id = board.conn.execute(
            'SELECT transaction_id FROM transactions WHERE display_tab_id=?', (trip,)).fetchone()[0]
        self.assertIn(transaction_id, held_ids)
        self.assertEqual(body['tsv'], '')
