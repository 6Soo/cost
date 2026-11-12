import json
import sqlite3

import pytest

from app import closed_period as boundary, closed_period_repair as repair
from app import automatic_classification as p1
from app.classify import classify_transaction
from tools.complete_card_classification import counts
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


@pytest.mark.parametrize('approval,posting,expected', [
    ('2025-01-01','2026-08-01','2025'), ('2025-12-31','','2025'),
    ('2026-01-01','','2026Q1'), ('2026-03-31','','2026Q1'),
    ('','2025-08-01','2025'), ('','2026-03-31','2026Q1'),
    ('2026-04-01','2025-01-01',None), ('2026-10-01','',None),
    ('bad','2025-01-01',None), ('','',None), ('2024-12-31','',None)])
def test_date_boundary_and_observed_date_precedence(approval,posting,expected):
    assert boundary.completed_period(dict(approval_date=approval,posting_date=posting)) == expected


def old_rows(c,day='2025-10-03'):
    c.execute("UPDATE transactions SET approval_date=?,classification_source='inference',"
              "classification_state='classified',item='기타경비',trip_id='A',display_tab_id='A',decided_at=NULL",(day,))
    c.commit()


def refund_pair(setup):
    board,_,_,rows=setup
    c=board.conn
    old_rows(c)
    purchase,refund=[r['transaction_id'] for r in rows[:2]]
    c.execute("UPDATE transactions SET approval_number='SYN-PAIR',original_approval_number='' WHERE transaction_id=?",(purchase,))
    c.execute("UPDATE transactions SET transaction_direction='cancellation',transaction_kind='cancellation',"
              "approval_number='SYN-CANCEL',original_approval_number='SYN-PAIR',approval_date='2026-01-02',"
              "amount_krw=-(SELECT amount_krw FROM transactions WHERE transaction_id=?),"
              "issuer=(SELECT issuer FROM transactions WHERE transaction_id=?),"
              "card_tail=(SELECT card_tail FROM transactions WHERE transaction_id=?),"
              "merchant=(SELECT merchant FROM transactions WHERE transaction_id=?) WHERE transaction_id=?",
              (purchase,purchase,purchase,purchase,refund))
    c.commit()
    return c,purchase,refund


def test_refund_both_sides_move_by_own_quarter_and_restore_atomically(setup):
    from app.partial_refund import refund_links
    c,purchase,refund=refund_pair(setup)
    for tid in (purchase,refund):
        row=repair._state(c,tid)['transaction']
        c.execute('INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (tid,setup[2],row['item'],'synthetic separate description','A','A',row['amount_krw'],
                   row['merchant'],row['approval_date'],row['transaction_direction'],row['source_hash'],'synthetic'))
        payload=dict(item=row['item'],description='synthetic board description',display_tab_id='A',trip_id='A',revision=1)
        c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense','A',1,?)",
                  ('card-'+tid,json.dumps(payload)))
    c.commit()
    before={tid:repair._state(c,tid) for tid in (purchase,refund)}
    links=refund_links(c,[purchase,refund])
    assert links[refund]['status']=='full' and links[refund]['net_krw']==0
    financial=repair._financial_state(c)
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['refund_candidate_rows']==2
    assert plan['summary']['refund_move_rows']==2
    assert plan['summary']['refund_move_groups']==1
    assert plan['summary']['refund_preserved_rows']==0
    repair.apply(c,plan,TRIPS,request_id='paired')
    assert c.execute('SELECT display_tab_id FROM transactions WHERE transaction_id=?',(purchase,)).fetchone()[0]=='quarter:2025:4'
    assert c.execute('SELECT display_tab_id FROM transactions WHERE transaction_id=?',(refund,)).fetchone()[0]=='quarter:2026:1'
    assert refund_links(c,[purchase,refund])==links
    assert repair._financial_state(c)==financial
    for tid,tab in ((purchase,'quarter:2025:4'),(refund,'quarter:2026:1')):
        state=repair._state(c,tid)
        assert state['ledger']['display_tab_id']==tab and state['board']['display_tab_id']==tab
        assert json.loads(state['board']['payload_json'])['display_tab_id']==tab
    assert repair.apply(c,plan,TRIPS,request_id='paired')['applied_this_run']==0
    assert repair.restore(c,repair.restore_preview(c,'paired'),'paired')['restore']==5
    assert repair._financial_state(c)==financial
    for tid,old in before.items():
        new=repair._state(c,tid)
        assert {k:v for k,v in new['transaction'].items() if k!='revision'}=={
            k:v for k,v in old['transaction'].items() if k!='revision'}
        assert new['ledger']==old['ledger']
        a,b=[json.loads(s['board']['payload_json']) for s in (new,old)]
        assert {k:v for k,v in a.items() if k!='revision'}=={k:v for k,v in b.items() if k!='revision'}


@pytest.mark.parametrize('protection',[
    'open_member','manual_member','review_hold','excluded','excess','source_conflict','completed_trip','formal_exception'])
