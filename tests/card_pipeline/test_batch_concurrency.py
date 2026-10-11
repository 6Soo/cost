import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import Store, StoreError
from app.review import save_decisions_atomic
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD


@pytest.fixture
def batch(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    path = tmp_path / 'board.sqlite'
    board = LedgerStore(path, seed_demo=False)
    flow = CardFlow(board)
    received = flow.pipeline.receive(CARD, 'synthetic.csv')
    row, = flow.pipeline.get_batch(received['batch_id'])['rows']
    decisions = [dict(transaction_id=row['transaction_id'], revision=row['revision'],
                      item='식비', description='', display_tab_id='', trip_id='', note='',
                      reuse_rule=False, resolve_hold=False, expected_amount_krw=row['amount_krw'])]
    yield path, board, decisions
    board.close()


@pytest.mark.parametrize('same_body', [True, False])
def test_concurrent_same_id_is_replayed_or_rejected_by_body(batch, same_body):
    path, board, decisions = batch
    source = board.conn.execute('SELECT source_hash, amount_krw, raw_row_json FROM transactions').fetchall()
    barrier = threading.Barrier(2)

    def approve(index):
        store = Store.open(str(path))
        real_replay = store.replay_request
        first = True

        def replay(*args):
            nonlocal first
            answer = real_replay(*args)
            if first:
                first = False
                barrier.wait(timeout=10)
            return answer

        store.replay_request = replay
        try:
            body = [dict(decisions[0], item='식비' if same_body or index == 0 else '교통비')]
            return save_decisions_atomic(store, body, request_id='same-request', basis='synthetic')
        except StoreError as error:
            return error.code
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, [0, 1]))
    if same_body:
        assert results[0] == results[1]
        assert isinstance(results[0], dict)
    else:
        assert sum(isinstance(r, dict) for r in results) == 1
        assert 'REQUEST_ID_REUSED' in results
    assert board.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0] == 1
    assert board.conn.execute('SELECT source_hash, amount_krw, raw_row_json FROM transactions').fetchall() == source
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_database_failure_rolls_back_decisions_requests_and_source(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    before = store.conn.execute('SELECT * FROM transactions').fetchall()
    requests = store.conn.execute('SELECT * FROM requests').fetchall()
    store.conn.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON requests "
                       "WHEN NEW.scope='save_decisions' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    try:
        with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
            save_decisions_atomic(store, decisions, request_id='db-failure')
        assert store.conn.execute('SELECT * FROM transactions').fetchall() == before
        assert store.conn.execute('SELECT * FROM requests').fetchall() == requests
        assert store.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0] == 0
        store.conn.execute('DROP TRIGGER synthetic_failure')
        assert len(save_decisions_atomic(store, decisions, request_id='db-failure')['results']) == 1
    finally:
        store.close()
