import json
import threading
from unittest.mock import patch
from urllib.parse import urlparse
import pytest
from playwright.sync_api import sync_playwright
from webapp import ledger_board, card_catalog
from webapp.card_actions import next_action
from webapp.card_flow import CardFlow, dispatch
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.fixtures import make_csv, domestic_row

@pytest.fixture
def flow(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '2026-04-01')
    # Every batch in these tests is collected now, so it counts as new collection.
    monkeypatch.setenv('WEBLEDGER_AUTO_RECORD_SINCE', '2000-01-01T00:00:00+00:00')
    board = LedgerStore(tmp_path/'ux.sqlite', seed_demo=False)
    previous = ledger_board._STORE
    ledger_board.bind_store(board)
    with patch.object(CardFlow, 'trip_valid', return_value=True), patch.object(CardFlow, 'ota_group_holds', return_value={}), patch.object(CardFlow, 'preview_metadata', return_value=None), patch.object(ledger_board, '_receipts_owner_request', return_value=True):
        f = CardFlow(board)
        batch = f.pipeline.receive(make_csv([
            domestic_row(merchant='합성 AGODA A', amount=89891, approval='UX1', date='2026-04-01'),
            domestic_row(merchant='합성 AGODA B', amount=188808, approval='UX2', date='2026-04-01'),
        ]), 'ux.csv')['batch_id']
        trip = board.create_trip(starts_on='2026-04-04', ends_on='2026-04-07', destination='합성 에히메', client_request_id='trip-ux')['tab_id']
        board.conn.execute("UPDATE transactions SET item='숙박비',classification_state='classified',display_tab_id='',trip_id=''")
        board.conn.execute('UPDATE transactions SET display_tab_id=?,trip_id=? WHERE amount_krw=188808', (trip, trip))
        board.conn.commit()
        yield f, batch, trip
    ledger_board.bind_store(previous)
    board.close()

def test_ready_auto_records_missing_trip_waits_and_replay_is_noop(flow):
    f, batch, trip = flow
    before = f.board.conn.execute('SELECT transaction_id,source_hash,amount_krw,approval_date,decided_at FROM transactions ORDER BY transaction_id').fetchall()
    state = f.auto_record(batch)
    assert state['auto_recorded'] == 1
    actions = {r['amount_krw']:r['next_action'] for r in state['preview']['rows']}
    assert actions[89891]['label'] == '여행 지정'
    assert actions[188808]['status'] == '기록 완료'
    assert f.auto_record(batch)['auto_recorded'] == 0
    assert f.board.conn.execute('SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries').fetchone() == (1,188808)
    assert before == f.board.conn.execute('SELECT transaction_id,source_hash,amount_krw,approval_date,decided_at FROM transactions ORDER BY transaction_id').fetchall()
    payload = json.loads(f.board.conn.execute('SELECT payload_json FROM board_rows').fetchone()[0])
    assert payload['confirmed_by'] == 'automatic' and payload['classification_state'] == 'classified'
    catalog = card_catalog.catalog(f.board, {'state':['booked']})
    assert catalog['total']==1 and catalog['rows'][0]['next_action']['status']=='기록 완료'

def test_recordable_row_has_no_user_visible_ready_state(flow):
    f, batch, _ = flow
    action = next(r['next_action'] for r in f.state(batch)['preview']['rows'] if r['amount_krw'] == 188808)
    assert action['status'] == ''
    assert 'group' not in action

def test_holds_and_lost_authority_prevent_recording(flow):
    f, batch, trip = flow
    ready = next(r for r in f.pipeline.get_batch(batch)['rows'] if r['amount_krw']==188808)
    f.board.conn.execute('INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
                         (ready['transaction_id'],ready['source_hash'],'refund_pending','합성 환불 확인 필요'))
    f.board.conn.commit()
    assert f.auto_record(batch)['auto_recorded'] == 0
    action = next(r['next_action'] for r in f.state(batch)['preview']['rows'] if r['transaction_id']==ready['transaction_id'])
    assert action['label'] == '사유 확인' and action['status'] == '확인 필요' and '환불' in action['reason']
    f.board.conn.execute('DELETE FROM transaction_review_holds');f.board.conn.commit()
    with patch.object(CardFlow,'trip_valid',return_value=False):
        assert f.auto_record(batch)['auto_recorded'] == 0

