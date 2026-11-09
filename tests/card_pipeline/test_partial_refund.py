"""Synthetic coverage for linked partial refunds. Memory databases only."""
import sqlite3

import pytest

from app import Pipeline, StoreError

HEADER = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
          'Date,Post Date,Authorization Code,Cancel,Status\n')
OK = lambda _: True


def build(gross=1000000, refunds=(-700000,), original_ref='100', extra=False):
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    lines = [f'국민,1234,domestic,purchase,합성항공,{gross},,,{gross},2026-10-01,2026-10-02,A100,,매입']
    for index, amount in enumerate(refunds):
        lines.append(f'국민,1234,domestic,purchase,합성항공,{abs(amount)},,,{abs(amount)},2026-10-0{3 + index},2026-10-0{4 + index},C{200 + index},,매입')
    if extra:
        lines.append('국민,1234,domestic,purchase,합성식당,50000,,,50000,2026-10-02,2026-10-03,O300,,매입')
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


def decide_refund(pipe, batch, approval):
    refund = next(r for r in pipe.get_batch(batch)['rows'] if r['approval_number'] == approval)
    pipe.save_decision(refund['transaction_id'], refund['revision'], item='항공료', display_tab_id='unclassified',
                       tab_validator=OK, request_id='decide-' + approval)


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


def book_alone(pipe, batch, approval):
    pipe.store.conn.execute(
        "INSERT INTO ledger_entries(transaction_id, batch_id, item, description, display_tab_id, trip_id,"
        " amount_krw, merchant, occurred_on, transaction_direction, source_hash, committed_at)"
        " SELECT transaction_id, ?, '항공료', '', 'unclassified', '', amount_krw, merchant, approval_date,"
        " transaction_direction, source_hash, '2026-10-10T00:00:00Z' FROM transactions WHERE approval_number=?",
        (batch, approval))


def test_full_refund_nets_to_zero_and_books_both():
    pipe, batch = build(refunds=(-1000000,))
    confirm_original(pipe, batch)
    rows = by_approval(pipe, preview(pipe, batch))
    assert rows['200']['refund_link']['status'] == 'full' and rows['200']['refund_link']['net_krw'] == 0
    done = pipe.commit(batch, preview(pipe, batch)['digest'], 'full-1', tab_validator=OK, trip_validator=OK)
    assert done['applied'] == 2
    assert pipe.store.conn.execute('SELECT SUM(amount_krw), COUNT(*) FROM ledger_entries').fetchone() == (0, 2)


def test_two_refunds_and_their_original_are_booked_as_one_group():
    pipe, batch = build(refunds=(-700000, -200000))
    confirm_original(pipe, batch)
    done = pipe.commit(batch, preview(pipe, batch)['digest'], 'group-1', tab_validator=OK, trip_validator=OK)
    assert done['applied'] == 3
    assert pipe.store.conn.execute('SELECT SUM(amount_krw), COUNT(*) FROM ledger_entries').fetchone() == (100000, 3)


def test_retry_of_an_all_booked_group_is_a_noop():
    pipe, batch = build(refunds=(-700000, -200000))
    confirm_original(pipe, batch)
    pipe.commit(batch, preview(pipe, batch)['digest'], 'group-1', tab_validator=OK, trip_validator=OK)
    again = pipe.commit(batch, preview(pipe, batch)['digest'], 'group-2', tab_validator=OK, trip_validator=OK)
    assert again['applied'] == 0
    assert pipe.store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 3



def test_refund_arriving_after_its_original_is_booked_completes_the_pair():
    pipe, batch = build()
    confirm_original(pipe, batch)
    book_alone(pipe, batch, '100')
    done = pipe.commit(batch, preview(pipe, batch)['digest'], 'late-refund', tab_validator=OK, trip_validator=OK)
    assert done['applied'] == 1
    assert ledger_state(pipe) == (2, 300000)



def test_original_arriving_after_its_refund_is_booked_completes_the_pair():
    pipe, batch = build()
    confirm_original(pipe, batch)
    decide_refund(pipe, batch, '200')
    book_alone(pipe, batch, '200')
    done = pipe.commit(batch, preview(pipe, batch)['digest'], 'late-original', tab_validator=OK, trip_validator=OK)
    assert done['applied'] == 1
    assert ledger_state(pipe) == (2, 300000)



def test_missing_members_of_a_partly_booked_group_are_completed_together():
    pipe, batch = build(refunds=(-700000, -200000))
    confirm_original(pipe, batch)
    decide_refund(pipe, batch, '201')
    book_alone(pipe, batch, '201')
    done = pipe.commit(batch, preview(pipe, batch)['digest'], 'late-group', tab_validator=OK, trip_validator=OK)
    assert done['applied'] == 2
    assert ledger_state(pipe) == (3, 100000)


