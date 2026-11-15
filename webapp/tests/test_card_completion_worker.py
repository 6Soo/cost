import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tests.card_pipeline.fixtures import make_csv, domestic_row
from webapp import ledger_board
from webapp.card_flow import CardFlow
from webapp.card_completion_worker import CardCompletionWorker, candidates, enabled_for, queue_batch
from webapp.ledger_store import LedgerStore

REAL_METADATA = CardFlow.preview_metadata
REAL_OTA_HOLDS = CardFlow.ota_group_holds


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', 'legacy')
    monkeypatch.delenv('WEBLEDGER_CARD_COMPLETION', raising=False)
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: True)
    monkeypatch.setattr(CardFlow, 'ota_group_holds', lambda self: {})
    monkeypatch.setattr(CardFlow, 'preview_metadata', lambda self, **kw: None)
    board = LedgerStore(tmp_path/'board.sqlite', seed_demo=False)
    yield board
    board.close()


def receive(board, count=3, card='3820', suffix=''):
    flow = CardFlow(board)
    batch = flow.pipeline.receive(make_csv([
        domestic_row(merchant='Booking.com SYNTHETIC '+suffix+str(i), amount=10000+i,
                     approval='SYNTHETIC'+suffix+str(i), date='2026-10-14', kind='매입',
                     issuer='국민', card='****'+card) for i in range(count)]), 'synthetic.csv')['batch_id']
    return batch, flow.pipeline.get_batch(batch)['rows']


def snapshot_originals(board):
    return board.conn.execute('SELECT transaction_id,source_hash,raw_row_json,amount_krw,approval_number,approval_date,posting_date,decided_at FROM transactions ORDER BY transaction_id').fetchall()


@pytest.mark.parametrize('entrypoint', ['worker', 'auto_record'])
def test_category_only_booking_recovers_using_service_period_not_card_date(setup, monkeypatch, entrypoint):
    board = setup
    batch, rows = receive(board, 1, card='1234')
    row = rows[0]
    board.create_trip(starts_on='2026-10-14', ends_on='2026-10-17',
                      destination='결제일 여행', client_request_id='payment-date-trip')
    service_trip = board.create_trip(starts_on='2026-11-01', ends_on='2026-11-04',
                      destination='예약 이용일 여행', client_request_id='service-trip')['tab_id']
    board.conn.execute("UPDATE transactions SET classification_state='classified',"
                       "classification_source='rule',item='숙박비',trip_id='',display_tab_id=''")
    board.conn.commit()
    original = snapshot_originals(board)
    report = {'matches': [dict(transaction_id=row['transaction_id'], source_hash=row['source_hash'],
        booking_ref='90000000001', item='숙박비', reservation_status='confirmed',
        period=dict(starts_on='2026-11-01', ends_on='2026-11-02'), source_digests=['a'*64])],
        'rules': [dict(conditions=dict(merchant_normalized=row['merchant_normalized'],
            transaction_direction='purchase'), optional=dict(source_hash=row['source_hash']),
            effects=dict(item='숙박비'))], 'type_only_candidates': []}
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', 'isolated')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(board.path.parent/'ota.sqlite'))
    monkeypatch.setattr(CardFlow, '_held_ota_snapshot', lambda self: ({'generation': 1}, True))
    monkeypatch.setattr(CardFlow, '_canonical_snapshot_report', lambda self, current: report)
    monkeypatch.setattr(CardFlow, '_ota_report', lambda self: report)
    monkeypatch.setattr(CardFlow, '_compute_ota_report', lambda self: pytest.fail('raw scan'))
    other_before = None
    if entrypoint == 'auto_record':
        _, other = receive(board, 1, card='1234', suffix='other-batch')
        other_id = other[0]['transaction_id']
        other_before = board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?', (other_id,)).fetchone()
        original = snapshot_originals(board)
    before = board.conn.execute('SELECT * FROM transactions').fetchall()
    # Reads must neither classify nor enqueue this historical incomplete row.
    CardFlow(board).state(batch)
    assert board.conn.execute('SELECT * FROM transactions').fetchall() == before
    if entrypoint == 'worker':
        assert len(candidates(board.conn)) == 1
        worker = CardCompletionWorker(board, threading.RLock())
        assert worker.sweep_once() and worker.status['failures'] == 0
        assert not worker.sweep_once()
    else:
        assert CardFlow(board).auto_record(batch)['auto_recorded'] == 1
        assert CardFlow(board).auto_record(batch)['auto_recorded'] == 0
    assert board.conn.execute('SELECT trip_id,amount_krw,item FROM ledger_entries').fetchall() == [(service_trip,10000,'숙박비')]
    assert snapshot_originals(board) == original
    assert not board.conn.execute('SELECT 1 FROM review_decisions').fetchone()
    if other_before:
        assert board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?', (other_id,)).fetchone() == other_before


