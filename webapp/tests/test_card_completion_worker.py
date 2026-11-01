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


def test_new_trip_evidence_resumes_a_waiting_row_without_an_owner_request(setup):
    board = setup
    receive(board, 1, card='1234')
    worker = CardCompletionWorker(board, threading.RLock())
    assert worker.sweep_once()
    assert not worker.sweep_once()
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    board.create_trip(starts_on='2026-10-14', ends_on='2026-10-17',
                      destination='합성', client_request_id='new-synthetic-authority')
    assert worker.sweep_once()
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 1


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
    assert board.conn.execute('SELECT trip_id,amount_krw FROM ledger_entries').fetchall() == [(next_trip,10000)]
    assert '준비기간' in board.conn.execute('SELECT classification_basis FROM transactions').fetchone()[0]
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
