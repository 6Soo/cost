"""새 파일 처리와 기존 장부 화면이 같은 거래를 한 번만 기록하는지 확인한다."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webapp.ledger_store import LedgerStore
from webapp.card_flow import CardFlow, page, batch_catalog


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
        self.assertIn("카드 자료 <b>2건</b>", html)
        self.assertIn("확인할 거래 <b>2건</b>", html)
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

    def test_mobile_page_has_answer_preview_and_no_cell_column(self):
        html = page('synthetic')
        self.assertIn('width=device-width',html)
        self.assertIn('내 답변·수정 이유',html)
        self.assertIn('장부 미리보기',html)
        self.assertNotIn('<th>칸</th>',html)


if __name__ == '__main__':
    unittest.main()