def test_category_only_recovery_preserves_all_protected_rows(setup):
    board = setup
    _, rows = receive(board, 9, card='1234')
    c = board.conn
    c.execute("UPDATE transactions SET classification_state='classified',classification_source='rule',item='숙박비',trip_id='',display_tab_id=''")
    c.execute("UPDATE transactions SET classification_source='user_decision' WHERE transaction_id=?", (rows[0]['transaction_id'],))
    c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)', (rows[1]['transaction_id'],rows[1]['source_hash'],'user_hold','synthetic'))
    c.execute("UPDATE transactions SET duplicate_of='synthetic' WHERE transaction_id=?", (rows[2]['transaction_id'],))
    c.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?", (rows[3]['transaction_id'],))
    c.execute("UPDATE transactions SET transaction_direction='cancellation',original_approval_number=? WHERE transaction_id=?", (rows[4]['approval_number'],rows[5]['transaction_id']))
    c.execute("UPDATE transactions SET conflict_reason='synthetic' WHERE transaction_id=?", (rows[6]['transaction_id'],))
    c.execute("UPDATE transactions SET classification_source='guide_airfare_evidence',item='항공료' WHERE transaction_id=?", (rows[7]['transaction_id'],))
    c.execute("UPDATE transactions SET item='분기 기타비용',display_tab_id='quarter:2026:4' WHERE transaction_id=?", (rows[8]['transaction_id'],))
    c.commit()
    before=c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    assert candidates(c)==[]
    assert not CardCompletionWorker(board,threading.RLock()).sweep_once()
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()==before


def test_assigned_historical_purchase_is_not_a_new_backfill_job(setup):
    board=setup
    receive(board,1,card='1234')
    trip=board.create_trip(starts_on='2026-10-14',ends_on='2026-10-17',
        destination='기존 배정',client_request_id='historical-trip')['tab_id']
    board.conn.execute("UPDATE transactions SET classification_state='classified',classification_source='rule',item='숙박비',trip_id=?,display_tab_id=?",(trip,trip))
    board.conn.commit()
    before=board.conn.execute('SELECT * FROM transactions').fetchall()
    assert candidates(board.conn)==[]
    assert not CardCompletionWorker(board,threading.RLock()).sweep_once()
    assert board.conn.execute('SELECT * FROM transactions').fetchall()==before


def test_no_request_needed_and_chunks_survive_a_new_worker(setup):
    board = setup
    _, rows = receive(board)
    original = snapshot_originals(board)
    worker = CardCompletionWorker(board, threading.RLock(), chunk=2)
    assert worker.sweep_once()
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 2
    # New process/worker reconstructs the remaining work from imported rows.
    restarted = CardCompletionWorker(board, threading.RLock(), chunk=2)
    assert restarted.sweep_once()
    assert not restarted.sweep_once()
    assert board.conn.execute('SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries').fetchone() == (3, 30003)
    assert board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 3
    assert snapshot_originals(board) == original
    assert all(json.loads(r[0])['confirmed_by']=='automatic' for r in board.conn.execute('SELECT payload_json FROM board_rows'))