def test_a_refund_decision_after_the_preview_makes_the_preview_stale():
    pipe, batch = build()
    confirm_original(pipe, batch)
    result = preview(pipe, batch)
    refund = next(r for r in pipe.get_batch(batch)['rows'] if r['approval_number'] == '200')
    pipe.save_decision(refund['transaction_id'], refund['revision'], item='숙박비',
                       display_tab_id='unclassified', tab_validator=OK, request_id='refund-change')
    with pytest.raises(StoreError):
        pipe.commit(batch, result['digest'], 'stale-refund', tab_validator=OK, trip_validator=OK)
    assert pipe.store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


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


def confirm_other(pipe, batch, item='식비'):
    other = next(r for r in pipe.get_batch(batch)['rows'] if r['approval_number'] == '300')
    pipe.save_decision(other['transaction_id'], other['revision'], item=item,
                       display_tab_id='unclassified', tab_validator=OK, request_id='confirm-other')
    return other['transaction_id']


def group_of(pipe, batch, original_id):
    return pipe.preview(batch, tab_validator=OK, trip_validator=OK, group_original=original_id)


def group_commit(pipe, batch, original_id, request_id, **kwargs):
    digest = group_of(pipe, batch, original_id)['digest']
    return pipe.commit(batch, digest, request_id, tab_validator=OK, trip_validator=OK,
                       group_original=original_id, **kwargs)


def ledger_state(pipe):
    return pipe.store.conn.execute('SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM ledger_entries').fetchone()


def test_group_preview_holds_only_the_original_and_its_refund():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    confirm_other(pipe, batch)
    scoped = group_of(pipe, batch, original_id)
    refund_id = pipe.store.conn.execute("SELECT transaction_id FROM transactions WHERE approval_number='200'").fetchone()[0]
    assert {r['transaction_id'] for r in scoped['rows']} == {original_id, refund_id}
    assert scoped['ready'] == 2 and scoped['recordable'] is True
    assert scoped['digest'] != preview(pipe, batch)['digest']


def test_group_commit_books_only_the_pair_and_their_net_sum():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    confirm_other(pipe, batch)
    done = group_commit(pipe, batch, original_id, 'group-1')
    assert done['applied'] == 2
    assert ledger_state(pipe) == (2, 300000)
    booked = {r[0] for r in pipe.store.conn.execute('SELECT transaction_id FROM ledger_entries')}
    other = pipe.store.conn.execute("SELECT transaction_id FROM transactions WHERE approval_number='300'").fetchone()[0]
    assert other not in booked


def test_group_commit_leaves_source_amounts_unchanged():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    confirm_other(pipe, batch)
    before = pipe.store.conn.execute('SELECT approval_number, amount_krw FROM transactions ORDER BY approval_number').fetchall()
    group_commit(pipe, batch, original_id, 'group-amounts')
    assert pipe.store.conn.execute('SELECT approval_number, amount_krw FROM transactions ORDER BY approval_number').fetchall() == before


def test_stale_original_or_refund_rejects_the_group_commit():
    for approval in ('100', '200'):
        pipe, batch = build(extra=True)
        original_id = confirm_original(pipe, batch)
        confirm_other(pipe, batch)
        digest = group_of(pipe, batch, original_id)['digest']
        row = next(r for r in pipe.get_batch(batch)['rows'] if r['approval_number'] == approval)
        pipe.save_decision(row['transaction_id'], row['revision'], item='숙박비',
                           display_tab_id='unclassified', tab_validator=OK, request_id='change-' + approval)
        with pytest.raises(StoreError) as caught:
            pipe.commit(batch, digest, 'stale-' + approval, tab_validator=OK, trip_validator=OK,
                        group_original=original_id)
        assert caught.value.code == 'PREVIEW_STALE'
        assert ledger_state(pipe) == (0, 0)



def test_partly_booked_group_completes_the_missing_original():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    decide_refund(pipe, batch, '200')
    book_alone(pipe, batch, '200')
    done = group_commit(pipe, batch, original_id, 'late-group-commit')
    assert done['applied'] == 1
    assert ledger_state(pipe) == (2, 300000)


def test_group_with_a_member_outside_the_batch_is_rejected():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    pipe.store.conn.execute('DELETE FROM import_batch_rows WHERE batch_id=? AND transaction_id IN'
                            ' (SELECT transaction_id FROM transactions WHERE approval_number=?)', (batch, '200'))
    with pytest.raises(StoreError) as caught:
        group_of(pipe, batch, original_id)
    assert caught.value.code == 'REFUND_GROUP_INCOMPLETE'


