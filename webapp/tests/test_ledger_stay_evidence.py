"""Synthetic OTA-to-ledger display coverage; no operating data is used."""
from copy import deepcopy
from types import SimpleNamespace
from threading import RLock
import sqlite3

import pytest

from webapp import ledger_design as design, ledger_stay_evidence as stays
from webapp.read_scope import scoped


@pytest.fixture
def context(monkeypatch):
    data = {
        'events': [dict(ota_event_id='e1', provider='agoda', booking_ref='B1',
                        item='숙박비', reservation_status='completed', source_digest='digest',
                        service_period={'starts_on': '2026-07-05', 'ends_on': '2026-07-07'})],
        'transactions': [dict(transaction_id='t1', source_hash='s1',
                              transaction_direction='purchase', amount_krw=1000)],
        'results': [dict(ota_event_id='e1', transaction_id='t1', status='MATCHED_AUTO')],
    }
    state = {'fresh': True}
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT, field TEXT)')
    calls = []
    def display_context():
        calls.append(1)
        return {'data': data}, state
    store = SimpleNamespace(conn=conn, _lock=RLock(),
                            _ota_snapshot_service=SimpleNamespace(display_context=display_context))
    monkeypatch.setattr(design.board, '_active_store', lambda: store)
    from webapp import ota_payment_review
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    yield store, data, state, calls
    conn.close()


def card(**values):
    return dict(row_id='card-t1', source_event_id='t1', item='숙박비', **values)


def test_existing_card_reads_linked_stay_without_writes_or_card_date_guess(context):
    store, data, _, calls = context
    before = deepcopy(data)
    row = card(occurred_on='2026-06-22', service_period='')
    changes = store.conn.total_changes
    @scoped
    def render():
        return design._stay_text(row), design._stay_text(row)
    assert render() == ('7월 5일(일) ~ 7월 7일(화) · 2박',) * 2
    assert calls == [1]
    assert store.conn.total_changes == changes
    assert data == before and row['service_period'] == ''


@pytest.mark.parametrize('override', ['2026-08-01~2026-08-02', 'invalid'])
def test_stored_dates_and_invalid_explicit_values_are_preserved(context, override):
    assert stays.period_for(card(service_period=override), stays.stay_index(context[0])) == override


def test_manual_empty_period_and_different_reservation_are_preserved(context):
    store = context[0]
    assert stays.period_for(card(reservation_no='OTHER'), stays.stay_index(store)) == ''
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('flag', ['evidence_missing', 'evidence_changed', 'service_period_conflict'])
def test_changed_missing_and_conflicting_evidence_is_not_used(context, flag):
    store, data, _, _ = context
    data['events'][0][flag] = True
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('status', ['cancelled', 'refunded', 'refund_pending', 'evidence_pending'])
def test_cancelled_and_pending_reservations_are_not_used(context, status):
    store, data, _, _ = context
    data['events'][0]['reservation_status'] = status
    assert stays.stay_index(store) == {}


def test_stale_or_unstarted_service_is_not_used(context):
    store, _, state, _ = context
    state['fresh'] = False
    assert stays.stay_index(store) == {}
    del store._ota_snapshot_service
    assert stays.stay_index(store) == {}


def test_group_order_is_not_individual_booking_evidence(context):
    store, data, _, _ = context
    data['results'][0].update(allocation_basis='auto_stable_order', individual_payment_evidence=False)
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('flag', ['duplicate_of', 'parse_error', 'conflict_reason'])
def test_financial_source_protections_remain(context, flag):
    store, data, _, _ = context
    data['transactions'][0][flag] = 'blocked'
    assert stays.stay_index(store) == {}


def test_multiple_claims_and_refund_card_are_not_used(context):
    store, data, _, _ = context
    data['transactions'][0]['transaction_direction'] = 'refund'
    assert stays.stay_index(store) == {}
    data['transactions'][0]['transaction_direction'] = 'purchase'
    data['results'].append(dict(data['results'][0], ota_event_id='e2'))
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('period', [None, {}, {'starts_on': '2026-07-05'},
                                    {'starts_on': '2026-07-05', 'ends_on': None}])
