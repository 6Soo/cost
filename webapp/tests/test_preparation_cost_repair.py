import json
import pytest
from app import automatic_classification as p1, preparation_cost_repair as repair
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


def prepare(c):
    c.execute("UPDATE transactions SET approval_date='2026-09-30',classification_state='classified',"
              "classification_source='inference',item='식비',trip_id='A',display_tab_id='A',"
              "classification_basis='AUTO_INFERRED · 다음 여행 준비기간 · 카드 이용일과 여행 기간 거리 1일',decided_at=NULL")
    c.commit()


def test_outside_period_completes_in_payment_quarter_and_service_period_still_wins(setup):
    c=setup[0].conn
    c.execute("UPDATE transactions SET approval_date='2026-09-30'")
    c.commit()
    plan=p1.plan(c,TRIPS)
    assert len(plan['targets'])==5
    p1.apply(c,plan,TRIPS)
    assert set(c.execute('SELECT trip_id,display_tab_id,item FROM transactions'))=={('', 'quarter:2026:3', '분기 기타비용')}
    # A verified source-bound reservation may be paid before the actual trip.
    c.execute("UPDATE transactions SET item='숙박비',classification_source='inference',display_tab_id='',trip_id=''")
    c.commit()
    from app.automatic_classification import _read
    evidence={r['transaction_id']:dict(source_hash=r['source_hash'],trip_id='A',item='숙박비',basis='예약 이용기간',
                service_period=dict(starts_on='2026-10-02',ends_on='2026-10-03')) for r in _read(c)}
    reviewed=p1.plan(c,TRIPS,reconsider=True,evidence=evidence)
    p1.apply(c,reviewed,TRIPS,reconsider=True,evidence=evidence)
    assert {r[0] for r in c.execute('SELECT trip_id FROM transactions')}=={'A'}


def test_repair_apply_replay_restore_protects_source_finance_and_projections(setup):
    c=setup[0].conn
    prepare(c)
    before={r['transaction_id']:repair._state(c,r['transaction_id']) for r in p1._read(c)}
    financial=repair._financial_state(c)
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['to_move']==5
    assert repair.apply(c,plan,TRIPS,request_id='synthetic-preparation')['applied_this_run']==5
    assert repair.apply(c,plan,TRIPS,request_id='synthetic-preparation')['applied_this_run']==0
    assert repair.replay(c,'synthetic-preparation')['to_move']==5
    assert repair.preview(c,TRIPS)['summary']['to_move']==0
    assert repair._financial_state(c)==financial
    repair.restore(c,repair.restore_preview(c,'synthetic-preparation'),'synthetic-preparation')
    for tid,old in before.items():
        current=repair._state(c,tid)
        assert {k:v for k,v in current['transaction'].items() if k!='revision'}=={k:v for k,v in old['transaction'].items() if k!='revision'}
        assert current['ledger']==old['ledger'] and current['board']==old['board']
    assert repair._financial_state(c)==financial


@pytest.mark.parametrize('kind',['manual','exception','reservation','unknown','closed','inside','source_conflict'])
def test_repair_preserves_every_protection_and_uncertain_provenance(setup,kind):
    c=setup[0].conn
    prepare(c)
    changes={
        'manual':"decided_at='synthetic'",
        'exception':"classification_source='user_exception'",
        'reservation':"classification_basis=classification_basis || ' · 예약 이용기간'",
        'unknown':"classification_basis='날짜 추론'",
        'closed':"approval_date='2026-03-01'",
        'inside':"approval_date='2026-10-03'",
        'source_conflict':"conflict_reason='synthetic'",
    }
    c.execute('UPDATE transactions SET '+changes[kind]);c.commit()
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['to_move']==0
    assert sum(plan['summary']['excluded'].values())==5


def test_refund_group_moves_only_when_every_member_qualifies_and_follows_original(setup):
    from webapp.tests.test_closed_period_grouping import refund_pair
    c,purchase,refund=refund_pair(setup)
    prepare(c)
    c.execute("UPDATE transactions SET approval_date='2026-10-06' WHERE transaction_id=?",(refund,));c.commit()
    plan=repair.preview(c,TRIPS)
    assert {purchase,refund}<={t['tid'] for t in plan['targets']}
    assert plan['summary']['refund_move_rows']==2
    assert {t['values']['display_tab_id'] for t in plan['targets'] if t['tid'] in {purchase,refund}}=={'quarter:2026:3'}
    c.execute("UPDATE transactions SET classification_source='user_exception' WHERE transaction_id=?",(refund,));c.commit()
    assert not {purchase,refund}&{t['tid'] for t in repair.preview(c,TRIPS)['targets']}


def test_repair_stale_preview_and_mid_apply_failure_are_atomic(setup):
    import sqlite3
    c=setup[0].conn
    prepare(c)
    plan=repair.preview(c,TRIPS)
    c.execute("UPDATE transactions SET classification_basis='unknown' WHERE transaction_id=?",(setup[3][0]['transaction_id'],));c.commit()
    before='\n'.join(c.iterdump())
    with pytest.raises(ValueError,match='GROUPING_PREVIEW_STALE'):
        repair.apply(c,plan,TRIPS,request_id='stale')
    assert '\n'.join(c.iterdump())==before
    plan=repair.preview(c,TRIPS)
    tid=plan['targets'][-1]['tid']
    c.execute("CREATE TEMP TRIGGER reject_repair BEFORE UPDATE ON transactions WHEN OLD.transaction_id='"+tid+"' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError,match='synthetic failure'):
        repair.apply(c,plan,TRIPS,request_id='fails')
    assert '\n'.join(c.iterdump())==before


def test_p2_cannot_restore_a_generic_preparation_guess(setup):
    from app import ai_classification as ai
    c=setup[0].conn
    c.execute("UPDATE transactions SET approval_date='2026-09-30'");c.commit()
    p1.apply(c,p1.plan(c,TRIPS),TRIPS)
    tid=setup[3][0]['transaction_id']
    request=ai.prepare(c,TRIPS,[tid],reconsider=True)
    execution=dict(kind='connected_agent',provider='codex',model='gpt-6.1-sol',run_id='synthetic')
    result=dict(transaction_id=tid,trip_id='A',item='식비',basis='next departure',uncertainty='')
    with pytest.raises(ValueError,match='AI_ATTRIBUTION_INVALID'):
        ai.preview(c,TRIPS,request,dict(request_digest=request['digest'],execution=execution,results=[result]))
    result.update(trip_id='quarter:2026:3',item='분기 기타비용',basis='PROC-004')
    assert ai.preview(c,TRIPS,request,dict(request_digest=request['digest'],execution=execution,results=[result]))['count']==1
