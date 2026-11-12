import json

import pytest

from app import automatic_classification as p1, decision_provenance as repair
from app.ledger import _decision_rows
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


def save_batch(flow, row, *, request='dist141-synthetic', trip='A'):
    return flow.pipeline.save_decision(row['transaction_id'],row['revision'],item='숙박비',
        display_tab_id=trip,trip_id=trip,trip_validator=lambda _:True,tab_validator=lambda _:True,
        note='낮은 확신 분배 synthetic automatic batch',request_id=request)


def test_release_preserves_history_and_sources_reconsiders_open_and_restores(setup):
    board,flow,batch,rows = setup
    c = board.conn
    save_batch(flow,rows[0])
    tid = rows[0]['transaction_id']
    original = repair._state(c,tid)
    history = c.execute('SELECT * FROM review_decisions').fetchall()
    evidence = {tid:dict(source_hash=rows[0]['source_hash'],trip_id='B',item='宿泊',basis='synthetic period')}
    plan = repair.preview(c,TRIPS,evidence=evidence)
    assert plan['summary'] == dict(identified=1,eligible=1,excluded=0,open=1,closed=0)
    result = repair.apply(c,plan,TRIPS,request_id='repair-demo',evidence=evidence)
    assert result['open'] == 1 and result['attribution_or_item_changed'] == 1
    assert repair.apply(c,plan,TRIPS,request_id='repair-demo',evidence=evidence)['replay']
    after = repair._state(c,tid)['transaction']
    assert after['trip_id'] == 'B' and after['classification_source'] == 'inference'
    assert after['decided_at'] is None and after['revision'] > original['transaction']['revision']
    assert c.execute('SELECT * FROM review_decisions').fetchall() == history
    assert not _decision_rows(flow.pipeline.store,batch)
    for key in ('amount_krw','source_hash','raw_row_json','transaction_id'):
        assert after[key] == original['transaction'][key]
    restored = repair.restore(c,repair.restore_preview(c,'repair-demo'),'repair-demo')
    assert restored['restore'] == 1
    back = repair._state(c,tid)['transaction']
    assert {k:v for k,v in back.items() if k!='revision'} == {k:v for k,v in original['transaction'].items() if k!='revision'}
    assert _decision_rows(flow.pipeline.store,batch)


def test_closed_release_only_changes_provenance_and_future_p1_keeps_attribution(setup):
    board,flow,_,rows = setup
    save_batch(flow,rows[0])
    trips = [dict(t,starts_on='2026-01-01',ends_on='2026-01-05') for t in TRIPS]
    tid = rows[0]['transaction_id']
    plan = repair.preview(board.conn,trips)
    assert plan['summary']['closed'] == 1
    result = repair.apply(board.conn,plan,trips,request_id='closed')
    assert result['attribution_or_item_changed'] == 0
    row = repair._state(board.conn,tid)['transaction']
    assert row['trip_id'] == 'A' and row['item'] == '숙박비'
    assert 'CLOSED_QUARTER_REVIEW_REQUIRED' in row['classification_basis']
    assert not p1.plan(board.conn,trips,transaction_ids={tid},reconsider=True)['targets']


@pytest.mark.parametrize('later',['manual','source','override','other_request'])
def test_repair_excludes_later_changes_and_non_batch_decisions(setup,later):
    board,flow,_,rows = setup
    tid = rows[0]['transaction_id']
    decision = save_batch(flow,rows[0],request='other' if later=='other_request' else 'dist141-synthetic')
    c = board.conn
    if later == 'manual':
        flow.pipeline.save_decision(tid,decision['revision'],item='식비',display_tab_id='B',trip_id='B',
            trip_validator=lambda _:True,tab_validator=lambda _:True,request_id='human')
    elif later == 'source':
        c.execute("UPDATE transactions SET source_hash='changed' WHERE transaction_id=?",(tid,))
    elif later == 'override':
        c.execute("INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?, 'item','human')",('card-'+tid,))
    c.commit()
    assert repair.preview(c,TRIPS)['summary']['eligible'] == 0


def test_automatic_revision_without_a_new_manual_decision_can_be_released(setup):
    board,flow,_,rows = setup
    save_batch(flow,rows[0])
    board.conn.execute('UPDATE transactions SET revision=revision+1,trip_id=?,display_tab_id=? WHERE transaction_id=?',
                       ('B','B',rows[0]['transaction_id']))
    board.conn.commit()
    assert repair.preview(board.conn,TRIPS)['summary']['eligible'] == 1


def test_already_automatic_row_releases_false_history_without_becoming_manual_or_losing_provenance(setup):
    board,flow,batch,rows = setup
    save_batch(flow,rows[0])
    c = board.conn
    tid = rows[0]['transaction_id']
    c.execute("UPDATE transactions SET classification_source='ai_inference',decided_at=NULL,"
              "classification_basis='AI_INFERRED existing evidence',revision=revision+1 WHERE transaction_id=?",(tid,))
    c.commit()
    plan = repair.preview(c,TRIPS)
    assert plan['summary']['eligible'] == 1
    repair.apply(c,plan,TRIPS,request_id='already-automatic')
    row = repair._state(c,tid)['transaction']
    assert row['classification_source'] == 'ai_inference'
    assert row['classification_basis'].startswith('AI_INFERRED existing evidence')
    assert not _decision_rows(flow.pipeline.store,batch)