def test_completed_historical_classifications_are_not_a_backfill_job(setup):
    board = setup
    batch,rows = receive(board,3)
    board.conn.execute("UPDATE transactions SET classification_state='classified',item='분기 기타비용',display_tab_id='quarter:2026:4'")
    board.conn.commit()
    assert candidates(board.conn)==[]
    # Only a persisted, exact processing job may resume after classification.
    queue_batch(board,batch,{rows[0]['transaction_id']})
    worker = CardCompletionWorker(board,threading.RLock())
    assert worker.sweep_once()
    assert not worker.sweep_once()
    assert board.conn.execute('SELECT transaction_id FROM ledger_entries').fetchall()==[(rows[0]['transaction_id'],)]


def test_transient_recording_failure_backs_off_and_retries_saved_classification(setup, monkeypatch):
    board = setup
    receive(board, 1)
    original = snapshot_originals(board)
    clock = [0]
    attempts = []
    record = CardFlow._auto_record_locked

    def fail_once(self, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError('synthetic transient failure')
        return record(self, *args, **kwargs)

    monkeypatch.setattr(CardFlow, '_auto_record_locked', fail_once)
    worker = CardCompletionWorker(board, threading.RLock(), clock=lambda: clock[0])
    assert worker.sweep_once() and worker.status['state']=='retry'
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    assert not worker.sweep_once() and len(attempts)==1
    clock[0] = 5
    assert worker.sweep_once() and len(attempts)==2
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 1
    assert not worker.sweep_once()
    assert snapshot_originals(board)==original


def test_no_trip_finishes_in_quarter_and_new_trip_does_not_duplicate_entry(setup):
    board = setup
    receive(board, 1, card='1234')
    worker = CardCompletionWorker(board, threading.RLock())
    assert worker.sweep_once()
    assert not worker.sweep_once()
    # The final-destination contract completes in the payment quarter when no
    # actual trip exists. It must never leave an owner-facing waiting row.
    original = board.conn.execute('SELECT trip_id,amount_krw FROM ledger_entries').fetchall()
    assert original == [('', 10000)]  # Only actual trips occupy ledger trip_id.
    assert board.conn.execute('SELECT display_tab_id FROM transactions').fetchone()[0] == 'quarter:2026:4'
    board.create_trip(starts_on='2026-10-14', ends_on='2026-10-17',
                      destination='합성', client_request_id='new-synthetic-authority')
    assert not worker.sweep_once()
    assert board.conn.execute('SELECT trip_id,amount_krw FROM ledger_entries').fetchall() == original


@pytest.mark.parametrize('day,next_start,previous_end,destination', [
    ('2026-10-14', '2026-10-15', '2026-10-13', '오제'),
    ('2026-10-25', '2026-10-26', '2026-10-24', '가루이자와')])
def test_preparation_costs_complete_without_a_request_and_replay_once(setup, day, next_start, previous_end, destination):
    board = setup
    flow = CardFlow(board)
    batch = flow.pipeline.receive(make_csv([domestic_row(
        merchant='SYNTHETIC PREPARATION SERVICE', amount=10000,
        approval='PREP', date=day, kind='매입', issuer='국민', card='****3820')]), 'preparation.csv')['batch_id']
    board.conn.execute("UPDATE transactions SET foreign_currency='JPY',card_kind='해외'")
    board.create_trip(starts_on='2026-10-10', ends_on=previous_end,
                      destination='도쿠시마', client_request_id='prep-previous')
    next_trip = board.create_trip(starts_on=next_start, ends_on='2026-10-30',
                                 destination=destination, client_request_id='prep-next')['tab_id']
    original = snapshot_originals(board)
    worker = CardCompletionWorker(board, threading.RLock())
    assert worker.sweep_once()
    assert board.conn.execute('SELECT trip_id,amount_krw FROM ledger_entries').fetchall() == [('',10000)]
    assert '분기 기타비용' in board.conn.execute('SELECT classification_basis FROM transactions').fetchone()[0]
    assert not worker.sweep_once()
    assert snapshot_originals(board) == original


def test_manual_hold_duplicate_parse_and_refund_original_are_unchanged(setup):
    board = setup
    _, rows = receive(board, 6)
    c = board.conn
    c.execute("UPDATE transactions SET decided_at='synthetic',classification_source='user_decision' WHERE transaction_id=?", (rows[0]['transaction_id'],))
    c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)', (rows[1]['transaction_id'],rows[1]['source_hash'],'user_hold','synthetic'))
    c.execute("UPDATE transactions SET duplicate_of='synthetic-original' WHERE transaction_id=?", (rows[2]['transaction_id'],))
    c.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?", (rows[3]['transaction_id'],))
    # A refund protects its original, and a cancellation is not a purchase job.
    c.execute("UPDATE transactions SET transaction_direction='cancellation',original_approval_number=? WHERE transaction_id=?", (rows[4]['approval_number'],rows[5]['transaction_id']))
    c.commit()
    before = c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    assert candidates(c)==[]
    assert not CardCompletionWorker(board, threading.RLock()).sweep_once()
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()==before


