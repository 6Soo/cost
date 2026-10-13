"""완료 기간 보존과 현지 여행 조건을 합성 자료로 검증한다."""
import sqlite3
from unittest.mock import patch

from app import Pipeline
from app.classify import classify_transaction
from app.rules import merchant_country, normalize_rule
from webapp.card_flow import CardFlow
from .fixtures import make_csv, domestic_row


class Board:
    def list_trips(self):
        return [dict(tab_id='japan',destination='교토',display_key='0408_교토',
                     starts_on='2026-04-08',ends_on='2026-04-12'),
                dict(tab_id='future',destination='도쿄',display_key='1201_도쿄',
                     starts_on='2026-12-01',ends_on='2026-12-03')]


def test_scoped_reclassification_preserves_every_other_transaction(tmp_path):
    conn=sqlite3.connect(tmp_path/'cost.sqlite',isolation_level=None)
    try:
        pipe=Pipeline(conn)
        batch=pipe.receive(make_csv([domestic_row(merchant='TARGET',amount=100,approval='one'),
                                     domestic_row(merchant='KEEP',amount=200,approval='two')]),'synthetic.csv')['batch_id']
        target=conn.execute("SELECT transaction_id FROM transactions WHERE merchant='TARGET'").fetchone()[0]
        previous=conn.execute("SELECT * FROM transactions WHERE merchant='KEEP'").fetchone()
        pipe.save_rule({'conditions':{'merchant_normalized':'TARGET'},'effects':{'item':'숙박비'}})
        pipe.save_rule({'conditions':{'merchant_normalized':'KEEP'},'effects':{'item':'식비'}})
        pipe.classify_batch(batch,transaction_ids=[target])
        assert conn.execute("SELECT item FROM transactions WHERE merchant='TARGET'").fetchone()[0]=='숙박비'
        assert conn.execute("SELECT * FROM transactions WHERE merchant='KEEP'").fetchone()==previous
        first=conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        pipe.classify_batch(batch,transaction_ids=[])
        assert conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()==first
    finally:
        conn.close()


def flow():
    f=CardFlow.__new__(CardFlow)
    f.board=Board()
    f.trip_valid=lambda identity:identity in ('japan','future')
    return f


def retail_rule():
    return normalize_rule({'conditions':{'merchant_normalized':'FAMILYMART'},
                           'optional':{'travel_country':'JP'},'effects':{'item':'식비'}})


def test_domestic_store_cannot_become_a_japan_trip_expense():
    transaction=dict(merchant='FAMILYMART',issuer='국민',card_kind='국내',approval_date='2026-04-09',raw_row={})
    result=classify_transaction(transaction,rules=[retail_rule()],trip_resolver=flow().retail_trip)
    assert result['classification_state']=='needs_review'
    assert not result['trip_id']


def test_verified_local_store_and_explicit_schedule_match():
    transaction=dict(merchant='FAMILYMART',issuer='국민',card_kind='해외',approval_date='2026-04-09',
                     raw_row={'c8':'JP'},foreign_currency='JPY')
    result=classify_transaction(transaction,rules=[retail_rule()],trip_resolver=flow().retail_trip)
    assert result['item']=='식비' and result['trip_id']=='japan'
    assert result['classification_state']=='classified'
    transaction['approval_date']=''
    transaction['posting_date']='2026-04-09'
    assert classify_transaction(transaction,rules=[retail_rule()],trip_resolver=flow().retail_trip)['classification_state']=='needs_review'


def test_currency_and_stale_schedule_cannot_supply_a_location():
    transaction=dict(merchant='FAMILYMART',issuer='국민',card_kind='해외',approval_date='2026-04-09',
                     raw_row={'c8':'SG'},foreign_currency='JPY')
    assert merchant_country(transaction)=='SG'
    assert not flow().retail_trip(transaction,'JP')
    transaction['raw_row']['c8']='JP'
    f=flow();f.trip_valid=lambda _:False
    assert not f.retail_trip(transaction,'JP')