def test_automatic_endpoint_keeps_csrf_and_read_only_get(flow):
    f, batch, _ = flow
    class Handler:
        headers = {}
        def _send_json(self, value, status=200): self.result=(status,value)
    h=Handler()
    dispatch(h,urlparse('/api/imports/'+batch+'/auto-record'),raw=b'{}',csrf='csrf')
    assert h.result[0]==403
    dispatch(h,urlparse('/api/imports/'+batch),raw=None,csrf='csrf')
    assert h.result[0]==200
    assert f.board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0]==0


def test_classification_save_is_complete_when_ledger_needs_a_trip_and_replay_is_safe(flow):
    f, batch, _ = flow
    row = next(r for r in f.pipeline.get_batch(batch)['rows'] if r['amount_krw'] == 89891)
    source = f.board.conn.execute(
        'SELECT source_hash,amount_krw,approval_date,approval_number FROM transactions WHERE transaction_id=?',
        (row['transaction_id'],)).fetchone()
    body = json.dumps(dict(transaction_id=row['transaction_id'], revision=row['revision'],
        item='소모품비', display_tab_id='unclassified', request_id='classification-without-trip')).encode()

    class Handler:
        headers = {'X-CSRF-Token': 'csrf'}
        def _send_json(self, value, status=200):
            self.result = (status, value)

    for _ in range(2):
        handler = Handler()
        dispatch(handler, urlparse('/api/imports/' + batch + '/decision'), raw=body, csrf='csrf')
        status, response = handler.result
        assert status == 200 and response['saved']
        assert response['classification_state'] == 'classified'
        assert response['ledger_recording']['status'] == 'held'
        assert response['ledger_recording']['code'] == 'NOT_RECORDED'
    saved = next(r for r in f.pipeline.get_batch(batch)['rows'] if r['transaction_id'] == row['transaction_id'])
    assert saved['classification_state'] == 'classified' and saved['item'] == '소모품비'
    assert saved['classification_source'] == 'user_decision'
    assert f.board.conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0] == 1
    assert f.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    assert source == f.board.conn.execute(
        'SELECT source_hash,amount_krw,approval_date,approval_number FROM transactions WHERE transaction_id=?',
        (row['transaction_id'],)).fetchone()

def test_mobile_catalog_automatically_records_and_opens_exact_transaction(flow):
    f, batch, _ = flow
    previous = ledger_board._STORE
    ledger_board.bind_access(None)
    server = ledger_board.serve(port=0, with_worker=False, db_path=f.board.path, seed_demo=False)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':390,'height':844})
            errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
            page.goto(f'http://127.0.0.1:{server.server_address[1]}/cards')
            page.wait_for_timeout(500)
            assert page.locator('tbody tr').filter(has_text='188,808').get_by_role('link',name='장부 보기').count()==0
            page.locator('tbody tr').filter(has_text='89,891').get_by_role('link',name='여행 지정').click()
            page.locator('#questions form').first.wait_for()
            assert '합성 AGODA A' in page.locator('#questions article').first.inner_text()
            assert '여행 지정' in page.locator('#questions article h2').first.inner_text()
            assert not page.locator('#commit').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            target=next(r['transaction_id'] for r in f.pipeline.get_batch(batch)['rows'] if r['amount_krw']==89891)
            page.goto('about:blank')
            page.goto(f'http://127.0.0.1:{server.server_address[1]}/import?batch={batch}&transaction={target}#preview')
            page.locator('#preview tbody tr').first.wait_for()
            assert page.locator('#preview tbody tr').count()==1
            assert '89,891원' in page.locator('#preview tbody tr').inner_text()
            assert errors==[]
            browser.close()
    finally:
        server.shutdown();server.server_close();server.card_store.close();thread.join(timeout=3)
        ledger_board.bind_store(previous)

