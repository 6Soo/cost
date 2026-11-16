import copy
import hashlib
import json

import pytest

from app import automatic_classification as policy
from app import reviewed_booking_evidence as reviewed
from tests.card_pipeline.fixtures import domestic_row, make_csv
from webapp.card_flow import CardFlow
from webapp.card_classification_completion import completed_period_evidence
from webapp.ledger_store import LedgerStore


@pytest.fixture
def booking(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '2026-04-01')
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda *args: True)
    monkeypatch.setattr(CardFlow, '_held_ota_snapshot', lambda *args: (None, False))
    monkeypatch.setattr(CardFlow, '_ota_report', lambda *args: {})
    monkeypatch.setattr(CardFlow, 'ota_group_holds', lambda *args, **kw: {})
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    flow = CardFlow(board)
    old = board.create_trip(starts_on='2026-01-01', ends_on='2026-01-05',
        destination='SYNTHETIC OLD', client_request_id='old')['tab_id']
    target = board.create_trip(starts_on='2026-07-12', ends_on='2026-07-16',
        destination='SYNTHETIC SERVICE', client_request_id='new')['tab_id']
    batch = flow.pipeline.receive(make_csv([domestic_row(merchant='SYNTHETIC AIR',
        amount=5000, approval=f'SYN-{i}', date='2026-01-02') for i in range(2)]), 'synthetic.csv')['batch_id']
    board.conn.execute("UPDATE transactions SET classification_source='inference',classification_state='classified',"
        "item='기타경비',trip_id=?,display_tab_id=?", (old, old))
    board.conn.commit()
    cards = [dict(transaction_id=r['transaction_id'], source_hash=r['source_hash'],
                  approval_date=r['approval_date'], amount_krw=r['amount_krw']) for r in policy._read(board.conn)]
    root = tmp_path / 'reviewed-bookings'
    root.mkdir()
    period = dict(starts_on='2026-07-12', ends_on='2026-07-16')
    originals = []
    for i in range(2):
        body = f'SYNTHETIC ORIGINAL {i} paid 2026-01-02 5000 KRW; service July12-16'.encode()
        (root / f'original-{i}.txt').write_bytes(body)
        originals.append(dict(path=f'original-{i}.txt', sha256=hashlib.sha256(body).hexdigest(),
            status='confirmed', service_period=period, payments=[dict(paid_on='2026-01-02', amount_krw=5000)]))
    manifest = dict(version=1, reviewer=dict(kind='ai_review', provider='synthetic', model='synthetic', run_id='syn'),
        groups=[dict(id='syn-group', trip_id=target, item='항공료', basis='synthetic original review',
            service_period=period, cards=cards, originals=originals)])
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    yield board, flow, batch, target, root, manifest
    board.close()


def test_source_review_reaches_real_ledger_and_board_exactly_once(booking):
    board, flow, batch, target, root, _ = booking
    originals = board.conn.execute('SELECT source_hash,amount_krw,raw_row_json,approval_date,decided_at FROM transactions').fetchall()
    trips = [dict(t, trip_id=t['tab_id']) for t in board.list_trips()]
    facts = completed_period_evidence(board, trips, flow)
    assert len(facts) == 2
    planned = policy.plan(board.conn, trips, evidence=facts)
    assert len(planned['targets']) == 2
    policy.apply(board.conn, planned, trips, evidence=facts)
    result = flow._auto_record_locked(batch, include_state=False)
    assert result['auto_recorded'] == 2
    assert board.conn.execute('SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries WHERE display_tab_id=?', (target,)).fetchone() == (2, 10000)
    rows = board.list_tab_rows(target)
    assert len(rows) == 2 and sum(r['amount_krw'] for r in rows) == 10000
    assert all(r['service_period'] == '2026-07-12~2026-07-16' and not r.get('booking_ref') for r in rows)
    assert all(r['ota_evidence']['individual_payment_link'] is False for r in rows)
    assert flow._auto_record_locked(batch, include_state=False)['auto_recorded'] == 0
    assert board.conn.execute('SELECT source_hash,amount_krw,raw_row_json,approval_date,decided_at FROM transactions').fetchall() == originals