def test_refund_group_never_moves_one_side_or_relaxes_other_protection(setup,protection):
    c,purchase,refund=refund_pair(setup)
    board,flow,_,_=setup
    trips,evidence=TRIPS,{}
    if protection=='open_member':
        c.execute("UPDATE transactions SET approval_date='2026-10-03' WHERE transaction_id=?",(refund,))
    elif protection=='manual_member':
        row=repair._state(c,refund)['transaction']
        flow.pipeline.save_decision(refund,row['revision'],item='식비',trip_id='A',display_tab_id='A',
            trip_validator=lambda _:True,tab_validator=lambda _:True,request_id='actual-manual-refund')
    elif protection=='review_hold':
        row=repair._state(c,refund)['transaction']
        c.execute('INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
                  (refund,row['source_hash'],'evidence_pending','synthetic protection'))
    elif protection=='excluded':
        row=repair._state(c,refund)['transaction']
        # Use the existing schema; no source or finance relation is changed.
        c.execute('INSERT INTO transaction_company_exclusions(transaction_id,source_hash,excluded,revision,note,updated_at) VALUES (?,?,1,1,?,?)',
                  (refund,row['source_hash'],'synthetic exclusion','synthetic'))
    elif protection=='excess':
        c.execute('UPDATE transactions SET amount_krw=amount_krw*2 WHERE transaction_id=?',(refund,))
    elif protection=='source_conflict':
        c.execute("UPDATE transactions SET conflict_reason='synthetic conflict' WHERE transaction_id=?",(refund,))
    elif protection=='completed_trip':
        c.execute("UPDATE transactions SET trip_id='closed',display_tab_id='closed' WHERE transaction_id=?",(refund,))
        trips=TRIPS+[dict(trip_id='closed',starts_on='2026-01-01',ends_on='2026-01-05')]
    else:
        evidence={refund:fact(repair._state(c,refund)['transaction'])}
    c.commit()
    before={tid:repair._state(c,tid) for tid in (purchase,refund)}
    financial=repair._financial_state(c)
    plan=repair.preview(c,trips,evidence=evidence)
    assert not {purchase,refund}&{t['tid'] for t in plan['targets']}
    assert plan['summary']['refund_move_rows']==0
    repair.apply(c,plan,trips,request_id='protected-'+protection,evidence=evidence)
    assert {tid:repair._state(c,tid) for tid in before}==before
    assert repair._financial_state(c)==financial


@pytest.mark.parametrize('numerator,denominator,moved',[(1,2,2),(1,1,2),(2,1,0)])
def test_foreign_refund_group_checks_actual_net_before_moving(setup,numerator,denominator,moved):
    from app.partial_refund import refund_links
    c,purchase,refund=refund_pair(setup)
    c.execute("UPDATE transactions SET original_approval_number='',foreign_currency='JPY',foreign_amount='100',"
              "merchant_normalized='SYNTHETIC FOREIGN NET' WHERE transaction_id IN (?,?)",(purchase,refund))
    c.execute("UPDATE transactions SET approval_date='2025-12-30' WHERE transaction_id=?",(purchase,))
    c.execute('UPDATE transactions SET amount_krw=-(SELECT amount_krw FROM transactions WHERE transaction_id=?)*?/? '
              'WHERE transaction_id=?',(purchase,numerator,denominator,refund))
    c.commit()
    links=refund_links(c,[purchase,refund])
    assert links[refund]['basis']=='merchant_card_foreign_amount'
    assert (links[refund]['net_krw']<0)==(moved==0)
    before={tid:repair._state(c,tid) for tid in (purchase,refund)}
    financial=repair._financial_state(c)
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['refund_move_rows']==moved
    assert ({purchase,refund}&{t['tid'] for t in plan['targets']})==({purchase,refund} if moved else set())
    if not moved:
        assert plan['summary']['refund_preserved']['EXCESS_REFUND']==2
    repair.apply(c,plan,TRIPS,request_id='foreign-net-'+str(numerator)+'-'+str(denominator))
    if not moved:
        assert {tid:repair._state(c,tid) for tid in before}==before
    assert repair._financial_state(c)==financial
    assert refund_links(c,[purchase,refund])==links


def test_unpaired_completed_refund_stays_and_reports_reason(setup):
    c,_,refund=refund_pair(setup)
    c.execute("UPDATE transactions SET original_approval_number='UNKNOWN',merchant='UNPAIRED SYNTHETIC' WHERE transaction_id=?",(refund,))
    c.commit()
    plan=repair.preview(c,TRIPS)
    assert refund not in {t['tid'] for t in plan['targets']}
    assert plan['summary']['refund_preserved']['UNPAIRED']==1


def test_partial_refund_group_with_multiple_cancellations_moves_all_members(setup):
    from app.partial_refund import refund_links
    c,purchase,refund=refund_pair(setup)
    extra=setup[3][2]['transaction_id']
    c.execute('UPDATE transactions SET amount_krw=-(SELECT amount_krw/4 FROM transactions WHERE transaction_id=?) WHERE transaction_id=?',
              (purchase,refund))
    c.execute("UPDATE transactions SET transaction_direction='cancellation',transaction_kind='cancellation',"
              "original_approval_number='SYN-PAIR',approval_number='SYN-EXTRA',approval_date='2025-12-01',"
              "amount_krw=(SELECT amount_krw FROM transactions WHERE transaction_id=?),"
              "issuer=(SELECT issuer FROM transactions WHERE transaction_id=?),"
              "card_tail=(SELECT card_tail FROM transactions WHERE transaction_id=?) WHERE transaction_id=?",
              (refund,purchase,purchase,extra))
    c.commit()
    links=refund_links(c,[refund,extra])
    assert len(links)==2 and all(v['status']=='partial' and v['refund_count']==2 for v in links.values())
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['refund_move_rows']==3 and plan['summary']['refund_move_groups']==1
    repair.apply(c,plan,TRIPS,request_id='partial-multiple')
    assert refund_links(c,[refund,extra])==links
    assert {r[0] for r in c.execute('SELECT display_tab_id FROM transactions WHERE transaction_id IN (?,?)',
                                   (purchase,extra))}=={'quarter:2025:4'}
    repair.restore(c,repair.restore_preview(c,'partial-multiple'),'partial-multiple')
    assert refund_links(c,[refund,extra])==links