def test_completed_period_is_kept_internally_and_cannot_be_posted(tmp_path):
    conn=sqlite3.connect(tmp_path/'cost.sqlite',isolation_level=None)
    try:
        pipe=Pipeline(conn)
        source=make_csv([domestic_row(merchant='OLD',amount=100,approval='1',date='2026-03-31'),
                         domestic_row(merchant='NEW',amount=200,approval='2',date='2026-04-01')])
        batch=pipe.receive(source,'synthetic.csv')['batch_id']
        original=conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions ORDER BY transaction_id').fetchall()
        result=pipe.classify_batch(batch,review_from='2026-04-01')
        assert result['counts']['preserved']==1
        assert len(pipe.get_batch(batch)['rows'])==2
        assert len(pipe.preview(batch)['rows'])==1
        pipe.classify_batch(batch)
        assert conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_state='preserved'").fetchone()[0]==1
        assert original==conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions ORDER BY transaction_id').fetchall()
        assert conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
    finally:
        conn.close()


def test_booking_rule_cannot_transfer_to_a_different_source():
    rule=normalize_rule({'conditions':{'merchant_normalized':'TRIP.COM'},
                         'optional':{'source_hash':'a'*64,'booking_period':{
                             'starts_on':'2026-04-09','ends_on':'2026-04-10','target_code':'0408_교토','source_sha256':'b'*64}},
                         'effects':{'item':'숙박비'}})
    transaction=dict(merchant='TRIP.COM',source_hash='a'*64)
    result=classify_transaction(transaction,rules=[rule],trip_resolver=flow().retail_trip)
    assert result['trip_id']=='japan'
    transaction['source_hash']='c'*64
    result=classify_transaction(transaction,rules=[rule],trip_resolver=flow().retail_trip)
    assert result['classification_state']=='needs_review' and not result['trip_id']


def test_owner_default_covers_new_local_merchants_but_not_ota_or_foreign_trip():
    rule=normalize_rule({'conditions':{'merchant_normalized':'*','transaction_direction':'purchase'},
                         'optional':{'travel_country':'local'},'effects':{'item':'현지경비'}})
    row=dict(merchant='SYNTHETIC LOCAL SHOP',transaction_direction='purchase',issuer='국민',card_kind='해외',
             approval_date='2026-04-09',raw_row={'c8':'JP'})
    result=classify_transaction(row,rules=[rule],trip_resolver=flow().retail_trip)
    assert result['item']=='현지경비' and result['trip_id']=='japan'
    row['merchant']='TRIP.COM'
    assert classify_transaction(row,rules=[rule],trip_resolver=flow().retail_trip)['classification_state']=='needs_review'
    row['merchant']='SYNTHETIC LOCAL SHOP';row['raw_row']['c8']='KR'
    assert not classify_transaction(row,rules=[rule],trip_resolver=flow().retail_trip)['trip_id']
    row['raw_row']['c8']='JP'
    specific=normalize_rule({'conditions':{'merchant_normalized':row['merchant']},'effects':{'item':'입장료'}})
    assert classify_transaction(row,rules=[specific,rule],trip_resolver=flow().retail_trip)['item']=='입장료'


def test_recovered_rule_ids_and_application_remain_stable(tmp_path):
    from tools import recover_history_rules as recovery
    conn=sqlite3.connect(tmp_path/'board.sqlite',isolation_level=None)
    try:
        pipe=Pipeline(conn)
        pipe.receive(make_csv([domestic_row(merchant='SYNTHETIC LOCAL SHOP JP',amount=100,approval='one')]),'synthetic.csv')
        report={'candidates':[],'booking_rules':[]}
        first=recovery.confirmed_drafts(report)
        second=recovery.confirmed_drafts(report)
        assert first==second and len(first)==1
        with patch.object(recovery,'OUTPUT',tmp_path):
            a=recovery.apply_rules(tmp_path/'board.sqlite',report,flow=flow())
            b=recovery.apply_rules(tmp_path/'board.sqlite',report,flow=flow())
        assert a['counts']==b['counts']
        assert conn.execute('SELECT COUNT(*) FROM cost_classification_rules').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
    finally:
        conn.close()