def test_refund_is_atomic_and_keeps_the_two_source_amounts(flow):
    f, batch, trip = flow
    rows = f.pipeline.get_batch(batch)['rows']
    original=next(r for r in rows if r['amount_krw']==188808)
    refund=next(r for r in rows if r['amount_krw']==89891)
    number=f.board.conn.execute('SELECT approval_number FROM transactions WHERE transaction_id=?',(original['transaction_id'],)).fetchone()[0]
    f.board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-89891,original_approval_number=?,classification_state='needs_review',item='',display_tab_id='',trip_id='' WHERE transaction_id=?",(number,refund['transaction_id']))
    f.board.conn.commit()
    result=f.auto_record(batch)
    assert result['auto_recorded']==2
    assert f.board.conn.execute('SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries').fetchone()==(2,98917)
    assert f.auto_record(batch)['auto_recorded']==0

def test_projection_failure_rolls_back_the_entire_automatic_write(flow):
    f,batch,_=flow
    before=f.board.conn.execute('SELECT transaction_id,classification_state,revision FROM transactions ORDER BY transaction_id').fetchall()
    with patch.object(f,'project',side_effect=RuntimeError('synthetic failure')):
        with pytest.raises(RuntimeError):f.auto_record(batch)
    assert f.board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
    assert before==f.board.conn.execute('SELECT transaction_id,classification_state,revision FROM transactions ORDER BY transaction_id').fetchall()

def test_real_blocking_causes_take_precedence_over_trip_and_classification(flow):
    f,batch,_=flow
    row=dict(f.pipeline.get_batch(batch)['rows'][0],batch_id=batch,display_tab_id='')
    refund=next_action(row,{'blocked':'refund_pair_partially_booked'})
    assert refund['label']=='환불 기록 확인' and refund['href'].endswith('#preview')
    booking=next_action(row,extra_hold={'kind':'ota_pending','reason':'OTA-first 연결이 확정되지 않은 OTA 카드 거래라 기록하지 않아요'})
    assert booking['label']=='예약 연결 확인' and booking['href'].endswith('#ota-review')
    assert 'OTA-first' not in booking['reason']

def test_existing_partial_refund_does_not_stop_an_unrelated_ready_transaction(flow):
    f,_,trip=flow
    batch=f.pipeline.receive(make_csv([
        domestic_row(merchant='합성 원결제',amount=500000,approval='P1',date='2026-04-05'),
        domestic_row(merchant='합성 환불',amount=200000,approval='P2',date='2026-04-06'),
        domestic_row(merchant='합성 정상 거래',amount=12345,approval='P3',date='2026-04-07'),
    ]),'isolated-refund.csv')['batch_id']
    rows=f.pipeline.get_batch(batch)['rows']
    original=next(r for r in rows if r['amount_krw']==500000)
    refund=next(r for r in rows if r['amount_krw']==200000)
    normal=next(r for r in rows if r['amount_krw']==12345)
    conn=f.board.conn
    conn.execute("UPDATE transactions SET item='숙박비',classification_state='classified',display_tab_id=?,trip_id=? WHERE transaction_id=?",(trip,trip,original['transaction_id']))
    conn.commit()
    assert f.auto_record(batch)['auto_recorded']==1
    number=conn.execute('SELECT approval_number FROM transactions WHERE transaction_id=?',(original['transaction_id'],)).fetchone()[0]
    conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-200000,original_approval_number=? WHERE transaction_id=?",(number,refund['transaction_id']))
    conn.execute("UPDATE transactions SET item='숙박비',classification_state='classified',display_tab_id=?,trip_id=? WHERE transaction_id=?",(trip,trip,normal['transaction_id']))
    conn.commit()
    before=conn.execute('SELECT transaction_id,source_hash,amount_krw,decided_at FROM transactions ORDER BY transaction_id').fetchall()
    result=f.auto_record(batch)
    assert result['auto_recorded']==1
    assert {r[0] for r in conn.execute('SELECT transaction_id FROM ledger_entries')}=={original['transaction_id'],normal['transaction_id']}
    assert before==conn.execute('SELECT transaction_id,source_hash,amount_krw,decided_at FROM transactions ORDER BY transaction_id').fetchall()
    assert f.auto_record(batch)['auto_recorded']==0