def test_display_only_inferred_pair_is_preserved(setup,monkeypatch):
    from app import partial_refund
    c,purchase,refund=refund_pair(setup)
    actual=partial_refund.refund_links
    def inferred(conn,ids):
        return {tid:dict(link,inferred=True) for tid,link in actual(conn,ids).items()}
    monkeypatch.setattr(partial_refund,'refund_links',inferred)
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['refund_preserved']['INFERRED_LINK']==2
    assert not {purchase,refund}&{r['tid'] for r in plan['targets']}


@pytest.mark.parametrize('protection',['conflict_reason','parse_error','duplicate_of'])
@pytest.mark.parametrize('foreign',[False,True])
@pytest.mark.parametrize('invalid_date',['','missing','invalid'])
def test_filtered_protected_sibling_blocks_the_entire_raw_group(setup,protection,foreign,invalid_date):
    from app.partial_refund import refund_links
    c,purchase,refund=refund_pair(setup)
    extra=setup[3][2]['transaction_id']
    c.execute('UPDATE transactions SET amount_krw=-(SELECT amount_krw/2 FROM transactions WHERE transaction_id=?) WHERE transaction_id=?',
              (purchase,refund))
    c.execute("UPDATE transactions SET transaction_direction='cancellation',transaction_kind='cancellation',"
              "original_approval_number='SYN-PAIR',approval_number='SYN-BROKEN',approval_date='2026-01-03',"
              "amount_krw=(SELECT amount_krw FROM transactions WHERE transaction_id=?),"
              "issuer=(SELECT issuer FROM transactions WHERE transaction_id=?),"
              "card_tail=(SELECT card_tail FROM transactions WHERE transaction_id=?),"
              "merchant_normalized=(SELECT merchant_normalized FROM transactions WHERE transaction_id=?) WHERE transaction_id=?",
              (refund,purchase,purchase,purchase,extra))
    c.execute('UPDATE transactions SET '+protection+'=? WHERE transaction_id=?',('synthetic protection',extra))
    if foreign:
        c.execute("UPDATE transactions SET original_approval_number='',foreign_currency='JPY',foreign_amount='100',"
                  "merchant_normalized='SYNTHETIC SAME KEY' WHERE transaction_id IN (?,?,?)",(purchase,refund,extra))
        c.execute("UPDATE transactions SET approval_date='2025-12-30' WHERE transaction_id=?",(purchase,))
    if invalid_date:
        c.execute("UPDATE transactions SET approval_date=?,posting_date='' WHERE transaction_id=?",
                  ('' if invalid_date=='missing' else 'invalid',extra))
    c.commit()
    links=refund_links(c,[refund,extra])
    assert refund in links and extra not in links
    before={tid:repair._state(c,tid) for tid in (purchase,refund,extra)}
    plan=repair.preview(c,TRIPS)
    assert not set(before)&{r['tid'] for r in plan['targets']}
    repair.apply(c,plan,TRIPS,request_id='protected-sibling-'+protection+str(foreign))
    assert {tid:repair._state(c,tid) for tid in before}==before


def test_new_refund_protection_invalidates_whole_preview(setup):
    c,_,refund=refund_pair(setup)
    plan=repair.preview(c,TRIPS)
    row=repair._state(c,refund)['transaction']
    c.execute('INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
              (refund,row['source_hash'],'evidence_pending','new protection'))
    c.commit()
    before=list(c.iterdump())
    with pytest.raises(ValueError,match='GROUPING_PREVIEW_STALE'):
        repair.apply(c,plan,TRIPS,request_id='new-financial-protection')
    assert list(c.iterdump())==before


def test_financial_postcheck_rolls_back_entire_request(setup,monkeypatch):
    c,purchase,refund=refund_pair(setup)
    before=list(c.iterdump())
    actual=repair._financial_state
    def state(conn):
        if conn.execute('SELECT display_tab_id FROM transactions WHERE transaction_id=?',(purchase,)).fetchone()[0].startswith('quarter:'):
            return 'synthetic changed financial graph'
        return actual(conn)
    monkeypatch.setattr(repair,'_financial_state',state)
    plan=repair.preview(c,TRIPS)
    with pytest.raises(ValueError,match='GROUPING_FINANCIAL_CHANGED'):
        repair.apply(c,plan,TRIPS,request_id='rollback-whole-refund-group')
    assert list(c.iterdump())==before


def test_restore_refuses_changed_financial_protection(setup):
    c,_,refund=refund_pair(setup)
    repair.apply(c,repair.preview(c,TRIPS),TRIPS,request_id='financial-stale')
    row=repair._state(c,refund)['transaction']
    c.execute('INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)',
              (refund,row['source_hash'],'evidence_pending','new protection'))
    c.commit()
    with pytest.raises(ValueError,match='GROUPING_RESTORE_FINANCIAL_STALE'):
        repair.restore_preview(c,'financial-stale')


def fact(row,trip='A'):
    return dict(source_hash=row['source_hash'],trip_id=trip,formal_link=True,
        service_period=dict(starts_on='2026-10-02',ends_on='2026-10-03'),item='숙박비',basis='synthetic exact link')


