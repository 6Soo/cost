from copy import deepcopy

import pytest

from app.ota_payments import match_ota_payment_events, pair_check, search_card_candidates
from app.ota_payment_relations import catalog_links
from app.ota_core_projection import card_matches, project_card_ota_statuses
from app.ota_queue_projection import classify_event
from tests.card_pipeline.test_ota_payments import card, event


def undated(identity='booking', **changes):
    return event(identity, paid_on=None, **changes)


def test_missing_date_matches_merchant_amount_and_tail_even_with_manual_travel_hold():
    source = undated()
    row = card(merchant='AGODA_NICE-Agoda', merchant_normalized='agoda_nice-agoda',
               ota_review_held=True, ota_inference_eligible=False)
    before = deepcopy((source, row))
    result = match_ota_payment_events([source], [row])[0]
    assert pair_check(source, row) is None
    assert result['status'] == 'MATCHED_AUTO' and result['transaction_id'] == 'card-a'
    assert result['payment_relation']['payment_date_verified'] is False
    assert result['paid_on'] is None
    assert search_card_candidates(source, [row])['candidates'][0]['resolution_allowed']
    assert before == (source, row)


@pytest.mark.parametrize('key', ['merchant', 'merchant_extended', 'expanded_merchant_name', '가맹점명(확장)'])
def test_expanded_descriptors_are_evidence(key):
    row = card(**{key:'AGODA_NICE-Agoda_온라인'})
    assert match_ota_payment_events([undated()], [row])[0]['transaction_id'] == 'card-a'


@pytest.mark.parametrize('provider,merchant', [('trip','TRIP.COM'),('trip','트립닷컴_이니시스'),
                                              ('agoda','AGODA_NICE-Agoda'),('booking','BOOKING.COM'),('klook','KLOOK')])
def test_undated_rule_uses_registered_provider_name_expansions(provider,merchant):
    result=match_ota_payment_events([undated(provider=provider)], [card(merchant=merchant,merchant_normalized=merchant.lower())])[0]
    assert result['status']=='MATCHED_AUTO' and result['transaction_id']=='card-a'


@pytest.mark.parametrize('changes', [
    {'card_tail':'9876'}, {'amount_krw':30001}, {'duplicate_of':'original'},
    {'parse_error':'bad'}, {'conflict_reason':'conflict'},
    {'transaction_direction':'refund'}, {'merchant':'트립닷컴(구)_NICE'},
    {'foreign_currency':'JPY','foreign_amount':'30000','amount_krw':None},
])
def test_missing_date_never_overrides_mismatch_or_financial_protection(changes):
    row = card(merchant='AGODA_NICE-Agoda', merchant_normalized='agoda_nice-agoda')
    row.update(changes)
    result = match_ota_payment_events([undated()], [row])[0]
    assert not result.get('payment_relation') and not result.get('transaction_id')


@pytest.mark.parametrize('m,n', [(1,1),(2,1),(1,2),(2,2),(2,3),(3,2)])
@pytest.mark.parametrize('missing_date', [False,True])
def test_all_mn_edges_survive_without_merging_events_or_double_counting_cards(m,n,missing_date):
    sources = [event('ota-'+str(i),booking_ref='B-'+str(i),paid_on=None if missing_date else '2026-08-01')
               for i in range(m)]
    rows = [card('card-'+str(i),merchant='Agoda',merchant_normalized='agoda',approval_number=str(i))
            for i in range(n)]
    original = deepcopy((sources,rows))
    results = match_ota_payment_events(sources, rows)
    repeated = match_ota_payment_events(list(reversed(sources)),list(reversed(rows)))
    assert len(results) == m
    assert {r['ota_event_id']:r['payment_relation'] for r in results} == {
        r['ota_event_id']:r['payment_relation'] for r in repeated}
    for result in results:
        relation = result['payment_relation']
        assert relation['event_count'] == m and relation['card_count'] == n
        assert relation['transaction_ids'] == sorted(r['transaction_id'] for r in rows)
        assert relation['source_total'] == str(m*30000)
        assert relation['card_total'] == str(n*30000)
        assert relation['balance'] == ('BALANCED' if m == n else 'AMOUNT_DIFFERENCE')
    assert original == (sources,rows)


def test_existing_manual_card_ownership_is_not_reused_by_relations():
    results = match_ota_payment_events([undated()], [card(merchant='Agoda')],
                                      existing_links={'manual-other':'card-a'})
    assert not results[0].get('payment_relation') and not results[0].get('transaction_id')


def test_two_absent_dates_are_not_equal_date_evidence_without_a_matching_merchant():
    result=match_ota_payment_events([undated()], [card(approval_date=None)])[0]
    assert not result.get('payment_relation') and not result.get('transaction_id')


def test_undated_rule_does_not_turn_an_approved_flight_discount_into_exact_amount():
    source=undated(provider='trip',item='항공',amount=100000,amount_krw=100000)
    row=card(merchant='TRIP.COM',merchant_normalized='trip.com',amount_krw=96000)
    result=match_ota_payment_events([source],[row])[0]
    assert not result.get('transaction_id') and not result.get('payment_relation')