def test_incomplete_stay_is_not_guessed_or_crashed(context, period):
    store, data, _, _ = context
    data['events'][0]['service_period'] = period
    assert stays.stay_index(store) == {}


def linked_group(data):
    data['events'].append(dict(data['events'][0], ota_event_id='e2', booking_ref='B2'))
    relation = dict(status='LINKED', event_ids=['e1', 'e2'], transaction_ids=['t1'],
                    individual_payment_verified=False)
    data['results'] = [dict(ota_event_id=eid, status='MATCHED_GROUP', payment_relation=relation)
                       for eid in ['e1', 'e2']]


def test_linked_many_to_many_shared_period_is_display_only(context):
    store, data, _, _ = context
    linked_group(data)
    before = deepcopy(data)
    changes = store.conn.total_changes
    metadata = stays.stay_index(store)['t1']
    assert metadata['booking_ref'] == ''
    assert metadata['booking_refs'] == ['B1', 'B2']
    assert metadata['ota_evidence']['payment_verified'] is False
    assert stays.period_for(card(reservation_no='B2'), {'t1': metadata}) == '2026-07-05~2026-07-07'
    assert stays.period_for(card(reservation_no='OTHER'), {'t1': metadata}) == ''
    assert data == before and store.conn.total_changes == changes
    from app.ota_core_projection import card_matches
    assert card_matches([], data) == []


def test_linked_missing_event_category_uses_period_without_reclassifying(context):
    store, data, _, _ = context
    del data['events'][0]['item']
    assert stays.stay_index(store)['t1']['service_period'] == '2026-07-05~2026-07-07'
    assert 'item' not in data['events'][0]


@pytest.mark.parametrize('change', ['different_period', 'missing_event', 'cancelled', 'conflict',
                                  'missing_digest', 'stale_link', 'changed_digest', 'unlinked',
                                  'manual', 'refund', 'duplicate', 'ordered', 'invalid_period'])
def test_group_period_requires_every_observation_to_be_safe(context, change):
    store, data, _, _ = context
    linked_group(data)
    event = data['events'][1]
    if change == 'different_period':
        event['service_period'] = {'starts_on':'2026-07-06', 'ends_on':'2026-07-07'}
    elif change == 'missing_event':
        data['events'].pop()
    elif change == 'cancelled':
        event['reservation_status'] = 'cancelled'
    elif change == 'conflict':
        event['service_period_conflict'] = True
    elif change == 'missing_digest':
        event['source_digest'] = ''
    elif change == 'stale_link':
        data['links'] = {'e2': {'status':'STALE'}}
    elif change == 'changed_digest':
        data['links'] = {'e2': {'source_digest':'other'}}
    elif change == 'unlinked':
        data['results'][0]['payment_relation']['status'] = 'UNLINKED'
    elif change == 'manual':
        store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    elif change == 'refund':
        data['transactions'][0]['transaction_direction'] = 'refund'
    elif change == 'duplicate':
        data['transactions'][0]['duplicate_of'] = 'other'
    elif change == 'ordered':
        data['results'][0].update(allocation_basis='auto_stable_order', individual_payment_evidence=False)
    elif change == 'invalid_period':
        event['service_period'] = {'starts_on':'2026-07-09', 'ends_on':'2026-07-07'}
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('where', ['events', 'results'])
def test_alternate_period_conflict_is_protected(context, where):
    store, data, _, _ = context
    data[where][0]['period_conflict'] = True
    assert stays.stay_index(store) == {}


def toyoko_candidates(data):
    event = data['events'][0]
    event.update(provider='toyoko', event_type='reservation', source_trust='sender_domain',
                 evidence_status='reservation_only', reservation_status='observed')
    data['transactions'][0].update(merchant='토요코인 합성지점')
    data['results'] = [dict(ota_event_id='e1', status='RESERVATION_ONLY',
        candidate_search={'status': 'CANDIDATES_FOUND', 'candidates': [
            dict(transaction_id='t1', branch_status='MATCH', stay_date_status='MATCH',
                 amount_status='MISMATCH', basis='HOTEL_BRANCH_AND_STAY_ONLY')]})]