def test_only_confirmed_period_or_actual_manual_can_escape_boundary():
    row=dict(approval_date='2025-10-03',source_hash='synthetic',trip_id='A',classification_source='user_decision')
    assert boundary.excluded(row,TRIPS)
    assert not boundary.excluded(row,TRIPS,manual=True)
    proof=fact(row)
    assert not boundary.excluded(row,TRIPS,evidence=proof)
    for change in [dict(formal_link=False),dict(source_hash='changed'),
                   dict(service_period=dict(starts_on='2026-09-30',ends_on='2026-10-03'))]:
        assert boundary.excluded(row,TRIPS,evidence=dict(proof,**change))
    historical=[dict(trip_id='A',starts_on='2026-01-01',ends_on='2026-01-05'),TRIPS[1]]
    assert boundary.excluded(row,historical,evidence=fact(row,'B'),manual=True)
    assert boundary.excluded(dict(row,trip_id='',display_tab_id='quarter:2025:4'),TRIPS,evidence=proof)


def test_review_lists_and_question_counters_exclude_completed_before_ranking(setup,monkeypatch):
    from webapp.card_flow import batch_catalog, _cleanup_card_count
    from webapp.provisional_trip_review import read_page
    board,flow,batch,_=setup
    old_rows(board.conn)
    board.conn.execute("UPDATE transactions SET classification_state='needs_review',item='',trip_id='',display_tab_id=''")
    board.conn.commit()
    monkeypatch.setattr(flow,'trip_valid',lambda _:True)
    before=board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    assert batch_catalog(board)[0]['questions'] == 0
    assert _cleanup_card_count(board) == 0
    assert read_page(flow,batch)['total'] == 0
    assert board.conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == before


def test_p1_reconsider_and_latest_trip_fallback_skip_completed_but_accept_formal_exception(setup):
    board,_,_,rows=setup
    old_rows(board.conn)
    assert p1.plan(board.conn,TRIPS,reconsider=True)['targets'] == []
    assert p1.infer_trip(dict(approval_date='',posting_date='2025-10-03'),TRIPS)[0] == ''
    tid=rows[0]['transaction_id']
    evidence={tid:fact(rows[0],'B')}
    assert len(p1.plan(board.conn,TRIPS,evidence=evidence)['targets']) == 1
    plan=p1.plan(board.conn,TRIPS,reconsider=True,evidence=evidence)
    assert len(plan['targets']) == 1
    assert plan['targets'][0]['id'] == tid
    p1.apply(board.conn,plan,TRIPS,reconsider=True,evidence=evidence)
    assert board.conn.execute('SELECT trip_id FROM transactions WHERE transaction_id=?',(tid,)).fetchone()[0] == 'B'
    assert len(p1.plan(board.conn,TRIPS,reconsider=True)['targets']) == 0


def test_closed_gate_does_not_change_open_inference_and_counts_only_open_scope(setup):
    board,_,_,rows=setup
    assert len(p1.plan(board.conn,TRIPS)['targets']) == 5
    before=counts(board.conn,TRIPS)
    assert before['unclassified_purchases'] == 5
    old_rows(board.conn,'2026-03-31')
    board.conn.execute("UPDATE transactions SET item='',classification_state='needs_review',trip_id='',display_tab_id='' ")
    board.conn.commit()
    assert counts(board.conn,TRIPS)['unclassified_purchases'] == 0
    board.conn.execute("UPDATE transactions SET approval_date='2026-05-01'")
    board.conn.commit()
    assert counts(board.conn,TRIPS)['unclassified_purchases'] == 0


def test_low_level_p1_preserves_completed_input():
    row=dict(approval_date='2025-10-03',classification_state='preserved',item='',trip_id='A')
    assert classify_transaction(row,rules=[])['classification_state'] == 'preserved'
    assert classify_transaction(row,rules=[])['item'] == ''


def test_p2_scope_excludes_completed_first_but_keeps_formal_open_exception():
    from tests.test_p2_batch import row, data
    from tools.p2_batch.scope import select
    old=row(approval_date='2025-10-03')
    d=data([old,row(transaction_id='open-row',approval_date='2026-10-03')])
    assert [r['transaction_id'] for r in select(d)[1]] == ['open-row']
    assert select(d)[0]['protected']['COMPLETED_PERIOD'] == 1
    d['completed_period_evidence']={'synthetic':dict(source_hash='hash',trip_id='open',formal_link=True,
        service_period=dict(starts_on='2026-06-30',ends_on='2026-07-01'))}
    assert len(select(d)[1]) == 2


