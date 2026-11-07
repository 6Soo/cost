"""모바일 화면에서 업로드·답변·미리보기·기록을 실제 HTTP로 검증한다."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from webapp import ledger_board
from webapp.tests.test_card_flow import CARD


def synthetic_google_source(directory, trip):
    """A fresh empty Google trip source, isolated from all operating snapshots."""
    from app import google_authority as ga
    from webapp.tests.test_sheet_expense_projection import _snapshot, _rows_doc, GOOGLE_KEY
    root = Path(directory)
    snapshot, rows = _snapshot(), _rows_doc()
    rows['sources']['main']['trips'][GOOGLE_KEY]['expense'] = []
    snapshot_path, rows_path = root / 'google-snapshot.json', root / 'google-rows.json'
    snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
    ga._rows_file(rows_path, rows['generation']).write_text(json.dumps(rows), encoding='utf-8')
    (root / 'google-tab-mapping.json').write_text(json.dumps({GOOGLE_KEY: trip}), encoding='utf-8')
    return patch.dict(os.environ, {'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(snapshot_path),
                                  'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(rows_path)})


class CardFlowBrowserTests(unittest.TestCase):
    def test_legacy_cleanup_links_migrate_to_actions_and_history(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'cleanup-browser.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_address[1]}'
                with patch.object(ledger_board, '_participant_owner_request', return_value=True), \
                     sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(viewport={'width':390,'height':844})
                        page.set_default_timeout(5000)
                        self.assertEqual(page.request.get(base + '/import?cleanup_reason=bad').status, 400)
                        self.assertEqual(page.request.get(
                            base + '/import?cleanup_reason=no_item&cleanup_reason=no_trip').status, 400)

                        response = page.goto(base + '/import?cleanup_reason=classification')
                        self.assertEqual(response.status, 200)
                        self.assertIn('/cards/all?cleanup_reason=classification&legacy_cleanup=1', response.url)
                        self.assertEqual(page.locator('#expense-cleanup').count(), 0)

                        page.goto(base + '/import#expense-cleanup')
                        page.wait_for_url('**/my-actions')
                        self.assertTrue(page.get_by_role('heading', name='내 확인 필요').is_visible())
                        self.assertNotIn('/import', page.url)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                        page.close()
                    finally:
                        browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)
    def test_browser_duplicate_card_never_reaches_expense_copy(self):
        from webapp.card_flow import CardFlow

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip = server.card_store.create_trip(starts_on='2026-08-01', ends_on='2026-08-03',
                    destination='Synthetic duplicate trip', client_request_id='duplicate-trip')['tab_id']
                batch = flow.pipeline.receive(CARD, 'duplicate-browser.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                server.card_store.conn.execute(
                    "UPDATE transactions SET duplicate_of='synthetic-original' WHERE transaction_id=?",
                    (row['transaction_id'],))
                server.card_store.conn.commit()
                with patch.object(CardFlow, 'trip_valid', side_effect=lambda identity: identity == trip):
                    flow.classify(batch)
                    server.card_store.conn.execute(
                        "UPDATE transactions SET classification_state='classified', item=?, trip_id=?, "
                        "display_tab_id=? WHERE transaction_id=?",
                        ('숙박비', trip, trip, row['transaction_id']))
                    server.card_store.conn.commit()
                    with sync_playwright() as api:
                        browser = api.chromium.launch(headless=True)
                        page = browser.new_page(viewport={'width':390,'height':844})
                        base_url = f'http://127.0.0.1:{server.server_address[1]}'
                        page.goto(base_url + '/import?batch=' + batch + '&transaction=' +
                                  row['transaction_id'] + '#preview')
                        page.locator('#preview tbody tr').first.wait_for()
                        state = page.request.get(base_url + '/api/imports/' + batch).json()
                        reviewed = state['preview']['rows'][0]
                        self.assertTrue(reviewed['blocked'])
                        self.assertEqual(reviewed['internal_expense_status'], 'HELD')
                        self.assertEqual(state['preview']['ready'], 0)
                        self.assertEqual(state['rows'][0]['duplicate_of'], 'synthetic-original')
                        self.assertEqual(page.request.get(base_url + '/api/imports/' + batch +
                                          '/google-tsv?tab=' + trip).json()['row_count'], 0)
                        self.assertEqual(server.card_store.conn.execute(
                            "SELECT COUNT(*) FROM board_rows WHERE row_id=?",
                            ('card-' + row['transaction_id'],)).fetchone()[0], 0)
                        browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_browser_marks_stale_ota_status_unknown_without_holding_valid_expense(self):
        from types import SimpleNamespace
        from webapp.card_flow import CardFlow
        from webapp import ota_payment_review

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':'',
                 'WEBLEDGER_OTA_REVIEW_MODE':'isolated',
                 'WEBLEDGER_OTA_REVIEW_DB':str(Path(directory)/'ota.sqlite')}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip = server.card_store.create_trip(starts_on='2026-08-01', ends_on='2026-08-03',
                    destination='Synthetic stale snapshot trip', client_request_id='stale-ota-trip')['tab_id']
                batch = flow.pipeline.receive(CARD, 'stale-ota-browser.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                server.card_store.conn.execute(
                    "UPDATE transactions SET classification_state='classified', item=?, trip_id=?, "
                    "display_tab_id=? WHERE transaction_id=?",
                    ('숙박비', trip, trip, row['transaction_id']))
                server.card_store.conn.commit()
                old_result = {'transaction_id':row['transaction_id'], 'status':'MATCHED_AUTO'}
                current = {'generation':8, 'results':[old_result], 'data':{
                    'events':[], 'transactions':[], 'links':{}, 'results':[old_result]}}
                service = SimpleNamespace(held=lambda: (current, False))
                base_url = f'http://127.0.0.1:{server.server_address[1]}'
                with patch.object(ota_payment_review, 'enabled', return_value=True), \
                     patch.object(ota_payment_review, 'snapshot_service', return_value=service), \
                     patch.object(CardFlow, 'trip_valid', return_value=True), \
                     patch.object(CardFlow, 'preview_metadata', return_value=lambda _entry: {}), \
                     patch.object(CardFlow, 'ota_group_holds', return_value={}):
                    with sync_playwright() as api:
                        browser = api.chromium.launch(headless=True)
                        try:
                            page = browser.new_page(viewport={'width':390,'height':844})
                            page.goto(base_url + '/import?batch=' + batch + '&transaction=' +
                                      row['transaction_id'] + '#preview')
                            warning = ('OTA 대사 자료가 갱신 중입니다. 예약 연결 표시는 최신 확인 전까지 '
                                       '미확정으로 표시합니다.')
                            page.locator('#summary').get_by_text(warning, exact=True).wait_for()
                            state = page.request.get(base_url + '/api/imports/' + batch).json()
                            self.assertEqual(state['ota_reconciliation']['status'], 'stale')
                            reviewed = state['preview']['rows'][0]
                            self.assertEqual(reviewed['ota_link_status'], 'UNKNOWN')
                            self.assertEqual(reviewed['internal_expense_status'], 'READY_FOR_INTERNAL_SAVE')
                        finally:
                            browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_browser_unlinked_candidate_reason_and_expense_preview_keep_booking_unconfirmed(self):
        from types import SimpleNamespace
        from webapp.card_flow import CardFlow
        from webapp import ota_payment_review
        from tests.card_pipeline.test_ota_payments import card as ota_card, event as ota_event

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':'',
                 'WEBLEDGER_OTA_REVIEW_MODE':'isolated',
                 'WEBLEDGER_OTA_REVIEW_DB':str(Path(directory)/'ota.sqlite')}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip = server.card_store.create_trip(starts_on='2026-09-30', ends_on='2026-10-03',
                    destination='Synthetic candidate trip', client_request_id='candidate-trip')['tab_id']
                header, source_line = CARD.splitlines(keepends=True)
                fields = source_line.decode('utf-8').rstrip('\r\n').split(',')
                fields[4], fields[5], fields[8] = 'AGODA.COM', '120000', '120000'
                batch = flow.pipeline.receive(header + (','.join(fields)+'\n').encode(),
                                              'ota-unlinked-browser.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                candidate_card = ota_card(row['transaction_id'], source_hash=row['source_hash'],
                    merchant='AGODA.COM', merchant_normalized='agoda.com', approval_date='2026-10-01',
                    amount_krw=120000, card_tail='1234', ota_inference_eligible=True)
                event = ota_event('ota-unlinked-browser', booking_ref='SYNTHETIC-UNCONFIRMED-REF',
                    paid_on=None, amount=120000, amount_krw=120000, verified_portal_snapshot=True,
                    reservation_status='completed',
                    service_period={'starts_on':'2026-10-01','ends_on':'2026-10-03'})
                from app import ota_payments
                result = {'ota_event_id':event['ota_event_id'], 'transaction_id':None,
                          'status':'HOLD_DATE_UNKNOWN', 'reason':'payment_date_not_in_source',
                          'candidates':[], 'candidate_search':ota_payments.search_card_candidates(
                              event, [candidate_card])}
                current = {'generation':28, 'data':{'events':[event], 'transactions':[candidate_card],
                    'links':{}, 'results':[result]}, 'results':[result]}
                service = SimpleNamespace(held=lambda: (current, True))
                backend = SimpleNamespace(store=SimpleNamespace(group_pins=lambda: []), close=lambda: None)
                base = {'matches':[], 'type_only_candidates':[], 'rules':[],
                        'unmatched_transactions':[dict(candidate_card, reason='payment_date_unknown')],
                        'ota_source_errors':[],
                        'ota_source_inventory':{'missing':[]}, 'evidence_gate':{}}
                with patch.object(ota_payment_review, 'enabled', return_value=True), \
                     patch.object(ota_payment_review, 'snapshot_service', return_value=service), \
                     patch.object(ota_payment_review.CoreOtaPaymentBackend, 'from_host', return_value=backend), \
                     patch.object(flow, '_compute_ota_report', return_value=base), \
                    patch.object(CardFlow, 'trip_valid', side_effect=lambda identity: identity == trip):
                    flow.classify(batch)
                    assigned = server.card_store.conn.execute(
                        'SELECT display_tab_id FROM transactions WHERE transaction_id=?',
                        (row['transaction_id'],)).fetchone()[0]
                    self.assertEqual(assigned, trip)
                    with sync_playwright() as api:
                        browser = api.chromium.launch(headless=True)
                        page = browser.new_page(viewport={'width':390,'height':844})
                        base_url = f'http://127.0.0.1:{server.server_address[1]}'
                        page.goto(base_url + '/import?batch=' + batch + '&transaction=' +
                                  row['transaction_id'] + '#preview')
                        page.locator('#preview tbody tr').first.wait_for()
                        state = page.request.get(base_url + '/api/imports/' + batch).json()
                        reviewed = state['preview']['rows'][0]
                        self.assertEqual(reviewed['ota_link_status'], 'UNLINKED')
                        self.assertIn(reviewed['internal_expense_status'],
                                      ('READY_FOR_INTERNAL_SAVE', 'SAVED'), reviewed)
                        self.assertEqual(reviewed['display_tab_id'], trip)
                        self.assertEqual(reviewed.get('booking_ref') or '', '')
                        visible = page.locator('#preview').inner_text()
                        # Unlinked OTA identifiers stay in evidence storage and
                        # are not fabricated as a confirmed expense reference.
                        self.assertNotIn('SYNTHETIC-UNCONFIRMED-REF', visible)
                        self.assertIn('후보 근거 · 결제 미검증', visible)
                        self.assertIn('ota_candidate_notes', state['rows'][0])
                        self.assertTrue(state['rows'][0]['ota_candidate_notes'])
                        with synthetic_google_source(directory, trip):
                            copied = page.request.get(base_url + '/api/imports/' + batch +
                                                       '/google-tsv?tab=' + trip).json()
                        self.assertEqual(copied['row_count'], 1)
                        self.assertNotIn('SYNTHETIC-UNCONFIRMED-REF', copied['tsv'])
                        self.assertEqual(copied['tsv'].splitlines()[0].split('\t')[4], '')
                        page.locator('[data-edit]').first.click()
                        decision = page.locator('form[data-index]').first
                        self.assertEqual(decision.locator('select[name=display_tab_id]').input_value(), trip)
                        status_before = page.locator('#status').inner_text()
                        decision.locator('button').click()
                        page.wait_for_function("old => document.querySelector('#status')?.textContent !== old",
                                               arg=status_before)
                        stored = server.card_store.get_row('card-' + row['transaction_id'])
                        self.assertEqual(stored['display_tab_id'], trip)
                        self.assertEqual(stored['reservation_no'], '')
                        self.assertEqual(stored['amount_krw'], 120000)
                        self.assertEqual(server.card_store.conn.execute(
                            'SELECT COUNT(*) FROM board_rows WHERE row_id=?',
                            ('card-' + row['transaction_id'],)).fetchone()[0], 1)
                        self.assertEqual(server.card_store.conn.execute(
                            'SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?',
                            (row['transaction_id'],)).fetchone()[0], 1)
                        self.assertEqual(server.card_store.conn.execute(
                            'SELECT COUNT(*) FROM board_rows').fetchone()[0], 1)
                        browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_browser_trip_move_saves_before_opening_existing_learning_dialog(self):
        from webapp.card_flow import CardFlow
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip_a = server.card_store.create_trip(starts_on='2026-08-01', ends_on='2026-08-03',
                    destination='Synthetic A', client_request_id='browser-move-a')['tab_id']
                trip_b = server.card_store.create_trip(starts_on='2026-08-10', ends_on='2026-08-12',
                    destination='Synthetic B', client_request_id='browser-move-b')['tab_id']
                batch = flow.pipeline.receive(CARD, 'browser-trip-move.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                flow.pipeline.save_decision(row['transaction_id'], row['revision'], item='숙박비',
                    display_tab_id=trip_a, trip_id=trip_a, request_id='browser-assign-a',
                    trip_validator=lambda _value: True, tab_validator=lambda _value: True)
                base_url = f'http://127.0.0.1:{server.server_address[1]}'
                with patch.object(CardFlow, 'trip_valid', return_value=True):
                    with sync_playwright() as api:
                        browser = api.chromium.launch(headless=True)
                        page = browser.new_page(viewport={'width':390,'height':844})
                        page.goto(base_url + '/import?batch=' + batch + '&transaction=' + row['transaction_id'])
                        form = page.locator('form[data-index]').first
                        form.locator('select[name=display_tab_id]').select_option(trip_b)
                        form.locator('button').click()
                        page.wait_for_url('**/rules?case=*')
                        self.assertIn('이 거래를 이 여행으로 옮긴 이유를 알려주세요.',
                                      page.locator('body').inner_text())
                        saved = server.card_store.get_row('card-' + row['transaction_id'])
                        self.assertEqual(saved['display_tab_id'], trip_b)
                        self.assertTrue(page.locator('textarea[name=direct_answer]').count())
                        direct = page.locator('form').filter(
                            has=page.locator('textarea[name=direct_answer]'))
                        direct.locator('textarea[name=direct_answer]').fill('합성 일정 근거로 여행 B에 옮겼습니다.')
                        direct.locator('button').click()
                        page.wait_for_load_state('domcontentloaded')
                        case_id = page.url.split('case=', 1)[1].split('&', 1)[0]
                        dialog = server.card_store.rule_dialog_state(case_id)
                        self.assertEqual(dialog['answers']['trip_move_reason'],
                                         '합성 일정 근거로 여행 B에 옮겼습니다.')
                        browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_browser_trip_move_can_choose_a_synthetic_ai_reason_and_keeps_direct_input(self):
        from webapp.card_flow import CardFlow
        from webapp.dialog_turn import SyntheticAdapter
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip_a = server.card_store.create_trip(starts_on='2026-08-01', ends_on='2026-08-03',
                    destination='Synthetic A', client_request_id='browser-reason-a')['tab_id']
                trip_b = server.card_store.create_trip(starts_on='2026-08-10', ends_on='2026-08-12',
                    destination='Synthetic B', client_request_id='browser-reason-b')['tab_id']
                batch = flow.pipeline.receive(CARD, 'browser-ai-reason.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                flow.pipeline.save_decision(row['transaction_id'], row['revision'], item='숙박비',
                    display_tab_id=trip_a, trip_id=trip_a, request_id='browser-reason-assign-a',
                    trip_validator=lambda _value: True, tab_validator=lambda _value: True)
                flow.pipeline.save_decision(row['transaction_id'], row['revision'] + 1, item='숙박비',
                    display_tab_id=trip_b, trip_id=trip_b, request_id='browser-reason-assign-b',
                    trip_validator=lambda _value: True, tab_validator=lambda _value: True)
                flow.trip_valid = lambda _value: True
                flow.record_decision(batch, row['transaction_id'])
                learning = flow.open_trip_move_learning(row['transaction_id'], trip_a, trip_b,
                                                        request_id='browser-reason-assign-b')
                row_view = server.card_store.get_row('card-' + row['transaction_id'])
                adapter = SyntheticAdapter('muse', 'free-synthetic', summary=json.dumps(
                    {'options':['여행 일정에 맞는 비용이라서','이 여행을 준비하며 쓴 거래라서']},
                    ensure_ascii=False), draft={
                        'conditions': {'merchant_normalized': row_view['source_merchant']},
                        'effects': {'item':'숙박비', 'display_tab_id':trip_b},
                        'scope': {'trip_id':trip_b, 'event_year':2026, 'applicability':'future'},
                    })
                base_url = f'http://127.0.0.1:{server.server_address[1]}'
                with patch.object(ledger_board, '_MUSE', adapter), patch.object(CardFlow, 'trip_valid', return_value=True):
                    with sync_playwright() as api:
                        browser = api.chromium.launch(headless=True)
                        try:
                            page = browser.new_page(viewport={'width':390,'height':844})
                            page.goto(base_url + '/rules?case=' + learning['case_id'])
                            page.get_by_role('button', name='AI 예상 이유 2개 제안').click()
                            page.wait_for_load_state('domcontentloaded')
                            page.get_by_text('여행 일정에 맞는 비용이라서', exact=True).wait_for()
                            self.assertTrue(page.locator('textarea[name=direct_answer]').count())
                            answer_form = page.locator('form[action="/api/classification/dialog/answer"]').first
                            answer_form.locator('input[type=radio]').first.check()
                            answer_form.locator('button').click()
                            page.wait_for_load_state('domcontentloaded')
                            case_id = learning['case_id']
                            for _ in range(8):
                                answers = page.locator('form[action="/api/classification/dialog/answer"]')
                                if not answers.count():
                                    break
                                form = answers.first
                                radios = form.locator('input[type=radio]')
                                if radios.count():
                                    state = server.card_store.rule_dialog_state(case_id)
                                    question_id = form.locator('input[name=question_id]').get_attribute('value')
                                    question = next(q for q in state['open_questions']
                                                    if q['question_id'] == question_id)
                                    repeatable = form.locator('input[type=radio][value="repeatable"]')
                                    (repeatable if question['question_key'] == 'rule_kind' and
                                     repeatable.count() else radios.first).check()
                                else:
                                    form.locator('textarea[name=direct_answer]').fill('합성 답변입니다.')
                                form.locator('button').click()
                                page.wait_for_load_state('domcontentloaded')
                            self.assertFalse(page.locator(
                                'form[action="/api/classification/dialog/answer"]').count())
                            page.locator('form[action="/api/classification/conversation/advance"] button').click()
                            page.wait_for_load_state('domcontentloaded')
                            page.locator('form[action="/api/classification/conversation/confirm-draft"] button').click()
                            page.wait_for_load_state('domcontentloaded')
                            page.locator('input[name=apply_existing]').uncheck()
                            page.locator('input[name=apply_future]').check()
                            page.locator('form[action="/api/classification/rules/preview"] button').click()
                            page.wait_for_load_state('domcontentloaded')
                            self.assertIn('미래 입력', page.locator('body').inner_text())
                            page.locator('form[action="/api/classification/rules/apply"] button').click()
                            page.wait_for_load_state('domcontentloaded')
                            dialog = server.card_store.dialog_page_state(case_id)
                            self.assertTrue(dialog['rule'])
                            self.assertEqual(server.card_store.get_row(
                                'card-' + row['transaction_id'])['display_tab_id'], trip_b)
                            future_bytes = CARD.replace(b'A123', b'FUTURE-987')
                            future_batch = flow.pipeline.receive(
                                future_bytes, 'browser-future-rule.csv')['batch_id']
                            with patch.object(CardFlow, 'trip_valid', return_value=True):
                                flow.classify(future_batch)
                            future_row = flow.pipeline.get_batch(future_batch)['rows'][0]
                            self.assertEqual(future_row['display_tab_id'], trip_b)
                            self.assertNotIn('reservation_no', json.dumps(adapter.calls))
                        finally:
                            browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_browser_shows_inferred_undated_ota_without_confirming_booking_number(self):
        from types import SimpleNamespace
        from app import ota_payments
        from webapp.card_flow import CardFlow
        from webapp import ota_payment_review
        from tests.card_pipeline.test_ota_payments import card as ota_card, event as ota_event
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':'',
                 'WEBLEDGER_OTA_REVIEW_MODE':'isolated',
                 'WEBLEDGER_OTA_REVIEW_DB':str(Path(directory)/'ota.sqlite')}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip = server.card_store.create_trip(starts_on='2026-08-01', ends_on='2026-08-03',
                    destination='Synthetic stay trip', client_request_id='browser-inferred-trip')['tab_id']
                header, source_line = CARD.splitlines(keepends=True)
                fields = source_line.decode('utf-8').rstrip('\r\n').split(',')
                fields[4], fields[5], fields[8] = 'AGODA.COM', '30000', '30000'
                batch = flow.pipeline.receive(header + (','.join(fields)+'\n').encode(),
                                              'ota-inferred-browser.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                candidate_card = ota_card(row['transaction_id'], source_hash=row['source_hash'],
                    merchant='AGODA.COM', merchant_normalized='agoda.com', approval_date='2026-08-01',
                    amount_krw=30000, card_tail='1234', ota_inference_eligible=True)
                event = ota_event('ota-inferred-browser', paid_on=None, verified_portal_snapshot=True,
                    reservation_status='completed',
                    service_period={'starts_on':'2026-08-01','ends_on':'2026-08-03'})
                result = ota_payments.match_ota_payment_events([event], [candidate_card])[0]
                current = {'generation':4, 'data':{'events':[event], 'transactions':[candidate_card],
                    'links':{}, 'results':[result]}, 'results':[result]}
                service = SimpleNamespace(held=lambda: (current, True))
                backend = SimpleNamespace(store=SimpleNamespace(group_pins=lambda: []), close=lambda: None)
                base = {'matches':[], 'type_only_candidates':[], 'rules':[], 'ota_source_errors':[],
                        'ota_source_inventory':{'missing':[]}, 'evidence_gate':{}}
                with patch.object(ota_payment_review, 'enabled', return_value=True), \
                     patch.object(ota_payment_review, 'snapshot_service', return_value=service), \
                     patch.object(ota_payment_review.CoreOtaPaymentBackend, 'from_host', return_value=backend), \
                     patch.object(flow, '_compute_ota_report', return_value=base), \
                     patch.object(flow, 'trip_valid', side_effect=lambda identity: identity == trip):
                    flow.classify(batch)
                    with sync_playwright() as api:
                        browser = api.chromium.launch(headless=True)
                        page = browser.new_page(viewport={'width':390,'height':844})
                        base_url = f'http://127.0.0.1:{server.server_address[1]}'
                        page.goto(base_url + '/import?batch=' + batch + '&transaction=' +
                                  row['transaction_id'] + '#preview')
                        state = page.request.get(base_url + '/api/imports/' + batch).json()
                        page.locator('#preview tbody tr').first.wait_for()
                        prepared = state['preview']['rows'][0]
                        self.assertEqual(prepared['ota_link_status'], 'EXACT')
                        self.assertEqual(prepared['internal_expense_status'], 'SAVED')
                        self.assertEqual(prepared['display_tab_id'], trip)
                        self.assertEqual(prepared.get('booking_ref') or '', '')
                        self.assertIsNone(event.get('paid_on'))
                        self.assertFalse(result.get('payment_date_verified', False))
                        self.assertIn('거래 처리 결과', page.locator('#preview').inner_text())
                        saved = json.loads(server.card_store.conn.execute(
                            'SELECT payload_json FROM board_rows WHERE row_id=?',
                            ('card-' + row['transaction_id'],)).fetchone()[0])
                        self.assertEqual(saved['reservation_no'], '')
                        browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_auto_recorded_expense_is_visible_and_unique_without_a_second_book_action(self):
        from webapp.card_flow import CardFlow
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip = server.card_store.create_trip(starts_on='2026-10-01', ends_on='2026-10-03',
                    destination='Synthetic recording trip', client_request_id='browser-recording-trip')['tab_id']
                batch = flow.pipeline.receive(CARD, 'ready-synthetic.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                with patch.object(flow, 'trip_valid', side_effect=lambda identity: identity == trip):
                    flow.pipeline.save_decision(row['transaction_id'], row['revision'],
                                            item='소모품', display_tab_id=trip,
                                            tab_validator=flow.tab_valid, request_id='ready-confirm')
                    flow.classify(batch)
                    self.assertEqual(flow.auto_record(batch)['auto_recorded'], 0)
                    self.assertEqual(flow.auto_record(batch)['auto_recorded'], 0)
                row_id = 'card-' + row['transaction_id']
                self.assertEqual(server.card_store.conn.execute(
                    'SELECT COUNT(*) FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0], 1)
                self.assertEqual(server.card_store.conn.execute(
                    'SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?',
                    (row['transaction_id'],)).fetchone()[0], 1)
                with sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page()
                    base = f'http://127.0.0.1:{server.server_address[1]}'
                    for width, height in ((390,844), (1440,900)):
                        page.set_viewport_size({'width':width, 'height':height})
                        page.goto(base + '/import?batch=' + batch + '&transaction=' + row['transaction_id'] + '#preview')
                        state = page.request.get(base + '/api/imports/' + batch).json()
                        self.assertTrue(state['preview']['rows'][0]['already_booked'])
                        page.locator('[data-review-state="all"]').click()
                        page.locator('#preview tbody tr').first.wait_for()
                        self.assertEqual(page.locator('#preview tbody tr').count(), 1)
                        self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                        self.assertEqual(server.card_store.conn.execute(
                            'SELECT COUNT(*) FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0], 1)
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_verified_ota_metadata_is_visible_after_automatic_recording(self):
        import json
        from webapp.card_flow import CardFlow
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        from tests.card_pipeline.fixtures import make_csv, domestic_row
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':'',
                 'WEBLEDGER_OTA_MAIL_DIR': str(Path(directory)/'ota-mail')}):
            mail_dir = Path(directory)/'ota-mail'
            mail_dir.mkdir()
            save(mail_dir, [message(hotel())])
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                flow = CardFlow(server.card_store)
                trip = server.card_store.create_trip(starts_on='2026-05-22', ends_on='2026-05-23',
                    destination='Synthetic Italy stay', client_request_id='browser-ota-stay-trip')['tab_id']
                batch = flow.pipeline.receive(make_csv([domestic_row(merchant='TRIP.COM',
                    amount=123000, approval='87654321', date='2026-05-01')]), 'synthetic-ota.csv')['batch_id']
                from app import ota_payments
                payment_event = {'ota_event_id':'browser-verified-ota-payment', 'provider':'trip',
                    'booking_ref':'1111111111111111', 'event_type':'charge', 'evidence_status':'paid_verified',
                    'payment_status':'paid', 'currency':'KRW', 'amount_krw':123000,
                    'paid_on':'2026-05-01', 'card_last4':'1234'}
                authority = patch.object(CardFlow, 'trip_valid', autospec=True,
                                         side_effect=lambda instance, identity: identity == trip)
                authority.start()
                self.addCleanup(authority.stop)
                payment_source = patch.object(ota_payments, 'build_ota_payment_events', return_value=[payment_event])
                payment_source.start()
                self.addCleanup(payment_source.stop)
                with patch.object(flow, 'trip_valid', side_effect=lambda identity: identity == trip):
                    with patch.object(ota_payments, 'build_ota_payment_events', return_value=[payment_event]):
                        flow.classify(batch)
                        self.assertEqual(flow.auto_record(batch)['auto_recorded'], 0)
                        self.assertEqual(flow.auto_record(batch)['auto_recorded'], 0)
                transaction_id = flow.pipeline.get_batch(batch)['rows'][0]['transaction_id']
                row_id = 'card-' + transaction_id
                self.assertEqual(server.card_store.conn.execute(
                    'SELECT COUNT(*) FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0], 1)
                self.assertEqual(server.card_store.conn.execute(
                    'SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?',
                    (transaction_id,)).fetchone()[0], 1)
                with sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page()
                    for width, height in ((390,844), (1440,900)):
                        page.set_viewport_size({'width':width, 'height':height})
                        page.goto(f'http://127.0.0.1:{server.server_address[1]}/import?batch={batch}&transaction={transaction_id}#preview')
                        state = page.request.get(f'http://127.0.0.1:{server.server_address[1]}/api/imports/{batch}').json()
                        self.assertEqual(state['preview']['rows'][0].get('booking_ref'), '1111111111111111', state['preview']['rows'][0])
                        page.locator('[data-review-state="all"]').click()
                        page.locator('#preview').get_by_text('OTA 예약 근거', exact=False).wait_for()
                        text = page.locator('#preview').inner_text()
                        self.assertIn('1111111111111111', text)
                        self.assertIn('2026-05-22~2026-05-23', text)
                        self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                    row = json.loads(server.card_store.conn.execute(
                        'SELECT payload_json FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0])
                    self.assertEqual(row['reservation_no'], '1111111111111111')
                    self.assertEqual(row['service_period'], '2026-05-22~2026-05-23')
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_home_has_no_pending_ledger_state_at_mobile_and_desktop_widths(self):
        from webapp.card_flow import CardFlow
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1', 'WEBLEDGER_REVIEW_FROM':''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite',
                                        with_worker=False, seed_demo=False)
            flow = CardFlow(server.card_store)
            flow.pipeline.receive(CARD, 'pending-synthetic.csv')
            server.card_store.conn.execute("UPDATE transactions SET classification_state='classified', "
                                           "item='소모품비', display_tab_id='unclassified'")
            server.card_store.conn.commit()
            for index in range(6):
                server.card_store.create_trip(starts_on=f'2026-12-{10+index:02}',
                    ends_on=f'2026-12-{11+index:02}', destination=f'합성 여행 {index}',
                    client_request_id=f'pending-browser-{index}')
            registered = {trip['tab_id']:{'departure_status':'scheduled'}
                          for trip in server.card_store.list_trips()}
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as api, patch('app.reserve_trips.registrations', return_value=registered):
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page()
                    for width, height in ((390,844), (1440,900)):
                        page.set_viewport_size({'width':width, 'height':height})
                        self.assertEqual(page.goto(f'http://127.0.0.1:{server.server_address[1]}/').status, 200)
                        page.evaluate('document.fonts.ready')
                        self.assertNotIn('장부 반영 대기', page.locator('.home-status').inner_text())
                        self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                        self.assertTrue(page.locator('.home-review.primary').is_visible())
                        visible = page.locator('.home-trip').evaluate_all(
                            'els => els.filter(el => el.getBoundingClientRect().bottom <= innerHeight).length')
                        self.assertGreaterEqual(visible, 5)
                        artifact = Path('.local-archive/pending-authority-verification')
                        artifact.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(artifact/f'home-{width}.png'))
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_home_card_upload_cta_opens_integrated_workspace_without_writing(self):
        from app import Pipeline
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite', with_worker=False, seed_demo=False)
            pipe = Pipeline(server.card_store.conn)
            batch = pipe.receive(CARD, 'H.xlsx')['batch_id']
            original = pipe.get_batch(batch)['summary']['content_sha256']
            trip = server.card_store.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                destination='Synthetic home trip', display_key='1010 Synthetic home trip',
                client_request_id='home-mobile-trip')['tab_id']
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            errors = []
            try:
                with sync_playwright() as api, patch.object(
                        ledger_board, '_participant_owner_request', return_value=True):
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    base = f'http://127.0.0.1:{server.server_address[1]}'
                    response = page.goto(base + '/')
                    self.assertEqual(response.status, 200)
                    self.assertTrue(page.get_by_role('heading', name='장부 현황', exact=False).is_visible())
                    self.assertEqual(page.locator('input[type=file]').count(), 0)
                    self.assertEqual(page.locator('.home-review').get_attribute('href'), '/my-actions')
                    self.assertNotIn('지출 정리', page.locator('body').inner_text())
                    self.assertEqual(page.locator('.home-secondary a[href="/cards/all?panel=upload"]').count(), 1)
                    page.locator('.home-secondary a[href="/cards/all?panel=upload"]').click()
                    page.wait_for_url(base + '/cards/all?panel=upload')
                    self.assertTrue(page.locator('#card-upload-panel').is_visible())
                    self.assertTrue(page.locator('#card-upload-files').is_visible())
                    self.assertEqual(page.locator('#card-upload-selection').inner_text(), '선택된 파일 없음')
                    self.assertNotIn('H.xlsx', page.locator('body').inner_text())
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    self.assertEqual(pipe.get_batch(batch)['summary']['content_sha256'], original)
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 0)
                    page.keyboard.press('Escape')
                    page.wait_for_url(base + '/cards/all')
                    self.assertEqual(page.locator('.nav a[href="/cards/all"]').get_attribute('aria-current'), 'page')
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close(); thread.join(timeout=3); ledger_board.bind_store(previous)
    def test_upload_entry_opens_new_file_details_without_changing_selection(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1', 'WEBLEDGER_CARD_FLOW':'1'}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite', with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            errors = []
            try:
                with sync_playwright() as api, patch.object(
                        ledger_board, '_participant_owner_request', return_value=True):
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror', lambda e:errors.append(str(e)))
                    base = f'http://127.0.0.1:{server.server_address[1]}'
                    page.goto(base + '/')
                    page.locator('.home-secondary a[href="/cards/all?panel=upload"]').click()
                    page.wait_for_url(base + '/cards/all?panel=upload')
                    self.assertTrue(page.locator('#card-upload-panel').is_visible())
                    self.assertTrue(page.locator('#card-upload-files').is_visible())
                    self.assertEqual(page.locator('#card-upload-selection').inner_text(), '선택된 파일 없음')
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close(); thread.join(timeout=3); ledger_board.bind_store(None)

    def test_low_confidence_assignment_is_editable_and_does_not_require_approval_to_preview(self):
        from app import Pipeline
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1','WEBLEDGER_REVIEW_FROM':''}):
            ledger_board.bind_access(None)
            server=ledger_board.serve(port=0,db_path=Path(directory)/'board.sqlite',with_worker=False,seed_demo=False)
            pipe=Pipeline(server.card_store.conn)
            batch=pipe.receive(CARD,'synthetic-inference.csv')['batch_id']
            row=pipe.get_batch(batch)['rows'][0]
            pipe.save_rule({'conditions':{'merchant_normalized':row['merchant']},
                            'optional':{'source_hash':row['source_hash'],'inferred_assignment':{
                                'trip_id':'','confidence':'낮음','basis':'상품 설명을 참고한 공통 경비 추론'}},
                            'effects':{'item':'소모품비'},'origin':'owner-authorized-inference-20261003'})
            pipe.classify_batch(batch)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            errors=[]
            try:
                with sync_playwright() as api:
                    browser=api.chromium.launch(headless=True)
                    page=browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/import?batch={batch}&transaction={row["transaction_id"]}')
                    form = page.locator('form[data-index]').first
                    form.wait_for(state='attached')
                    self.assertEqual(page.get_by_text('비용 항목 확인 권장',exact=True).count(),0)
                    self.assertEqual(pipe.get_batch(batch)['rows'][0]['classification_state'],'classified')
                    self.assertFalse(pipe.get_batch(batch)['rows'][0]['decided'])
                    if not form.is_visible():
                        page.locator('#questions summary').first.click()
                    form.locator('input[name=item]').fill('사무용품비')
                    with page.expect_response(lambda response: response.url.endswith('/decision') and response.request.method == 'POST') as saved:
                        form.get_by_role('button',name='저장하고 자동 반영').click()
                    self.assertEqual(saved.value.status,200,saved.value.json())
                    pipe.classify_batch(batch)
                    actual=pipe.get_batch(batch)['rows'][0]
                    self.assertTrue(actual['decided'])
                    self.assertEqual(actual['item'],'사무용품비')
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],0)
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                server.shutdown();server.server_close();server.card_store.close();thread.join(timeout=3);ledger_board.bind_store(None)

    def test_review_evidence_labels_render_distinct_reasons_without_generic_warning(self):
        synthetic_state = {
            'batch_id':'synthetic-evidence',
            'summary':{
                'display_name':'synthetic evidence', 'period_start':'2026-07-01',
                'period_end':'2026-07-31', 'row_count':5, 'filename':'synthetic.csv',
                'counts':{'classified':4, 'needs_review':2},
            },
            'preview':{'digest':'synthetic-digest', 'rows':[]},
            'trips':[{'id':'trip-jp', 'name':'일본', 'available':True}],
            'rows':[
                {
                    'transaction_id':'booking-trip', 'revision':1, 'merchant':'AGODA',
                    'approval_date':'2026-07-11', 'posting_date':'2026-07-11', 'amount_krw':1301996,
                    'classification_state':'needs_review', 'classification_source':'inference',
                    'classification_basis':'추론 배정 · 낮음 · 일정 근거', 'item':'숙박비',
                    'display_tab_id':'trip-jp', 'trip_id':'trip-jp', 'description':'', 'note':'',
                    'decided':False, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_evidence_labels':['예약 근거 있음','여행 배정 확인 권장'],
                },
                {
                    'transaction_id':'mail-unlinked', 'revision':1, 'merchant':'TRIP.COM',
                    'approval_date':'2026-07-12', 'posting_date':'2026-07-12', 'amount_krw':64814,
                    'classification_state':'needs_review', 'classification_source':'rule',
                    'classification_basis':'예약 연결 확인 필요', 'item':'숙박비',
                    'display_tab_id':'unclassified', 'trip_id':'', 'description':'', 'note':'',
                    'decided':False, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_evidence_labels':['메일 있음 · 연결 확인 필요','분류 확인 권장'],
                },
                {
                    'transaction_id':'cancel-refund', 'revision':1, 'merchant':'TRIP.COM',
                    'approval_date':'2026-04-22', 'posting_date':'2026-04-22', 'amount_krw':-337406,
                    'classification_state':'needs_review', 'classification_source':'rule',
                    'classification_basis':'취소 정산 확인', 'item':'숙박비',
                    'display_tab_id':'unclassified', 'trip_id':'', 'description':'', 'note':'',
                    'decided':False, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_hold':{'kind':'refund_pending','reason':'카드 환불 원행 확인 필요'},
                    'review_evidence_labels':['취소 메일 있음','환불 확인 필요'],
                },
                {
                    'transaction_id':'no-link', 'revision':1, 'merchant':'AGODA',
                    'approval_date':'2026-07-12', 'posting_date':'2026-07-12', 'amount_krw':273560,
                    'classification_state':'needs_review', 'classification_source':'inference',
                    'classification_basis':'추론 배정 · 낮음 · 예약 연결 없음', 'item':'',
                    'display_tab_id':'unclassified', 'trip_id':'', 'description':'', 'note':'',
                    'decided':False, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_evidence_labels':['메일 연결 없음','분류 확인 권장'],
                },
                {
                    'transaction_id':'decided', 'revision':1, 'merchant':'AGODA',
                    'approval_date':'2026-07-13', 'posting_date':'2026-07-13', 'amount_krw':100000,
                    'classification_state':'classified', 'classification_source':'inference',
                    'classification_basis':'사용자 답변', 'item':'숙박비',
                    'display_tab_id':'trip-jp', 'trip_id':'trip-jp', 'description':'', 'note':'',
                    'decided':True, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_evidence_labels':['예약 근거 있음'],
                },
            ],
        }
        synthetic_state['preview']['rows'] = [
            {**row, 'next_action': {
                'required': row['transaction_id'] != 'decided',
                'label': '비용 항목 확인', 'reason': '합성 검토 상태',
                'state': 'review' if row['transaction_id'] != 'decided' else 'booked',
            }} for row in synthetic_state['rows']
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
            ledger_board.bind_access(None)
            server=ledger_board.serve(port=0,db_path=Path(directory)/'board.sqlite',with_worker=False,seed_demo=False)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as api:
                    browser=api.chromium.launch(headless=True)
                    for width,height in ((390,844),(1440,900)):
                        with self.subTest(width=width):
                            page=browser.new_page(viewport={'width':width,'height':height})
                            def route_api(route):
                                path=route.request.url.split('?',1)[0]
                                if path.endswith('/api/imports/rules'):
                                    route.fulfill(status=200,content_type='application/json',body='{"rules":[]}')
                                elif path.endswith('/api/imports/synthetic-evidence'):
                                    import json
                                    route.fulfill(status=200,content_type='application/json',body=json.dumps(synthetic_state,ensure_ascii=False))
                                elif path.endswith('/api/imports'):
                                    route.fulfill(status=200,content_type='application/json',body='{"batches":[{"batch_id":"synthetic-evidence","display_name":"synthetic evidence","period_start":"2026-07-01","period_end":"2026-07-31","rows":5,"questions":4}]}')
                                else:
                                    route.continue_()
                            page.route('**/api/imports**', route_api)
                            page.goto(
                                f'http://127.0.0.1:{server.server_address[1]}'
                                '/import?batch=synthetic-evidence&transaction=booking-trip#preview')
                            page.get_by_text('예약 근거 있음 · 여행 배정 확인 권장',exact=True).first.wait_for()
                            self.assertGreater(page.get_by_text('예약 근거 있음 · 여행 배정 확인 권장',exact=True).count(),0)
                            self.assertGreater(page.get_by_text('메일 있음 · 연결 확인 필요 · 분류 확인 권장',exact=True).count(),0)
                            self.assertEqual(page.locator('#holds summary').count(),0)
                            self.assertGreater(page.get_by_text('취소 메일 있음 · 환불 확인 필요',exact=True).count(),0)
                            self.assertGreater(page.get_by_text('메일 연결 없음 · 분류 확인 권장',exact=True).count(),0)
                            self.assertEqual(page.get_by_text('확인 권장',exact=True).count(),0)
                            self.assertEqual(page.locator('#questions .review-item[open]').count(),1)
                            self.assertLessEqual(page.locator('#questions .review-item').first.locator('summary').evaluate('el=>el.getBoundingClientRect().height'),96)
                            self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                            page.close()
                    browser.close()
            finally:
                server.shutdown();server.server_close();server.card_store.close();thread.join(timeout=3);ledger_board.bind_store(None)

    def test_legacy_batch_transaction_link_and_scoped_rule_edit(self):
        from app import Pipeline
        from tests.card_pipeline.fixtures import make_csv,domestic_row
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
            ledger_board.bind_access(None)
            server=ledger_board.serve(port=0,db_path=Path(directory)/'board.sqlite',with_worker=False,seed_demo=False)
            pipe=Pipeline(server.card_store.conn)
            rows=[domestic_row(merchant='Synthetic question '+str(n),amount=100+n,approval='Q'+str(n)) for n in range(25)]
            rows.append(domestic_row(merchant='Synthetic auto classification',amount=200,approval='AUTO'))
            batch=pipe.receive(make_csv(rows),'synthetic-existing.csv')['batch_id']
            auto=next(r for r in pipe.get_batch(batch)['rows'] if r['merchant']=='Synthetic auto classification')
            pipe.save_rule({'rule_id':'synthetic-scope','conditions':{'merchant_normalized':'Synthetic auto classification'},
                            'optional':{'source_hash':auto['source_hash'],'amount_range':{'min':200,'max':200}},
                            'effects':{'item':'소모품'}})
            pipe.classify_batch(batch)
            originals = server.card_store.conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions ORDER BY transaction_id').fetchall()
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            errors=[]
            try:
                with sync_playwright() as browser_api:
                    browser=browser_api.chromium.launch(headless=True)
                    page=browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    base=f'http://127.0.0.1:{server.server_address[1]}'
                    page.goto(base+'/import?batch='+batch+'&transaction='+auto['transaction_id'])
                    page.locator('#questions form[data-index]').first.wait_for()
                    page.locator('#questions h2').filter(has_text='Synthetic auto classification').wait_for()
                    self.assertEqual(page.locator('#questions form[data-index]').first.locator('input[name=item]').input_value(),'소모품')
                    if not page.locator('#expense-tab-rules').is_visible():
                        page.locator('.expense-tools > summary').click()
                    page.locator('#expense-tab-rules').click()
                    page.locator('#rulefilter').fill('Synthetic auto classification')
                    page.locator('[data-rule]').click()
                    page.locator('#ruleform input[name=rule_item]').fill('사무용품')
                    page.get_by_role('button',name='규칙 저장하고 다시 분류').click()
                    page.get_by_text('규칙은 저장되고 분류도 다시 계산됐습니다.',exact=False).wait_for()
                    rule=pipe.list_rules()[0]
                    self.assertEqual(rule['optional'],{'source_hash':auto['source_hash'],'amount_range':{'min':200,'max':200}})
                    self.assertEqual(rule['effects']['item'],'사무용품')
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    self.assertEqual(server.card_store.conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions ORDER BY transaction_id').fetchall(), originals)
                    recorded = server.card_store.conn.execute("SELECT row_id FROM board_rows WHERE row_kind='expense'").fetchall()
                    self.assertEqual({r[0] for r in recorded}, {'card-'+r[0] for r in originals})
                    self.assertEqual(len(recorded),len(originals))
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                server.shutdown();server.server_close();server.card_store.close();thread.join(timeout=3);ledger_board.bind_store(None)
    def test_mobile_full_flow_and_reupload(self):
        from webapp.card_flow import CardFlow
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0,db_path=Path(directory)/'board.sqlite',
                                        with_worker=False,seed_demo=False)
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            errors=[]
            trip = server.card_store.create_trip(starts_on='2026-10-01', ends_on='2026-10-03',
                destination='Synthetic mobile trip', client_request_id='browser-mobile-trip')['tab_id']
            valid_trip = patch.object(CardFlow, 'trip_valid', autospec=True,
                                      side_effect=lambda flow, identity: identity == trip)
            valid_trip.start()
            try:
                with sync_playwright() as browser_api, patch.object(
                        ledger_board, '_participant_owner_request', return_value=True):
                    browser = browser_api.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    base = f'http://127.0.0.1:{server.server_address[1]}'
                    page.goto(base + '/import#newupload')
                    self.assertTrue(page.locator('#card-upload-panel').is_visible())
                    page.locator('#card-upload-files').set_input_files(
                        {'name':'synthetic.csv','mimeType':'text/csv','buffer':CARD})
                    page.get_by_role('button',name='선택한 파일 업로드').click()
                    result_link = page.locator('.card-upload-result-link').first
                    result_link.wait_for()
                    batch = page.evaluate("href => new URL(href, location.href).searchParams.get('batch')",
                                          result_link.get_attribute('href'))
                    state = page.request.get(base + '/api/imports/' + batch).json()
                    transaction = state['rows'][0]['transaction_id']
                    page.goto(base + '/import?batch=' + batch + '&transaction=' + transaction)
                    page.locator('#questions form[data-index]').first.wait_for()
                    self.assertIn('합성상점', page.locator('#questions').inner_text())
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    page.locator('select[name=display_tab_id]').select_option(trip)
                    page.locator('input[name=item]').fill('소모품')
                    page.locator('textarea[name=note]').fill('사무실 소모품입니다')
                    page.locator('input[name=reuse_rule]').check()
                    with page.expect_response('**/decision') as decision:
                        page.get_by_role('button',name='저장하고 자동 반영').click()
                    self.assertEqual(decision.value.status, 200)
                    self.assertEqual(decision.value.json()['ledger_recording']['status'], 'recorded')
                    page.locator('#status').get_by_text('저장했습니다.',exact=True).wait_for()
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)
                    screenshot=Path(directory)/'card-flow-mobile.png'
                    page.screenshot(path=str(screenshot),full_page=True)
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0],1)
                    self.assertEqual(len(server.card_store.list_tab_rows(trip)),1)
                    if not page.locator('#expense-tab-rules').is_visible():
                        page.locator('.expense-tools > summary').click()
                    page.locator('#expense-tab-rules').click()
                    page.locator('#ruleform input[name=merchant]').fill('합성상점')
                    page.locator('#ruleform input[name=rule_item]').fill('사무용품')
                    page.get_by_role('button',name='규칙 저장하고 다시 분류').click()
                    page.get_by_text('규칙은 저장되고 분류도 다시 계산됐습니다.',exact=False).wait_for()
                    self.assertEqual(server.card_store.list_tab_rows(trip)[0]['item'],'소모품')
                    page.goto(base + '/cards/all?panel=upload')
                    page.locator('#card-upload-files').set_input_files(
                        {'name':'synthetic.csv','mimeType':'text/csv','buffer':CARD})
                    page.get_by_role('button',name='선택한 파일 업로드').click()
                    page.locator('.card-upload-result').first.wait_for()
                    page.locator('.card-upload-result[data-state="saved"]').first.wait_for()
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                valid_trip.stop()
                server.shutdown()
                server.server_close()
                server.card_store.close()
                thread.join(timeout=3)
                ledger_board.bind_store(None)


if __name__=='__main__':
    unittest.main()
