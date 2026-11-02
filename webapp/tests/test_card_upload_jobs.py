"""A slow classification must not keep POST or progress behind the writer lock."""
import json
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

from tests.card_pipeline.fixtures import domestic_row, make_csv
from webapp import card_flow, card_upload_jobs, ledger_board
from webapp.ledger_store import LedgerStore


def test_http_ack_and_progress_while_classifier_holds_writer(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', 'legacy')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    monkeypatch.setattr(ledger_board, 'ACCESS_ENFORCEMENT', False)
    entered, release = threading.Event(), threading.Event()
    def slow_classify(self, batch):
        entered.set()
        assert release.wait(10)
    monkeypatch.setattr(card_flow.CardFlow, 'classify', slow_classify)
    monkeypatch.setattr(card_flow.CardFlow, 'auto_record', lambda self, batch: {'batch_id': batch})
    monkeypatch.setattr(card_flow.CardFlow, 'state', lambda *a: (_ for _ in ()).throw(AssertionError('unused preview')))
    from app import upload_reconciliation
    from webapp import card_classification_completion
    monkeypatch.setattr(card_classification_completion, 'context', lambda flow: ([], {}))
    monkeypatch.setattr(upload_reconciliation, 'summarize', lambda *a, **k: {'status': 'passed'})
    from webapp import card_completion_worker
    monkeypatch.setattr(card_completion_worker, 'finish_jobs', lambda board: None)
    previous_store = ledger_board._STORE
    server = ledger_board.serve(db_path=tmp_path/'board.sqlite', host='127.0.0.1', port=0, with_worker=False, seed_demo=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:'+str(server.server_port)
    raw = make_csv([domestic_row(merchant='SYNTHETIC CAFE', amount=10000, approval='SYNTH001', issuer='국민', card='****3820', kind='매입')])
    headers = {'X-CSRF-Token': ledger_board.CSRF_TOKEN, 'X-Filename': 'synthetic.csv', 'X-Upload-Async': '1'}
    try:
        began = time.monotonic()
        with urlopen(Request(base+'/api/imports', data=raw, headers=headers), timeout=5) as response:
            assert response.status == 202
            ack = json.load(response)
        assert time.monotonic()-began < 3
        assert ack['source_rows_persisted'] is True
        assert entered.wait(3)
        with urlopen(base+ack['status_url'], timeout=2) as response:
            assert json.load(response)['status'] == 'running'
        with urlopen(base+'/import', timeout=2) as response:
            assert b'awaitUpload' in response.read()
        release.set()
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            with urlopen(base+ack['status_url'], timeout=2) as response:
                status = json.load(response)
            if status['status'] != 'running':
                break
            time.sleep(.02)
        assert status['status'] == 'done', status
        assert status['result']['upload_summary']['status'] == 'passed'
        with urlopen(Request(base+'/api/imports', data=raw, headers=headers), timeout=3) as response:
            second = json.load(response)
        # Same bytes reuse the committed batch and original transaction.
        assert second['batch_id'] == ack['batch_id']
    finally:
        release.set()
        # Drain any duplicate job before closing its database.
        with server.store_lock:
            pass
        server.shutdown()
        server.server_close()
        thread.join(3)
        server.card_store.close()
        ledger_board.bind_store(previous_store)


def test_job_coalesces_and_status_does_not_read_db(monkeypatch):
    gate = threading.Event()
    board = SimpleNamespace()
    handler = SimpleNamespace(server=SimpleNamespace(store_lock=threading.RLock()))
    calls = []
    def process(*args):
        calls.append(True)
        assert gate.wait(3)
        return {'upload_summary': {'status': 'passed'}}, 200
    monkeypatch.setattr(card_upload_jobs, 'process', process)
    try:
        first = card_upload_jobs.start(board, handler, None, {'batch_id': 'same'}, None, None)
        second = card_upload_jobs.start(board, handler, None, {'batch_id': 'same'}, None, None)
        assert first['status_url'] == second['status_url']
        assert card_upload_jobs.status(board, first['status_url'].split('/')[-1])[0]['status'] == 'running'
        assert card_upload_jobs.status(SimpleNamespace(), 'missing')[1] == 404
    finally:
        gate.set()
    with handler.server.store_lock:
        pass
    assert len(calls) == 1


def test_status_owner_and_csrf_gates(monkeypatch):
    monkeypatch.setattr(card_flow, 'enabled', lambda: True)
    monkeypatch.setattr(ledger_board, '_active_store', lambda: SimpleNamespace())
    from urllib.parse import urlparse
    class Handler:
        headers = {}
        def _send_json(self, body, code=200):
            self.reply = body, code
    handler = Handler()
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'viewer')
    assert card_flow.dispatch(handler, urlparse(card_upload_jobs.PREFIX+'a'*32))
    assert handler.reply[1] == 403
    # No Pipeline/DB access is permitted even when an owner polls.
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
    assert card_flow.dispatch(handler, urlparse(card_upload_jobs.PREFIX+'a'*32))
    assert handler.reply[1] == 404
    monkeypatch.setattr(card_flow, 'CardFlow', lambda *a: SimpleNamespace())
    assert card_flow.dispatch(handler, urlparse('/api/imports'), raw=b'bad', csrf='required')
    assert handler.reply[1] == 403