def test_country_code_formats_do_not_require_changing_the_source():
    row=dict(issuer='하나',card_kind='국내',merchant='LIONDOR                  AIDUWAKAMATSUJP',
             raw_row={'c11':'해외구매(신용)'})
    assert merchant_country(row)=='JP'
    assert row['merchant']=='LIONDOR                  AIDUWAKAMATSUJP'
    row['merchant']='BOSSFOODSMARKET        TAKAYAMA      JPN'
    assert merchant_country(row)=='JP'
    row['merchant']='SYNTHETIC SHOP';row.update(issuer='국민',card_kind='해외',raw_row={'c8':'JPN'})
    assert merchant_country(row)=='JP'


def test_explicit_myoko_and_mongolia_trips_match_only_their_source_country():
    f=flow()
    f.board.list_trips=lambda:[dict(tab_id='myoko',destination='묘코',display_key='0620_묘코',
                                    starts_on='2026-06-20',ends_on='2026-06-24'),
                              dict(tab_id='mongolia',destination='몽골',display_key='0712_몽골',
                                    starts_on='2026-07-12',ends_on='2026-07-18')]
    f.trip_valid=lambda identity:identity in ('myoko','mongolia')
    row=dict(issuer='하나',card_kind='국내',merchant='SYNTHETIC LOCAL SHOP CITY MN',
             approval_date='2026-07-15',raw_row={'c11':'해외구매(신용)'})
    assert merchant_country(row)=='MN'
    assert f.retail_trip(row,'MN')=='mongolia'
    assert not f.retail_trip(row,'JP')
    row.update(merchant='SYNTHETIC LOCAL SHOP CITY JP',approval_date='2026-06-21')
    assert f.retail_trip(row,'JP')=='myoko'
    assert not f.retail_trip(row,'MN')


def test_owner_answers_keep_office_shared_and_travel_product_source_bound():
    from tools.recover_history_rules import owner_answer_drafts
    office=dict(merchant='(주)아성다이소',card_kind='국내',transaction_direction='purchase',
                approval_date='2026-05-01',amount_krw=1000,source_hash='a'*64)
    adventure=dict(merchant='인터넷상거래_1-주식회사 어드벤처코리아',card_kind='국내',
                   transaction_direction='cancellation',approval_date='2026-05-27',
                   amount_krw=-325866,source_hash='b'*64)
    rules=[normalize_rule(r) for r in owner_answer_drafts([office,adventure])]
    result=classify_transaction(office,rules=rules,trip_resolver=flow().retail_trip)
    assert result['item']=='사무용품비' and result['display_tab_id']=='unclassified' and not result['trip_id']
    result=classify_transaction(adventure,rules=rules)
    assert result['item']=='여행상품비' and not result['trip_id']
    assert adventure['amount_krw']==-325866
    assert classify_transaction(dict(adventure,source_hash='c'*64),rules=rules)['classification_state']=='needs_review'


def test_owner_answer_rules_apply_twice_without_changing_sources_or_posting(tmp_path):
    from tools import recover_history_rules as recovery
    conn=sqlite3.connect(tmp_path/'board.sqlite',isolation_level=None)
    try:
        pipe=Pipeline(conn)
        batch=pipe.receive(make_csv([domestic_row(merchant='(주)아성다이소',amount=1000,approval='office',date='2026-05-01'),
                                    domestic_row(merchant='인터넷상거래_1-주식회사 어드벤처코리아',
                                                 amount=-325866,approval='refund',date='2026-05-27',kind='취소',cancel='Y')]),'synthetic.csv')
        rows=pipe.get_batch(batch['batch_id'])['rows']
        report={'candidates':[],'booking_rules':[],'user_rules':recovery.owner_answer_drafts(rows)}
        original=conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions ORDER BY 1').fetchall()
        with patch.object(recovery,'OUTPUT',tmp_path):
            first=recovery.apply_rules(tmp_path/'board.sqlite',report,flow=flow())
            second=recovery.apply_rules(tmp_path/'board.sqlite',report,flow=flow())
        assert first['counts']==second['counts']=={'classified':2}
        assert first['new_ledger_entries']==second['new_ledger_entries']==0
        assert original==conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions ORDER BY 1').fetchall()
    finally:
        conn.close()


