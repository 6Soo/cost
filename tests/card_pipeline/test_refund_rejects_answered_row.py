"""A verified full-refund recording must not overwrite a person's attribution (M3 §11.5).

`_persist_verified_refund_classification` used to test only `classification_source`. `decided_at` is the
timestamp every owner answer carries, and a restored row can hold it without a `user_*` source — so that
trace has to be read too. Synthetic rows only.
"""
import pytest

from app.db import Store
from tests.card_pipeline.test_batch_concurrency import batch


def _entry(tid, counterpart):
    return dict(transaction_id=tid, item='취소·환불',
                refund_link=dict(status='full', net_krw=0, counterpart_id=counterpart))


def _set(store, tid, **values):
    columns = ', '.join('%s=?' % name for name in values)
    store.conn.execute('UPDATE transactions SET ' + columns + ' WHERE transaction_id=?',
                       (*values.values(), tid))
    store.conn.commit()


def _read(store, tid):
    return store.conn.execute('SELECT display_tab_id, trip_id, classification_source, decided_at'
                              ' FROM transactions WHERE transaction_id=?', (tid,)).fetchone()


def test_a_person_answered_row_keeps_its_attribution_on_a_verified_full_refund(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        tid = decisions[0]['transaction_id']
        counterpart = decisions[0]['transaction_id']
        _set(store, tid, display_tab_id='trip-syn', trip_id='trip-syn',
             classification_source='inference', decided_at='2026-10-06T00:00:00Z')
        before = _read(store, tid)
        from app.ledger import _persist_verified_refund_classification
        _persist_verified_refund_classification(store, _entry(tid, counterpart), tid)
        assert _read(store, tid) == before, (
            'a person\'s answer (decided_at) must not be replaced by a refund tab: %r' % (_read(store, tid),))
    finally:
        store.close()


def test_a_person_board_correction_also_stops_the_refund_rewrite(batch):
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        tid = decisions[0]['transaction_id']
        _set(store, tid, display_tab_id='trip-syn', trip_id='trip-syn',
             classification_source='inference')
        board.conn.execute('INSERT OR REPLACE INTO board_manual_overrides(row_id, field, event_id)'
                           ' VALUES (?,?,?)', ('card-' + tid, 'display_tab_id', 'manual'))
        board.conn.commit()
        before = _read(store, tid)
        from app.ledger import _persist_verified_refund_classification
        _persist_verified_refund_classification(store, _entry(tid, tid), tid)
        assert _read(store, tid) == before
    finally:
        store.close()


def test_an_unanswered_row_still_takes_the_refund_tab(batch):
    """The guard must not block the ordinary case it exists for."""
    path, board, decisions = batch
    store = Store.open(str(path))
    try:
        tid = decisions[0]['transaction_id']
        _set(store, tid, display_tab_id='trip-syn', trip_id='trip-syn',
             classification_source='inference', decided_at=None)
        from app.ledger import _persist_verified_refund_classification
        _persist_verified_refund_classification(store, _entry(tid, tid), tid)
        row = _read(store, tid)
        assert row[0] == 'refunds' and row[1] == '' and row[2] == 'refund_original', row
    finally:
        store.close()
