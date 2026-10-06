"""새 파일 처리와 기존 장부 화면이 같은 거래를 한 번만 기록하는지 확인한다."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webapp.ledger_store import LedgerStore
from webapp.card_flow import (
    CardFlow, page, batch_catalog, _mail_evidence_from_report, _review_evidence_labels,
)


CARD = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
        'Date,Post Date,Authorization Code,Cancel,Status\n'
        '국민,1234,domestic,purchase,합성상점,37000,,,37000,2026-10-01,2026-10-02,A123,,매입\n').encode()


class CardFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB':'1'})
        self.env.start()
        self.board = LedgerStore(Path(self.tmp.name)/'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)

    def tearDown(self):
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_review_evidence_labels_distinguish_existing_mail_evidence(self):
        row = {
            'merchant':'AGODA', 'classification_source':'inference',
            'classification_state':'classified', 'classification_basis':'추론 배정 · 낮음 · 일정 근거',
            'display_tab_id':'trip-jp', 'trip_id':'trip-jp', 'user_confirmed':0,
        }
        self.assertEqual(
            _review_evidence_labels(row, {'booking_match':True}),
            ['예약 근거 있음', '여행 배정 확인 권장'],
        )

    def test_review_evidence_labels_distinguish_mail_from_card_linkage(self):
        row = {
            'merchant':'TRIP.COM', 'classification_source':'rule',
            'classification_state':'needs_review', 'classification_basis':'예약 근거 확인 필요',
            'display_tab_id':'unclassified', 'trip_id':'', 'user_confirmed':0,
        }
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_uncertain':True}),
            ['메일 있음 · 연결 확인 필요', '분류 확인 권장'],
        )

    def test_review_evidence_labels_separate_cancellation_mail_from_refund_status(self):
        row = {
            'merchant':'TRIP.COM', 'classification_source':'rule',
            'classification_state':'needs_review', 'classification_basis':'취소 정산 확인',
            'display_tab_id':'unclassified', 'trip_id':'', 'user_confirmed':0,
            'review_hold':{'kind':'refund_pending', 'reason':'카드 환불 원행 확인 필요'},
        }
        self.assertEqual(
            _review_evidence_labels(row, {'cancellation_mail':True}),
            ['취소 메일 있음', '환불 확인 필요'],
        )

    def test_review_evidence_labels_do_not_call_unlinked_mail_missing(self):
        row = {
            'merchant':'AGODA', 'classification_source':'inference',
            'classification_state':'needs_review', 'classification_basis':'추론 배정 · 낮음 · 예약 연결 없음',
            'display_tab_id':'unclassified', 'trip_id':'', 'user_confirmed':0,
        }
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_absent':True}),
            ['메일 연결 없음', '분류 확인 권장'],
        )

    def test_review_evidence_labels_do_not_warn_again_after_user_confirmation(self):
        row = {
            'merchant':'AGODA', 'classification_source':'inference',
            'classification_state':'confirmed', 'classification_basis':'추론 배정 · 낮음 · 과거 근거',
            'display_tab_id':'trip-jp', 'trip_id':'trip-jp', 'user_confirmed':1,
        }
        labels = _review_evidence_labels(row, {'booking_match':True})
        self.assertEqual(labels, ['예약 근거 있음'])
        self.assertNotIn('확인 권장', ' · '.join(labels))

    def test_mail_report_mapping_keeps_exact_uncertain_and_unlinked_distinct(self):
        report = {
            'matches':[
                {'source_hash':'exact', 'reservation_status':'confirmed'},
                {'source_hash':'cancelled', 'reservation_status':'cancelled'},
            ],
            'type_only_candidates':[
                {'source_hash':'uncertain'},
                {'source_hash':'exact'},
            ],
            'unmatched_transactions':[
                {'source_hash':'unlinked'},
                {'source_hash':'uncertain'},
            ],
        }
        self.assertEqual(_mail_evidence_from_report(report, {'exact','cancelled','uncertain','unlinked'}), {
            'exact':{'booking_match':True},
            'cancelled':{'cancellation_mail':True},
            'uncertain':{'mail_link_uncertain':True},
            'unlinked':{'mail_link_absent':True},
        })

    def test_review_mail_evidence_reuses_in_memory_cache(self):
        batch = self.flow.pipeline.receive(CARD.replace(b'\xed\x95\xa9\xec\x84\xb1\xec\x83\x81\xec\xa0\x90', b'AGODA'), 'ota.csv')['batch_id']
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        mail_dir = Path(self.tmp.name)/'ota-mail'
        mail_dir.mkdir()
        report = {
            'matches':[{'source_hash':row['source_hash'], 'reservation_status':'confirmed'}],
            'type_only_candidates':[], 'unmatched_transactions':[],
        }
        with patch('app.ota_mail.match_mail', return_value=report) as matcher:
            first = self.flow.review_mail_evidence([row])
            second = self.flow.review_mail_evidence([row])
        self.assertEqual(first, {row['source_hash']:{'booking_match':True}})
        self.assertEqual(second, first)
        self.assertEqual(matcher.call_count, 1)

    def test_overwritten_mail_file_refreshes_cancellation_evidence(self):
        from tests.card_pipeline.test_booking_mail import message
        from tests.card_pipeline.test_ota_refresh import save
        batch=self.flow.pipeline.receive(CARD.replace('합성상점'.encode(),b'AGODA'),'synthetic-mail.csv')['batch_id']
        row=self.flow.pipeline.get_batch(batch)['rows'][0]
        mail_dir=Path(self.tmp.name)/'ota-mail'
        mail_dir.mkdir()
        payment=message('예약번호: 1738864710\n총 금액 KRW 37,000\n체크인: 2026-10-05\n체크아웃: 2026-10-06',
                        subject='Payment confirmation',domain='agoda.com',sent='2026-10-01')
        save(mail_dir,[payment])
        self.assertEqual(self.flow.review_mail_evidence([row]),{row['source_hash']:{'booking_match':True}})
        directory_stamp=mail_dir.stat()
        save(mail_dir,[payment,message('예약번호: 1738864710',subject='취소됨 - 합성 예약',
            domain='agoda.com',identity='synthetic-cancel',sent='2026-10-02')])
        os.utime(mail_dir,ns=(directory_stamp.st_atime_ns,directory_stamp.st_mtime_ns))
        self.assertEqual(self.flow.review_mail_evidence([row]),{row['source_hash']:{'cancellation_mail':True}})

    def test_new_flow_reuses_the_existing_pipeline_without_schema_work(self):
        queries=[]
        self.board.conn.set_trace_callback(queries.append)
        try:
            another=CardFlow(self.board)
            self.assertIs(another.pipeline,self.flow.pipeline)
            self.assertFalse(any('CREATE TABLE' in statement.upper() for statement in queries))
        finally:
            self.board.conn.set_trace_callback(None)

    def test_classification_and_review_share_evidence_without_repeated_mail_parsing(self):
        from app.ota_mail import match_mail
        from tests.card_pipeline.test_booking_mail import message
        from tests.card_pipeline.test_ota_refresh import save
        batch=self.flow.pipeline.receive(CARD.replace('합성상점'.encode(),b'AGODA'),'synthetic-cache.csv')['batch_id']
        row=self.flow.pipeline.get_batch(batch)['rows'][0]
        mail_dir=Path(self.tmp.name)/'ota-mail'
        mail_dir.mkdir()
        save(mail_dir,[message('예약번호: 1738864710\n총 금액 KRW 37,000',
            subject='Payment confirmation',domain='agoda.com',sent='2026-10-01')])
        with patch('app.ota_mail.match_mail',wraps=match_mail) as matcher:
            self.flow.review_mail_evidence([row])
            self.flow.classify(batch)
            self.flow.review_mail_evidence(self.flow.pipeline.get_batch(batch)['rows'])
        self.assertEqual(matcher.call_count,1)
        self.assertEqual(self.flow.pipeline.get_batch(batch)['rows'][0]['item'],'숙박비')

    def decide(self):
        batch = self.flow.pipeline.receive(CARD,'synthetic.csv')['batch_id']
        self.flow.pipeline.classify_batch(batch)
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        self.flow.pipeline.save_decision(row['transaction_id'],row['revision'],item='소모품',
            description='사무실 소모품',display_tab_id='unclassified',
            tab_validator=self.flow.tab_valid,request_id='answer')
        return batch

    def test_commit_projects_once_and_keeps_original(self):
        batch = self.decide()
        preview = self.flow.state(batch)['preview']
        first = self.flow.pipeline.commit(batch,preview['digest'],'commit',projection=self.flow.project,
                                          tab_validator=self.flow.tab_valid)
        self.assertEqual(first,self.flow.pipeline.commit(batch,preview['digest'],'commit',
                                                         projection=self.flow.project,tab_validator=self.flow.tab_valid))
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0],1)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)
        row = self.board.conn.execute('SELECT row_id FROM board_rows').fetchone()[0]
        self.assertEqual(self.board.get_row(row)['amount_krw'],37000)
        self.assertEqual(len(self.board.list_tab_rows(None)),1)
        self.flow.pipeline.receive(CARD,'renamed.csv')
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)

    def test_projection_failure_rolls_back_then_retry(self):
        batch = self.decide()
        preview = self.flow.state(batch)['preview']
        def fail(entry):
            self.flow.project(entry)
            raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):
            self.flow.pipeline.commit(batch,preview['digest'],'commit',projection=fail,
                                      tab_validator=self.flow.tab_valid)
        for table in ('ledger_entries','board_rows','board_revisions'):
            self.assertEqual(self.board.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],0)
        self.flow.pipeline.commit(batch,preview['digest'],'commit',projection=self.flow.project,
                                  tab_validator=self.flow.tab_valid)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)

    def test_review_tab_is_not_authority(self):
        self.assertFalse(self.flow.trip_valid('unknown'))
        self.assertTrue(self.flow.tab_valid('unclassified'))
        self.assertFalse(self.flow.tab_valid('unknown'))

    def test_batch_names_come_from_the_card_data_and_keep_the_original_file(self):
        batch = self.flow.pipeline.receive(CARD, 'H.xlsx')['batch_id']
        original = self.board.conn.execute('SELECT filename,content_bytes,content_sha256 FROM import_batches').fetchall()
        catalog = batch_catalog(self.board)
        self.assertEqual(catalog[0]['display_name'], '국민카드 사용내역')
        self.assertEqual(catalog[0]['filename'], 'H.xlsx')
        self.assertEqual(catalog[0]['period_start'], '2026-10-01')
        self.assertEqual(catalog[0]['period_end'], '2026-10-01')
        self.assertEqual(catalog[0]['questions'], 1)
        state = self.flow.state(batch)
        self.assertEqual(state['summary']['display_name'], catalog[0]['display_name'])
        self.assertEqual(original, self.board.conn.execute('SELECT filename,content_bytes,content_sha256 FROM import_batches').fetchall())
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 0)

    def test_batch_catalog_prioritizes_questions_and_omits_completed_old_periods(self):
        confirmed = self.decide()
        unresolved = self.flow.pipeline.receive(CARD.replace(b'A123', b'Q456'), 'E.xlsx')['batch_id']
        self.flow.pipeline.receive(CARD.replace(b'2026-', b'2025-').replace(b'A123', b'OLD'), 'old.xlsx')
        with patch.dict(os.environ, {'WEBLEDGER_REVIEW_FROM':'2026-04-01'}):
            catalog = batch_catalog(self.board)
        self.assertEqual([r['batch_id'] for r in catalog], [unresolved, confirmed])
        self.assertEqual([r['questions'] for r in catalog], [1, 0])
        self.assertEqual([r['rows'] for r in catalog], [1, 1])

    def test_home_counts_the_same_transaction_in_two_files_only_once(self):
        from webapp.card_flow import home_page
        from webapp import ledger_board
        self.flow.pipeline.receive(CARD, 'F.xlsx')
        second = CARD + CARD.splitlines(keepends=True)[1].replace(b'A123', b'NEXT')
        self.flow.pipeline.receive(second, 'H.xlsx')
        self.assertEqual(sum(b['rows'] for b in batch_catalog(self.board)), 3)
        previous = ledger_board._STORE
        try:
            ledger_board.bind_store(self.board)
            html = home_page(self.board)
        finally:
            ledger_board.bind_store(previous)
        self.assertIn("카드 <b>2</b> · 확인 필요 <b>2</b> · 장부 반영 대기 <b>0</b> · 장부 <b>0</b>", html)
        self.assertIn("class='home-review btn primary' href='/import'>카드 검토 2건</a>", html)
        self.assertIn("class='home-secondary'", html)
        self.assertIn("href='/import'>새 카드 가져오기</a>", html)
        self.assertIn("href='/export'>XLSX 출력</a>", html)
        self.assertNotIn("class='btn primary' href='/export'>XLSX 출력</a>", html)
        self.assertNotIn("id='global-state'", html)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 0)

    def test_preview_and_choices_revalidate_a_changed_schedule_on_the_next_request(self):
        trip=self.board.create_trip(starts_on='2026-04-08',ends_on='2026-04-12',
                                    destination='합성 여행',client_request_id='synthetic-trip')['tab_id']
        batch=self.flow.pipeline.receive(CARD,'synthetic.csv')['batch_id']
        row=self.flow.pipeline.get_batch(batch)['rows'][0]
        self.flow.pipeline.save_rule({'conditions':{'merchant_normalized':row['merchant']},
                                     'optional':{'source_hash':row['source_hash'],'inferred_assignment':{
                                         'trip_id':trip,'confidence':'중간','basis':'합성 예약 지역과 일정'}},
                                     'effects':{'item':'숙박비'}})
        self.flow.trip_valid=lambda identity:identity==trip
        self.flow.classify(batch)
        first=self.flow.state(batch)
        self.assertFalse(first['preview']['rows'][0].get('blocked'))
        self.assertTrue(first['trips'][0]['available'])
        self.flow.trip_valid=lambda identity:False
        second=self.flow.state(batch)
        self.assertTrue(second['preview']['rows'][0]['blocked'])
        self.assertFalse(second['trips'][0]['available'])
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],0)

    def pending_fixture(self):
        trip = self.board.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                                      destination='합성 여행', client_request_id='pending-trip')['tab_id']
        batch = self.flow.pipeline.receive(CARD, 'pending.csv')['batch_id']
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        self.board.conn.execute("UPDATE transactions SET classification_state='classified', "
                                "item='숙박비', trip_id=?, display_tab_id=? WHERE transaction_id=?",
                                (trip, trip, row['transaction_id']))
        self.board.conn.commit()
        return trip, batch, row

    def pending_home(self):
        from webapp.card_flow import home_page
        from webapp import ledger_board
        previous = ledger_board._STORE
        try:
            ledger_board.bind_store(self.board)
            return home_page(self.board)
        finally:
            ledger_board.bind_store(previous)

    def test_home_pending_reuses_valid_authority_once_across_batches(self):
        trip, batch, row = self.pending_fixture()
        self.flow.pipeline.receive(CARD + CARD.splitlines(keepends=True)[1].replace(b'A123', b'NEXT'),
                                   'second.csv')
        with patch.object(CardFlow, 'trip_valid', return_value=True) as authority:
            self.assertIn('장부 반영 대기 <b>1</b>', self.pending_home())
            authority.assert_called_once_with(trip)
            preview = self.flow.state(batch)['preview']
        self.assertFalse(preview['rows'][0].get('blocked'))

    def test_home_pending_excludes_already_booked(self):
        trip, batch, row = self.pending_fixture()
        with patch.object(CardFlow, 'trip_valid', return_value=True):
            preview = self.flow.state(batch)['preview']
            self.flow.pipeline.commit(batch, preview['digest'], 'synthetic-pending-commit',
                                      trip_validator=self.flow.trip_valid, tab_validator=self.flow.tab_valid)
            self.assertIn('장부 반영 대기 <b>0</b>', self.pending_home())

    def test_home_pending_excludes_hold_and_preview_blockers(self):
        trip, batch, row = self.pending_fixture()
        cases = ('hold', 'invalid-trip', 'invalid-tab', 'needs-review', 'parse-error',
                 'conflict', 'preserved', 'review-period')
        for case in cases:
            with self.subTest(case=case):
                self.board.conn.execute('DELETE FROM transaction_review_holds')
                self.board.conn.execute("UPDATE transactions SET classification_state='classified', "
                                        "parse_error='', conflict_reason='', trip_id=?, display_tab_id=?",
                                        (trip, trip))
                if case == 'hold':
                    self.board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                                            (row['transaction_id'], row['source_hash'], 'user_hold', '합성 보류'))
                elif case == 'invalid-tab':
                    self.board.conn.execute("UPDATE transactions SET display_tab_id='unknown'")
                elif case == 'needs-review':
                    self.board.conn.execute("UPDATE transactions SET classification_state='needs_review'")
                elif case == 'parse-error':
                    self.board.conn.execute("UPDATE transactions SET parse_error='synthetic error'")
                elif case == 'conflict':
                    self.board.conn.execute("UPDATE transactions SET conflict_reason='synthetic conflict'")
                elif case == 'preserved':
                    self.board.conn.execute("UPDATE transactions SET classification_state='preserved'")
                self.board.conn.commit()
                with patch.object(CardFlow, 'trip_valid', return_value=case != 'invalid-trip'), \
                        patch.dict(os.environ, {'WEBLEDGER_REVIEW_FROM':
                                               '2026-10-02' if case == 'review-period' else ''}):
                    self.assertIn('장부 반영 대기 <b>0</b>', self.pending_home())

    def test_home_pending_failure_is_unknown_instead_of_zero(self):
        import sqlite3
        from app.db import StoreError, CODE_NOT_FOUND
        self.pending_fixture()
        for target, error in (('app.ledger.preview', sqlite3.OperationalError('synthetic read failure')),
                              ('app.ledger.preview', StoreError(CODE_NOT_FOUND, 'synthetic missing batch')),
                              ('webapp.card_flow.CardFlow.trip_valid', OSError('synthetic proof failure'))):
            with self.subTest(target=target, error=type(error).__name__), patch(target, side_effect=error):
                html = self.pending_home()
                self.assertIn('장부 반영 대기 <b>-</b>', html)
                self.assertNotIn('장부 반영 대기 <b>0</b>', html)

    def test_mobile_page_has_answer_preview_and_no_cell_column(self):
        html = page('synthetic')
        self.assertIn('width=device-width',html)
        self.assertIn('내 답변·수정 이유',html)
        self.assertIn('장부 미리보기',html)
        self.assertNotIn('<th>칸</th>',html)


class WorkbookScheduleRefreshTests(unittest.TestCase):
    def fixture(self):
        import hashlib
        import json
        from types import SimpleNamespace
        from openpyxl import Workbook
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        original = root/'original.xlsx'
        current = root/'current.xlsx'
        title = '2026년 4월 매출 확인자료_sample_0404_0407'
        book = Workbook()
        book.active.title = '0404_sample'
        book.active['C2'] = title
        book.save(original)
        book.active['E5'] = 123
        book.save(current)
        book.close()
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        record = dict(trip_code='0404_sample', event_year=2026,
                      starts_on='2026-04-04', ends_on='2026-04-07', region='sample',
                      authority_kind='explicit_trip_registry', authority_status='authoritative',
                      source_locator=str(original)+'#0404_sample!C2', source_sha256=digest,
                      end_semantics='inclusive_last_service_date')
        authority = root/'authority.json'
        authority.write_text(json.dumps(dict(schema_version='trip-schedule-authority-v3',
                                             records=[record])), encoding='utf-8')
        trip = dict(display_key='0404_sample', event_year=2026, starts_on=record['starts_on'],
                    ends_on=record['ends_on'], source_sha256=digest, deleted=0, archived=0)
        flow = CardFlow.__new__(CardFlow)
        flow.board = SimpleNamespace(get_trip=lambda identity:trip)
        service = SimpleNamespace(manifest=dict(snapshot_path=str(current),
                           snapshot_sha256=hashlib.sha256(current.read_bytes()).hexdigest()))
        environment = patch.dict(os.environ, {'WEBLEDGER_TRIP_AUTHORITY':str(authority)})
        environment.start()
        self.addCleanup(environment.stop)
        binding = patch('webapp.real_review.active_service', return_value=service)
        binding.start()
        self.addCleanup(binding.stop)
        return flow, original, current, service, trip

    def test_unrelated_transaction_change_preserves_verified_schedule(self):
        flow, _, _, _, _ = self.fixture()
        self.assertTrue(flow.trip_valid('synthetic-trip'))

    def test_schedule_changes_remain_blocked(self):
        import hashlib
        from openpyxl import load_workbook
        for change in ('changed-period', 'changed-year', 'missing-title', 'moved-title', 'ambiguous-title', 'formula'):
            with self.subTest(change=change):
                flow, _, current, service, _ = self.fixture()
                self.assertTrue(flow.trip_valid('synthetic-trip'))
                book = load_workbook(current)
                if change == 'changed-period':
                    book.active['C2'] = '2026년 4월 매출 확인자료_sample_0404_0408'
                elif change == 'changed-year':
                    book.active['C2'] = '2027년 4월 매출 확인자료_sample_0404_0407'
                elif change == 'missing-title':
                    book.active['C2'] = None
                elif change == 'moved-title':
                    book.active['D2'] = book.active['C2'].value
                    book.active['C2'] = None
                elif change == 'ambiguous-title':
                    book.active['D2'] = '2026년 4월 매출 확인자료_sample_0404_0408'
                else:
                    book.active['C2'] = '="2026년 4월 매출 확인자료_sample_0404_0407"'
                book.save(current)
                book.close()
                service.manifest['snapshot_sha256'] = hashlib.sha256(current.read_bytes()).hexdigest()
                self.assertFalse(flow.trip_valid('synthetic-trip'))

    def test_changed_proof_or_binding_remains_blocked(self):
        for change in ('original-proof', 'current-proof', 'board-period', 'board-digest'):
            with self.subTest(change=change):
                flow, original, current, _, trip = self.fixture()
                self.assertTrue(flow.trip_valid('synthetic-trip'))
                if change == 'original-proof':
                    original.write_bytes(b'synthetic tampering')
                elif change == 'current-proof':
                    current.write_bytes(b'synthetic tampering')
                elif change == 'board-period':
                    trip['ends_on'] = '2026-04-08'
                else:
                    trip['source_sha256'] = '0'*64
                self.assertFalse(flow.trip_valid('synthetic-trip'))


if __name__ == '__main__':
    unittest.main()