def test_online_supplier_cannot_be_assigned_by_payment_date_even_with_an_old_local_rule():
    f=flow()
    f.board.list_trips=lambda:[dict(tab_id='busan',destination='부산',display_key='0501_부산',
                                    starts_on='2026-05-01',ends_on='2026-05-05')]
    f.trip_valid=lambda identity:identity=='busan'
    row=dict(merchant='인터넷상거래_1-주식회사 어드벤처코리아',issuer='국민',card_kind='국내',
             approval_date='2026-05-04',raw_row={},source_hash='a'*64)
    local=normalize_rule({'conditions':{'merchant_normalized':row['merchant']},
                          'optional':{'travel_country':'local'},'effects':{'item':'현지경비'}})
    default=normalize_rule({'conditions':{'merchant_normalized':'*'},
                            'optional':{'travel_country':'local'},'effects':{'item':'현지경비'}})
    result=classify_transaction(row,rules=[local,default],trip_resolver=f.retail_trip)
    assert result['classification_state']=='needs_review' and not result['trip_id']
    purpose=normalize_rule({'conditions':{'merchant_normalized':row['merchant']},
                            'optional':{'source_hash':row['source_hash']},'effects':{'item':'여행상품비'}})
    result=classify_transaction(row,rules=[local,default,purpose],trip_resolver=f.retail_trip)
    assert result['item']=='여행상품비' and not result['trip_id']


def inference_rule(target='japan', merchant='TRIP.COM'):
    return normalize_rule({'conditions':{'merchant_normalized':merchant},
                           'optional':{'source_hash':'a'*64,'inferred_assignment':{
                               'trip_id':target,'basis':'과거 같은 카드 원행과 예약 지역을 참고',
                               'confidence':'중간'}},
                           'effects':{'item':'숙박비'}})


def test_authorized_inference_is_source_bound_and_not_a_human_confirmation():
    row=dict(merchant='TRIP.COM',source_hash='a'*64,approval_date='2026-04-01',amount_krw=50000)
    original=dict(row)
    result=classify_transaction(row,rules=[inference_rule()],trip_resolver=flow().retail_trip)
    assert result['trip_id']=='japan' and result['classification_source']=='inference'
    assert result['classification_state']=='classified' and '추론 배정' in result['classification_basis']
    assert row==original
    row['source_hash']='b'*64
    assert not classify_transaction(row,rules=[inference_rule()],trip_resolver=flow().retail_trip)['trip_id']


def test_inference_cannot_overwrite_a_persons_answer_or_a_verified_booking_trip():
    row=dict(merchant='TRIP.COM',source_hash='a'*64)
    prior={'item':'항공료','display_tab_id':'future','trip_id':'future'}
    result=classify_transaction(row,rules=[inference_rule()],prior_decision=prior,trip_resolver=flow().retail_trip)
    assert result['trip_id']=='future' and result['item']=='항공료'
    verified=normalize_rule({'conditions':{'merchant_normalized':'TRIP.COM'},
                             'optional':{'source_hash':'a'*64,'booking_period':{
                                 'starts_on':'2026-12-01','ends_on':'2026-12-02',
                                 'target_code':'1201_도쿄','source_sha256':'c'*64}},
                             'effects':{'item':'숙박비'}})
    result=classify_transaction(row,rules=[verified,inference_rule()],trip_resolver=flow().retail_trip)
    assert result['trip_id']=='future' and result['classification_source']=='rule'


