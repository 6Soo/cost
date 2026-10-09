"""Synthetic coverage for linked partial refunds. Memory databases only."""
import sqlite3

import pytest

from app import Pipeline, StoreError

HEADER = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
          'Date,Post Date,Authorization Code,Cancel,Status\n')
OK = lambda _: True


def build(gross=1000000, refunds=(-700000,), original_ref='100'):
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    lines = [f'국민,1234,domestic,purchase,합성항공,{gross},,,{gross},2026-10-01,2026-10-02,A100,,매입']
    for index, amount in enumerate(refunds):
        lines.append(f'국민,1234,domestic,purchase,합성항공,{abs(amount)},,,{abs(amount)},2026-10-0{3 + index},2026-10-0{4 + index},C{200 + index},,매입')
    batch = pipe.receive((HEADER + '\n'.join(lines) + '\n').encode(), 'synthetic.csv')['batch_id']
    conn = pipe.store.conn
    for index, amount in enumerate(refunds):
        conn.execute("UPDATE transactions SET transaction_direction='cancellation', amount_krw=?,"
                     " original_approval_number=? WHERE approval_number=?",
                     (amount, original_ref, str(200 + index)))
    pipe.classify_batch(batch)
    return pipe, batch


def row_of(pipe, approval):
    return next(r for r in pipe.get_batch(pipe_batch(pipe))['rows'] if r['approval_number'] == approval)


def pipe_batch(pipe):
    return pipe.store.conn.execute('SELECT batch_id FROM import_batches').fetchone()[0]


def confirm_original(pipe, batch, item='항공료', tab='unclassified'):
    original = next(r for r in pipe.get_batch(batch)['rows'] if r['approval_number'] == '100')
    pipe.save_decision(original['transaction_id'], original['revision'], item=item, display_tab_id=tab,
                       tab_validator=OK, request_id='confirm-original')
    return original['transaction_id']


def preview(pipe, batch):
    return pipe.preview(batch, tab_validator=OK, trip_validator=OK)


def by_approval(pipe, result):
    ids = {r['transaction_id']: r['approval_number'] for r in pipe.get_batch(pipe_batch(pipe))['rows']}
    return {ids[r['transaction_id']]: r for r in result['rows']}


def test_linked_partial_refund_is_decided_together_and_net_is_derived():
    pipe, batch = build()
    confirm_original(pipe, batch)
    rows = by_approval(pipe, preview(pipe, batch))
    original, refund = rows['100'], rows['200']
    assert not original.get('blocked') and not refund.get('blocked')
    assert refund['item'] == '항공료' and refund['display_tab_id'] == 'unclassified'
    assert refund['refund_link'] == {'gross_krw': 1000000, 'refund_krw': -700000, 'net_krw': 300000,
                                     'status': 'partial', 'role': 'refund',
                                     'counterpart_id': original['transaction_id']}
    assert original['refund_link']['role'] == 'original'
    assert (original['amount_krw'], refund['amount_krw']) == (1000000, -700000)


def test_commit_books_both_rows_once_with_provenance_and_is_idempotent():
    pipe, batch = build()
    confirm_original(pipe, batch)
    result = preview(pipe, batch)
    done = pipe.commit(batch, result['digest'], 'pair-1', tab_validator=OK, trip_validator=OK)
    assert done['applied'] == 2
    conn = pipe.store.conn
    assert conn.execute('SELECT SUM(amount_krw), COUNT(*) FROM ledger_entries').fetchone() == (300000, 2)
    assert conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='ledger.refund_linked'").fetchone()[0] == 1
    assert pipe.commit(batch, result['digest'], 'pair-1', tab_validator=OK, trip_validator=OK) == done
    again = preview(pipe, batch)
    assert pipe.commit(batch, again['digest'], 'pair-2', tab_validator=OK, trip_validator=OK)['applied'] == 0
    assert conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 2


