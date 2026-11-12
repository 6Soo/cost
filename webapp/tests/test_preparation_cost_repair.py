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
    from app.automatic_classification import _read
    evidence={r['transaction_id']:dict(source_hash=r['source_hash'],trip_id='A',item='숙박비',basis='예약 이용기간',
                service_period=dict(starts_on='2026-10-02',ends_on='2026-10-03')) for r in _read(c)}
    reviewed=p1.plan(c,TRIPS,reconsider=True,evidence=evidence)
    p1.apply(c,reviewed,TRIPS,reconsider=True,evidence=evidence)
    assert {r[0] for r in c.execute('SELECT trip_id FROM transactions')}=={'A'}


def test_p2_can_keep_p1_missing_date_destination(setup):
    from app import ai_classification as ai
    c=setup[0].conn
    c.execute("UPDATE transactions SET approval_date='',posting_date=''")
    c.commit()
    p1.apply(c,p1.plan(c,TRIPS),TRIPS)
    tid=setup[3][0]['transaction_id']
    request=ai.prepare(c,TRIPS,[tid],reconsider=True)
    target=p1.infer_trip(p1._read(c,[tid])[0],TRIPS)[0]
    assert target
    result=dict(transaction_id=tid,trip_id=target,item='식비',basis='날짜 미상 기존 귀속 유지',uncertainty='이용일 미상')
    response=dict(request_digest=request['digest'],results=[result],
        execution=dict(kind='connected_agent',provider='codex',model='gpt-6.1-sol',run_id='synthetic-missing-date'))
    assert ai.preview(c,TRIPS,request,response)['count']==1


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


@pytest.mark.parametrize('source',['inference','code_inference','auto_inferred'])
def test_existing_board_payload_without_trip_field_is_valid_and_restores_exactly(setup,source):
    c=setup[0].conn
    prepare(c)
    tid=setup[3][0]['transaction_id']
    c.execute('UPDATE transactions SET classification_source=?',(source,))
    payload=json.dumps(dict(item='식비',display_tab_id='A',confirmed_by='automatic',revision=1))
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense','A',1,?)",('card-'+tid,payload));c.commit()
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['to_move']==5
    repair.apply(c,plan,TRIPS,request_id='missing-trip-field')
    projected=json.loads(repair._state(c,tid)['board']['payload_json'])
    assert projected['trip_id']=='' and projected['display_tab_id']=='quarter:2026:3'
    assert projected['item']=='분기 기타비용' and 'PROC-004' in projected['classification_basis']
    repair.restore(c,repair.restore_preview(c,'missing-trip-field'),'missing-trip-field')
    restored=json.loads(repair._state(c,tid)['board']['payload_json'])
    assert 'trip_id' not in restored and restored['display_tab_id']=='A' and restored['item']=='식비'


@pytest.mark.parametrize('protection',['hold','exclusion','duplicate','parse','manual','unknown','closed'])
def test_refund_member_protection_blocks_the_whole_group(setup,protection):
    from webapp.tests.test_closed_period_grouping import refund_pair
    c,purchase,refund=refund_pair(setup);prepare(c)
    row=repair._state(c,refund)['transaction']
    if protection=='hold':
        c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',(refund,row['source_hash'],'evidence_pending','synthetic'))
    elif protection=='exclusion':
        c.execute('INSERT INTO transaction_company_exclusions VALUES (?,?,1,1,?,?)',(refund,row['source_hash'],'synthetic','synthetic'))
    else:
        values={'duplicate':"duplicate_of='synthetic'",'parse':"parse_error='synthetic'",'manual':"decided_at='synthetic'",'unknown':"classification_basis='unknown'",'closed':"approval_date='2026-03-01'"}
        c.execute('UPDATE transactions SET '+values[protection]+' WHERE transaction_id=?',(refund,))
    c.commit()
    plan=repair.preview(c,TRIPS)
    assert not {purchase,refund}&{t['tid'] for t in plan['targets']}


def test_p2_keeps_evidenced_preparation_lodging_exception(setup):
    from app import ai_classification as ai,p2_case
    from tests.test_p2_case import Evidence
    c=setup[0].conn
    c.execute("UPDATE transactions SET approval_date='2026-09-30'");c.commit()
    p1.apply(c,p1.plan(c,TRIPS),TRIPS)
    # Unique next trip preserves the existing preparation-stay tie protection.
    trips=[TRIPS[0]]
    tid=setup[3][0]['transaction_id']
    request=ai.prepare(c,trips,[tid],reconsider=True)
    bundle=p2_case.assemble(c,trips,request,repository=Evidence([
        dict(ref='mail:synthetic-stay',kind='mail',content='Synthetic lodging reservation 2026-09-29~2026-09-30')]))
    result=dict(transaction_id=tid,trip_id='A',item='숙박비',service_start='2026-09-29',service_end='2026-09-30',
                evidence_refs=['mail:synthetic-stay'],rule_ids=['TRIP-042'],basis='범위가 명시된 준비 숙박',uncertainty='')
    response=dict(request_digest=request['digest'],more_evidence=[],results=[result],
                  execution=dict(kind='connected_agent',provider='codex',model='gpt-6.1-sol',run_id='synthetic-stay'))
    assert ai.preview(c,trips,request,response,bundle=bundle)['count']==1
    result['item']='식비'
    with pytest.raises(ValueError,match='AI_ATTRIBUTION_INVALID'):
        ai.preview(c,trips,request,response,bundle=bundle)


def test_p2_reads_only_revised_preparation_rules_and_keeps_lodging_exception():
    from app.p2_case import policy_context
    policy=policy_context()
    assert '일반 준비기간 추론은 폐지한다' in policy['trip']
    assert '모든 카드 비용 항목은 가장 가까운 다음 검증 여행의 준비 비용으로 추론' not in policy['trip']
    assert 'TRIP-042' in policy['trip'] and 'DATE-039' in policy['date']