def test_deleted_or_stale_trip_blocks_the_inferred_assignment():
    row=dict(merchant='TRIP.COM',source_hash='a'*64)
    result=classify_transaction(row,rules=[inference_rule('missing')],trip_resolver=flow().retail_trip)
    assert result['classification_state']=='needs_review' and not result['trip_id']


def test_source_country_wins_over_the_general_card_kind_and_compact_city_is_read():
    assert merchant_country(dict(issuer='국민',card_kind='국내',raw_row={'c8':'CZ'}))=='CZ'
    assert merchant_country(dict(issuer='기업',card_kind='해외',merchant='SYNTHETIC  AIDUWAKAMATSUJP'))=='JP'


def test_inference_cannot_hide_conflicting_confirmed_rules():
    first=normalize_rule({'conditions':{'merchant_normalized':'TRIP.COM'},'effects':{'item':'항공료'}})
    second=normalize_rule({'conditions':{'merchant_normalized':'TRIP.COM'},'effects':{'item':'숙박비'}})
    row=dict(merchant='TRIP.COM',source_hash='a'*64)
    result=classify_transaction(row,rules=[first,second,inference_rule()],trip_resolver=flow().retail_trip)
    assert result['classification_source']=='rule_conflict' and result['classification_state']=='needs_review'


def test_inference_rule_requires_a_source_and_cannot_pretend_to_be_a_verified_period():
    import pytest
    from app import StoreError
    draft=inference_rule()
    draft['optional'].pop('source_hash')
    with pytest.raises(StoreError):normalize_rule(draft)


def test_common_office_inference_never_becomes_a_trip_and_domestic_food_stays_domestic():
    from tools.recover_history_rules import inferred_drafts
    def row(merchant,kind='국내',history=None):
        return dict(decided=False,classification_state='needs_review',trip_id='',parse_error='',
                    conflict_reason='',duplicate_of='',approval_date='2026-04-09',posting_date='',
                    merchant_normalized=merchant.lower(),merchant=merchant,issuer='국민',card_tail='1234',
                    amount_krw=10000,raw_row_json='{}',item='',classification_source='',description='',
                    source_hash='a'*64,card_kind=kind,transaction_direction='purchase',_history=history or [])
    office=row('ANTHROPIC* CLAUDE SUB','해외')
    food=row('GS25',history=[{'allocation_target':'0408_교토','account':'식비','classification_source':'manual'}])
    proposals=inferred_drafts([office,food],flow(),[])
    assert proposals[0]['effects']['item']=='소프트웨어구독료'
    assert not proposals[0]['optional']['inferred_assignment']['trip_id']
    assert not proposals[1]['optional']['inferred_assignment']['trip_id']


def test_known_service_date_prevents_assignment_to_the_nearest_payment_date_trip():
    from tools.recover_history_rules import inferred_drafts
    row=dict(decided=False,classification_state='needs_review',trip_id='',parse_error='',
             conflict_reason='',duplicate_of='',approval_date='2026-04-01',posting_date='',
             merchant_normalized='trip.com',merchant='TRIP.COM',issuer='국민',card_tail='1234',
             amount_krw=50000,raw_row_json='{}',item='숙박비',classification_source='',description='',
             source_hash='a'*64,card_kind='국내',transaction_direction='purchase',_history=[])
    match={'source_hash':'a'*64,'item':'숙박비','period':{'starts_on':'2026-08-27','ends_on':'2026-08-29'}}
    proposals=inferred_drafts([row],flow(),[match])
    assert not proposals[0]['optional']['inferred_assignment']['trip_id']
    assert '2026-08-27' in proposals[0]['optional']['inferred_assignment']['basis']


