import json
import sqlite3

import pytest

from app import classification_correction as correction
from app import automatic_classification as policy
from tools.complete_card_classification import protected_state
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


def fixes(rows):
    return [dict(transaction_id=r['transaction_id'],source_hash=r['source_hash'],
                 trip_id='B',item='항공료',basis='synthetic booking period; attribution only')
            for r in rows[:2]]


def test_correction_updates_existing_projections_and_keeps_originals_and_replay(setup):
    board,_,batch,rows=setup
    c=board.conn
    r=rows[0]
    c.execute("INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (r['transaction_id'],batch,'expense','','A','A',r['amount_krw'],r['merchant'],r['approval_date'],'purchase',r['source_hash'],'synthetic'))
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense','A',1,?)",
        ('card-'+r['transaction_id'],json.dumps(dict(item='expense',display_tab_id='A',amount_krw=r['amount_krw']))))
    before=protected_state(c)
    changes=fixes(rows)
    preview=correction.preview(c,changes,TRIPS)
    assert correction.apply(c,preview,changes,TRIPS,request_id='synthetic-correction')['applied']==2
    assert c.execute('SELECT item,trip_id FROM transactions WHERE transaction_id=?',(r['transaction_id'],)).fetchone()==('항공료','B')
    assert c.execute('SELECT item,trip_id FROM ledger_entries').fetchone()==('항공료','B')
    assert c.execute('SELECT display_tab_id FROM board_rows').fetchone()==('B',)
    after=protected_state(c)
    assert {k:v for k,v in before.items() if k!='board_rows'}=={k:v for k,v in after.items() if k!='board_rows'}
    payload=json.loads(c.execute('SELECT payload_json FROM board_rows').fetchone()[0])
    assert payload['amount_krw']==r['amount_krw'] and payload['classification_source']=='inference'
    audit=json.loads(c.execute("SELECT detail_json FROM change_log WHERE kind='card.classification_corrected' LIMIT 1").fetchone()[0])
    assert audit['previous']['trip_id'] != audit['after']['trip_id']
    assert audit['source']=='code_inference' and not audit['user_booking_or_refund_confirmation']
    state=c.total_changes
    assert correction.apply(c,preview,changes,TRIPS,request_id='synthetic-correction')['applied']==0
    assert c.total_changes==state


@pytest.mark.parametrize('protection',['manual','hold','override'])
def test_correction_refuses_protected_rows(setup,protection):
    board,flow,_,rows=setup
    c=board.conn; tid=rows[0]['transaction_id']
    if protection=='manual':
        flow.pipeline.save_decision(tid,rows[0]['revision'],item='manual',trip_id='A',trip_validator=lambda _:True,request_id='synthetic-manual')
    elif protection=='hold':
        c.execute("UPDATE transactions SET parse_error='synthetic hold' WHERE transaction_id=?",(tid,))
    else:
        c.execute("UPDATE transactions SET classification_source='user_exception' WHERE transaction_id=?",(tid,))
    with pytest.raises(ValueError,match='CORRECTION_PROTECTED'):
        correction.preview(c,fixes(rows),TRIPS)


def test_low_confidence_note_does_not_bypass_manual_decision_protection(setup):
    board, flow, _, rows = setup
    c = board.conn
    row = rows[0]
    decision = flow.pipeline.save_decision(row['transaction_id'], row['revision'], item='숙박비',
        display_tab_id='A', trip_id='A', trip_validator=lambda _: True, tab_validator=lambda _: True,
        note='낮은 확신 분배 synthetic', request_id='synthetic-legacy')
    change = dict(transaction_id=row['transaction_id'], source_hash=row['source_hash'],
        revision=decision['revision'], trip_id='B', item='항공료', basis='synthetic ticket evidence',
        classification_source='ai_inference', execution=dict(kind='connected_agent', provider='synthetic',
        model='synthetic', run_id='synthetic'), legacy_inference_reconsideration=dict(
            revision=decision['revision'], item='숙박비', display_tab_id='A', note='낮은 확신 분배 synthetic'))
    with pytest.raises(ValueError, match='CORRECTION_PROTECTED'):
        correction.preview(c, [change], TRIPS)


def test_original_with_refund_is_not_moved_independently(setup):
    board,_,_,rows=setup; c=board.conn
    c.execute("UPDATE transactions SET transaction_direction='cancellation',original_approval_number=? WHERE transaction_id=?",(rows[0]['approval_number'],rows[2]['transaction_id']))
    with pytest.raises(ValueError,match='CORRECTION_PROTECTED'):
        correction.preview(c,fixes(rows),TRIPS)


