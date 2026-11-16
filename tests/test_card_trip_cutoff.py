"""TRIP-099 boundaries and bypass regression, with synthetic source rows only."""
import json
import pytest
from app.trip_selection import past_trip, card_trip_allowed, limit_past_trip
from app.automatic_classification import infer_trip
from app import classification_correction, ai_review_repair
from app.ledger import _authority_block, _guard_past_trip_pairs
from webapp.tests.test_automatic_classification_completion import setup
from tests.test_ai_review_repair import prepare, correction_for, make_manifest
from tests.test_source_recheck import reviewed, TRIPS

TRIP = dict(trip_id='old', starts_on='2026-09-01', ends_on='2026-09-10')

@pytest.mark.parametrize('paid,expected', [('2026-09-09',False), ('2026-09-10',False),
    ('2026-09-16',False),('2026-09-17',False),('2026-09-18',True),('2026-10-03',True)])
def test_source_payment_cutoff_uses_trip_end_not_start(paid,expected):
    row=dict(approval_date=paid,posting_date='2026-12-31')
    assert past_trip(row,TRIP) is expected
    assert card_trip_allowed(row,TRIP) is not expected

def test_posting_is_only_used_when_approval_absent_and_unknown_is_not_elapsed_proof():
    assert past_trip(dict(posting_date='2026-10-03'),TRIP)
    assert not past_trip(dict(approval_date='invalid',posting_date='2026-10-03'),TRIP)
    assert not past_trip(dict(approval_date='2026-10-03'),dict(TRIP,ends_on=None))

def test_existing_automatic_trip_and_refund_inheritance_cannot_bypass_cutoff():
    row=dict(approval_date='2026-10-03',transaction_direction='purchase',trip_id='old',display_tab_id='old')
    assert infer_trip(row,[TRIP])[0]==''
    refund=dict(row,transaction_direction='cancellation',amount_krw=-1000)
    fixed=limit_past_trip(refund,dict(trip_id='old',display_tab_id='old',item='숙박비'),[TRIP])
    assert fixed['display_tab_id']=='quarter:2026:4' and fixed['trip_id']==''
    assert fixed['item']=='숙박비'
    assert limit_past_trip(refund,fixed,[TRIP])==fixed

def test_p2_apply_revalidates_cutoff_not_only_candidate_preparation(setup):
    board,flow,batch,rows=setup; c=board.conn;prepare(c);tid=rows[0]['transaction_id']
    correction=correction_for(c,tid,'old');correction['trip_id']=correction.pop('display_tab_id')
    with pytest.raises(ValueError,match='CORRECTION_PAST_TRIP'):
        classification_correction.preview(c,[correction],[TRIP])
    plan=ai_review_repair.preview(c,[TRIP],make_manifest([correction_for(c,tid,'old')]))
    assert plan['summary']['excluded']=={'PAST_TRIP':1}
    assert plan['targets']==[]

def test_ledger_final_authority_reads_source_payment_not_display_date(setup):
    board,flow,batch,rows=setup
    trip=board.create_trip(starts_on='2026-09-01',ends_on='2026-09-10',destination='합성',client_request_id='synthetic-past')
    tid=rows[0]['transaction_id'];entry=dict(transaction_id=tid,trip_id=trip['tab_id'],display_tab_id=trip['tab_id'],occurred_on='2026-09-01')
    before=board.conn.total_changes
    assert _authority_block(entry,lambda _:True,lambda _:True,conn=board.conn)[0]=='past_trip'
    assert board.conn.total_changes==before

def test_post_pair_guard_blocks_original_and_refund_together(setup):
    from tests.card_pipeline.test_partial_refund import build, row_of
    pipe,batch=build()
    c=pipe.store.conn
    c.execute('CREATE TABLE trip_tabs(tab_id TEXT PRIMARY KEY, ends_on TEXT)')
    c.execute("INSERT INTO trip_tabs VALUES ('old','2026-09-25')")
    original=dict(transaction_id=row_of(pipe,'100')['transaction_id'],trip_id='old',display_tab_id='old')
    refund=dict(transaction_id=row_of(pipe,'200')['transaction_id'],trip_id='old',display_tab_id='old',
                refund_link=dict(role='refund',counterpart_id=original['transaction_id']))
    original['refund_link']=dict(role='original',counterpart_id=refund['transaction_id'])
    # Original Oct 1 is within seven days. Only the Oct 3 refund violates it;
    # the existing verified partial-refund graph must still block both rows.
    assert _authority_block(original,lambda _:True,lambda _:True,conn=c) is None
    ready=[original,refund];unresolved=[]
    _guard_past_trip_pairs(c,[original,refund],ready,unresolved)
    assert ready==[] and len(unresolved)==2
    assert all(r['blocked']=='past_trip' for r in unresolved)

def test_q2_expired_automatic_attribution_requires_reparsed_originals(setup,tmp_path):
    c,tid,directory,doc,facts,manifest=reviewed(setup,tmp_path,kind='past_trip',day='2026-06-17')
    plan=ai_review_repair.preview(c,TRIPS,manifest,evidence=facts)
    assert plan['summary']['to_apply']==1
    assert facts[tid]['purpose']=='past_trip'
    assert plan['targets'][0]['values']['display_tab_id']=='quarter:2026:2'