def test_background_never_parses_raw_mail_or_runs_request_reconciliation(setup, monkeypatch):
    board = setup
    receive(board, 1)
    def forbidden(*args, **kwargs):
        raise AssertionError('unbounded source scan in writer lock')
    monkeypatch.setattr(CardFlow, '_compute_ota_report', forbidden)
    monkeypatch.setattr(CardFlow, '_evidence_period_assignments', forbidden)
    monkeypatch.setattr(CardFlow, 'preview_metadata', REAL_METADATA)
    monkeypatch.setattr(CardFlow, 'ota_group_holds', REAL_OTA_HOLDS)
    worker = CardCompletionWorker(board, threading.RLock())
    assert worker.sweep_once()
    assert worker.status['recorded']==1 and worker.status['failures']==0


def test_one_failed_chunk_cannot_starve_later_rows(setup, monkeypatch):
    board = setup
    _, rows = receive(board, 3)
    classify = CardFlow._classify
    failures = {rows[0]['transaction_id']}
    def fail_first(self, batch, **kwargs):
        if kwargs['transaction_ids'] & failures:
            raise OSError('synthetic first row failure')
        return classify(self,batch,**kwargs)
    monkeypatch.setattr(CardFlow,'_classify',fail_first)
    worker = CardCompletionWorker(board,threading.RLock(),chunk=1)
    assert worker.sweep_once()
    assert worker.sweep_once()
    assert worker.sweep_once()
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==2
    assert not worker.sweep_once()


def test_background_obeys_the_http_writer_lock(setup):
    board = setup
    receive(board,1)
    runtime_lock = threading.RLock()
    worker = CardCompletionWorker(board,runtime_lock)
    with runtime_lock:
        worker.start()
        threading.Event().wait(.05)
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        with runtime_lock:
            count = board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
        if count:
            break
        threading.Event().wait(.01)
    worker.stop()
    assert count==1 and not worker.running


def test_projection_failure_is_atomic_and_does_not_duplicate_on_retry(setup, monkeypatch):
    board = setup
    receive(board, 2)
    project = CardFlow.project
    calls = []
    def broken(self, entry):
        calls.append(1)
        if len(calls)==2:
            raise OSError('synthetic projection failure')
        return project(self, entry)
    monkeypatch.setattr(CardFlow, 'project', broken)
    worker = CardCompletionWorker(board, threading.RLock())
    assert worker.sweep_once()
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
    assert board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0]==0
    monkeypatch.setattr(CardFlow, 'project', project)
    assert CardCompletionWorker(board, threading.RLock()).sweep_once()
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==2