def test_stale_preview_and_restore_reject_and_rollback_is_atomic(setup):
    board,flow,_,rows = setup
    save_batch(flow,rows[0])
    c = board.conn
    plan = repair.preview(c,TRIPS)
    c.execute('UPDATE transactions SET revision=revision+1 WHERE transaction_id=?',(rows[0]['transaction_id'],))
    c.commit()
    with pytest.raises(ValueError,match='PREVIEW_STALE'):
        repair.apply(c,plan,TRIPS,request_id='stale')
    assert not c.execute('SELECT 1 FROM change_log WHERE kind=?',(repair.RELEASE,)).fetchone()


def test_restore_refuses_changes_made_after_release(setup):
    board,flow,_,rows = setup
    save_batch(flow,rows[0])
    c = board.conn
    repair.apply(c,repair.preview(c,TRIPS),TRIPS,request_id='restore-stale')
    plan = repair.restore_preview(c,'restore-stale')
    row = repair._state(c,rows[0]['transaction_id'])['transaction']
    flow.pipeline.save_decision(row['transaction_id'],row['revision'],item='식비',display_tab_id='B',trip_id='B',
        trip_validator=lambda _:True,tab_validator=lambda _:True,request_id='later-human')
    with pytest.raises(ValueError,match='RESTORE_STALE'):
        repair.restore(c,plan,'restore-stale')
    assert repair._state(c,row['transaction_id'])['transaction']['item'] == '식비'


def test_recorded_projection_changes_are_audited_and_reversible(setup):
    board,flow,batch,rows = setup
    save_batch(flow,rows[0])
    c = board.conn
    row = rows[0]
    tid = row['transaction_id']
    c.execute('INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (tid,batch,'숙박비','','A','A',row['amount_krw'],row['merchant'],row['approval_date'],'purchase',row['source_hash'],'synthetic'))
    payload = dict(item='숙박비',display_tab_id='A',trip_id='A',amount_krw=row['amount_krw'],
                   source_event_id=tid,confirmed_by='automatic',revision=1)
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense','A',1,?)",
              ('card-'+tid,json.dumps(payload)))
    c.commit()
    before = repair._state(c,tid)
    evidence = {tid:dict(source_hash=row['source_hash'],trip_id='B',item='숙박비',basis='synthetic verified stay')}
    plan = repair.preview(c,TRIPS,evidence=evidence)
    assert repair.apply(c,plan,TRIPS,request_id='recorded',evidence=evidence)['attribution_or_item_changed'] == 1
    after = repair._state(c,tid)
    assert after['ledger']['trip_id'] == 'B' and after['board']['display_tab_id'] == 'B'
    assert after['ledger']['amount_krw'] == before['ledger']['amount_krw']
    assert c.execute('SELECT count(*) FROM board_revisions WHERE row_id=?',('card-'+tid,)).fetchone()[0] >= 1
    repair.restore(c,repair.restore_preview(c,'recorded'),'recorded')
    restored = repair._state(c,tid)
    assert restored['ledger'] == before['ledger']
    restored_payload = json.loads(restored['board']['payload_json'])
    assert restored_payload.pop('revision') > payload['revision']
    assert restored_payload == {k:v for k,v in payload.items() if k!='revision'}


def test_maintenance_report_uses_current_core_periods_without_writes(setup,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from tools import repair_dist141_provenance as cli
    from tools.complete_card_classification import load_review_evidence
    from app import ota_payments
    board,flow,_,rows = setup
    row = rows[0]
    event = dict(provider='forest',booking_ref='',event_type='charge',evidence_status='paid_verified',
        payment_status='paid',evidence_kind='authenticated_forest_pg_card_receipt',
        service_period_basis='LINK-108',service_period=dict(starts_on='2026-10-02',ends_on='2026-10-03'),
        item='숙박비',paid_on=row['approval_date'],amount=row['amount_krw'],amount_krw=row['amount_krw'],
        currency='KRW',authorization_scheme='issuer_card_approval',approval_number=row['approval_number'],
        source_digest='synthetic-digest',source_digests=['synthetic-digest'],ota_event_id='synthetic-forest',
        reservation_status='observed')
    monkeypatch.setattr(cli,'read_flow',lambda *args:SimpleNamespace(_ota_sources=lambda:{}))
    monkeypatch.setattr(ota_payments,'build_ota_payment_events',lambda sources:[event])
    original = repair._state(board.conn,row['transaction_id'])
    report = cli.canonical_report(board.conn,tmp_path)
    assert report['matches'][0]['period'] == event['service_period']
    evidence,_ = load_review_evidence(board.conn,tmp_path,[TRIPS[0]],report=report)
    assert evidence[row['transaction_id']]['trip_id'] == 'A'
    assert repair._state(board.conn,row['transaction_id']) == original
    assert not (tmp_path/'data/ota-review/ota-review.sqlite').exists()


def test_maintenance_apply_requires_preview_and_backup_before_opening_store(tmp_path,capsys):
    from tools.repair_dist141_provenance import main
    assert main(['--host-root',str(tmp_path),'--request-id','synthetic','--apply']) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'PREVIEW_AND_BACKUP_REQUIRED'
    assert not (tmp_path/'data/board.sqlite').exists()