def test_repair_projection_restore_preserves_descriptions_and_payload_provenance(setup):
    board,_,batch,rows=setup
    c=board.conn
    old_rows(c)
    row=rows[0]
    tid=row['transaction_id']
    c.execute('INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (tid,batch,'숙박비','separate ledger description','A','A',row['amount_krw'],row['merchant'],row['approval_date'],'purchase',row['source_hash'],'synthetic'))
    payload=dict(item='숙박비',description='board description',display_tab_id='A',trip_id='A',confirmed_by='automatic',revision=1)
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense','A',1,?)",('card-'+tid,json.dumps(payload)))
    c.commit()
    before=repair._state(c,tid)
    repair.apply(c,repair.preview(c,TRIPS),TRIPS,request_id='projection')
    assert repair._state(c,tid)['ledger']['description'] == before['ledger']['description']
    repair.restore(c,repair.restore_preview(c,'projection'),'projection')
    after=repair._state(c,tid)
    assert after['ledger'] == before['ledger']
    restored_payload=json.loads(after['board']['payload_json'])
    assert {k:v for k,v in restored_payload.items() if k!='revision'} == {k:v for k,v in payload.items() if k!='revision'}


@pytest.mark.parametrize('day,item,tab',[('2025-10-03','2025년 항목','quarter:2025:4'),
                                     ('2026-03-31','분기 기타비용','quarter:2026:1')])
def test_repair_apply_restore_idempotency_and_raw_history_invariants(setup,day,item,tab):
    board,_,_,rows=setup
    c=board.conn
    old_rows(c,day)
    before={r['transaction_id']:repair._state(c,r['transaction_id']) for r in rows}
    plan=repair.preview(c,TRIPS)
    assert plan['summary']['to_move'] == 5
    assert repair.apply(c,plan,TRIPS,request_id='synthetic')['applied_this_run'] == 5
    assert c.execute('SELECT DISTINCT item,display_tab_id,trip_id FROM transactions').fetchall() == [(item,tab,'')]
    assert repair.preview(c,TRIPS)['summary']['to_move'] == 0
    assert repair.apply(c,plan,TRIPS,request_id='synthetic')['applied_this_run'] == 0
    restored=repair.restore(c,repair.restore_preview(c,'synthetic'),'synthetic')
    assert restored['restore'] == 5
    for tid,old in before.items():
        new=repair._state(c,tid)
        assert {k:v for k,v in new['transaction'].items() if k!='revision'} == {
            k:v for k,v in old['transaction'].items() if k!='revision'}
    assert repair.restore_preview(c,'synthetic')['summary']['restore'] == 0


def test_completed_trip_manual_and_formal_exceptions_never_move(setup):
    board,flow,_,rows=setup
    old_rows(board.conn)
    c=board.conn
    c.execute("UPDATE transactions SET trip_id='closed',display_tab_id='closed' WHERE transaction_id=?",(rows[0]['transaction_id'],))
    c.commit()
    current=p1._read(c,{rows[1]['transaction_id']})[0]
    flow.pipeline.save_decision(current['transaction_id'],current['revision'],item='식비',trip_id='A',display_tab_id='A',
        trip_validator=lambda _:True,tab_validator=lambda _:True,request_id='real-user')
    trips=TRIPS+[dict(trip_id='closed',starts_on='2026-01-01',ends_on='2026-01-05')]
    plan=repair.preview(c,trips,evidence={rows[2]['transaction_id']:fact(rows[2])})
    assert plan['summary']['completed_trip_unchanged'] == 1
    assert plan['summary']['confirmed_exceptions'] == 2
    assert plan['summary']['to_move'] == 2


def test_existing_quarter_destination_contract_accepts_closed_years_without_new_tabs(setup):
    _,flow,_,_=setup
    assert flow.tab_valid('quarter:2025:1')
    assert flow.tab_valid('quarter:2025:4')
    assert flow.tab_valid('quarter:2026:1')


def test_only_source_bound_exact_central_facts_create_an_exception():
    source=dict(transaction_id='synthetic',source_hash='hash',core_link=True,inferred_link=False,
        source_sha256='evidence-digest',reservation_status='confirmed',
        period=dict(starts_on='2026-10-02',ends_on='2026-10-03'))
    proof=boundary.formal_facts([source],TRIPS[:1])
    assert proof['synthetic']['trip_id'] == 'A'
    assert boundary.formal_facts([dict(source,source_sha256='changed-source')],TRIPS[:1]) != proof
    for changes in [dict(inferred_link=True),dict(core_link=False),dict(source_sha256=''),
                    dict(service_period_basis='LINK-108'),dict(reservation_status='cancelled'),dict(period_conflict=True)]:
        assert boundary.formal_facts([dict(source,**changes)],TRIPS[:1]) == {}


def test_formal_exception_reaches_real_p2_prepare_preview_apply_and_is_bound_to_trip(setup):
    from app import ai_classification as ai, classification_correction as correction
    board,_,_,rows=setup
    c=board.conn
    old_rows(c)
    tid=rows[0]['transaction_id']
    evidence={tid:fact(rows[0])}
    # No P1 prerequisite mock: the real completion plan must be stable first.
    stage=p1.plan(c,TRIPS,transaction_ids={tid},evidence=evidence)
    p1.apply(c,stage,TRIPS,transaction_ids={tid},evidence=evidence)
    assert not p1.plan(c,TRIPS,transaction_ids={tid},evidence=evidence)['targets']
    request=ai.prepare(c,TRIPS,{tid},reconsider=True,completed_evidence=evidence)
    assert len(request['cases']) == 1
    assert {t['trip_id'] for t in request['cases'][0]['trips']} == {'A'}
    response=dict(request_digest=request['digest'],execution=dict(kind='connected_agent',provider='synthetic',model='synthetic',run_id='formal'),
        results=[dict(transaction_id=tid,trip_id='A',item='식비',basis='synthetic service evidence',uncertainty='')])
    changed={tid:dict(evidence[tid],service_period=dict(starts_on='2026-10-03',ends_on='2026-10-04'))}
    with pytest.raises(ValueError,match='AI_REQUEST_STALE'):
        ai.preview(c,TRIPS,request,response,completed_evidence=changed)
    fix=dict(transaction_id=tid,source_hash=rows[0]['source_hash'],trip_id='B',item='식비',basis='synthetic')
    with pytest.raises(ValueError,match='CORRECTION_INVALID_ATTRIBUTION'):
        correction.preview(c,[fix],TRIPS,completed_evidence=evidence)
    ai.preview(c,TRIPS,request,response,completed_evidence=evidence)
    result=ai.apply(c,TRIPS,request,response,request_id='formal-p2',completed_evidence=evidence)
    assert result['applied'] == 1
    assert c.execute('SELECT trip_id,item FROM transactions WHERE transaction_id=?',(tid,)).fetchone() == ('A','식비')
    assert not ai.prepare(c,TRIPS,{tid},reconsider=True)['cases']


def test_review_and_counters_use_fresh_published_formal_facts_not_source_labels(setup,monkeypatch):
    from webapp.card_flow import CardFlow,batch_catalog,_cleanup_card_count
    from webapp.provisional_trip_review import read_page
    board,flow,batch,rows=setup
    old_rows(board.conn)
    board.conn.execute("UPDATE transactions SET classification_state='needs_review',item=''")
    board.conn.commit()
    monkeypatch.setattr(board,'list_trips',lambda:[dict(TRIPS[0],tab_id='A',display_key='synthetic',deleted=False,archived=False)])
    monkeypatch.setattr(CardFlow,'trip_valid',lambda *a:True)
    monkeypatch.setattr(CardFlow,'_held_ota_snapshot',lambda *a:({'synthetic':True},True))
    source=dict(transaction_id=rows[0]['transaction_id'],source_hash=rows[0]['source_hash'],core_link=True,
        inferred_link=False,source_sha256='synthetic-evidence',reservation_status='confirmed',period=fact(rows[0])['service_period'])
    monkeypatch.setattr(CardFlow,'_canonical_snapshot_report',lambda *a:dict(matches=[source]))
    assert batch_catalog(board)[0]['questions'] == 1
    assert _cleanup_card_count(board) == 1
    assert read_page(flow,batch)['total'] == 1
    monkeypatch.setattr(CardFlow,'_held_ota_snapshot',lambda *a:({'synthetic':True},False))
    assert batch_catalog(board)[0]['questions'] == 0
    assert _cleanup_card_count(board) == 0


def test_real_p2_projection_loads_formal_evidence_before_selection(setup,tmp_path,monkeypatch):
    from tools.p2_batch.scope import read_projection,select
    import tools.complete_card_classification as loader
    board,_,_,rows=setup
    old_rows(board.conn)
    trip=board.create_trip(starts_on='2026-10-01',ends_on='2026-10-05',destination='synthetic',client_request_id='projection-trip')['tab_id']
    board.conn.execute('UPDATE transactions SET trip_id=?,display_tab_id=?',(trip,trip))
    board.conn.commit()
    host=tmp_path/'projection-host'
    (host/'data').mkdir(parents=True)
    (host/'config').mkdir()
    (host/'config/card-flow.json').write_text('{}')
    db=host/'data/board.sqlite'
    with sqlite3.connect(db) as target:board.conn.backup(target)
    tid=rows[0]['transaction_id']
    def loaded(conn,root,trips):
        assert root == host.resolve()
        assert trips[0]['trip_id'] == trip
        return {tid:fact(rows[0],trip)}
    monkeypatch.setattr(loader,'load_completed_period_evidence',loaded)
    projection=read_projection(db)
    assert [r['transaction_id'] for r in select(projection)[2]] == [tid]


def test_copy_apply_requires_fresh_verified_backup_and_checks_state(setup,tmp_path,monkeypatch):
    from tools import complete_card_classification as gate
    from tools.verify_operational_backup_restore import database_state
    from datetime import datetime,timezone
    board,_,_,_=setup
    host=tmp_path/'isolated-host'
    (host/'data/backups/verified').mkdir(parents=True)
    db=host/'data/board.sqlite'
    with sqlite3.connect(db) as copied:
        board.conn.backup(copied)
    manifest=host/'data/backups/verified/manifest.json'
    manifest.write_text(json.dumps(dict(databases={'board.sqlite':database_state(db)})),encoding='utf8')
    evidence=host/'data/backups/proof.json'
    evidence.write_text(json.dumps(dict(recorded_at=datetime.now(timezone.utc).isoformat(),
        live_state_unchanged=True,all_database_tables_and_columns_compared=True,
        restored_review_binding_equal=True,backup_directory=str(manifest.parent))),encoding='utf8')
    monkeypatch.setattr(gate.subprocess,'run',lambda *a,**k:pytest.fail('copy checked operating writers'))
    gate.require_offline_backup(host,evidence,db,isolated_copy=True)
    with sqlite3.connect(db) as copied:
        copied.execute('UPDATE transactions SET revision=revision+1')
    with pytest.raises(ValueError,match='BACKUP_SOURCE_CHANGED'):
        gate.require_offline_backup(host,evidence,db,isolated_copy=True)


def test_stale_preview_and_audit_failure_roll_back(setup):
    board,_,_,_=setup
    c=board.conn
    old_rows(c)
    plan=repair.preview(c,TRIPS)
    c.execute('UPDATE transactions SET revision=revision+1')
    c.commit()
    with pytest.raises(ValueError,match='PREVIEW_STALE'):
        repair.apply(c,plan,TRIPS,request_id='stale')
    plan=repair.preview(c,TRIPS)
    before=c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    c.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON change_log BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    c.commit()
    with pytest.raises(sqlite3.IntegrityError):
        repair.apply(c,plan,TRIPS,request_id='atomic')
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == before


def test_cli_repreview_after_apply_is_readonly_without_loading_sources(setup,tmp_path,monkeypatch,capsys):
    from tools import repair_closed_period_grouping as cli
    board,_,_,_=setup
    old_rows(board.conn)
    plan=repair.preview(board.conn,TRIPS)
    repair.apply(board.conn,plan,TRIPS,request_id='cli')
    host=tmp_path/'isolated'
    (host/'data').mkdir(parents=True)
    with sqlite3.connect(host/'data/board.sqlite') as target:
        board.conn.backup(target)
    monkeypatch.setattr(cli,'load_context',lambda *a:pytest.fail('replay loaded sources'))
    args=['--host-root',str(host),'--request-id','cli']
    assert cli.main(args) == 0
    report=json.loads(capsys.readouterr().out)
    assert report['to_move'] == report['applied_this_run'] == 0
    assert cli.main(args+['--apply','--expected-digest','wrong']) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'GROUPING_REQUEST_CONFLICT'


# --- Hana overseas double-import repair (SRC-013) -----------------------------
from app import card_hana_duplicate_repair as hana
from app.card_export_profiles import HANA_FOREIGN
from tests.card_pipeline.fixtures import make_csv
from tests.card_pipeline.test_export_downloads import hana_foreign

_HANA_APPROVAL_HEADERS = ['카드사', '이용일', '카드번호', '승인번호', '가맹점명', '승인금액', '가맹점번호']


def _hana_book(c, tid, batch, tab='A'):
    row = hana._state(c, tid)['transaction']
    c.execute('INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
              (tid, batch, '기타경비', 'synthetic', tab, tab, row['amount_krw'], row['merchant'],
               row['approval_date'], row['transaction_direction'], row['source_hash'], 'synthetic'))
    payload = dict(item='기타경비', description='synthetic', display_tab_id=tab, trip_id=tab, revision=1)
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense',?,1,?)",
              ('card-' + tid, tab, json.dumps(payload)))


