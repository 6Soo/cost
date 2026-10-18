"""새 파일 처리와 기존 장부 화면이 같은 거래를 한 번만 기록하는지 확인한다."""
import json
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

# 같은 발급사·카드·승인번호·승인일, 부호만 반대인 결제와 취소. 실제로는 서로 다른 두 거래다.
PAIR_HEADER = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
               'Date,Post Date,Authorization Code,Cancel,Status\n').encode('utf-8')
PAIR_LINES = ('국민,1234,domestic,purchase,합성상점,5800,,,5800,2026-10-01,2026-10-02,58001111,,매입\n'
              '국민,1234,domestic,cancellation,합성상점,5800,,,5800,2026-10-01,2026-10-02,58001111,취소,취소\n').encode('utf-8')
PAIR = PAIR_HEADER + PAIR_LINES


def _same_approval_from_another_issuer():
    """승인번호와 카드 끝자리는 같고 발급사만 다른 합성 거래 두 줄."""
    return ('하나,1234,domestic,purchase,합성상점,5800,,,5800,2026-10-01,2026-10-02,58001111,,매입\n'
            '하나,1234,domestic,cancellation,합성상점,5800,,,5800,2026-10-01,2026-10-02,58001111,취소,취소\n').encode('utf-8')


def _no_approval_line(amount):
    """승인번호가 없는 합성 거래 한 줄. 같은 줄을 두 번 쓰면 원문은 같고 거래 ID만 다르다."""
    return ('국민,1234,domestic,purchase,합성상점,%d,,,%d,2026-10-01,2026-10-02,,,매입\n'
            % (amount, amount)).encode('utf-8')


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
            'display_tab_id':'trip-jp', 'trip_id':'trip-jp', 'decided':False,
        }
        self.assertEqual(
            _review_evidence_labels(row, {'booking_match':True}),
            ['예약 근거 있음', '여행 배정 확인 권장'],
        )

    def test_review_evidence_labels_distinguish_mail_from_card_linkage(self):
        row = {
            'merchant':'TRIP.COM', 'classification_source':'rule',
            'classification_state':'needs_review', 'classification_basis':'예약 근거 확인 필요',
            'display_tab_id':'unclassified', 'trip_id':'', 'decided':False,
        }
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_uncertain':True}),
            ['메일 있음 · 연결 확인 필요', '분류 확인 권장'],
        )

    def test_review_evidence_labels_separate_cancellation_mail_from_refund_status(self):
        row = {
            'merchant':'TRIP.COM', 'classification_source':'rule',
            'classification_state':'needs_review', 'classification_basis':'취소 정산 확인',
            'display_tab_id':'unclassified', 'trip_id':'', 'decided':False,
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
            'display_tab_id':'unclassified', 'trip_id':'', 'decided':False,
        }
        # 근거가 없다는 것과 자료가 없다는 것은 다르다. 연결 확인을 요청하되
        # 메일이 없다고 말하지 않는다.
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_absent':True}),
            ['예약 근거 확인 필요', '분류 확인 권장'],
        )
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_absent':True,
                                          'link_diagnosis':'no_exact_payment_evidence'}),
            ['결제 근거 미확인 · 연결 필요', '분류 확인 권장'],
        )
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_absent':True,
                                          'link_diagnosis':'multiple_real_transactions_same_amount'}),
            ['동액 거래 여러 건 · 구분 필요', '분류 확인 권장'],
        )
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_absent':True,
                                          'link_diagnosis':'no_exact_payment_evidence',
                                          'reference_only':'reference_only'}),
            ['결제 근거 미확인 · 연결 필요', '참고 자료만 있음 · 검증 필요', '분류 확인 권장'],
        )
        self.assertEqual(
            _review_evidence_labels(row, {'mail_link_absent':True,
                                          'source_diagnostic':'registered_source_missing'}),
            ['등록된 근거 자료 없음 · 확인 필요', '분류 확인 권장'],
        )

    def test_review_evidence_labels_do_not_warn_again_after_user_decision(self):
        row = {
            'merchant':'AGODA', 'classification_source':'inference',
            'classification_state':'classified', 'classification_basis':'추론 배정 · 낮음 · 과거 근거',
            'display_tab_id':'trip-jp', 'trip_id':'trip-jp', 'decided':True,
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

    def test_worker_managed_card_page_does_not_parse_all_mail_under_request_lock(self):
        row = {'merchant': 'AGODA', 'source_hash': 'synthetic-source'}
        with patch('webapp.ota_payment_review.enabled', return_value=True), \
                patch.object(self.flow, '_ota_report', side_effect=AssertionError('synchronous mail scan')):
            evidence = self.flow.review_mail_evidence([row])
        self.assertEqual(evidence, {'synthetic-source': {'source_diagnostic': 'snapshot_managed'}})
        labels = _review_evidence_labels(row, evidence['synthetic-source'])
        self.assertTrue(any('OTA 검토' in label for label in labels))

    def test_overwritten_mail_file_refreshes_cancellation_evidence(self):
        # 메일 캐시와 취소 갱신만 검사한다. 정확 매칭 게이트는 test_ota_exact_gate.py에서 따로 확인한다.
        gate=patch.dict(os.environ,{'WEBLEDGER_OTA_EXACT_GATE':'0'})
        gate.start()
        self.addCleanup(gate.stop)
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

    def test_approval_batch_state_shows_evidence_without_accounting_rows(self):
        approval = Path(__file__).resolve().parents[2] / 'tests' / 'card_pipeline' / 'data' / 'kb-approval-synthetic.xls'
        receipt = self.flow.pipeline.receive(approval.read_bytes(), 'kb-approval-synthetic.xls')
        state = self.flow.state(receipt['batch_id'])
        self.assertEqual(state['summary']['channel'], 'approval')
        self.assertEqual(state['summary']['row_count'], state['approval_summary']['source_rows'])
        self.assertGreater(state['approval_summary']['source_rows'], 0)
        self.assertEqual(state['rows'], [])
        self.assertEqual(state['preview']['ready'], 0)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0], 0)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], 0)

    def test_classification_and_review_share_evidence_without_repeated_mail_parsing(self):
        # 메일 캐시와 취소 갱신만 검사한다. 정확 매칭 게이트는 test_ota_exact_gate.py에서 따로 확인한다.
        gate=patch.dict(os.environ,{'WEBLEDGER_OTA_EXACT_GATE':'0'})
        gate.start()
        self.addCleanup(gate.stop)
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

    def confirm_all(self, batch, item='합성 비용'):
        for row in self.flow.pipeline.get_batch(batch)['rows']:
            self.flow.pipeline.save_decision(row['transaction_id'], row['revision'],
                                             item=item, display_tab_id='unclassified',
                                             request_id='confirm-' + row['transaction_id'],
                                             tab_validator=self.flow.tab_valid)
        return self.flow.pipeline.get_batch(batch)['rows']

    def commit(self, batch, request_id='commit'):
        return self.flow.pipeline.commit(batch, self.flow.state(batch)['preview']['digest'],
                                         request_id, projection=self.flow.project,
                                         trip_validator=self.flow.trip_valid,
                                         tab_validator=self.flow.tab_valid)

    def board_payload(self, row_id):
        return json.loads(self.board.conn.execute(
            'SELECT payload_json FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0])

    def insert_legacy(self, row_id, **fields):
        """거래 ID가 없는 과거 장부 행을 만들어 둔다."""
        record = dict(row_id=row_id, row_kind='expense', revision=1, display_tab_id=None,
                      occurred_on='2026-10-01', item='합성 비용', description='',
                      service_period='', reservation_no='', evidence_type='카드',
                      amount_krw=5800, source_kind='카드', source_event_id='',
                      source_fact_digest='', source_merchant='합성상점', source_issuer='국민',
                      source_card_last4='1234', source_approval_number='58001111',
                      source_approval_date='2026-10-01', source_posting_date='2026-10-02',
                      source_local_amount='', source_currency='', event_kind='purchase',
                      classification_state='classified', confirmed_by='owner', memo='')
        record.update(fields)
        self.board.conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
                                (row_id, 'expense', None, 1,
                                 json.dumps(record, ensure_ascii=False, sort_keys=True)))
        self.board.conn.commit()

    def project_entry(self, row):
        return dict(row, item='합성 비용', description='', display_tab_id='', trip_id='',
                    occurred_on=row['approval_date'], now='synthetic-now')

    def test_same_approval_purchase_and_cancellation_both_reach_the_board(self):
        batch = self.flow.pipeline.receive(PAIR, 'synthetic-pair.csv')['batch_id']
        rows = self.confirm_all(batch)
        self.assertEqual(sorted(row['amount_krw'] for row in rows), [-5800, 5800])
        self.assertEqual(len({row['transaction_id'] for row in rows}), 2)
        self.assertEqual(self.commit(batch, 'commit-pair')['applied'], 2)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 2)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], 2)
        amounts = sorted(self.board_payload('card-' + row['transaction_id'])['amount_krw']
                         for row in rows)
        self.assertEqual(amounts, [-5800, 5800])

    def test_same_card_and_approval_from_another_issuer_is_a_separate_transaction(self):
        batch = self.flow.pipeline.receive(
            PAIR_HEADER + PAIR_LINES + _same_approval_from_another_issuer(),
            'synthetic-issuers.csv')['batch_id']
        rows = self.confirm_all(batch)
        self.assertEqual({row['issuer'] for row in rows}, {'국민', '하나'})
        self.assertEqual({row['approval_number'] for row in rows}, {'58001111'})
        self.assertEqual(len({row['transaction_id'] for row in rows}), 4)
        self.assertEqual(self.commit(batch, 'commit-issuers')['applied'], 4)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 4)

    def test_same_source_hash_with_different_ids_keeps_every_real_transaction(self):
        line = _no_approval_line(9100)
        batch = self.flow.pipeline.receive(PAIR_HEADER + line + line,
                                           'synthetic-repeat.csv')['batch_id']
        rows = self.confirm_all(batch)
        self.assertEqual(len({row['transaction_id'] for row in rows}), 2)
        self.assertEqual(len({row['source_hash'] for row in rows}), 1)
        self.assertEqual(self.commit(batch, 'commit-repeat')['applied'], 2)
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 2)

    def test_alias_row_with_the_same_source_event_id_is_blocked_without_approval_number(self):
        from app.db import StoreError
        line = _no_approval_line(10100)
        batch = self.flow.pipeline.receive(PAIR_HEADER + line, 'synthetic-alias.csv')['batch_id']
        row = self.confirm_all(batch)[0]
        self.assertEqual(row['approval_number'], '')
        # 카드 행이 아직 없고, 같은 거래 ID를 가진 별칭 행만 남아 있는 상태.
        self.insert_legacy('legacy-alias', source_event_id=row['transaction_id'],
                           source_card_last4='9999', source_approval_number='')
        with self.assertRaises(StoreError) as caught:
            self.flow.project(self.project_entry(row))
        self.assertEqual(caught.exception.code, 'EXISTING_LEDGER_TRANSACTION')
        self.assertEqual(self.board.conn.execute(
            "SELECT COUNT(*) FROM board_rows WHERE row_id=?", ('card-' + row['transaction_id'],)
        ).fetchone()[0], 0)

    def test_legacy_row_blocks_the_exact_purchase_and_the_exact_cancellation(self):
        from app.db import StoreError
        # 과거 장부에 결제와 취소가 이미 있다. 뒤에 있는 취소 행이 진짜 중복이어야 막힌다.
        self.insert_legacy('legacy-buy', amount_krw=5800, event_kind='purchase')
        self.insert_legacy('legacy-cancel', amount_krw=-5800, event_kind='cancellation')
        batch = self.flow.pipeline.receive(PAIR, 'synthetic-legacy.csv')['batch_id']
        rows = self.confirm_all(batch)
        purchase = next(row for row in rows if row['amount_krw'] == 5800)
        cancellation = next(row for row in rows if row['amount_krw'] == -5800)
        for row in (purchase, cancellation):
            with self.subTest(amount=row['amount_krw']):
                with self.assertRaises(StoreError) as caught:
                    self.flow.project(self.project_entry(row))
                self.assertEqual(caught.exception.code, 'EXISTING_LEDGER_TRANSACTION')
        self.assertEqual(self.board.conn.execute(
            'SELECT COUNT(*) FROM board_rows WHERE row_id LIKE ?', ('card-%',)).fetchone()[0], 0)

    def test_legacy_row_of_another_issuer_or_kind_does_not_block_the_same_approval(self):
        batch = self.flow.pipeline.receive(PAIR, 'synthetic-narrow.csv')['batch_id']
        rows = self.confirm_all(batch)
        purchase = next(row for row in rows if row['amount_krw'] == 5800)
        # 다른 발급사의 같은 승인번호, 같은 금액, 다른 거래 종류: 어느 쪽도 중복이 아니다.
        self.insert_legacy('legacy-other-issuer', source_issuer='하나')
        self.insert_legacy('legacy-other-kind', event_kind='cancellation')
        self.insert_legacy('legacy-other-amount', amount_krw=10100)
        self.flow.project(self.project_entry(purchase))
        self.assertEqual(self.board.conn.execute(
            'SELECT COUNT(*) FROM board_rows WHERE row_id=?',
            ('card-' + purchase['transaction_id'],)).fetchone()[0], 1)

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
        self.assertIn("카드 <b>2</b> · 정리할 지출 <b>2</b> · 장부 <b>0</b>", html)
        self.assertNotIn("장부 반영 대기", html)
        self.assertIn("class='home-review btn primary' href='/import'>", html)
        self.assertIn("지출 정리 2건</a>", html)
        self.assertIn("class='home-secondary'", html)
        self.assertIn("새 카드 가져오기</a>", html)
        self.assertIn("href='/import#newupload'", html)
        self.assertNotIn("href='/export'", html)
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
        self.assertEqual(self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],1)  # 처음 유효했을 때 기록된 한 건만 남는다

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

    def test_home_counts_visible_ledger_rows_without_loading_all_tabs(self):
        from webapp import ledger_board

        trip = self.board.create_trip(
            starts_on='2026-10-10', ends_on='2026-10-13',
            destination='Synthetic', client_request_id='count-visible-trip')['tab_id']
        rows = [
            ('expense-trip', 'expense', trip, 10),
            ('income-split', 'income', None, 70),
            ('expense-hidden', 'expense', 'missing-trip', 20),
        ]
        for row_id, kind, tab_id, amount in rows:
            record = {'row_id': row_id, 'row_kind': kind,
                      'occurred_on': '2026-10-11', 'amount_krw': amount,
                      'source_kind': 'synthetic'}
            self.board.conn.execute(
                'INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)'
                ' VALUES(?,?,?,?,?)',
                (row_id, kind, tab_id, 1, json.dumps(record)))
        for index, amount in enumerate((50, 10)):
            self.board.conn.execute(
                'INSERT INTO income_allocations('
                'allocation_id,source_row_id,display_tab_id,amount_krw,'
                'source_revision,created_at,client_request_id)'
                ' VALUES(?,?,?,?,?,?,?)',
                (f'allocation-{index}', 'income-split', trip, amount,
                 1, '2026-10-11', f'allocation-request-{index}'))
        self.board.conn.commit()

        previous = ledger_board._STORE
        try:
            ledger_board.bind_store(self.board)
            self.assertEqual(
                len(ledger_board._expense_rows()) + len(ledger_board._income_rows()), 4)
            self.assertEqual(self.board.visible_row_count(), 4)
            with patch.object(ledger_board, '_expense_rows', side_effect=AssertionError('full expense scan')), \
                    patch.object(ledger_board, '_income_rows', side_effect=AssertionError('full income scan')):
                self.assertIn('장부 <b>4</b>', self.pending_home())
        finally:
            ledger_board.bind_store(previous)

    def test_ready_matches_recordable_transactions_before_and_after_commit(self):
        from app.ledger import recordable_rows
        trip, batch, row = self.pending_fixture()
        with patch.object(CardFlow, 'trip_valid', return_value=True):
            before = self.flow.state(batch)['preview']
            visible = recordable_rows(before['rows'])
            self.assertEqual(before['ready'], len(visible))
            self.assertEqual({r['transaction_id'] for r in visible}, {row['transaction_id']})
            self.flow.pipeline.commit(batch, before['digest'], 'ready-commit',
                                      trip_validator=self.flow.trip_valid, tab_validator=self.flow.tab_valid)
            after = self.flow.state(batch)['preview']
            self.assertEqual(after['ready'], len(recordable_rows(after['rows'])))
            self.assertFalse(recordable_rows(after['rows']))
            self.assertTrue(after['rows'][0]['already_booked'])

    def test_ready_counts_shared_source_transaction_once_and_excludes_blockers(self):
        from app.ledger import recordable_rows
        trip, batch, row = self.pending_fixture()
        second_batch = self.flow.pipeline.receive(
            CARD + CARD.splitlines(keepends=True)[1].replace(b'A123', b'OTHER'),
            'shared-source.csv')['batch_id']
        with patch.object(CardFlow, 'trip_valid', return_value=True):
            preview = self.flow.state(second_batch)['preview']
            first_ids = {r['transaction_id'] for r in recordable_rows(self.flow.state(batch)['preview']['rows'])}
            self.assertEqual(first_ids, {row['transaction_id']})
        visible = recordable_rows(preview['rows'])
        self.assertEqual(preview['ready'], len({r['transaction_id'] for r in visible}))
        self.assertEqual({r['transaction_id'] for r in visible}, {row['transaction_id']})
        sample = visible[0]
        self.assertEqual(recordable_rows([sample, sample]), visible)
        self.assertFalse(recordable_rows([dict(sample, blocked='needs_review'),
                                         dict(sample, already_booked=True)]))

    def test_home_does_not_scan_pending_ledger_previews(self):
        self.pending_fixture()
        with patch('app.ledger.preview', side_effect=AssertionError('home must not scan pending previews')), \
                patch.object(CardFlow, 'trip_valid', side_effect=AssertionError('home must not validate pending rows')):
            html = self.pending_home()
        self.assertNotIn('장부 반영 대기', html)

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