def test_activation_is_explicit_and_receive_failure_recovers_without_a_second_request(setup, monkeypatch, tmp_path):
    assert not enabled_for(setup)
    monkeypatch.setenv('WEBLEDGER_CARD_COMPLETION','1')
    assert enabled_for(setup)
    ledger_board.bind_access(None)
    original_store = ledger_board._STORE
    server = ledger_board.serve(port=0,db_path=tmp_path/'http.sqlite',with_worker=False,seed_demo=False)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        def interrupted(*args, **kwargs):
            raise OSError('synthetic synchronous upload interrupted')
        monkeypatch.setattr(CardFlow,'classify',interrupted)
        payload = make_csv([domestic_row(merchant='Booking.com SYNTHETIC HTTP',amount=10001,
            approval='HTTP1',date='2026-10-14',kind='매입',issuer='국민',card='****3820')])
        request = Request(f'http://127.0.0.1:{server.server_address[1]}/api/imports',data=payload,
            headers={'Content-Type':'application/octet-stream','X-Filename':'synthetic.csv','X-CSRF-Token':ledger_board.CSRF_TOKEN})
        with pytest.raises(HTTPError) as response:
            urlopen(request,timeout=5)
        assert response.value.code==503
        result = json.load(response.value)
        assert result['automatic_recovery_scheduled'] and not result['retry_same_file']
        deadline = time.monotonic()+5
        recorded = 0
        while time.monotonic()<deadline:
            with server.store_lock:
                recorded = server.card_store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
            if recorded:
                break
            threading.Event().wait(.02)
        assert recorded==1
    finally:
        server.shutdown()
        server.server_close()
        assert not server.card_worker.running
        server.card_store.close()
        thread.join(3)
        ledger_board.bind_store(original_store)


def test_worker_start_failure_closes_new_runtime_and_preserves_existing_store(setup, monkeypatch, tmp_path):
    from webapp import card_completion_worker
    monkeypatch.setenv('WEBLEDGER_CARD_COMPLETION','1')
    previous_store = ledger_board._STORE
    previous_importer = ledger_board._IMPORTER
    def fail(self):
        raise RuntimeError('synthetic thread unavailable')
    monkeypatch.setattr(card_completion_worker.CardCompletionWorker,'start',fail)
    with pytest.raises(RuntimeError,match='synthetic thread unavailable'):
        ledger_board.serve(port=0,db_path=tmp_path/'startup.sqlite',with_worker=False,seed_demo=False)
    assert ledger_board._STORE is previous_store
    assert ledger_board._IMPORTER is previous_importer


def test_host_activation_cannot_be_overridden_by_an_inherited_environment(tmp_path, monkeypatch):
    from types import SimpleNamespace
    fake = SimpleNamespace(path=tmp_path/'data/board.sqlite')
    folder=tmp_path/'config'
    folder.mkdir()
    config=folder/'card-flow.json'
    monkeypatch.setenv('WEBLEDGER_CARD_COMPLETION','1')
    config.write_text('{"automatic_card_completion":false}',encoding='utf-8')
    assert not enabled_for(fake)
    config.write_text('invalid',encoding='utf-8')
    assert not enabled_for(fake)
    config.write_text('{"automatic_card_completion":true}',encoding='utf-8')
    assert enabled_for(fake)


def test_resume_keeps_saved_guide_evidence_and_its_live_recording_guard(setup, monkeypatch):
    board = setup
    batch,rows = receive(board,1)
    trip=board.create_trip(starts_on='2026-10-14',ends_on='2026-10-17',destination='합성',client_request_id='guide-trip')['tab_id']
    board.conn.execute("UPDATE transactions SET classification_state='classified',classification_source='guide_airfare_evidence',classification_basis='synthetic verified guide evidence',item='항공료',display_tab_id=?,trip_id=?",(trip,trip))
    board.conn.commit()
    queue_batch(board,batch,{rows[0]['transaction_id']})
    before=board.conn.execute('SELECT * FROM transactions').fetchall()
    monkeypatch.setattr(CardFlow,'ota_group_holds',REAL_OTA_HOLDS)
    def no_basic_reclassification(*args,**kwargs):
        raise AssertionError('saved classification must not be erased on restart')
    monkeypatch.setattr(CardFlow,'_classify',no_basic_reclassification)
    worker=CardCompletionWorker(board,threading.RLock())
    assert worker.sweep_once()
    assert worker.status['failures']==0
    assert board.conn.execute('SELECT * FROM transactions').fetchall()==before
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0


