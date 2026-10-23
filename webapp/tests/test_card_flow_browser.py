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


class CardFlowBrowserTests(unittest.TestCase):
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
                fields[4], fields[5], fields[8] = 'TRIP.COM', '30000', '30000'
                batch = flow.pipeline.receive(header + (','.join(fields)+'\n').encode(),
                                              'ota-inferred-browser.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                candidate_card = ota_card(row['transaction_id'], source_hash=row['source_hash'],
                    merchant='TRIP.COM', merchant_normalized='trip.com', approval_date='2026-08-01',
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
                        page.goto(base_url + '/import')
                        state = page.request.get(base_url + '/api/imports/' + batch).json()
                        page.get_by_text('정리할 지출이 없습니다.', exact=True).wait_for()
                        prepared = state['preview']['rows'][0]
                        self.assertEqual(prepared['ota_link_status'], 'INFERRED')
                        self.assertEqual(prepared['internal_expense_status'], 'SAVED')
                        self.assertEqual(prepared['display_tab_id'], trip)
                        self.assertEqual(prepared.get('booking_ref') or '', '')
                        self.assertIn('정리할 지출이 없습니다.', page.locator('body').inner_text())
                        saved = json.loads(server.card_store.conn.execute(
                            'SELECT payload_json FROM board_rows WHERE row_id=?',
                            ('card-' + row['transaction_id'],)).fetchone()[0])
                        self.assertEqual(saved['reservation_no'], '')
                        browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_api_ready_matches_visible_recordable_count_before_and_after_booking(self):
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
                batch = flow.pipeline.receive(CARD, 'ready-synthetic.csv')['batch_id']
                row = flow.pipeline.get_batch(batch)['rows'][0]
                flow.pipeline.save_decision(row['transaction_id'], row['revision'],
                                            item='소모품비', display_tab_id='unclassified',
                                            tab_validator=flow.tab_valid, request_id='ready-confirm')
                with sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page()
                    base = f'http://127.0.0.1:{server.server_address[1]}'
                    for booked in (False, True):
                        for width, height in ((390,844), (1440,900)):
                            page.set_viewport_size({'width':width, 'height':height})
                            page.goto(base + '/import')
                            state = page.request.get(base + '/api/imports/' + batch).json()
                            count = state['preview']['ready']
                            page.get_by_role('button', name=f'미리본 {count}건을 장부에 기록').wait_for()
                            visible = page.locator('#preview tbody tr').count()
                            self.assertEqual(count, visible)
                            self.assertEqual(bool(visible), not booked)
                            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                        if not booked:
                            page.locator('#commit').click()
                            page.get_by_text('장부 기록 결과를 저장했습니다.', exact=False).wait_for()
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close()
                thread.join(timeout=3); ledger_board.bind_store(previous)

    def test_verified_ota_metadata_is_visible_before_http_commit(self):
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
                batch = flow.pipeline.receive(make_csv([domestic_row(merchant='TRIP.COM',
                    amount=123000, approval='87654321', date='2026-05-01')]), 'synthetic-ota.csv')['batch_id']
                flow.classify(batch)
                with sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page()
                    for width, height in ((390,844), (1440,900)):
                        page.set_viewport_size({'width':width, 'height':height})
                        page.goto(f'http://127.0.0.1:{server.server_address[1]}/import')
                        page.locator('#preview').get_by_text('OTA 예약 근거', exact=False).wait_for()
                        text = page.locator('#preview').inner_text()
                        self.assertIn('1111111111111111', text)
                        self.assertIn('2026-05-22~2026-05-23', text)
                        self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                    page.locator('#commit').click()
                    page.get_by_text('장부 기록 결과를 저장했습니다.', exact=False).wait_for()
                    row = json.loads(server.card_store.conn.execute(
                        'SELECT payload_json FROM board_rows').fetchone()[0])
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

    def test_home_shows_saved_work_and_card_names_without_uploading_or_booking(self):
        from app import Pipeline
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory)/'board.sqlite', with_worker=False, seed_demo=False)
            pipe = Pipeline(server.card_store.conn)
            batch = pipe.receive(CARD, 'H.xlsx')['batch_id']
            original = pipe.get_batch(batch)['summary']['content_sha256']
            for index, (start, end, destination, display_key) in enumerate((
                    ('2026-10-10', '2026-10-13', '도쿠시마', '1010 도쿠시마'),
                    ('2026-10-15', '2026-10-20', '오제', '1015 오제'),
                    ('2026-10-20', '2026-10-24', '알펜루트', '1020 알펜루트'),
                    ('2026-10-26', '2026-10-30', '가루이자와', '1026 가루이자와'))):
                server.card_store.create_trip(
                    starts_on=start, ends_on=end, destination=destination,
                    display_key=display_key, client_request_id=f'home-mobile-{index}')
            registered = {trip['tab_id']:{'departure_status':'scheduled'}
                          for trip in server.card_store.list_trips()}
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            errors = []
            try:
                with sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror', lambda e:errors.append(str(e)))
                    with patch('app.reserve_trips.registrations', return_value=registered):
                        response = page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    self.assertEqual(response.status, 200)
                    self.assertTrue(page.url.endswith('/'))
                    self.assertTrue(page.get_by_role('heading', name='장부 현황', exact=False).is_visible())
                    self.assertEqual(page.locator('input[type=file]').count(), 0)
                    self.assertNotIn('H.xlsx', page.locator('body').inner_text())
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    self.assertTrue(page.get_by_role('link', name='카드 검토 1건', exact=True).is_visible())
                    self.assertTrue(page.locator('.home-secondary').is_visible())
                    self.assertEqual(page.get_by_role('link', name='XLSX 출력', exact=True).count(), 0)
                    primary_bg = page.locator('.home-review').evaluate(
                        "el => getComputedStyle(el).backgroundColor")
                    secondary_bg = page.locator('.home-secondary .btn').first.evaluate(
                        "el => getComputedStyle(el).backgroundColor")
                    self.assertNotEqual(primary_bg, secondary_bg)
                    visible_trips = page.locator('.home-trip').evaluate_all(
                        "els => els.filter(el => { const r=el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }).length")
                    self.assertGreaterEqual(visible_trips, 3)
                    page.get_by_role('link', name='카드 검토 1건', exact=True).click()
                    page.locator('#saved-materials summary').click()
                    page.locator('[data-batch]').wait_for()
                    self.assertIn('국민카드 사용내역', page.locator('[data-batch]').inner_text())
                    self.assertNotIn('H.xlsx', page.locator('[data-batch]').inner_text())
                    self.assertFalse(page.locator('#newupload').evaluate('(el) => el.open'))
                    page.locator('#summary').get_by_role('heading', name='국민카드 사용내역').wait_for()
                    self.assertNotIn('H.xlsx', page.locator('#summary').inner_text())
                    page.locator('#summary summary').click()
                    self.assertIn('H.xlsx', page.locator('#summary').inner_text())
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    self.assertEqual(pipe.get_batch(batch)['summary']['content_sha256'], original)
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 0)
                    self.assertEqual(errors, [])
                    page.get_by_role('button', name='전체 메뉴 열기').click()
                    page.locator('#nav').get_by_role('link', name='여행 장부', exact=True).click()
                    self.assertIn('/board', page.url)
                    self.assertNotIn('/import', page.url)
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close(); thread.join(timeout=3); ledger_board.bind_store(None)

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
                with sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror', lambda e:errors.append(str(e)))
                    base = f'http://127.0.0.1:{server.server_address[1]}'
                    page.goto(base + '/')
                    page.get_by_role('link', name='새 카드 가져오기', exact=True).click()
                    self.assertIn('/import#newupload', page.url)
                    page.locator('#newupload').wait_for()
                    self.assertTrue(page.locator('#newupload').evaluate('(el) => el.open'))
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); server.card_store.close(); thread.join(timeout=3); ledger_board.bind_store(None)

    def test_low_confidence_assignment_is_editable_and_does_not_require_approval_to_preview(self):
        from app import Pipeline
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
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
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/import')
                    page.get_by_text('비용 항목 확인 권장',exact=True).wait_for()
                    self.assertTrue(page.get_by_role('button',name='미리본 1건을 장부에 기록').is_enabled())
                    self.assertEqual(page.locator('#preview').get_by_text('추론 배정',exact=True).count(),1)
                    page.locator('#preview summary').click()
                    self.assertIn('공통 경비 추론',page.locator('#preview details').inner_text())
                    page.locator('form[data-index] input[name=item]').fill('사무용품비')
                    page.get_by_role('button',name='답변 저장하고 다시 분류').click()
                    page.wait_for_function("document.querySelector('#preview').innerText.includes('사무용품비')")
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
                            page.goto(f'http://127.0.0.1:{server.server_address[1]}/import')
                            page.get_by_text('예약 근거 있음 · 여행 배정 확인 권장',exact=True).first.wait_for()
                            self.assertGreater(page.get_by_text('예약 근거 있음 · 여행 배정 확인 권장',exact=True).count(),0)
                            self.assertGreater(page.get_by_text('메일 있음 · 연결 확인 필요 · 분류 확인 권장',exact=True).count(),0)
                            page.locator('#holds summary').click()
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

    def test_existing_batch_pages_and_scoped_rule_edit(self):
        from app import Pipeline
        from tests.card_pipeline.fixtures import make_csv,domestic_row
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
            ledger_board.bind_access(None)
            server=ledger_board.serve(port=0,db_path=Path(directory)/'board.sqlite',with_worker=False,seed_demo=False)
            pipe=Pipeline(server.card_store.conn)
            rows=[domestic_row(merchant='합성 질문 '+str(n),amount=100+n,approval='Q'+str(n)) for n in range(25)]
            rows.append(domestic_row(merchant='합성 자동분류',amount=200,approval='AUTO'))
            batch=pipe.receive(make_csv(rows),'synthetic-existing.csv')['batch_id']
            auto=next(r for r in pipe.get_batch(batch)['rows'] if r['merchant']=='합성 자동분류')
            pipe.save_rule({'rule_id':'synthetic-scope','conditions':{'merchant_normalized':'합성 자동분류'},
                            'optional':{'source_hash':auto['source_hash'],'amount_range':{'min':200,'max':200}},
                            'effects':{'item':'소모품'}})
            pipe.classify_batch(batch)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            errors=[]
            try:
                with sync_playwright() as browser_api:
                    browser=browser_api.chromium.launch(headless=True)
                    page=browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/import')
                    page.get_by_role('button',name='다음 20건').wait_for()
                    self.assertEqual(page.locator('form[data-index]').count(),20)
                    questions = page.locator('#questions .review-item')
                    self.assertEqual(questions.count(), 20)
                    self.assertEqual(page.locator('#questions .review-item[open]').count(), 1)
                    second = questions.nth(1)
                    self.assertFalse(second.evaluate('el => el.open'))
                    second.locator('summary').click()
                    field = second.locator('input[name=item]')
                    self.assertTrue(field.is_visible())
                    original_item = field.input_value()
                    field.fill('합성 펼침 입력')
                    second.locator('summary').click()
                    second.locator('summary').click()
                    self.assertEqual(field.input_value(), '합성 펼침 입력')
                    field.fill(original_item)
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    page.get_by_role('button',name='다음 20건').click()
                    self.assertEqual(page.locator('form[data-index]').count(),5)
                    self.assertEqual(page.locator('#questions .review-item[open]').count(), 1)
                    page.get_by_role('button',name='이전 20건').click()
                    self.assertEqual(page.locator('form[data-index]').count(),20)
                    page.get_by_role('button',name='다음 20건').click()
                    self.assertEqual(page.locator('form[data-index]').count(),5)
                    page.locator('[data-edit]').click()
                    page.get_by_role('heading',name='수정 · 합성 자동분류').wait_for()
                    self.assertEqual(page.locator('form[data-index]').first.locator('input[name=item]').input_value(),'소모품')
                    page.locator('#rules summary').click()
                    page.locator('#rulefilter').fill('자동분류')
                    page.locator('[data-rule]').click()
                    page.locator('#ruleform input[name=rule_item]').fill('사무용품')
                    page.get_by_role('button',name='규칙 저장하고 다시 분류').click()
                    page.get_by_text('규칙을 저장하고 분류에 적용했습니다.',exact=False).wait_for()
                    rule=pipe.list_rules()[0]
                    self.assertEqual(rule['optional'],{'source_hash':auto['source_hash'],'amount_range':{'min':200,'max':200}})
                    self.assertEqual(rule['effects']['item'],'사무용품')
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],0)
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                server.shutdown();server.server_close();server.card_store.close();thread.join(timeout=3);ledger_board.bind_store(None)

    def test_mobile_full_flow_and_reupload(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1'}):
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0,db_path=Path(directory)/'board.sqlite',
                                        with_worker=False,seed_demo=False)
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            errors=[]
            try:
                with sync_playwright() as browser_api:
                    browser = browser_api.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':390,'height':844})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/import')
                    page.locator('#file').set_input_files({'name':'synthetic.csv','mimeType':'text/csv','buffer':CARD})
                    page.get_by_role('button',name='업로드하고 분류').click()
                    page.get_by_role('heading',name='합성상점').wait_for()
                    self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    page.locator('input[name=item]').fill('소모품')
                    page.locator('textarea[name=note]').fill('사무실 소모품입니다')
                    page.locator('input[name=reuse_rule]').check()
                    page.get_by_role('button',name='답변 저장하고 다시 분류').click()
                    page.get_by_role('button',name='미리본 1건을 장부에 기록').wait_for()
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],0)
                    screenshot=Path('C:/AX/cost/.local-archive/lightweight-20261003/card-flow-mobile.png')
                    page.screenshot(path=str(screenshot),full_page=True)
                    page.get_by_role('button',name='미리본 1건을 장부에 기록').click()
                    page.get_by_text('장부 기록 결과를 저장했습니다.',exact=False).wait_for()
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)
                    self.assertEqual(len(server.card_store.list_tab_rows(None)),1)
                    page.locator('#rules summary').click()
                    page.locator('#ruleform input[name=merchant]').fill('합성상점')
                    page.locator('#ruleform input[name=rule_item]').fill('사무용품')
                    page.get_by_role('button',name='규칙 저장하고 다시 분류').click()
                    page.get_by_text('규칙을 저장하고 분류에 적용했습니다.',exact=False).wait_for()
                    self.assertEqual(server.card_store.list_tab_rows(None)[0]['item'],'소모품')
                    page.get_by_role('button',name='업로드하고 분류').click()
                    page.get_by_text('분류가 끝났습니다.',exact=True).wait_for()
                    self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                server.card_store.close()
                thread.join(timeout=3)
                ledger_board.bind_store(None)


if __name__=='__main__':
    unittest.main()