@pytest.mark.parametrize('defect', ['file', 'hash', 'date', 'amount', 'period', 'missing_card', 'duplicate_card', 'escape'])
def test_stale_or_ambiguous_review_never_reaches_a_financial_write(booking, defect):
    board, flow, batch, target, root, manifest = booking
    group = manifest['groups'][0]
    if defect == 'file':
        (root / 'original-0.txt').write_text('tampered', encoding='utf-8')
    elif defect == 'hash':
        group['cards'][0]['source_hash'] = 'stale'
    elif defect == 'date':
        group['originals'][0]['payments'][0]['paid_on'] = '2026-01-03'
    elif defect == 'amount':
        group['originals'][0]['payments'][0]['amount_krw'] = 10000
    elif defect == 'period':
        group['service_period'] = dict(starts_on='2026-08-01', ends_on='2026-08-02')
    elif defect == 'missing_card':
        group['cards'].pop()
        group['originals'].pop()
    elif defect == 'duplicate_card':
        group['cards'][1] = copy.deepcopy(group['cards'][0])
    elif defect == 'escape':
        group['originals'][0]['path'] = '../board.sqlite'
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    before = board.conn.total_changes
    with pytest.raises(ValueError):
        completed_period_evidence(board, board.list_trips(), flow)
    assert board.conn.total_changes == before
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_manual_decision_remains_protected_with_valid_review(booking):
    board, flow, _, _, _, _ = booking
    board.conn.execute("UPDATE transactions SET classification_source='user_decision',decided_at='2026-11-17'")
    board.conn.commit()
    facts = completed_period_evidence(board, board.list_trips(), flow)
    assert policy.plan(board.conn, board.list_trips(), evidence=facts)['targets'] == []


def test_central_source_conflict_stops_completion(booking, monkeypatch):
    board, flow, _, target, _, manifest = booking
    from app import closed_period
    card = manifest['groups'][0]['cards'][0]
    monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: ({'synthetic': True}, True))
    monkeypatch.setattr(flow, '_canonical_snapshot_report', lambda *args: {'matches': []})
    monkeypatch.setattr(closed_period, 'formal_facts', lambda *args: {card['transaction_id']: dict(
        source_hash=card['source_hash'], trip_id=target, service_period=dict(starts_on='2026-07-13', ends_on='2026-07-16'))})
    with pytest.raises(ValueError, match='REVIEWED_BOOKING_CORE_CONFLICT'):
        completed_period_evidence(board, board.list_trips(), flow)


def test_durable_worker_rejudges_old_calendar_assignment_before_booking(booking):
    from webapp.card_completion_worker import CardCompletionWorker, queue_batch
    board, flow, batch, target, _, manifest = booking
    ids = {c['transaction_id'] for c in manifest['groups'][0]['cards']}
    queue_batch(board, batch, ids)
    worker = CardCompletionWorker(board, board._lock, flow_factory=lambda _: flow)
    assert worker.sweep_once() is True
    assert worker.status['recorded'] == 2 and worker.status['failures'] == 0
    assert board.conn.execute('SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries WHERE display_tab_id=?', (target,)).fetchone() == (2, 10000)
    assert worker.sweep_once() is False


@pytest.mark.parametrize('store', ['ledger', 'board'])
def test_previously_recorded_closed_trip_is_never_recovered(booking, store):
    board, flow, batch, _, _, manifest = booking
    row = policy._read(board.conn, [manifest['groups'][0]['cards'][0]['transaction_id']])[0]
    tid = row['transaction_id']
    if store == 'board':
        board.conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
            ('card-'+tid, 'expense', row['display_tab_id'], 1, json.dumps(dict(row_id='card-'+tid))))
    else:
        board.conn.execute('INSERT INTO ledger_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, batch, row['item'], '', row['display_tab_id'], row['trip_id'], row['amount_krw'],
             row['merchant'], row['approval_date'], 'purchase', row['source_hash'], '2026-11-17'))
    board.conn.commit()
    trips = [dict(t, trip_id=t['tab_id']) for t in board.list_trips()]
    facts = completed_period_evidence(board, trips, flow)
    before = board.conn.total_changes
    assert policy.plan(board.conn, trips, transaction_ids=[tid], evidence=facts)['targets'] == []
    assert board.conn.total_changes == before

