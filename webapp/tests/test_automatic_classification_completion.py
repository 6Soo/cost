import json

import pytest

from app import automatic_classification as policy
from app.db import StoreError
from tests.card_pipeline.fixtures import make_csv, domestic_row
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore

TRIPS = [dict(trip_id='A', starts_on='2026-10-01', ends_on='2026-10-05'),
         dict(trip_id='B', starts_on='2026-10-01', ends_on='2026-10-05')]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    board = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    flow = CardFlow(board)
    batch = flow.pipeline.receive(make_csv([
        domestic_row(merchant='SYNTHETIC UNKNOWN '+str(i), amount=1000+i,
                     approval='INFER'+str(i), date='2026-10-03') for i in range(5)]), 'synthetic.csv')['batch_id']
    rows = flow.pipeline.get_batch(batch)['rows']
    yield board, flow, batch, rows
    board.close()


@pytest.mark.parametrize('source,item', [('음식점', '식비'), ('주차장','주차비'),
    ('주유소','주유비'), ('철도','교통비'), ('SYNTHETIC HOTEL','숙박비'),
    ('SYNTHETIC AIRWAYS','항공료'), ('OPAQUE PAYMENT','기타경비')])
def test_general_service_rules_do_not_need_merchant_specific_answers(source, item):
    assert policy.infer_item({'description_raw':'card-category:'+source})[0] == item
    assert policy.infer_item({'description_raw':'card-category:호텔','merchant':'PARKING SYNTHETIC'})[0] == '숙박비'


def test_weak_ties_and_missing_dates_complete_using_only_actual_trips():
    target, basis = policy.infer_trip({'approval_date':'2026-10-03'}, TRIPS)
    assert target == 'A' and '동률' in basis
    assert policy.infer_trip({'approval_date':'2026-10-03'}, TRIPS, nets={'B':100})[0] == 'B'
    assert policy.infer_trip({'posting_date':'1900-01-01'}, TRIPS)[0] == 'B'
    assert policy.infer_trip({}, [])[0] == ''


def test_preview_is_read_only_apply_preserves_manual_holds_raw_data_and_is_idempotent(setup):
    board, flow, batch, rows = setup
    c = board.conn
    held, manual = rows[1]['transaction_id'], rows[2]['transaction_id']
    c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
              (held, rows[1]['source_hash'], 'user_hold', 'synthetic'))
    flow.pipeline.save_decision(manual, rows[2]['revision'], item='수동 항목', display_tab_id='A',trip_id='A',
                               tab_validator=lambda _: True,trip_validator=lambda _: True, request_id='synthetic-manual')
    before = c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    source = c.execute('SELECT transaction_id,source_hash,raw_row_json,amount_krw,approval_date,posting_date FROM transactions').fetchall()
    protected = c.execute('SELECT * FROM transactions WHERE transaction_id IN (?,?) ORDER BY transaction_id', (held,manual)).fetchall()
    preview = policy.plan(c, TRIPS)
    assert preview['summary']['to_classify'] == 3
    assert before == c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    policy.apply(c, preview, TRIPS)
    assert protected == c.execute('SELECT * FROM transactions WHERE transaction_id IN (?,?) ORDER BY transaction_id', (held,manual)).fetchall()
    assert source == c.execute('SELECT transaction_id,source_hash,raw_row_json,amount_krw,approval_date,posting_date FROM transactions').fetchall()
    assert c.execute("SELECT COUNT(*) FROM transactions WHERE classification_state='classified'").fetchone()[0] == 4
    assert c.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    assert policy.plan(c, TRIPS)['summary']['to_classify'] == 0


