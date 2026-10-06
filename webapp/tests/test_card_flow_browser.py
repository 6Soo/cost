"""모바일 화면에서 업로드·답변·미리보기·기록을 실제 HTTP로 검증한다."""
import os
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from webapp import ledger_board
from webapp.tests.test_card_flow import CARD


class CardFlowBrowserTests(unittest.TestCase):
    def test_home_pending_number_and_unknown_at_mobile_and_desktop_widths(self):
        from webapp.card_flow import CardFlow
        import sqlite3
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
                        for unknown in (False, True):
                            failure = (patch('app.ledger.preview', side_effect=sqlite3.OperationalError('synthetic'))
                                       if unknown else nullcontext())
                            with failure:
                                self.assertEqual(page.goto(f'http://127.0.0.1:{server.server_address[1]}/').status, 200)
                            page.evaluate('document.fonts.ready')
                            self.assertIn('장부 반영 대기 ' + ('-' if unknown else '1'),
                                          page.locator('.home-status').inner_text())
                            self.assertEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                            self.assertTrue(page.locator('.home-review.primary').is_visible())
                            visible = page.locator('.home-trip').evaluate_all(
                                'els => els.filter(el => el.getBoundingClientRect().bottom <= innerHeight).length')
                            self.assertGreaterEqual(visible, 5)
                            artifact = Path('.local-archive/pending-authority-verification')
                            artifact.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(artifact/f'home-{width}-{"unknown" if unknown else "ready"}.png'))
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
                    self.assertFalse(page.get_by_role('link', name='XLSX 출력', exact=True).evaluate(
                        "el => el.classList.contains('primary')"))
                    primary_bg = page.locator('.home-review').evaluate(
                        "el => getComputedStyle(el).backgroundColor")
                    secondary_bg = page.locator('.home-secondary .btn').first.evaluate(
                        "el => getComputedStyle(el).backgroundColor")
                    self.assertNotEqual(primary_bg, secondary_bg)
                    visible_trips = page.locator('.home-trip').evaluate_all(
                        "els => els.filter(el => { const r=el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }).length")
                    self.assertGreaterEqual(visible_trips, 3)
                    page.get_by_role('link', name='카드 검토 1건', exact=True).click()
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
                    page.locator('nav').get_by_role('link', name='장부', exact=True).click()
                    self.assertIn('/board', page.url)
                    self.assertNotIn('/import', page.url)
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
                    self.assertTrue(actual['user_confirmed'])
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
                'counts':{'classified':3, 'needs_review':2, 'confirmed':1},
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
                    'user_confirmed':0, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_evidence_labels':['예약 근거 있음','여행 배정 확인 권장'],
                },
                {
                    'transaction_id':'mail-unlinked', 'revision':1, 'merchant':'TRIP.COM',
                    'approval_date':'2026-07-12', 'posting_date':'2026-07-12', 'amount_krw':64814,
                    'classification_state':'needs_review', 'classification_source':'rule',
                    'classification_basis':'예약 연결 확인 필요', 'item':'숙박비',
                    'display_tab_id':'unclassified', 'trip_id':'', 'description':'', 'note':'',
                    'user_confirmed':0, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_evidence_labels':['메일 있음 · 연결 확인 필요','분류 확인 권장'],
                },
                {
                    'transaction_id':'cancel-refund', 'revision':1, 'merchant':'TRIP.COM',
                    'approval_date':'2026-04-22', 'posting_date':'2026-04-22', 'amount_krw':-337406,
                    'classification_state':'needs_review', 'classification_source':'rule',
                    'classification_basis':'취소 정산 확인', 'item':'숙박비',
                    'display_tab_id':'unclassified', 'trip_id':'', 'description':'', 'note':'',
                    'user_confirmed':0, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_hold':{'kind':'refund_pending','reason':'카드 환불 원행 확인 필요'},
                    'review_evidence_labels':['취소 메일 있음','환불 확인 필요'],
                },
                {
                    'transaction_id':'no-link', 'revision':1, 'merchant':'AGODA',
                    'approval_date':'2026-07-12', 'posting_date':'2026-07-12', 'amount_krw':273560,
                    'classification_state':'needs_review', 'classification_source':'inference',
                    'classification_basis':'추론 배정 · 낮음 · 예약 연결 없음', 'item':'',
                    'display_tab_id':'unclassified', 'trip_id':'', 'description':'', 'note':'',
                    'user_confirmed':0, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
                    'review_evidence_labels':['메일 연결 없음','분류 확인 권장'],
                },
                {
                    'transaction_id':'confirmed', 'revision':1, 'merchant':'AGODA',
                    'approval_date':'2026-07-13', 'posting_date':'2026-07-13', 'amount_krw':100000,
                    'classification_state':'confirmed', 'classification_source':'inference',
                    'classification_basis':'사용자 확정', 'item':'숙박비',
                    'display_tab_id':'trip-jp', 'trip_id':'trip-jp', 'description':'', 'note':'',
                    'user_confirmed':1, 'duplicate_of':'', 'conflict_reason':'', 'parse_error':'',
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