def test_many_rooms_and_cards_share_dates_without_claiming_payment_or_writing(context):
    store, data, _, calls = context
    toyoko_candidates(data)
    data['transactions'].append(dict(data['transactions'][0], transaction_id='t2', source_hash='s2'))
    data['results'][0]['candidate_search']['candidates'].append(dict(
        data['results'][0]['candidate_search']['candidates'][0], transaction_id='t2'))
    data['events'].append(dict(data['events'][0], ota_event_id='e2', booking_ref='B2', reservation_group_only=True))
    data['results'].append(dict(data['results'][0], ota_event_id='e2'))
    before = deepcopy(data)
    changes = store.conn.total_changes
    @scoped
    def render():
        return design._stay_text(card()), design._stay_text(dict(row_id='card-t2', item='숙박비'))
    assert render() == ('7월 5일(일) ~ 7월 7일(화) · 2박 · 예약 근거 추론',) * 2
    assert calls == [1] and store.conn.total_changes == changes and data == before
    inferred = stays.stay_index(store)['t1']
    assert inferred['booking_ref'] == '' and inferred['ota_evidence']['payment_verified'] is False
    from app.ota_core_projection import card_matches
    assert card_matches([], data) == []


def test_different_candidate_periods_do_not_pick_a_room(context):
    store, data, _, _ = context
    toyoko_candidates(data)
    data['events'].append(dict(data['events'][0], ota_event_id='e2',
        service_period={'starts_on':'2026-07-04', 'ends_on':'2026-07-07'}))
    data['results'].append(dict(data['results'][0], ota_event_id='e2'))
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('field,value', [
    ('source_trust', 'subject_only_unverified'), ('reservation_status','cancelled'),
    ('reservation_status','refunded'), ('reservation_status','refund_pending'),
    ('evidence_status','evidence_conflict'), ('period_conflict',True),
    ('service_period_conflict',True), ('evidence_changed',True), ('evidence_missing',True),
    ('source_digest','')])
def test_toyoko_unsafe_reservation_period_is_not_displayed(context, field, value):
    store, data, _, _ = context
    toyoko_candidates(data)
    data['events'][0][field] = value
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('field,value', [
    ('transaction_direction','refund'), ('duplicate_of','other'), ('parse_error','error'),
    ('conflict_reason','conflict'), ('ota_review_held', True),
    ('reservation_refund_blocked', True), ('refund_status','refund_requested')])
def test_toyoko_financial_holds_are_preserved(context, field, value):
    store, data, _, _ = context
    toyoko_candidates(data)
    data['transactions'][0][field] = value
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('field', ['branch_status','stay_date_status'])
def test_toyoko_requires_branch_and_card_date_in_stay(context, field):
    store, data, _, _ = context
    toyoko_candidates(data)
    data['results'][0]['candidate_search']['candidates'][0][field] = 'UNKNOWN'
    assert stays.stay_index(store) == {}


def test_toyoko_manual_empty_period_stored_booking_and_other_occupancy_win(context):
    store, data, _, _ = context
    toyoko_candidates(data)
    assert stays.period_for(card(reservation_no='B1'), stays.stay_index(store)) == ''
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}
    store.conn.execute('DELETE FROM board_manual_overrides')
    data['links'] = {'other': {'transaction_id':'t1'}}
    assert stays.stay_index(store) == {}


def test_one_conflicting_reservation_blocks_other_agreeing_candidates(context):
    store, data, _, _ = context
    toyoko_candidates(data)
    data['events'].append(dict(data['events'][0], ota_event_id='e2', period_conflict=True))
    data['results'].append(dict(data['results'][0], ota_event_id='e2'))
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('relation', [
    {'reservation_link': {'status':'USER_CONFIRMED', 'transaction_id':'t1'}},
    {'payment_relation': {'status':'LINKED', 'transaction_ids':['t1']}},
    {'reserved_card_ids':['t1']}])
def test_existing_relations_cannot_be_replaced_with_reservation_inference(context, relation):
    store, data, _, _ = context
    toyoko_candidates(data)
    data['results'].append(dict(ota_event_id='other', status='MATCHED_GROUP', **relation))
    assert stays.stay_index(store) == {}