def test_stale_source_or_audit_failure_cannot_partially_apply(setup):
    board, _, _, _ = setup
    c = board.conn
    preview = policy.plan(c, TRIPS)
    c.execute('UPDATE transactions SET revision=revision+1')
    with pytest.raises(ValueError, match='PREVIEW_STALE'):
        policy.apply(c, preview, TRIPS)
    before = c.execute('SELECT * FROM transactions').fetchall()
    c.execute("CREATE TRIGGER reject_completion BEFORE INSERT ON change_log WHEN NEW.kind='card.automatic_classification' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with pytest.raises(Exception, match='synthetic'):
        policy.apply(c, policy.plan(c, TRIPS), TRIPS)
    assert before == c.execute('SELECT * FROM transactions').fetchall()


def test_operational_verifier_detects_amount_and_financial_link_changes(setup):
    from tools.complete_card_classification import protected_state
    board, _, _, rows = setup
    c = board.conn
    c.execute('CREATE TABLE synthetic_payment_link (id TEXT, target TEXT)')
    c.execute("INSERT INTO synthetic_payment_link VALUES ('synthetic','before')")
    before = protected_state(c)
    c.execute("UPDATE transactions SET item='기타경비',classification_state='classified'")
    assert protected_state(c) == before
    c.execute('UPDATE transactions SET amount_krw=amount_krw+1 WHERE transaction_id=?',(rows[0]['transaction_id'],))
    assert protected_state(c) != before
    c.execute('UPDATE transactions SET amount_krw=amount_krw-1 WHERE transaction_id=?',(rows[0]['transaction_id'],))
    assert protected_state(c) == before
    c.execute("UPDATE synthetic_payment_link SET target='after'")
    assert protected_state(c) != before


def test_empty_trip_in_history_and_override_is_completed_without_changing_user_category(setup):
    board, flow, batch, rows = setup
    c = board.conn
    tid = rows[0]['transaction_id']
    flow.pipeline.save_decision(tid,rows[0]['revision'],item='사용자 비용 항목',display_tab_id='unclassified',
        tab_validator=lambda _: True,request_id='default-empty-trip')
    payload = {'source_event_id':tid,'item':'사용자 비용 항목','amount_krw':rows[0]['amount_krw'],'display_tab_id':'unclassified'}
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense',NULL,1,?)",('card-'+tid,json.dumps(payload)))
    c.execute("INSERT INTO board_manual_overrides VALUES (?,'display_tab_id','synthetic-history')",('card-'+tid,))
    decisions = c.execute('SELECT * FROM review_decisions').fetchall()
    overrides = c.execute('SELECT * FROM board_manual_overrides').fetchall()
    policy.apply(c,policy.plan(c,TRIPS),TRIPS)
    saved = c.execute('SELECT item,trip_id,classification_basis FROM transactions WHERE transaction_id=?',(tid,)).fetchone()
    assert saved[0:2] == ('사용자 비용 항목','A') and 'AUTO_TRIP_INFERRED' in saved[2]
    projected = c.execute('SELECT display_tab_id,payload_json FROM board_rows WHERE row_id=?',('card-'+tid,)).fetchone()
    assert projected[0] == json.loads(projected[1])['display_tab_id'] == 'A'
    assert decisions == c.execute('SELECT * FROM review_decisions').fetchall()
    assert overrides == c.execute('SELECT * FROM board_manual_overrides').fetchall()


def test_existing_saved_trip_is_restored_before_any_new_trip_guess(setup):
    board, flow, _, rows = setup
    tid = rows[0]['transaction_id']
    flow.pipeline.save_decision(tid,rows[0]['revision'],item='기존 항목',display_tab_id='B',trip_id='B',
        tab_validator=lambda _: True,trip_validator=lambda _: True,request_id='saved-real-trip')
    board.conn.execute("UPDATE transactions SET trip_id='',display_tab_id='',classification_source='authority_review' WHERE transaction_id=?",(tid,))
    policy.apply(board.conn,policy.plan(board.conn,TRIPS,nets={'A':100}),TRIPS,nets={'A':100})
    saved = board.conn.execute('SELECT item,trip_id,classification_basis FROM transactions WHERE transaction_id=?',(tid,)).fetchone()
    assert saved[0:2] == ('기존 항목','B') and 'TRIP_ASSIGNMENT_RESTORED' in saved[2]


def test_future_import_completes_even_when_booking_evidence_is_unavailable(setup, monkeypatch):
    board, flow, batch, rows = setup
    board.conn.execute("UPDATE transactions SET merchant='SYNTHETIC AGODA',merchant_normalized='synthetic agoda'")
    trip = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                             destination='Synthetic', client_request_id='synthetic-trip')['tab_id']
    monkeypatch.setattr(flow, 'trip_valid', lambda identity: identity == trip)
    monkeypatch.setattr(flow, '_ota_report', lambda: (_ for _ in ()).throw(StoreError('OTA_EVIDENCE_UNAVAILABLE','synthetic')))
    flow._classify(batch)
    result = flow.pipeline.get_batch(batch)['rows']
    assert all(r['classification_state'] == 'classified' and r['item'] == '숙박비' and r['trip_id'] == trip for r in result)
    assert not any(r['decided'] for r in result)
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_verified_partial_refunds_inherit_but_orphans_do_not_create_financial_links(setup):
    board, _, _, rows = setup
    c = board.conn
    original, refund, orphan = rows[:3]
    c.execute("UPDATE transactions SET item='식비',trip_id='A',display_tab_id='A',classification_state='classified' WHERE transaction_id=?", (original['transaction_id'],))
    c.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-100,original_approval_number=? WHERE transaction_id=?", (original['approval_number'],refund['transaction_id']))
    c.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-100,original_approval_number='NO-SOURCE' WHERE transaction_id=?", (orphan['transaction_id'],))
    identity = c.execute('SELECT transaction_id,approval_number,original_approval_number,amount_krw FROM transactions').fetchall()
    policy.apply(c, policy.plan(c, TRIPS), TRIPS)
    assert c.execute('SELECT item,trip_id FROM transactions WHERE transaction_id=?', (refund['transaction_id'],)).fetchone() == ('식비','A')
    assert c.execute('SELECT item,classification_state FROM transactions WHERE transaction_id=?', (orphan['transaction_id'],)).fetchone() == ('취소·환불','classified')
    assert identity == c.execute('SELECT transaction_id,approval_number,original_approval_number,amount_krw FROM transactions').fetchall()