def hana_double_import(tmp_path, monkeypatch, *, day='2026-10-09', acquired_amount=10300,
                       approval_amount=10000, acquired_approval='1111', approval_approval='00001111'):
    """Two booked rows for one purchase: acquired billed view + approval source.

    The approval view is imported with the cross-view matcher disabled so it stays
    a separate booked row, reproducing the pre-fix double import the repair cleans.
    """
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    board = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    flow = CardFlow(board)
    c = board.conn
    frow = hana_foreign(amount=acquired_amount)
    frow[1] = day
    frow[3] = acquired_approval
    ab = flow.pipeline.receive(make_csv([frow], headers=HANA_FOREIGN), 'acquired.csv')['batch_id']
    arow = ['하나', day, '****1234', approval_approval, '합성상점', approval_amount, '100']
    with monkeypatch.context() as m:
        m.setattr('app.card_export_profiles.existing_purchase', lambda *a, **k: None)
        pb = flow.pipeline.receive(make_csv([arow], headers=_HANA_APPROVAL_HEADERS), 'approval.csv')['batch_id']
    atid = c.execute('SELECT transaction_id FROM transactions WHERE batch_id=?', (ab,)).fetchone()[0]
    ptid = c.execute('SELECT transaction_id FROM transactions WHERE batch_id=?', (pb,)).fetchone()[0]
    _hana_book(c, atid, ab)
    _hana_book(c, ptid, pb)
    c.commit()
    return board, flow, c, atid, ptid