def test_inference_recovery_does_not_create_a_second_competing_proposal():
    from tools.recover_history_rules import inferred_drafts
    row=dict(decided=False,classification_state='classified',classification_source='inference',
             trip_id='',parse_error='',conflict_reason='',duplicate_of='',approval_date='2026-04-09',posting_date='')
    assert inferred_drafts([row],flow(),[])==[]


def test_georgia_and_kazakhstan_are_an_explicit_europe_exception():
    from tools.recover_history_rules import inferred_drafts
    f=flow()
    f.board.list_trips=lambda:[dict(tab_id='europe',destination='유럽',display_key='5월_유럽',
                                    starts_on='2026-05-20',ends_on='2026-06-10')]
    f.trip_valid=lambda identity:identity=='europe'
    for country in ('GE','KZ'):
        row=dict(decided=False,classification_state='needs_review',classification_source='travel_location_hold',
                 trip_id='',parse_error='',conflict_reason='',duplicate_of='',approval_date='2026-05-09',posting_date='',
                 merchant_normalized='synthetic local shop',merchant='SYNTHETIC LOCAL SHOP',issuer='국민',card_tail='1234',
                 amount_krw=5000,raw_row_json='{"c8":"'+country+'"}',item='현지경비',description='',
                 source_hash='a'*64,card_kind='해외',transaction_direction='purchase',_history=[])
        proposals=inferred_drafts([row],f,[])
        assert proposals[0]['origin']=='owner-country-exception-20261003'
        assert proposals[0]['optional']['inferred_assignment']['trip_id']=='europe'
        row['raw_row']={'c8':country}
        result=classify_transaction(row,rules=[normalize_rule(proposals[0])],trip_resolver=f.retail_trip)
        assert result['trip_id']=='europe' and result['classification_source']=='user_exception'
        conn=sqlite3.connect(':memory:',isolation_level=None)
        try:
            pipe=Pipeline(conn)
            pipe.save_rule(proposals[0])
            loaded=classify_transaction(row,rules=pipe.list_rules(),trip_resolver=f.retail_trip)
            assert loaded['classification_source']=='user_exception'
        finally:
            conn.close()


def test_multi_word_city_and_full_country_suffixes_keep_the_original_card_country():
    row=dict(issuer='하나',card_kind='국내',raw_row={'c11':'해외구매'},
             merchant='SYNTHETIC SHOP          MONT SAINT AIFR')
    assert merchant_country(row)=='FR'
    row['merchant']='SYNTHETIC AIRLINE       BARCELONA    ES'
    assert merchant_country(row)=='ES'
    row['merchant']='SYNTHETIC HOTEL         AMSTERDAM    NL'
    assert merchant_country(row)=='NL'
    row['merchant']='AGODA.COM              Internet      SGP'
    assert merchant_country(row)=='SG'
    row.update(merchant='SYNTHETIC LOCAL SHOP',raw_row={})
    assert merchant_country(row)=='KR'


def test_korean_booking_gateway_is_not_a_domestic_onsite_purchase():
    from app.rules import is_booking_or_online
    from tools.recover_history_rules import inferred_drafts
    row=dict(decided=False,classification_state='needs_review',trip_id='',parse_error='',
             conflict_reason='',duplicate_of='',approval_date='2026-04-08',posting_date='',
             merchant_normalized='아고다_나이스',merchant='아고다_나이스',issuer='국민',card_tail='1234',
             amount_krw=50000,raw_row_json='{}',item='숙박비',classification_source='',description='',
             source_hash='a'*64,card_kind='국내',transaction_direction='purchase',_history=[])
    assert is_booking_or_online(row)
    proposed=inferred_drafts([row],flow(),[])[0]
    assert proposed['optional']['inferred_assignment']['trip_id']=='japan'
    assert '국내 현장 거래' not in proposed['optional']['inferred_assignment']['basis']