def test_legacy_source_completion_keeps_valid_recorded_trip_and_projection_unchanged(setup, monkeypatch):
    board, flow, batch, rows = setup
    c = board.conn
    trip = board.create_trip(starts_on='2026-10-01',ends_on='2026-10-05',destination='Synthetic',client_request_id='legacy-trip')['tab_id']
    monkeypatch.setattr(flow,'trip_valid',lambda identity: identity == trip)
    tid = rows[0]['transaction_id']
    c.execute("UPDATE transactions SET classification_state='classified',item='교통비',display_tab_id=?,trip_id=? WHERE transaction_id=?", (trip,trip,tid))
    preview = flow.pipeline.preview(batch,trip_validator=lambda _: True,tab_validator=lambda _: True)
    flow.pipeline.commit(batch,preview['digest'],'synthetic-record',trip_validator=lambda _: True,
                         tab_validator=lambda _: True,projection=flow.project)
    c.execute("UPDATE transactions SET classification_state='needs_review',classification_source='authority_review',trip_id='',display_tab_id='' WHERE transaction_id=?",(tid,))
    ledger = c.execute('SELECT * FROM ledger_entries').fetchall()
    projection = c.execute('SELECT * FROM board_rows').fetchall()
    trips = [dict(trip_id=trip,starts_on='2026-10-01',ends_on='2026-10-05')]
    policy.apply(c,policy.plan(c,trips),trips)
    assert c.execute('SELECT classification_state,trip_id FROM transactions WHERE transaction_id=?',(tid,)).fetchone() == ('classified',trip)
    assert ledger == c.execute('SELECT * FROM ledger_entries').fetchall()
    assert projection == c.execute('SELECT * FROM board_rows').fetchall()