def _unnarrowed_preview(flow, batch, selected):
    """The preview an automatic chunk used before it was narrowed: the whole batch, everything else held."""
    from app.ledger import recordable_rows
    options = dict(trip_validator=flow.trip_valid, tab_validator=flow.tab_valid, review_from=None,
                   entry_metadata=flow.preview_metadata(), include_verified_full_refunds=False,
                   additional_holds=flow.automatic_holds(batch))
    options['additional_holds'].update({row[0]: {'kind': 'completion_scope', 'reason': 'x'}
        for row in flow.board.conn.execute('SELECT transaction_id FROM transactions') if row[0] not in selected})
    return recordable_rows(flow.pipeline.preview(batch, **options)['rows'])


def _narrowed_preview(flow, batch, selected):
    from app.ledger import recordable_rows
    scope = flow._refund_scope(batch, selected)
    options = dict(trip_validator=flow.trip_valid, tab_validator=flow.tab_valid, review_from=None,
                   entry_metadata=flow.preview_metadata(), include_verified_full_refunds=False,
                   additional_holds=flow.automatic_holds(batch, scope=scope), transaction_ids=frozenset(scope[0]))
    options['additional_holds'].update({tid: {'kind': 'completion_scope', 'reason': 'x'}
                                        for tid in scope[0] if tid not in selected})
    return recordable_rows(flow.pipeline.preview(batch, **options)['rows'])


@pytest.mark.parametrize('booked_original', [False, True])
def test_narrowed_preview_records_exactly_what_the_whole_batch_preview_did(setup, booked_original):
    board = setup
    batch, rows = receive(board, 6, card='1234')
    ids = [r['transaction_id'] for r in rows]
    c = board.conn
    c.execute("UPDATE transactions SET classification_state='classified',classification_source='rule',item='식비',"
              "display_tab_id='quarter:2026:4',trip_id=''")
    c.execute("UPDATE transactions SET transaction_direction='cancellation',original_approval_number=?,amount_krw=?"
              " WHERE transaction_id=?", (rows[0]['approval_number'], -rows[0]['amount_krw'], ids[1]))
    c.execute("UPDATE transactions SET classification_state='needs_review',item='' WHERE transaction_id=?", (ids[2],))
    c.commit()
    flow = CardFlow(board)
    if booked_original:
        scope = flow._refund_scope(batch, {ids[0]})
        assert set(ids[:2]) <= scope[0]
        flow._auto_record_locked(batch, include_state=False, transaction_ids={ids[0], ids[1]})
    for selected in ({ids[0]}, {ids[1]}, {ids[0], ids[1]}, {ids[2]}, {ids[3], ids[4]}, set(ids)):
        old = {r['transaction_id']: r for r in _unnarrowed_preview(flow, batch, selected)}
        new = {r['transaction_id']: r for r in _narrowed_preview(flow, batch, selected)}
        assert set(new) == set(old), selected
        assert {k: (v['item'], v['display_tab_id'], v['amount_krw']) for k, v in new.items()} == \
               {k: (v['item'], v['display_tab_id'], v['amount_krw']) for k, v in old.items()}


def test_worker_chunk_reads_and_previews_only_the_selected_rows(setup):
    board = setup
    batch, rows = receive(board, 12, card='1234')
    seen = {'get_batch': [], 'preview': [], 'commit': []}

    def instrumented(store):
        flow = CardFlow(store)
        pipeline = flow.pipeline
        for name in seen:
            original = getattr(pipeline, name)

            def wrapper(*args, _original=original, _name=name, **kwargs):
                seen[_name].append(kwargs.get('transaction_ids'))
                return _original(*args, **kwargs)
            setattr(pipeline, name, wrapper)
        return flow

    worker = CardCompletionWorker(board, threading.RLock(), chunk=4, flow_factory=instrumented)
    assert worker.sweep_once() and worker.status['failures'] == 0
    assert seen['preview'] and seen['get_batch']
    # No call under the store lock reads or previews the whole batch.
    assert all(value is not None and len(value) <= 4 for value in seen['get_batch'] + seen['preview'] + seen['commit'])
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 4