def test_refinement_reuses_one_rule_and_rejects_a_concurrent_rule_edit(tmp_path):
    import copy, pytest
    from tools import recover_history_rules as recovery
    conn=sqlite3.connect(tmp_path/'board.sqlite',isolation_level=None)
    try:
        pipe=Pipeline(conn)
        batch=pipe.receive(make_csv([domestic_row(merchant='아고다_나이스',amount=50000,
                           approval='booking',date='2026-04-08')]),'synthetic.csv')
        row=pipe.get_batch(batch['batch_id'])['rows'][0]
        draft=copy.deepcopy(inference_rule(''))
        draft.update(rule_id='source-inference',origin='owner-authorized-inference-20261003')
        draft['conditions']={'merchant_normalized':row['merchant_normalized']}
        draft['optional']['source_hash']=row['source_hash']
        draft['optional']['inferred_assignment'].update(confidence='낮음',basis='예약 상세 확인 전')
        pipe.save_rule(draft)
        pipe.classify_batch(batch['batch_id'],trip_resolver=flow().retail_trip)
        f=flow();f.pipeline=pipe
        rows=recovery.current_rows(tmp_path/'board.sqlite')
        updates=recovery.refined_drafts(rows,f,[])
        assert len(updates)==1 and updates[0]['draft']['rule_id']=='source-inference'
        report={'candidates':[],'booking_rules':[],'refined_rules':updates}
        with patch.object(recovery,'OUTPUT',tmp_path):
            first=recovery.apply_rules(tmp_path/'board.sqlite',report,flow=f)
            second=recovery.apply_rules(tmp_path/'board.sqlite',report,flow=f)
        assert first['counts']==second['counts'] and pipe.get_batch(batch['batch_id'])['rows'][0]['trip_id']=='japan'
        assert conn.execute("SELECT COUNT(*) FROM cost_classification_rules WHERE origin='owner-authorized-inference-20261003'").fetchone()[0]==1
        assert recovery.refined_drafts(recovery.current_rows(tmp_path/'board.sqlite'),f,[])==[]
        manual=copy.deepcopy(updates[0]['draft']);manual['effects']['item']='입장료';pipe.save_rule(manual)
        with patch.object(recovery,'OUTPUT',tmp_path),pytest.raises(RuntimeError,match='INFERENCE_RULE_CHANGED'):
            recovery.apply_rules(tmp_path/'board.sqlite',report,flow=f)
        assert conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
    finally:conn.close()


def test_when_two_inferences_agree_on_the_trip_the_higher_confidence_gives_the_basis():
    def inference(confidence, basis):
        return normalize_rule({'conditions':{'merchant_normalized':'TRIP.COM'},
                               'optional':{'source_hash':'a'*64,'inferred_assignment':{
                                   'trip_id':'japan','basis':basis,'confidence':confidence}},
                               'effects':{'item':'숙박비'}})
    row=dict(merchant='TRIP.COM',source_hash='a'*64,approval_date='2026-04-01',amount_krw=50000)
    result=classify_transaction(row,rules=[inference('낮음','낮은 근거'),inference('높음','높은 근거')],
                                trip_resolver=flow().retail_trip)
    assert result['trip_id']=='japan' and '추론 배정 · 높음 · 높은 근거' in result['classification_basis']


def test_an_owner_inference_is_not_applied_when_the_payment_is_more_than_30_days_before_the_trip():
    from app.classify import OWNER_AUTHORIZED_INFERENCE_ORIGIN
    rule=inference_rule(target='future')
    rule['origin']=OWNER_AUTHORIZED_INFERENCE_ORIGIN
    early=dict(merchant='TRIP.COM',source_hash='a'*64,approval_date='2026-09-01',amount_krw=50000)
    result=classify_transaction(early,rules=[rule],trip_resolver=flow().retail_trip)
    assert result['classification_state']=='needs_review' and not result['trip_id']
    near=dict(early,approval_date='2026-11-25')
    assert classify_transaction(near,rules=[rule],trip_resolver=flow().retail_trip)['trip_id']=='future'