class OtaPreviewMetadataTests(unittest.TestCase):
    """합성 OTA 메일만으로 미리보기 메타데이터와 장부 보존을 확인한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1'})
        self.env.start()
        self.board = LedgerStore(Path(self.tmp.name) / 'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)
        self.mail_dir = Path(self.tmp.name) / 'ota-mail'
        self.mail_dir.mkdir()
        self.mail_env = patch.dict(os.environ, {'WEBLEDGER_OTA_MAIL_DIR': str(self.mail_dir)})
        self.mail_env.start()

    def tearDown(self):
        self.mail_env.stop()
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def _receive(self, merchant='TRIP.COM', amount=123000, approval='87654321'):
        from tests.card_pipeline.fixtures import make_csv, domestic_row
        data = make_csv([domestic_row(merchant=merchant, amount=amount,
                                      approval=approval, date='2026-05-01')])
        return self.flow.pipeline.receive(data, 'synthetic.csv')['batch_id']

    def _confirm(self, batch, request_id='synthetic-confirm'):
        row = self.flow.pipeline.get_batch(batch)['rows'][0]
        self.flow.pipeline.save_decision(row['transaction_id'], row['revision'],
                                         item='숙박비', display_tab_id='unclassified',
                                         request_id=request_id,
                                         tab_validator=self.flow.tab_valid)
        return row

    def _preview_entry(self, batch):
        state = self.flow.state(batch)
        rows = state['preview']['rows']
        ready = [r for r in rows if not r.get('blocked')]
        self.assertEqual(len(ready), 1)
        return state, ready[0]

    def test_exact_match_flows_to_board_with_provenance(self):
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        save(self.mail_dir, [message(hotel())])
        batch = self._receive()
        self._confirm(batch)
        state, entry = self._preview_entry(batch)
        self.assertEqual(entry.get('booking_ref'), '1111111111111111')
        self.assertEqual(entry.get('service_period'), '2026-05-22~2026-05-23')
        self.assertIsInstance(entry.get('ota_evidence'), dict)
        self.assertTrue(entry['ota_evidence'])
        digests = (entry.get('ota_evidence') or {}).get('source_digests') or []
        self.assertTrue(digests)
        digest = state['preview']['digest']
        result = self.flow.pipeline.commit(
            batch, digest, 'synthetic-commit-1',
            entry_metadata=self.flow.preview_metadata(),
            projection=self.flow.project,
            tab_validator=self.flow.tab_valid,
            trip_validator=self.flow.trip_valid)
        self.assertEqual(result['applied'], 1)
        self.assertEqual(
            self.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], 1)
        payload = self.board.conn.execute('SELECT payload_json FROM board_rows').fetchone()[0]
        import json as _json
        body = _json.loads(payload)
        self.assertEqual(body['reservation_no'], '1111111111111111')
        self.assertEqual(body['service_period'], '2026-05-22~2026-05-23')
        for digest_value in digests:
            self.assertIn(digest_value, body['classification_basis'])

    def test_ambiguous_shared_period_blanks_ref(self):
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        save(self.mail_dir, [message(hotel(), identity='one'),
                             message(hotel('2222222222222222'), identity='two')])
        batch = self._receive()
        self._confirm(batch)
        state, entry = self._preview_entry(batch)
        self.assertFalse(entry.get('booking_ref'))
        self.assertEqual(entry.get('service_period'), '2026-05-22~2026-05-23')
        self.assertIsInstance(entry.get('ota_evidence'), dict)
        result = self.flow.pipeline.commit(
            batch, state['preview']['digest'], 'synthetic-shared-commit',
            entry_metadata=self.flow.preview_metadata(),
            projection=self.flow.project,
            tab_validator=self.flow.tab_valid,
            trip_validator=self.flow.trip_valid)
        self.assertEqual(result['applied'], 1)
        payload = self.board.conn.execute('SELECT payload_json FROM board_rows').fetchone()[0]
        import json as _json
        body = _json.loads(payload)
        self.assertFalse(body.get('reservation_no'))
        self.assertEqual(body.get('service_period'), '2026-05-22~2026-05-23')

    def test_conflict_and_cancelled_leave_metadata_blank(self):
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        cases = {
            'different-period': [message(hotel(), identity='one'),
                                 message(hotel(start='2026년 5월 24일',
                                               end='2026년 5월 25일'), identity='two')],
            'cancelled': [message(hotel()),
                          message('예약번호: 1111111111111111', subject='예약 취소 완료',
                                  identity='cancel', sent='2026-05-02')],
            'ambiguous-period': [message(hotel(), identity='one'),
                                message(hotel('2222222222222222', start='2026년 5월 24일',
                                              end='2026년 5월 25일'), identity='two')],
            'cancelled-candidate': [message(hotel(), identity='one'),
                                   message(hotel('2222222222222222'), identity='two'),
                                   message('예약번호: 2222222222222222', subject='예약 취소 완료',
                                           identity='cancel', sent='2026-05-02')],
        }
        for name, mails in cases.items():
            with self.subTest(case=name):
                for child in self.mail_dir.glob('*.json'):
                    child.unlink()
                if hasattr(self.flow.board, '_card_review_mail_cache'):
                    delattr(self.flow.board, '_card_review_mail_cache')
                save(self.mail_dir, mails)
                batch = self._receive(approval='synthetic-%s' % name)
                self._confirm(batch, request_id='synthetic-%s' % name)
                state, entry = self._preview_entry(batch)
                self.assertFalse(entry.get('booking_ref'))
                self.assertFalse(entry.get('service_period'))
                self.flow.pipeline.commit(batch, state['preview']['digest'], 'commit-'+name,
                    entry_metadata=self.flow.preview_metadata(), projection=self.flow.project,
                    tab_validator=self.flow.tab_valid, trip_validator=self.flow.trip_valid)
                import json
                body = json.loads(self.board.conn.execute(
                    'SELECT payload_json FROM board_rows WHERE row_id=?',
                    ('card-'+entry['transaction_id'],)).fetchone()[0])
                self.assertEqual(body['reservation_no'], '')
                self.assertEqual(body['service_period'], '')

    def test_evidence_change_after_preview_is_stale(self):
        from app.db import StoreError
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        save(self.mail_dir, [message(hotel())])
        batch = self._receive()
        self._confirm(batch)
        digest = self.flow.state(batch)['preview']['digest']
        changes = {
            'ref': [message(hotel('2222222222222222'))],
            'period': [message(hotel(start='2026년 5월 24일', end='2026년 5월 25일'))],
            'digest': [message(hotel() + '\n메모 합성', identity='changed')],
        }
        for name, mails in changes.items():
            with self.subTest(change=name):
                save(self.mail_dir, mails)
                with self.assertRaises(StoreError) as caught:
                    self.flow.pipeline.commit(
                        batch, digest, 'synthetic-stale-%s' % name,
                        entry_metadata=self.flow.preview_metadata(),
                        projection=self.flow.project,
                        tab_validator=self.flow.tab_valid,
                        trip_validator=self.flow.trip_valid)
                self.assertEqual(caught.exception.code, 'PREVIEW_STALE')
        self.assertEqual(
            self.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], 0)
        self.assertEqual(
            self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 0)

    def test_replay_writes_once(self):
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        save(self.mail_dir, [message(hotel())])
        batch = self._receive()
        self._confirm(batch)
        digest = self.flow.state(batch)['preview']['digest']
        first = self.flow.pipeline.commit(
            batch, digest, 'synthetic-replay',
            entry_metadata=self.flow.preview_metadata(),
            projection=self.flow.project,
            tab_validator=self.flow.tab_valid,
            trip_validator=self.flow.trip_valid)
        second = self.flow.pipeline.commit(
            batch, digest, 'synthetic-replay',
            entry_metadata=self.flow.preview_metadata(),
            projection=self.flow.project,
            tab_validator=self.flow.tab_valid,
            trip_validator=self.flow.trip_valid)
        self.assertEqual(first, second)
        self.assertEqual(
            self.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0], 1)
        self.assertEqual(
            self.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0], 1)

    def test_projection_failure_rolls_back_both_tables(self):
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        save(self.mail_dir, [message(hotel())])
        batch = self._receive()
        self._confirm(batch)
        digest = self.flow.state(batch)['preview']['digest']

        def fail(entry):
            self.flow.project(entry)
            raise RuntimeError('synthetic projection failure')

        with self.assertRaises(RuntimeError):
            self.flow.pipeline.commit(
                batch, digest, 'synthetic-rollback',
                entry_metadata=self.flow.preview_metadata(),
                projection=fail,
                tab_validator=self.flow.tab_valid,
                trip_validator=self.flow.trip_valid)
        for table in ('ledger_entries', 'board_rows'):
            self.assertEqual(
                self.board.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_resolver_is_lazy_report_once(self):
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        save(self.mail_dir, [message(hotel())])
        batch = self._receive()
        self._confirm(batch)
        _, row = self._preview_entry(batch)
        with patch.object(CardFlow, '_ota_report',
                          wraps=self.flow._ota_report) as spy:
            resolver = self.flow.preview_metadata()
            first = resolver(row)
            second = resolver(row)
            self.assertEqual(first, second)
            self.assertEqual(spy.call_count, 1)

    def test_unexpected_report_failure_propagates(self):
        batch = self._receive()
        self._confirm(batch, request_id='synthetic-boom')
        with patch.object(CardFlow, '_ota_report', side_effect=RuntimeError('synthetic boom')):
            if hasattr(self.flow.board, '_card_review_mail_cache'):
                delattr(self.flow.board, '_card_review_mail_cache')
            with self.assertRaises(RuntimeError):
                self.flow.state(batch)
            with self.assertRaises(RuntimeError):
                self.flow.preview_metadata()(self.flow.pipeline.get_batch(batch)['rows'][0])

    def test_uncertain_report_metadata_is_not_projected(self):
        from app.ota_mail import ledger_metadata
        entry = dict(transaction_id='synthetic', source_hash='source', item='숙박비',
                     transaction_direction='purchase')
        fact = dict(transaction_id='synthetic', source_hash='source', item='숙박비',
                    booking_ref='ABC123', period={'starts_on':'2026-08-02','ends_on':'2026-08-03'},
                    reservation_status='observed', source_sha256='digest')
        for flags in ({'booking_link_conflict':True}, {'period_conflict':True},
                      {'reservation_status':'evidence_pending'}, {'reservation_status':'refund_pending'},
                      {'source_sha256':''}, {'period':None}):
            with self.subTest(flags=flags):
                metadata = ledger_metadata({'matches':[dict(fact, **flags)]}, entry)
                self.assertEqual(metadata['booking_ref'], '')
                self.assertEqual(metadata['service_period'], '')

    def test_digest_protects_each_written_metadata_field(self):
        from copy import deepcopy
        from app.ledger import preview_digest
        from tests.card_pipeline.test_booking_mail import message, hotel
        from tests.card_pipeline.test_ota_refresh import save
        save(self.mail_dir, [message(hotel())])
        batch = self._receive()
        self._confirm(batch)
        preview = self.flow.state(batch)['preview']
        for field, value in (('booking_ref', 'ABC999'), ('service_period', '2026-08-02~2026-08-03'),
                             ('ota_evidence', {'source_digests':['changed']})):
            with self.subTest(field=field):
                changed = deepcopy(preview)
                changed['rows'][0][field] = value
                self.assertNotEqual(preview_digest(changed), preview['digest'])

    def test_lodging_period_evidence_digest_is_preserved_and_revalidated(self):
        from app.db import StoreError
        from tests.card_pipeline.test_booking_mail import message
        from tests.card_pipeline.test_ota_refresh import save
        payment = message('예약번호: 1738864710\n총 금액 KRW 123000',
                          subject='Payment confirmation', domain='agoda.com', identity='payment')
        period = message('예약번호: 1738864710\n체크인: 2026-08-02\n체크아웃: 2026-08-03',
                         domain='agoda.com', identity='period')
        save(self.mail_dir, [payment, period])
        batch = self._receive(merchant='AGODA')
        self._confirm(batch)
        state, entry = self._preview_entry(batch)
        self.assertEqual(entry['booking_ref'], '1738864710')
        self.assertEqual(entry['service_period'], '2026-08-02~2026-08-03')
        self.assertEqual(len(entry['ota_evidence']['source_digests']), 2)
        period['payload']['body']['content'] += '\n합성 메모 추가'
        save(self.mail_dir, [payment, period])
        with self.assertRaises(StoreError) as caught:
            self.flow.pipeline.commit(batch, state['preview']['digest'], 'changed-period-evidence',
                entry_metadata=self.flow.preview_metadata(), projection=self.flow.project,
                tab_validator=self.flow.tab_valid, trip_validator=self.flow.trip_valid)
        self.assertEqual(caught.exception.code, 'PREVIEW_STALE')
        for table in ('ledger_entries', 'board_rows'):
            self.assertEqual(self.board.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()


def test_import_summary_counts_match_the_metric_tiles():
    # The header and the tiles must use the same row states, or "확인 필요" shows two different numbers.
    from webapp.card_flow import PAGE as page
    assert "기록 가능" not in page and "['ready','기록 가능']" not in page
    assert "확인 필요 '+reviewCounts.review" in page
    assert "자동분류 '+(counts.classified" not in page and "'+(counts.needs_review" not in page