def test_stale_or_failed_projection_rolls_back_all_rows(setup):
    board,_,_,rows=setup
    c=board.conn; changes=fixes(rows)
    p=correction.preview(c,changes,TRIPS)
    c.execute('UPDATE transactions SET revision=revision+1 WHERE transaction_id=?',(rows[1]['transaction_id'],))
    with pytest.raises(ValueError,match='CORRECTION_PREVIEW_STALE'):
        correction.apply(c,p,changes,TRIPS,request_id='stale')
    c.commit()
    c.execute("CREATE TEMP TRIGGER correction_failure BEFORE UPDATE ON transactions WHEN OLD.transaction_id='"+rows[1]['transaction_id']+"' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    before='\n'.join(c.iterdump())
    with pytest.raises(sqlite3.IntegrityError,match='synthetic failure'):
        correction.apply(c,correction.preview(c,changes,TRIPS),changes,TRIPS,request_id='failed')
    assert '\n'.join(c.iterdump())==before


def test_october_local_purchase_does_not_rank_named_may_trip_above_near_domestic_trip():
    trips=[dict(trip_id='may',destination='부산',starts_on='2026-05-01',ends_on='2026-05-05'),
           dict(trip_id='near',destination='영남',starts_on='2026-10-02',ends_on='2026-10-04'),
           dict(trip_id='foreign',destination='북큐슈',starts_on='2026-09-27',ends_on='2026-10-01')]
    target,_=policy.infer_trip(dict(merchant='SYNTHETIC 부산 STORE',card_kind='국내',approval_date='2026-10-01'),trips)
    assert target=='near'
    target,_=policy.infer_trip(dict(merchant='SYNTHETIC 부산 STORE',card_kind='국내',approval_date='2026-05-02'),trips)
    assert target=='may'


def test_booking_period_precedes_3820_residual_but_manual_stays_protected(setup):
    board,_,_,rows=setup; c=board.conn; tid=rows[0]['transaction_id']
    c.execute("UPDATE transactions SET card_tail='3820',item='분기 기타비용',display_tab_id='quarter:2026:4',classification_source='owner_card_residual' WHERE transaction_id=?",(tid,))
    fact={tid:dict(source_hash=rows[0]['source_hash'],trip_id='B',item='항공료',basis='synthetic booking period')}
    preview=policy.plan(c,TRIPS,transaction_ids=[tid],reconsider=True,evidence=fact)
    policy.apply(c,preview,TRIPS,transaction_ids=[tid],reconsider=True,evidence=fact)
    assert c.execute('SELECT item,trip_id FROM transactions WHERE transaction_id=?',(tid,)).fetchone()==('항공료','B')
    assert policy.plan(c,TRIPS,transaction_ids=[tid],reconsider=True,evidence=fact)['summary']['to_classify']==0


def test_verified_ota_review_replaces_saved_quarter_residual_but_keeps_manual_decision(setup):
    board, flow, _, rows = setup
    c = board.conn
    residual, manual = rows[:2]
    for row in (residual, manual):
        c.execute("UPDATE transactions SET card_tail='3820',classification_state='classified',"
                  "classification_source='owner_card_residual',classification_basis='synthetic residual',"
                  "item='분기 기타비용',description='분기 기타비용',display_tab_id='quarter:2026:4',trip_id='' "
                  "WHERE transaction_id=?", (row['transaction_id'],))
    flow.pipeline.save_decision(manual['transaction_id'], manual['revision'], item='내가 정한 항목',
                                trip_id='A', trip_validator=lambda _: True,
                                request_id='synthetic-manual-before-ota')
    c.commit()
    manual_before = c.execute('SELECT item,display_tab_id,trip_id,classification_source,decided_at '
                              'FROM transactions WHERE transaction_id=?', (manual['transaction_id'],)).fetchone()
    evidence = {residual['transaction_id']: dict(source_hash=residual['source_hash'], trip_id='B',
                item='항공료', basis='synthetic verified reservation', status='confirmed')}
    ids = [residual['transaction_id'], manual['transaction_id']]
    options = dict(transaction_ids=ids, reconsider=True, evidence=evidence)
    preview = policy.plan(c, TRIPS, **options)
    assert preview['summary']['to_classify'] == 1
    policy.apply(c, preview, TRIPS, **options)
    assert c.execute('SELECT item,display_tab_id,trip_id,classification_source FROM transactions '
                     'WHERE transaction_id=?', (residual['transaction_id'],)).fetchone() == (
                         '항공료', 'B', 'B', 'inference')
    assert c.execute('SELECT item,display_tab_id,trip_id,classification_source,decided_at FROM transactions '
                     'WHERE transaction_id=?', (manual['transaction_id'],)).fetchone() == manual_before


@pytest.mark.parametrize('fact_changes', [
    {'source_hash': 'f' * 64, 'trip_id': 'B'},
    {'source_hash': None, 'trip_id': 'deleted-trip'},
])
def test_unverified_ota_fact_cannot_replace_gotogate_residual_item(setup, fact_changes):
    board, _, _, rows = setup
    c = board.conn
    row = rows[0]
    c.execute("UPDATE transactions SET card_tail='3820',merchant='SYNTHETIC GOTOGATE',"
              "classification_state='classified',classification_source='owner_card_residual',"
              "item='분기 기타비용',description='분기 기타비용',display_tab_id='quarter:2026:4',trip_id='' "
              "WHERE transaction_id=?", (row['transaction_id'],))
    c.commit()
    fact = dict(source_hash=row['source_hash'], trip_id='B', item='식비',
                basis='unverified synthetic fact', status='observed')
    fact.update(fact_changes)
    options = dict(transaction_ids=[row['transaction_id']], reconsider=True,
                   evidence={row['transaction_id']: fact})
    preview = policy.plan(c, TRIPS, **options)
    policy.apply(c, preview, TRIPS, **options)
    saved = c.execute('SELECT item,trip_id,display_tab_id,classification_source FROM transactions '
                       'WHERE transaction_id=?', (row['transaction_id'],)).fetchone()
    assert saved[0] == '항공료'
    assert saved[1:] != ('B', 'B', 'inference')


def test_known_airfare_ota_is_not_quarter_expense_when_exact_mail_is_unavailable(setup):
    board,_,_,rows=setup; c=board.conn; tid=rows[0]['transaction_id']
    c.execute("UPDATE transactions SET card_tail='3820',merchant='SYNTHETIC 고투게이트',item='분기 기타비용',display_tab_id='quarter:2026:4',classification_source='owner_card_residual' WHERE transaction_id=?",(tid,))
    options=dict(transaction_ids=[tid],reconsider=True)
    before=protected_state(c)
    policy.apply(c,policy.plan(c,TRIPS,**options),TRIPS,**options)
    assert c.execute('SELECT item,trip_id FROM transactions WHERE transaction_id=?',(tid,)).fetchone()==('항공료','A')
    assert protected_state(c)==before
    assert c.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