def test_catalog_retains_cancelled_charge_and_financial_projection_never_copies_mn_booking():
    sources = [event('one',booking_ref='ONE',reservation_status='cancelled'),
               event('two',booking_ref='TWO')]
    rows = [card()]
    results = match_ota_payment_events(sources, rows)
    data = dict(events=sources,transactions=rows,results=results,links={})
    links = catalog_links(data)
    assert set(links) == {('agoda','ONE'),('agoda','TWO')}
    assert all(v[0]['transaction_id'] == 'card-a' for v in links.values())
    assert card_matches([],data) == []  # A relationship is not two financial writes.
    states,_,_ = project_card_ota_statuses({'results':results,'data':data})
    assert states == {'card-a':'GROUP_LINKED'}


def test_public_relation_allowlist_and_catalog_count_do_not_hide_cancelled_cards():
    from webapp.ota_payment_review import public_snapshot
    from webapp.ota_catalog import _linked_card_count, _payment_links_html
    source=event()
    result=match_ota_payment_events([source],[card()])[0]
    relation=result['payment_relation']
    relation['private_raw']='not public'
    public=public_snapshot({'events':[dict(source,**result)]})
    assert 'private_raw' not in public['events'][0]['payment_relation']
    link=dict(transaction_id='card-a',merchant='Agoda',day='2026-08-01',amount_krw=30000,
              event_count=2,card_count=1,balance='AMOUNT_DIFFERENCE',payment_date_verified=True)
    assert _linked_card_count({'card_matches':[],'payment_links':[link]}) == 1
    assert _linked_card_count({'card_matches':[link],'payment_links':[link]}) == 1
    html=_payment_links_html({'payment_links':[link]})
    assert '30,000원' in html and 'M:N 2:1' in html and '그룹 금액 차이' in html


def test_queue_distinguishes_linked_group_balance_from_absent_payment():
    sources=[event('one',booking_ref='ONE'),event('two',booking_ref='TWO')]
    results=match_ota_payment_events(sources,[card()])
    freshness=dict(status='ready',stale=False,refreshing=False,fresh=True,enabled=True,generation=1)
    verdict=classify_event(results[0],freshness)
    assert verdict['queue'] == 'needs_action'
    assert 'LINKED_GROUP_AMOUNT_DIFFERENCE' in verdict['reason_codes']


def test_same_booking_observations_are_not_counted_as_two_distinct_payments():
    sources=[event('mail'),event('portal')]
    result=match_ota_payment_events(sources,[card()])[0]
    relation=result['payment_relation']
    assert relation['event_count']==2 and relation['booking_count']==1
    assert relation['card_total']=='30000' and relation['source_total'] is None
    assert relation['source_total_status']=='OBSERVATIONS_NOT_DISTINCT_PAYMENTS'
    assert relation['balance']=='UNKNOWN' and relation['status']=='LINKED'


@pytest.mark.parametrize('payment_ids,total', [(['PAY-1','PAY-2'],'60000'),(['PAY-1','PAY-1'],'30000')])
def test_explicit_payment_identity_controls_source_total_without_merging_events(payment_ids,total):
    sources=[event(str(i),payment_event_id=payment_id) for i,payment_id in enumerate(payment_ids)]
    results=match_ota_payment_events(sources,[card()])
    assert len(results)==2
    assert all(r['payment_relation']['source_total']==total for r in results)


@pytest.mark.parametrize('scenario,reason,queue', [
    ('difference', 'LINKED_GROUP_AMOUNT_DIFFERENCE', 'needs_action'),
    ('unverified', 'LINKED_GROUP_AMOUNT_UNVERIFIED', 'needs_action'),
    ('balanced', 'MATCHING_RELATION_RESOLVED', 'completed'),
    ('observations', 'MATCHING_RELATION_RESOLVED', 'completed'),
])
def test_mn_relations_publish_through_canonical_worker_paging(scenario, reason, queue):
    from app.ota_queue_paging import build_queue_index, list_queue_page
    from webapp.ota_payment_review import (
        _canonical_queue_rows, _canonical_queue_page_rows, _canonical_queue_group_rows,
    )
    sources = [event('one', booking_ref='ONE'),
               event('two', booking_ref='ONE' if scenario == 'observations' else 'TWO')]
    cards = [card('a'), card('b')] if scenario == 'balanced' else [card()]
    results = match_ota_payment_events(sources, cards)
    if scenario == 'unverified':
        for result in results:
            result['payment_relation'].update(balance='UNKNOWN', source_total=None,
                                               source_total_status='AMOUNT_UNVERIFIED')
    canonical = _canonical_queue_rows(sources, results, {})
    before = deepcopy(canonical)
    for rows in (_canonical_queue_page_rows(canonical), _canonical_queue_group_rows(canonical)):
        index = build_queue_index(rows, generation=7, snapshot_nonce='mn-runtime', signing_key=b'x'*32)
        page = list_queue_page(index, queue=queue, limit=20)
        assert page['total_count'] == len(rows)
        assert all(reason in row['reason_codes'] for row in page['items'])
        assert all(row['event']['status'] in {result['status'] for result in results}
                   for row in page['items'])
    assert canonical == before