def test_original_hold_holds_the_refund_too():
    pipe, batch = build()
    original_id = confirm_original(pipe, batch)
    source = pipe.store.conn.execute('SELECT source_hash FROM transactions WHERE transaction_id=?',
                                     (original_id,)).fetchone()[0]
    pipe.store.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                            (original_id, source, 'refund_pending', '환불 확인 대기'))
    result = preview(pipe, batch)
    rows = by_approval(pipe, result)
    assert rows['100']['blocked'] == 'review_hold'
    assert rows['200']['blocked'] == 'refund_pair_incomplete'
    assert result['ready'] == 0


def test_unconfirmed_original_blocks_the_pair():
    pipe, batch = build()
    rows = by_approval(pipe, preview(pipe, batch))
    assert rows['100'].get('blocked') and rows['200']['blocked'] == 'refund_pair_incomplete'


def test_refund_larger_than_the_original_holds_both():
    pipe, batch = build(refunds=(-700000, -400000))
    confirm_original(pipe, batch)
    rows = by_approval(pipe, preview(pipe, batch))
    assert {rows['100']['blocked'], rows['200']['blocked'], rows['201']['blocked']} == {'refund_exceeds_original'}


def test_two_refunds_within_the_original_are_both_linked_and_net_uses_the_total():
    pipe, batch = build(refunds=(-700000, -200000))
    confirm_original(pipe, batch)
    rows = by_approval(pipe, preview(pipe, batch))
    assert rows['200']['refund_link']['net_krw'] == rows['201']['refund_link']['net_krw'] == 100000
    assert rows['200']['refund_link']['refund_krw'] == -900000
    assert (rows['200']['amount_krw'], rows['201']['amount_krw']) == (-700000, -200000)


def test_conflicting_classification_on_the_refund_holds_the_pair():
    pipe, batch = build()
    confirm_original(pipe, batch)
    refund = next(r for r in pipe.get_batch(batch)['rows'] if r['approval_number'] == '200')
    pipe.save_decision(refund['transaction_id'], refund['revision'], item='숙박비',
                       display_tab_id='unclassified', tab_validator=OK, request_id='other')
    rows = by_approval(pipe, preview(pipe, batch))
    assert rows['100']['blocked'] == rows['200']['blocked'] == 'refund_pair_mismatch'


def test_failure_while_projecting_the_second_row_rolls_back_both():
    pipe, batch = build()
    confirm_original(pipe, batch)
    result = preview(pipe, batch)
    calls = []

    def projection(entry):
        calls.append(entry['transaction_id'])
        if len(calls) == 2:
            raise RuntimeError('projection failed')

    with pytest.raises(RuntimeError):
        pipe.commit(batch, result['digest'], 'fail', tab_validator=OK, trip_validator=OK, projection=projection)
    assert pipe.store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_a_decision_after_the_preview_makes_the_preview_stale():
    pipe, batch = build()
    confirm_original(pipe, batch)
    result = preview(pipe, batch)
    original = next(r for r in pipe.get_batch(batch)['rows'] if r['approval_number'] == '100')
    pipe.save_decision(original['transaction_id'], original['revision'], item='숙박비',
                       display_tab_id='unclassified', tab_validator=OK, request_id='change')
    with pytest.raises(StoreError):
        pipe.commit(batch, result['digest'], 'stale', tab_validator=OK, trip_validator=OK)
    assert pipe.store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_an_unlinked_cancellation_is_unchanged():
    pipe, batch = build(original_ref='')
    confirm_original(pipe, batch)
    rows = by_approval(pipe, preview(pipe, batch))
    assert 'refund_link' not in rows['200'] and rows['200'].get('blocked') == 'needs_review'


def test_a_refund_with_two_possible_originals_is_not_linked():
    from app.partial_refund import refund_links
    pipe, batch = build()
    conn = pipe.store.conn
    ids = [r['transaction_id'] for r in pipe.get_batch(batch)['rows']]
    assert len(refund_links(conn, ids)) == 1
    conn.execute("CREATE TEMP TABLE twin AS SELECT * FROM transactions WHERE approval_number='100'")
    conn.execute("UPDATE twin SET transaction_id='twin-id', source_hash='twin-hash'")
    conn.execute("INSERT INTO transactions SELECT * FROM twin")
    assert refund_links(conn, ids) == {}
