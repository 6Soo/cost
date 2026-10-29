"""환불 쌍만 기록하는 경로: 상세 상태의 묶음 목록과 묶음 commit 라우트를 합성 자료로 확인한다."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from webapp import ledger_board
from webapp.card_flow import CardFlow, dispatch
from webapp.ledger_store import LedgerStore

CSV = (
    'Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
    'Date,Post Date,Authorization Code,Cancel,Status\n'
    '국민,1234,domestic,purchase,합성항공,1000000,,,1000000,2026-10-01,2026-10-02,A100,,매입\n'
    '국민,1234,domestic,purchase,합성항공,700000,,,700000,2026-10-03,2026-10-04,C200,,매입\n'
    '국민,1234,domestic,purchase,합성식당,50000,,,50000,2026-10-02,2026-10-03,O300,,매입\n'
).encode('utf-8')
OK = lambda _: True
TOKEN = 'synthetic-token'


class FakeHandler:
    def __init__(self):
        self.headers = {'X-CSRF-Token': TOKEN}
        self.sent = []

    def _send_json(self, payload, status=200):
        self.sent.append((status, payload))


class RefundGroupCommitTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1'})
        self.env.start()
        self.board = LedgerStore(Path(self.tmp.name) / 'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)
        self.previous_store = ledger_board._STORE
        ledger_board.bind_store(self.board)
        self.batch = self.flow.pipeline.receive(CSV, 'pair.csv')['batch_id']
        conn = self.board.conn
        conn.execute("UPDATE transactions SET transaction_direction='cancellation', amount_krw=-700000,"
                     " original_approval_number='100' WHERE approval_number='200'")
        self.flow.pipeline.classify_batch(self.batch)
        self.original = self.id_of('100')
        self.refund = self.id_of('200')
        self.other = self.id_of('300')
        for transaction_id in (self.original, self.other):
            row = next(r for r in self.flow.pipeline.get_batch(self.batch)['rows']
                       if r['transaction_id'] == transaction_id)
            self.flow.pipeline.save_decision(transaction_id, row['revision'], item='항공료' if transaction_id == self.original else '식비',
                                             display_tab_id='unclassified', tab_validator=OK, request_id='c-' + transaction_id)

    def tearDown(self):
        ledger_board.bind_store(self.previous_store)
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def id_of(self, approval):
        return self.board.conn.execute('SELECT transaction_id FROM transactions WHERE approval_number=?',
                                       (approval,)).fetchone()[0]

    def ledger(self):
        return self.board.conn.execute('SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM ledger_entries').fetchone()

    def post(self, original_id, body):
        handler = FakeHandler()
        parsed = urlparse(f'/api/imports/{self.batch}/refund-groups/{original_id}/commit')
        dispatch(handler, parsed, None, json.dumps(body).encode('utf-8'), TOKEN)
        return handler.sent[-1]

    def test_state_lists_the_pair_as_one_recordable_group(self):
        state = self.flow.state(self.batch)
        self.assertEqual(len(state['refund_groups']), 1)
        group = state['refund_groups'][0]
        self.assertTrue(group['recordable'])
        self.assertEqual(group['original_id'], self.original)
        self.assertEqual((group['gross_krw'], group['refund_krw'], group['net_krw']), (1000000, -700000, 300000))
        self.assertEqual({r['transaction_id'] for r in group['rows']}, {self.original, self.refund})
        same_screen = self.flow.pipeline.preview(self.batch, trip_validator=OK,
                                                 tab_validator=lambda target: target in ('', 'unclassified'),
                                                 group_original=self.original)
        self.assertEqual(group['digest'], same_screen['digest'])

    def test_group_route_books_only_the_pair_and_repeats_are_noops(self):
        digest = self.flow.state(self.batch)['refund_groups'][0]['digest']
        status, payload = self.post(self.original, {'digest': digest, 'request_id': 'route-1'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['result']['applied'], 2)
        self.assertEqual(self.ledger(), (2, 300000))
        booked = {r[0] for r in self.board.conn.execute('SELECT transaction_id FROM ledger_entries')}
        self.assertEqual(booked, {self.original, self.refund})
        self.assertEqual(self.post(self.original, {'digest': digest, 'request_id': 'route-1'})[1]['result'],
                         payload['result'])
        again = self.post(self.original, {'digest': digest, 'request_id': 'route-2'})[1]
        self.assertEqual(again['result']['applied'], 0)
        self.assertEqual(self.ledger(), (2, 300000))

    def test_group_route_rejects_a_stale_digest_without_writes(self):
        status, payload = self.post(self.original, {'digest': 'f' * 64, 'request_id': 'stale-1'})
        self.assertEqual(status, 409)
        self.assertEqual(payload['code'], 'PREVIEW_STALE')
        self.assertEqual(self.ledger(), (0, 0))

    def test_replay_fails_closed_after_amount_changes(self):
        digest = self.flow.state(self.batch)['refund_groups'][0]['digest']
        self.assertEqual(self.post(self.original, {'digest': digest, 'request_id': 'amount-1'})[0], 200)
        self.board.conn.execute(
            "UPDATE transactions SET amount_krw=amount_krw+1, revision=revision+1 WHERE transaction_id=?",
            (self.original,))
        status, payload = self.post(self.original, {'digest': digest, 'request_id': 'amount-2'})
        self.assertEqual(status, 409)
        self.assertEqual(payload['code'], 'PREVIEW_STALE')
        self.assertEqual(self.ledger(), (2, 300000))

    def test_replay_fails_closed_after_user_revision_changes(self):
        digest = self.flow.state(self.batch)['refund_groups'][0]['digest']
        self.assertEqual(self.post(self.original, {'digest': digest, 'request_id': 'revision-1'})[0], 200)
        self.board.conn.execute(
            "UPDATE transactions SET classification_basis='사용자 수정', revision=revision+1 WHERE transaction_id=?",
            (self.original,))
        status, payload = self.post(self.original, {'digest': digest, 'request_id': 'revision-2'})
        self.assertEqual(status, 409)
        self.assertEqual(payload['code'], 'PREVIEW_STALE')
        self.assertEqual(self.ledger(), (2, 300000))

    def test_group_commit_keeps_saved_pair_when_state_refresh_fails(self):
        digest = self.flow.state(self.batch)['refund_groups'][0]['digest']
        body = {'digest': digest, 'request_id': 'group-refresh-failure'}
        with patch.object(CardFlow, 'state', side_effect=RuntimeError('private refresh failure')):
            status, payload = self.post(self.original, body)
        self.assertEqual(status, 200)
        self.assertTrue(payload['saved'])
        self.assertTrue(payload['refresh_required'])
        self.assertEqual(self.ledger(), (2, 300000))
        self.assertEqual(self.post(self.original, body)[1]['result'], payload['result'])
        self.assertEqual(self.ledger(), (2, 300000))

    def test_group_route_rejects_an_id_that_is_not_a_linked_original(self):
        digest = self.flow.state(self.batch)['refund_groups'][0]['digest']
        status, payload = self.post(self.other, {'digest': digest, 'request_id': 'wrong-1'})
        self.assertEqual(status, 409)
        self.assertEqual(payload['code'], 'INVALID_INPUT')
        self.assertEqual(self.ledger(), (0, 0))