def test_narrowed_chunk_equals_the_old_result_after_a_full_drain(setup):
    board = setup
    receive(board, 9, card='1234')
    worker = CardCompletionWorker(board, threading.RLock(), chunk=4)
    while worker.sweep_once():
        pass
    assert worker.status['failures'] == 0
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 9
    assert candidates(board.conn) == []


def _refund_cases(board):
    """Multi partial refunds, an inferred link, an excess refund and a group with sibling cancellations."""
    batch, rows = receive(board, 14, card='1234')
    ids = [r['transaction_id'] for r in rows]
    c = board.conn
    c.execute("UPDATE transactions SET classification_state='classified',classification_source='rule',item='식비',"
              "display_tab_id='quarter:2026:4',trip_id='',amount_krw=100000")
    def cancel(index, original_index, amount, original_number=True):
        c.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=?,original_approval_number=?"
                  " WHERE transaction_id=?", (amount, rows[original_index]['approval_number'] if original_number else '', ids[index]))
    cancel(1, 0, -25000); cancel(2, 0, -25000)                       # two partial refunds of one original
    cancel(4, 3, -150000)                                            # excess
    c.execute("UPDATE transactions SET merchant='INFER SHOP',merchant_normalized='INFER SHOP'"
              " WHERE transaction_id IN (?,?)", (ids[5], ids[6]))
    cancel(6, 5, -100000, original_number=False)                     # inferred (same card, day, merchant, amount)
    cancel(8, 7, -50000); cancel(9, 7, -50000)                       # full offset by two sibling cancellations
    c.execute("UPDATE transactions SET merchant='FX SHOP',merchant_normalized='FX SHOP',foreign_currency='USD',foreign_amount='50'"
              " WHERE transaction_id IN (?,?)", (ids[12], ids[13]))
    cancel(13, 12, -100000, original_number=False)                   # inferred by foreign amount
    c.execute("UPDATE transactions SET classification_state='needs_review',item='' WHERE transaction_id=?", (ids[11],))
    c.commit()
    return batch, ids


def test_refund_cases_are_really_linked(setup):
    from app.partial_refund import all_refund_links
    _, ids = _refund_cases(setup)
    links = all_refund_links(setup.conn)
    assert {links[ids[1]]['status'], links[ids[4]]['status'], links[ids[8]]['status']} == {'partial', 'excess', 'full'}
    assert links[ids[1]]['refund_count'] == 2 and links[ids[8]]['refund_count'] == 2
    assert 'basis' in links[ids[6]] and links[ids[6]]['original_id'] == ids[5]
    assert links[ids[13]]['basis'] == 'merchant_card_foreign_amount' and links[ids[13]]['original_id'] == ids[12]


@pytest.mark.parametrize('booked_first', [False, True])
def test_narrowed_preview_matches_the_whole_batch_for_refund_groups(setup, booked_first):
    board = setup
    batch, ids = _refund_cases(board)
    flow = CardFlow(board)
    if booked_first:
        flow._auto_record_locked(batch, include_state=False, transaction_ids={ids[0], ids[1], ids[2], ids[7], ids[8], ids[9]})
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] >= 1
    selections = [{i} for i in ids] + [{ids[1], ids[2]}, {ids[8]}, {ids[0], ids[3], ids[5], ids[7]},
                                       {ids[2], ids[4], ids[6], ids[9], ids[10]}, set(ids[:4]), set(ids[4:9]), {ids[12]}, {ids[13]}, set(ids)]
    for selected in selections:
        old = {r['transaction_id']: r for r in _unnarrowed_preview(flow, batch, selected)}
        new = {r['transaction_id']: r for r in _narrowed_preview(flow, batch, selected)}
        assert set(new) == set(old), selected
        assert {k: (v['item'], v['display_tab_id'], v['amount_krw'], v.get('refund_link', {}).get('status')) for k, v in new.items()} == \
               {k: (v['item'], v['display_tab_id'], v['amount_krw'], v.get('refund_link', {}).get('status')) for k, v in old.items()}