def test_hana_repair_marks_approval_duplicate_and_counts_once(tmp_path, monkeypatch):
    board, flow, c, atid, ptid = hana_double_import(tmp_path, monkeypatch)
    before = {tid: hana._state(c, tid) for tid in (atid, ptid)}
    financial = hana._financial_state(c)
    plan = hana.preview(c)
    assert plan['summary']['to_mark'] == 1 and plan['summary']['to_unbook'] == 1
    assert plan['targets'][0]['tid'] == ptid and plan['targets'][0]['keep'] == atid
    assert hana.apply(c, plan, request_id='hana-synthetic')['applied_this_run'] == 1
    dup = hana._state(c, ptid)
    assert dup['transaction']['duplicate_of'] == atid
    assert dup['ledger'] is None and dup['board'] is None
    for key in ('raw_row_json', 'amount_krw', 'approval_number', 'source_hash', 'transaction_id'):
        assert dup['transaction'][key] == before[ptid]['transaction'][key]
    keep = hana._state(c, atid)
    assert keep['transaction']['duplicate_of'] is None and keep['ledger'] == before[atid]['ledger']
    assert hana._financial_state(c) == financial
    assert c.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 1
    assert hana.apply(c, plan, request_id='hana-synthetic')['applied_this_run'] == 0
    assert hana.preview(c)['summary']['to_mark'] == 0
    assert hana.restore(c, hana.restore_preview(c, 'hana-synthetic'), 'hana-synthetic')['restore'] == 1
    after = hana._state(c, ptid)
    assert after['transaction']['duplicate_of'] is None
    assert after['ledger'] == before[ptid]['ledger']
    assert json.loads(after['board']['payload_json']) == json.loads(before[ptid]['board']['payload_json'])
    assert hana._financial_state(c) == financial
    board.close()


def test_hana_repair_closed_period_marks_only_without_changing_ledger(tmp_path, monkeypatch):
    board, flow, c, atid, ptid = hana_double_import(tmp_path, monkeypatch, day='2026-03-31')
    plan = hana.preview(c)
    assert plan['summary']['closed_mark_only'] == 1 and plan['summary']['to_unbook'] == 0
    assert plan['summary']['closed_amount_krw'] == 10000
    before = hana._state(c, ptid)
    hana.apply(c, plan, request_id='hana-closed')
    dup = hana._state(c, ptid)
    assert dup['transaction']['duplicate_of'] == atid
    assert dup['ledger'] == before['ledger'] and dup['board'] == before['board']
    assert c.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 2
    hana.restore(c, hana.restore_preview(c, 'hana-closed'), 'hana-closed')
    assert hana._state(c, ptid)['transaction']['duplicate_of'] is None
    board.close()