def test_projection_failure_on_the_second_row_rolls_back_the_pair():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    confirm_other(pipe, batch)
    calls = []

    def projection(entry):
        calls.append(entry['transaction_id'])
        if len(calls) == 2:
            raise RuntimeError('projection failed')

    with pytest.raises(RuntimeError):
        group_commit(pipe, batch, original_id, 'fail-group', projection=projection)
    assert ledger_state(pipe) == (0, 0)


def test_retry_of_the_same_request_does_not_duplicate_and_a_new_request_is_a_noop():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    confirm_other(pipe, batch)
    first = group_commit(pipe, batch, original_id, 'retry-1')
    assert group_commit(pipe, batch, original_id, 'retry-1') == first
    again = group_commit(pipe, batch, original_id, 'retry-2')
    assert again['applied'] == 0 and again['already'] == 2
    assert ledger_state(pipe) == (2, 300000)


def test_a_subset_of_the_batch_digest_or_a_non_refund_cannot_be_committed_as_a_group():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    confirm_other(pipe, batch)
    batch_digest = preview(pipe, batch)['digest']
    with pytest.raises(StoreError) as caught:
        pipe.commit(batch, batch_digest, 'subset-1', tab_validator=OK, trip_validator=OK,
                    group_original=original_id)
    assert caught.value.code == 'PREVIEW_STALE'
    other_id = pipe.store.conn.execute("SELECT transaction_id FROM transactions WHERE approval_number='300'").fetchone()[0]
    with pytest.raises(StoreError) as caught:
        group_of(pipe, batch, other_id)
    assert caught.value.code == 'INVALID_INPUT'
    assert ledger_state(pipe) == (0, 0)


def test_group_commit_against_a_batch_that_does_not_hold_the_group_is_rejected():
    pipe, batch = build(extra=True)
    original_id = confirm_original(pipe, batch)
    other_batch = pipe.receive((HEADER + '국민,1234,domestic,purchase,합성식당,9000,,,9000,2026-10-02,2026-10-03,O999,,매입\n').encode(),
                               'other.csv')['batch_id']
    pipe.classify_batch(other_batch)
    with pytest.raises(StoreError) as caught:
        group_of(pipe, other_batch, original_id)
    assert caught.value.code == 'REFUND_GROUP_INCOMPLETE'
    assert ledger_state(pipe) == (0, 0)


def test_a_fully_offset_pair_leaves_the_trip_for_the_refund_tab():
    from app.ledger import REFUND_TAB
    pipe, batch = build(refunds=(-1000000,))
    confirm_original(pipe, batch, tab='trip-x')
    decide_refund(pipe, batch, '200')
    result = preview(pipe, batch)
    rows = by_approval(pipe, result)
    assert rows['100']['display_tab_id'] == REFUND_TAB and rows['200']['display_tab_id'] == REFUND_TAB
    assert rows['100']['trip_id'] == '' and rows['200']['trip_id'] == ''


def test_committed_refund_analysis_is_reused_until_a_write_or_another_commit(tmp_path, monkeypatch):
    from app import partial_refund
    pipe, _ = build(refunds=(-700000,))
    conn = pipe.store.conn
    path = tmp_path / 'refunds.sqlite'
    conn.execute(f"VACUUM INTO '{path}'")
    conn = sqlite3.connect(path, isolation_level=None)
    other = sqlite3.connect(path, isolation_level=None)
    calls = []
    original = partial_refund._analyse
    monkeypatch.setattr(partial_refund, '_analyse', lambda c: calls.append(1) or original(c))
    ids = [r[0] for r in conn.execute('SELECT transaction_id FROM transactions')]
    first = partial_refund.refund_links(conn, ids)
    assert first and partial_refund.refund_links(conn, ids) == first and len(calls) == 1
    conn.execute("UPDATE transactions SET merchant=merchant||'' WHERE 1=1")
    partial_refund.refund_links(conn, ids)
    assert len(calls) == 2
    other.execute("UPDATE transactions SET original_approval_number='999' WHERE transaction_direction='cancellation'")
    assert partial_refund.refund_links(conn, ids) == {}
    assert len(calls) == 3


def test_an_uncommitted_refund_read_is_not_kept_after_rollback():
    from app import partial_refund
    pipe, _ = build(refunds=(-700000,))
    conn = pipe.store.conn
    ids = [r[0] for r in conn.execute('SELECT transaction_id FROM transactions')]
    before = partial_refund.refund_links(conn, ids)
    conn.execute('BEGIN')
    conn.execute("UPDATE transactions SET original_approval_number='999' WHERE transaction_direction='cancellation'")
    assert partial_refund.refund_links(conn, ids) == {}
    conn.execute('ROLLBACK')
    assert partial_refund.refund_links(conn, ids) == before