def test_merged_classification_and_narrow_refresh_leave_the_same_database(setup, tmp_path, monkeypatch):
    """One `_classify` over unfinished + category-only rows equals the old two calls."""
    def build(path):
        board = LedgerStore(path, seed_demo=False)
        batch, rows = receive(board, 8, card='1234')
        board.create_trip(starts_on='2026-10-14', ends_on='2026-10-17', destination='결제일 여행', client_request_id='t')
        board.conn.execute("UPDATE transactions SET classification_state='classified',classification_source='rule',item='숙박비',trip_id='',display_tab_id=''"
                           " WHERE rowid%2=0")
        board.conn.commit()
        return board
    def dump(board):
        return (board.conn.execute('SELECT transaction_id,classification_state,classification_source,item,display_tab_id,trip_id,revision FROM transactions ORDER BY transaction_id').fetchall(),
                board.conn.execute('SELECT transaction_id,item,display_tab_id,trip_id,amount_krw FROM ledger_entries ORDER BY transaction_id').fetchall())
    def same(a, b):
        # Trip ids are generated per database: compare them by role.
        def norm(dump_):
            return [[('TRIP' if isinstance(v, str) and v.startswith('trip-') else v) for v in row] for part in dump_ for row in part]
        return norm(a) == norm(b)
    merged = build(tmp_path / 'a.sqlite')
    split = build(tmp_path / 'b.sqlite')
    try:
        original = CardFlow._classify

        def two_calls(self, batch, *, transaction_ids=None, **kw):
            rows = {r[0]: r for r in self.board.conn.execute('SELECT transaction_id,classification_state,item FROM transactions')}
            first = {t for t in transaction_ids if rows[t][1] != 'classified' or not rows[t][2]}
            result = None
            for part in (first, set(transaction_ids) - first):
                if part:
                    result = original(self, batch, transaction_ids=part, **kw)
            return result
        calls = []
        def counted(self, batch, **kw):
            calls.append(len(kw['transaction_ids']))
            return original(self, batch, **kw)
        monkeypatch.setattr(CardFlow, '_classify', counted)
        w = CardCompletionWorker(merged, threading.RLock())
        while w.sweep_once():
            pass
        monkeypatch.setattr(CardFlow, '_classify', two_calls)
        w = CardCompletionWorker(split, threading.RLock())
        while w.sweep_once():
            pass
        assert len(calls) == 1 and calls[0] == 8
        assert same(dump(merged), dump(split)) and len(dump(merged)[1]) == 8
    finally:
        merged.close(); split.close()


def test_finish_jobs_looks_only_at_the_rows_a_pending_job_names(setup):
    from webapp.card_completion_worker import finish_jobs
    board = setup
    batch, rows = receive(board, 4, card='1234')
    ids = [r['transaction_id'] for r in rows]
    queue_batch(board, batch, set(ids[:2]))
    pending = lambda: json.loads(board.conn.execute("SELECT response_json FROM requests WHERE scope='card_completion_job'").fetchone()[0])['pending']
    finish_jobs(board)
    assert pending()  # its rows are still unfinished
    for tid, source_hash in board.conn.execute('SELECT transaction_id,source_hash FROM transactions WHERE transaction_id IN (?,?)', ids[:2]).fetchall():
        board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)', (tid, source_hash, 'user_hold', 'synthetic'))
    board.conn.commit()
    assert {r[0] for r in candidates(board.conn)} == set(ids[2:])  # the other rows are unfinished but not this job's
    finish_jobs(board)
    assert not pending()
    assert candidates(board.conn, set(ids[:2])) == []
    assert {r[0] for r in candidates(board.conn, set(ids[2:]))} == set(ids[2:])