def test_hana_repair_preserves_refund_paired_pair(tmp_path, monkeypatch):
    board, flow, c, atid, ptid = hana_double_import(tmp_path, monkeypatch)
    c.execute("""INSERT INTO transactions(transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,
        transaction_direction,transaction_kind,approval_number,original_approval_number,approval_date,posting_date,
        merchant,merchant_normalized,amount_krw,row_index,raw_row_json,created_at)
        SELECT ?,source_hash,batch_id,issuer,card_tail,card_kind,'cancellation','cancellation','SYN-CANCEL',
        approval_number,approval_date,posting_date,merchant,merchant_normalized,-amount_krw,row_index,raw_row_json,created_at
        FROM transactions WHERE transaction_id=?""", (ptid + ':cancel', ptid))
    c.commit()
    plan = hana.preview(c)
    assert plan['summary']['to_mark'] == 0
    assert plan['summary']['excluded'].get('REFUND_PAIRED') == 1
    before = hana._state(c, ptid)
    hana.apply(c, plan, request_id='hana-refund')
    assert hana._state(c, ptid) == before
    board.close()


def test_hana_repair_preserves_manual_correction(tmp_path, monkeypatch):
    board, flow, c, atid, ptid = hana_double_import(tmp_path, monkeypatch)
    row = hana._state(c, ptid)['transaction']
    flow.pipeline.save_decision(ptid, row['revision'], item='식비', display_tab_id='A', trip_id='A',
                                tab_validator=lambda _: True, trip_validator=lambda _: True, request_id='hana-manual')
    plan = hana.preview(c)
    assert plan['summary']['to_mark'] == 0
    assert plan['summary']['excluded'].get('MANUAL_CORRECTION') == 1
    before = hana._state(c, ptid)
    hana.apply(c, plan, request_id='hana-manual-apply')
    assert hana._state(c, ptid) == before
    board.close()


def test_hana_repair_excludes_amount_multiple_false_positive(tmp_path, monkeypatch):
    board, flow, c, atid, ptid = hana_double_import(tmp_path, monkeypatch,
                                                    acquired_amount=900000, approval_amount=10000)
    plan = hana.preview(c)
    assert plan['summary']['to_mark'] == 0
    assert plan['summary']['excluded'].get('DIFFERENT_TRANSACTION') == 1
    board.close()


def test_hana_repair_cli_preview_is_count_only(tmp_path, monkeypatch, capsys):
    board, flow, c, atid, ptid = hana_double_import(tmp_path, monkeypatch)
    host = tmp_path / 'preview-host'
    (host / 'data').mkdir(parents=True)
    db = host / 'data/board.sqlite'
    with sqlite3.connect(db) as target:
        board.conn.backup(target)
    board.close()
    assert hana.main(['--host-root', str(host), '--request-id', 'hana-preview']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'PREVIEW' and report['to_mark'] == 1
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as check:
        assert check.execute('SELECT COUNT(*) FROM transactions WHERE duplicate_of IS NOT NULL').fetchone()[0] == 0
    assert hana.main(['--host-root', str(host), '--request-id', 'hana-preview', '--apply',
                      '--expected-digest', report['digest']]) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'PREVIEW_AND_BACKUP_REQUIRED'


def test_hana_repair_cli_apply_on_verified_isolated_copy(tmp_path, monkeypatch, capsys):
    from tools import complete_card_classification as gate
    from tools.verify_operational_backup_restore import database_state
    from datetime import datetime, timezone
    board, flow, c, atid, ptid = hana_double_import(tmp_path, monkeypatch)
    host = tmp_path / 'isolated-host'
    (host / 'data/backups/verified').mkdir(parents=True)
    db = host / 'data/board.sqlite'
    with sqlite3.connect(db) as copied:
        board.conn.backup(copied)
    board.close()
    manifest = host / 'data/backups/verified/manifest.json'
    manifest.write_text(json.dumps(dict(databases={'board.sqlite': database_state(db)})), encoding='utf8')
    evidence = host / 'data/backups/proof.json'
    evidence.write_text(json.dumps(dict(recorded_at=datetime.now(timezone.utc).isoformat(),
        live_state_unchanged=True, all_database_tables_and_columns_compared=True,
        restored_review_binding_equal=True, backup_directory=str(manifest.parent))), encoding='utf8')
    monkeypatch.setattr(gate.subprocess, 'run', lambda *a, **k: pytest.fail('copy checked operating writers'))
    assert hana.main(['--host-root', str(host), '--request-id', 'hana-cli']) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['status'] == 'PREVIEW' and preview['to_mark'] == 1
    assert hana.main(['--host-root', str(host), '--request-id', 'hana-cli', '--apply',
                      '--expected-digest', preview['digest'], '--backup-evidence', str(evidence),
                      '--isolated-copy']) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied['status'] == 'APPLIED' and applied['applied_this_run'] == 1
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as check:
        assert check.execute('SELECT duplicate_of FROM transactions WHERE transaction_id=?', (ptid,)).fetchone()[0] == atid
        assert check.execute('SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?', (ptid,)).fetchone()[0] == 0
    assert hana.main(['--host-root', str(host), '--request-id', 'hana-cli']) == 0
    assert json.loads(capsys.readouterr().out)['applied_this_run'] == 0
