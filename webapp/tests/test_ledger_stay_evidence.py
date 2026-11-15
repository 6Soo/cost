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


def test_verified_flight_dates_reach_both_ledger_views_without_saved_booking_number(context, monkeypatch):
    store, data, _, calls = context
    data['events'][0].update(provider='trip', item='항공료', event_type='charge',
                             evidence_status='paid_verified', payment_status='paid')
    data['transactions'][0]['item'] = '항공료'
    monkeypatch.setattr(design, '_load_flight_dates', lambda: ({}, set()))
    value = dict(card(), item='항공료', row_kind='expense', reservation_no='', service_period='',
                 occurred_on='2026-06-01', amount_krw=1000, description='Synthetic flight')
    before = deepcopy(data)
    changes = store.conn.total_changes
    @scoped
    def render():
        return (design._flight_date_labels(value),
                design._table_html([value], kind='expense', selected='', unclassified=False),
                design._mobile_html([], [value], selected='', unclassified=False))
    labels, desktop, mobile = render()
    assert labels[0] == '07.05–07.07'
    assert labels[0] in desktop and labels[0] in mobile
    assert calls == [1] and data == before and store.conn.total_changes == changes
    assert value['reservation_no'] == value['service_period'] == ''


def test_verified_rental_pickup_return_reach_existing_card_views_without_stay_nights(context):
    store, data, _, calls = context
    data['events'][0].update(provider='trip', item='렌터카', event_type='charge',
                             evidence_status='paid_verified', payment_status='paid')
    value = dict(card(), item='렌터카', row_kind='expense', reservation_no='', service_period='',
                 occurred_on='2026-06-01', amount_krw=1000, description='Synthetic rental')
    before = deepcopy(data)
    changes = store.conn.total_changes
    @scoped
    def render():
        return (design._service_date_labels(value),
                design._table_html([value], kind='expense', selected='', unclassified=False),
                design._mobile_html([], [value], selected='', unclassified=False))
    labels, desktop, mobile = render()
    assert labels == ('07.05–07.07', '렌터카 인수 2026-07-05 · 반납 2026-07-07')
    assert labels[0] in desktop and labels[0] in mobile and '2박' not in desktop + mobile
    assert calls == [1] and data == before and store.conn.total_changes == changes


@pytest.mark.parametrize('period', ['', '2026-07-07~2026-07-05', '2026-02-30~2026-03-01',
                                   '2026-01-01~2028-01-01'])
def test_rental_period_display_rejects_invalid_explicit_period(context, period):
    assert design._service_date_labels(dict(card(), item='렌터카', row_id='manual',
                                             service_period=period))[0] == '이용일 미확인'


@pytest.mark.parametrize('field,value', [('ota_review_held', True), ('reservation_refund_blocked', True),
    ('refund_status', 'refund_pending'), ('transaction_direction', 'cancellation')])
def test_linked_flight_display_preserves_card_financial_holds(context, field, value):
    store, data, _, _ = context
    data['events'][0].update(provider='trip', item='항공료', event_type='charge',
                             evidence_status='paid_verified', payment_status='paid')
    data['transactions'][0][field] = value
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('field,value', [('refund_status', 'refund_pending'),
    ('evidence_status', 'not_card_charge'), ('payment_status', 'scheduled'),
    ('event_type', 'refund'), ('source_digest', '')])
def test_linked_flight_dates_require_verified_active_charge(context, field, value):
    store, data, _, _ = context
    data['events'][0].update(provider='trip', item='항공료', event_type='charge',
                             evidence_status='paid_verified', payment_status='paid')
    data['events'][0][field] = value
    assert stays.stay_index(store) == {}


def test_linked_flight_dates_preserve_empty_override_and_saved_other_booking(context):
    store, data, _, _ = context
    data['events'][0].update(provider='trip', item='항공료', event_type='charge',
                             evidence_status='paid_verified', payment_status='paid')
    assert stays.period_for(dict(card(), item='항공료', reservation_no='OTHER'), stays.stay_index(store)) == ''
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


def rakuten_candidates(data):
    from app import ota_rakuten_mail,ota_payments
    from tests.card_pipeline.test_ota_rakuten_mail import mail
    event=ota_rakuten_mail.collect({'rakuten':mail()},[])[0]
    data['events']=[event]
    data['transactions'][0].update(merchant='Rakuten Travel Singapore',card_tail='1234',
        approval_date='2026-05-01',foreign_currency='KRW',foreign_amount='120000',amount_krw=124000)
    data['results']=ota_payments.match_ota_payment_events(data['events'],data['transactions'])
    data['results'][0]['candidate_search']=ota_payments.search_card_candidates(event,data['transactions'])


def agoda_recorded(data, **event_values):
    data['events'] = [dict(ota_event_id='a1', provider='agoda', booking_ref='1744399422', item='숙박비',
        event_type='charge', payment_status='paid', evidence_status='paid_verified', paid_on=None,
        verified_portal_snapshot=True, reservation_status='completed', refund_status='none_displayed',
        card_last4='8835', currency='KRW', amount=94401, amount_krw=94401, source_digest='d',
        service_period={'starts_on': '2026-07-08', 'ends_on': '2026-07-09'}, **event_values)]
    data['transactions'] = [dict(transaction_id='t1', source_hash='s1', transaction_direction='purchase',
        amount_krw=94401, merchant='AGODA_NICE-Agoda', card_tail='8835', approval_date='2026-07-05')]
    data['results'] = [dict(ota_event_id='a1', status='HOLD_DATE_UNKNOWN', transaction_id=None)]


def test_recorded_card_reads_the_mutually_unique_agoda_portal_stay(context):
    store, data, _, _ = context
    agoda_recorded(data)
    before = deepcopy(data)
    found = stays.stay_index(store)
    assert stays.period_for(card(reservation_no=''), found) == '2026-07-08~2026-07-09'
    assert found['t1']['ota_evidence']['kind'] == 'reservation_period_inferred'
    assert data == before


@pytest.mark.parametrize('mutation', [
    lambda d: d['transactions'].append(dict(d['transactions'][0], transaction_id='t2', source_hash='s2')),
    lambda d: d['transactions'][0].update(card_tail='1111'),
    lambda d: d['transactions'][0].update(refund_status='refunded'),
    lambda d: d['transactions'][0].update(ota_review_held=True),
    lambda d: d['events'][0].update(refund_status='refund_requested'),
    lambda d: d['events'][0].update(reservation_status='cancelled'),
    lambda d: d['events'][0].update(evidence_changed=True),
    lambda d: d['links'].update(other={'transaction_id': 't1'}),
])
def test_recorded_card_agoda_pairing_stays_unknown_when_ambiguous_or_unsafe(context, mutation):
    store, data, _, _ = context
    agoda_recorded(data)
    data['links'] = {}
    mutation(data)
    assert stays.stay_index(store) == {}


def test_recorded_card_agoda_pairing_keeps_manual_empty_period(context):
    store, data, _, _ = context
    agoda_recorded(data)
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


def skyticket_candidates(data, tmp_path):
    import json
    from app import ota_payments
    from tests.card_pipeline.test_airline_payment_mail import OVERSEAS_SKYTICKET_BODY, message
    original = message('kaigai@skyticket.com', '【skyticket】구매 완료 안내 <신청번호：32779155>', OVERSEAS_SKYTICKET_BODY)
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [original]}), encoding='utf-8')
    data['events'] = ota_payments._parse_mail_events([tmp_path])
    data['transactions'] = [dict(transaction_id='t1', source_hash='s1', transaction_direction='purchase',
        amount_krw=736240, merchant='인터넷상거래_1-주식회사 어드벤처코리아', card_tail='3820',
        approval_date='2026-07-08')]
    data['results'] = ota_payments.match_ota_payment_events(data['events'], data['transactions'])
    for record, event in zip(data['results'], data['events']):
        record['candidate_search'] = ota_payments.search_card_candidates(event, data['transactions'])
    assert [r['status'] for r in data['results']] == ['HOLD_DATE_UNKNOWN']


def test_unlinked_skyticket_total_shows_airfare_days_on_the_airfare_row(context, tmp_path):
    store, data, _, calls = context
    skyticket_candidates(data, tmp_path)
    before = deepcopy(data)
    value = dict(card(row_kind='expense', occurred_on='2026-07-08', amount_krw=736240, reservation_no=''), item='항공료')
    @scoped
    def render():
        return (design._service_date_labels(value),
                design._table_html([value], kind='expense', selected='', unclassified=False),
                design._mobile_html([], [value], selected='', unclassified=False))
    labels, desktop, mobile = render()
    assert labels[0] == '08.06–08.11' and '2026-08-06' in labels[1] and '2026-08-11' in labels[1]
    assert '08.06–08.11' in desktop and '08.06–08.11' in mobile
    assert data == before and data['results'][0]['transaction_id'] is None
    # A row typed as another category shows no service date; its category is corrected instead.
    other = dict(card(row_kind='expense', amount_krw=736240, reservation_no=''), item='여행상품비')
    @scoped
    def render_other():
        return design._service_date_labels(other)
    assert render_other() == ('', '')


@pytest.mark.parametrize('mutation', [
    lambda d: d['transactions'][0].update(refund_status='refund_requested'),
    lambda d: d['transactions'][0].update(parse_error='bad'),
    lambda d: d['events'][0].update(refund_status='refund_requested'),
    lambda d: d['events'][0].update(source_digest=''),
    lambda d: d['events'][0].update(service_period_conflict=True),
    lambda d: d['results'][0].update(evidence_changed=True),
    lambda d: d['links'].update(other={'transaction_id': 't1'}),
    lambda d: d['events'].append(dict(d['events'][0], ota_event_id='dup', booking_ref='99999999')) or
              d['results'].append(dict(d['results'][0], ota_event_id='dup')),
])
def test_unlinked_skyticket_total_stays_unknown_when_evidence_is_unsafe_or_ambiguous(context, tmp_path, mutation):
    store, data, _, _ = context
    skyticket_candidates(data, tmp_path)
    data['links'] = {}
    mutation(data)
    assert stays.stay_index(store) == {}


def test_unlinked_skyticket_total_keeps_manual_empty_period(context, tmp_path):
    store, data, _, _ = context
    skyticket_candidates(data, tmp_path)
    assert stays.period_for(card(reservation_no='OTHER'), stays.stay_index(store)) == ''
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


def asiana_ticket(data, tmp_path):
    import json
    from app import ota_payments
    from tests.card_pipeline.test_airline_payment_mail import message
    original = message('noreply@flyasiana.com', '[아시아나항공] 항공권 발급이 완료 되었습니다.',
                       '예약번호 ABC123\n예약일자(GMT) 2026-09-17\n출발\n도쿄 (NRT)\n2026.11.09 (월) 13:20\n'
                       '총 지불금액 (결제완료) KRW 131,800')
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [original]}), encoding='utf-8')
    data['events'] = ota_payments._parse_mail_events([tmp_path])
    data['transactions'] = [dict(transaction_id='t1', source_hash='s1', transaction_direction='purchase',
        amount_krw=131800, merchant='아시아나항공', card_tail='8835', approval_date='2026-09-17')]
    data['results'] = ota_payments.match_ota_payment_events(data['events'], data['transactions'])
    assert [r['status'] for r in data['results']] == ['HOLD_DATE_UNKNOWN']


def test_unlinked_asiana_ticket_shows_its_departure_day_on_the_equal_airline_card(context, tmp_path):
    store, data, _, _ = context
    asiana_ticket(data, tmp_path)
    before = deepcopy(data)
    value = dict(card(row_kind='expense', occurred_on='2026-09-17', amount_krw=131800, reservation_no=''), item='항공료')
    labels = scoped(lambda: design._service_date_labels(value))()
    assert labels[0] == '11.09' and '2026-11-09' in labels[1]
    assert stays.stay_index(store)['t1']['ota_evidence'] == {'kind': 'reservation_period_inferred',
                                                             'payment_verified': False}
    assert data == before and data['results'][0]['transaction_id'] is None


@pytest.mark.parametrize('mutation', [
    lambda d: d['transactions'].append(dict(d['transactions'][0], transaction_id='t2', source_hash='s2')),
    lambda d: d['transactions'][0].update(amount_krw=131000),
    lambda d: d['transactions'][0].update(merchant='다른 항공사'),
    lambda d: d['transactions'][0].update(approval_date='2026-11-10'),
    lambda d: d['transactions'][0].update(refund_status='refunded'),
    lambda d: d['transactions'][0].update(ota_review_held=True),
    lambda d: d['events'][0].update(reservation_status='cancelled'),
    lambda d: d['events'][0].update(service_period_conflict=True),
    lambda d: d['results'][0].update(evidence_changed=True),
    lambda d: d['links'].update(other={'transaction_id': 't1'}),
    lambda d: d['events'].append(dict(d['events'][0], ota_event_id='dup', booking_ref='XYZ789')) or
              d['results'].append(dict(d['results'][0], ota_event_id='dup')),
])
def test_unlinked_asiana_ticket_stays_unknown_when_ambiguous_or_unsafe(context, tmp_path, mutation):
    store, data, _, _ = context
    asiana_ticket(data, tmp_path)
    data['links'] = {}
    mutation(data)
    assert stays.stay_index(store) == {}


def test_unlinked_asiana_ticket_keeps_manual_empty_period(context, tmp_path):
    store, data, _, _ = context
    asiana_ticket(data, tmp_path)
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


def airbnb_stay(data):
    from app import airbnb_mail
    from tests.card_pipeline.test_airbnb_mail import confirmed
    data['events'] = airbnb_mail.collect({'m1': confirmed()})
    data['transactions'] = [dict(transaction_id='t1', source_hash='s1', transaction_direction='purchase',
        amount_krw=261401, merchant='AIRBNB * HMSYNTH001', card_tail='8835', approval_date='2026-05-12')]
    data['results'] = []


def test_an_airbnb_card_reads_the_stay_of_the_code_in_its_descriptor(context):
    store, data, _, _ = context
    airbnb_stay(data)
    before = deepcopy(data)
    value = dict(card(row_kind='expense', occurred_on='2026-05-12', amount_krw=261401, reservation_no=''))
    labels = scoped(lambda: design._service_date_labels(value))()
    assert labels[0].startswith('05.16–05.17') and '추론' in labels[0]
    assert data == before


@pytest.mark.parametrize('mutation', [
    lambda d: d['transactions'][0].update(merchant='AIRBNB * HMSYNTH002'),
    lambda d: d['transactions'][0].update(merchant='AIRBNB * INC'),
    lambda d: d['transactions'].append(dict(d['transactions'][0], transaction_id='t2', source_hash='s2')),
    lambda d: d['transactions'][0].update(refund_status='refunded'),
    lambda d: d['events'][0].update(reservation_status='cancelled'),
    lambda d: d['events'][0].update(service_period=None, service_period_conflict=True),
    lambda d: d['events'].append(dict(d['events'][0], ota_event_id='dup')),
    lambda d: d['results'].append(dict(ota_event_id='other', transaction_id='t1')),
])
def test_an_airbnb_card_stays_unknown_when_the_code_pairing_is_unsafe(context, mutation):
    store, data, _, _ = context
    airbnb_stay(data)
    mutation(data)
    assert stays.stay_index(store) == {}


def test_an_airbnb_card_keeps_a_manual_empty_period(context):
    store, data, _, _ = context
    airbnb_stay(data)
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


def gotogate_stay(data):
    from app import mytrip_mail
    from tests.card_pipeline.test_mytrip_mail import confirmed
    data['events'] = mytrip_mail.collect({'m1': confirmed(legs=('2026년9월18일', '2026년9월21일'))})
    data['transactions'] = [dict(transaction_id='t1', source_hash='s1', transaction_direction='purchase',
        amount_krw=224682, merchant='이니시스(빌링)-고투게이트코리아유', card_tail='8835', approval_date='2026-08-19')]
    data['results'] = []


def test_a_gateway_card_reads_the_flight_dates_of_the_one_confirmation_with_its_total(context):
    store, data, _, _ = context
    gotogate_stay(data)
    before = deepcopy(data)
    found = stays.stay_index(store)['t1']
    assert found['service_period'] == '2026-09-18~2026-09-21' and found['item'] == '항공료'
    assert found['ota_evidence']['kind'] == 'reservation_period_inferred' and not found['ota_evidence']['payment_verified']
    assert data == before


@pytest.mark.parametrize('mutation', [
    lambda d: d['transactions'][0].update(amount_krw=224683),
    lambda d: d['transactions'][0].update(approval_date='2026-08-22'),
    lambda d: d['transactions'][0].update(merchant='아시아나항공'),
    lambda d: d['transactions'].append(dict(d['transactions'][0], transaction_id='t2', source_hash='s2')),
    lambda d: d['transactions'][0].update(refund_status='refunded'),
    lambda d: d['events'][0].update(reservation_status='cancelled'),
    lambda d: d['events'][0].update(service_period=None, service_period_conflict=True),
    lambda d: d['events'].append(dict(d['events'][0], ota_event_id='dup', booking_ref='9999-999-999')),
    lambda d: d['results'].append(dict(ota_event_id='other', transaction_id='t1')),
])
def test_a_gateway_card_stays_unknown_when_the_pairing_is_unsafe(context, mutation):
    store, data, _, _ = context
    gotogate_stay(data)
    mutation(data)
    assert stays.stay_index(store) == {}


def test_a_gateway_card_keeps_a_manual_empty_period(context):
    store, data, _, _ = context
    gotogate_stay(data)
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


def test_rakuten_quote_displays_original_period_without_confirming_payment_or_rewriting_ledger(context):
    store,data,_,calls=context
    rakuten_candidates(data)
    before=deepcopy(data);changes=store.conn.total_changes
    value=card(row_kind='expense',occurred_on='2026-05-01',amount_krw=124000,reservation_no='')
    @scoped
    def render():return (design._stay_text(value),
        design._table_html([value],kind='expense',selected='',unclassified=False),
        design._mobile_html([],[value],selected='',unclassified=False))
    label,desktop,mobile=render()
    assert label=='8월 14일(금) ~ 8월 16일(일) · 2박 · 예약 근거 추론'
    assert '08.14' in desktop and '08.14' in mobile and '124,000' in desktop and '124,000' in mobile
    assert calls==[1] and store.conn.total_changes==changes and data==before
    assert data['results'][0]['transaction_id'] is None
    assert data['events'][0]['paid_on'] is None and data['events'][0]['payment_event_id'] is None


@pytest.mark.parametrize('field,value',[('reservation_status','cancelled'),('source_digest',''),
    ('source_trust','untrusted'),('evidence_status','paid_verified'),('service_period_conflict',True),
    ('reservation_amount_conflict',True),('evidence_changed',True),('refund_status','refund_pending')])
def test_rakuten_unsafe_source_never_fills_period(context,field,value):
    store,data,_,_=context;rakuten_candidates(data)
    data['events'][0][field]=value
    assert stays.stay_index(store)=={}


@pytest.mark.parametrize('field,value',[('ota_review_held',True),('reservation_refund_blocked',True),
    ('duplicate_of','other'),('parse_error','bad'),('conflict_reason','hold'),
    ('transaction_direction','cancellation'),('refund_status','refund_requested')])
def test_rakuten_card_financial_guards_remain_after_candidate_snapshot(context,field,value):
    store,data,_,_=context;rakuten_candidates(data)
    data['transactions'][0][field]=value
    assert stays.stay_index(store)=={}


def test_rakuten_different_periods_existing_links_and_manual_override_are_preserved(context):
    store,data,_,_=context;rakuten_candidates(data)
    assert stays.period_for(card(reservation_no='OTHER'),stays.stay_index(store))==''
    other=deepcopy(data['events'][0]);other.update(ota_event_id='other',booking_ref='OTHER',
        service_period={'starts_on':'2026-08-15','ends_on':'2026-08-16'})
    data['events'].append(other)
    data['results'].append(dict(data['results'][0],ota_event_id='other'))
    assert stays.stay_index(store)=={}
    data['events'].pop();data['results'].pop()
    data['links']={'other':{'transaction_id':'t1'}}
    assert stays.stay_index(store)=={}
    data['links']={}
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store)=={}


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


def test_a_refreshing_service_keeps_the_last_complete_generation(context):
    store, data, state, _ = context
    fresh = stays.stay_index(store)
    assert fresh
    state.update(fresh=False, status='refreshing')
    assert stays.stay_index(store) == fresh
    state.update(status='error')
    assert stays.stay_index(store) == fresh


def test_an_incomplete_or_unstarted_service_is_not_used(context, monkeypatch):
    store, _, _, _ = context
    monkeypatch.setattr(store._ota_snapshot_service, 'display_context', lambda: ({'data': None}, {'fresh': False}))
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


def trip_rise(data, tmp_path, *extra_cards):
    from app import ota_payments
    from tests.card_pipeline.test_trip_price_change_charge import confirmation, update, events_for
    data['events'] = events_for(tmp_path, confirmation(119965), update(167572))
    card = dict(transaction_id='t1', source_hash='s1', transaction_direction='purchase', merchant='트립닷컴(구)_NICE',
                approval_date='2026-07-11', amount_krw=47607, card_tail='8835')
    data['transactions'] = [card, *extra_cards]
    data['results'] = ota_payments.match_ota_payment_events(data['events'], data['transactions'])
    for record, event in zip(data['results'], data['events']):
        record['candidate_search'] = ota_payments.search_card_candidates(event, data['transactions'])


def test_trip_price_change_rise_shows_its_stay_for_the_one_card_charged_that_day(context, tmp_path):
    store, data, _, _ = context
    trip_rise(data, tmp_path)
    before = deepcopy(data)
    found = stays.stay_index(store)
    assert stays.period_for(card(reservation_no=''), found) == '2026-08-03~2026-08-04'
    assert found['t1']['ota_evidence'] == {'kind': 'reservation_period_inferred', 'payment_verified': False}
    assert data == before and all(r['transaction_id'] != 't1' for r in data['results'])


def test_trip_price_change_rise_shows_nothing_when_two_cards_match_or_the_card_is_protected(context, tmp_path):
    store, data, _, _ = context
    other = dict(transaction_id='t2', source_hash='s2', transaction_direction='purchase', merchant='트립닷컴(구)_NICE',
                 approval_date='2026-07-11', amount_krw=47607, card_tail='8835')
    trip_rise(data, tmp_path, other)
    assert 't1' not in stays.stay_index(store)
    trip_rise(data, tmp_path)
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert 't1' not in stays.stay_index(store)


def test_index_is_built_once_per_snapshot_generation_and_rebuilt_on_manual_change(monkeypatch):
    import sqlite3 as _sqlite3
    from threading import RLock as _RLock
    from types import SimpleNamespace as _NS
    from webapp import ota_payment_review
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    current = {'key': 'k1', 'data': {'events': [], 'transactions': [], 'results': []}}
    conn = _sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT, field TEXT)')
    store = _NS(conn=conn, _lock=_RLock(), _ota_snapshot_service=_NS(
        display_context=lambda: (current, {'fresh': True})))
    builds = []
    real = stays._build_index
    monkeypatch.setattr(stays, '_build_index', lambda data, manual: builds.append(1) or real(data, manual))
    stays.stay_index(store)
    stays.stay_index(store)
    assert len(builds) == 1
    conn.execute("INSERT INTO board_manual_overrides VALUES ('card-x','service_period')")
    stays.stay_index(store)
    assert len(builds) == 2
    current = {'key': 'k2', 'data': {'events': [], 'transactions': [], 'results': []}}
    stays.stay_index(store)
    assert len(builds) == 3
    conn.close()


@pytest.fixture
def onsite(context, monkeypatch):
    monkeypatch.setattr(design.board, 'live_trips', lambda include_archived=False: [
        dict(tab_id='trip-a', starts_on='2026-07-05', ends_on='2026-07-12'),
        dict(tab_id='trip-open', starts_on='2026-08-01', ends_on='')])

    def labels(item='숙박비', merchant='SYNTH HOTEL KYOTO', day='2026-07-08', tab='trip-a', **values):
        value = {**dict(row_id='card-t9', source_event_id='t9', item=item, row_kind='expense',
                        reservation_no='', service_period='', occurred_on=day, amount_krw=90000,
                        source_merchant=merchant, display_tab_id=tab), **values}
        return scoped(lambda: design._service_date_labels(value))()
    return labels


def test_a_lodging_paid_at_the_property_shows_its_card_use_date(onsite):
    assert onsite() == ('07.08 현장 결제', '현장 결제한 카드 이용일 2026-07-08 기준 · 숙박 기간은 원문에 없음')
    assert onsite(day='2026-08-20', tab='trip-open')[0] == '08.20 현장 결제'
    assert onsite(merchant='RAKUTENPAY SYNTHHOTEL')[0] == '07.08 현장 결제'
    # Arrival the night before the trip's first day is still that trip's stay.
    assert onsite(day='2026-07-04')[0] == '07.04 현장 결제'
    assert onsite(item='렌터카', merchant='SYNTH RENT A CAR') == (
        '07.08 현장 결제', '현장 결제한 카드 이용일 2026-07-08 기준 · 인수·반납일은 원문에 없음')
    # A rental broker charge is a booking, not a pickup at the counter.
    assert onsite(item='렌터카', merchant='DISCOVERCARS*COM') == ('이용일 미확인', '렌터카 인수·반납일 미확인')


@pytest.mark.parametrize('values', [
    dict(merchant='NICE*결제대행'), dict(merchant='KCP 트래블로버'), dict(merchant='AGODA.COM'),
    dict(merchant='TRIP.COM'), dict(merchant='RAKUTENTRAVELKOKUNAISH'), dict(merchant='(주)어드벤처코리아'), dict(merchant='KG INICIS'),
    dict(merchant='호텔스닷컴'), dict(merchant='인터파크투어'), dict(merchant='마이리얼트립'), dict(merchant='호텔엔조이'),
    dict(merchant='이스타항공_ARS-이스타항공㈜'),
    dict(day='2026-07-03'), dict(day='2026-07-13'), dict(tab=''), dict(tab='unknown'),
    dict(reservation_no='R1')])
def test_a_booking_or_a_charge_outside_its_trip_keeps_the_unknown_date(onsite, values):
    assert onsite(**values) == ('이용일 확인 필요', '이용일 확인 필요')


def _charge_without_stay(data, *periods, status='observed'):
    data['events'][0].update(provider='booking', item='', event_type='charge', service_period=None)
    for index, period in enumerate(periods):
        data['events'].append(dict(ota_event_id=f'r{index}', provider='booking', booking_ref='B1', item='숙박비',
                                   event_type='reservation', reservation_status=status, source_digest=f'd{index}',
                                   service_period=dict(zip(('starts_on', 'ends_on'), period))))
        data['results'].append(dict(ota_event_id=f'r{index}', status='RESERVATION_ONLY'))


def test_a_linked_charge_without_a_stay_reads_its_own_reservation_period(context):
    store, data, _, _ = context
    _charge_without_stay(data, ('2026-07-05', '2026-07-07'))
    before = deepcopy(data)
    found = stays.stay_index(store)
    assert found['t1']['service_period'] == '2026-07-05~2026-07-07'
    assert found['t1']['ota_evidence']['kind'] == 'reservation_period_inferred'
    assert data == before


@pytest.mark.parametrize('periods,status', [
    ((('2026-07-05', '2026-07-07'), ('2026-07-06', '2026-07-08')), 'observed'),
    ((('2026-07-05', '2026-07-07'),), 'cancelled'),
    ((), 'observed')])
def test_a_linked_charge_stays_unknown_without_one_stated_reservation_period(context, periods, status):
    store, data, _, _ = context
    _charge_without_stay(data, *periods, status=status)
    assert 't1' not in stays.stay_index(store)


@pytest.mark.parametrize('link', [dict(status='STALE'), dict(source_digest='older'), dict(evidence_changed=True)])
def test_a_stale_or_changed_reservation_does_not_lend_its_period(context, link):
    store, data, _, _ = context
    _charge_without_stay(data, ('2026-07-05', '2026-07-07'))
    data['links'] = {'r0': link}
    assert 't1' not in stays.stay_index(store)


def test_a_reservation_showing_no_refund_still_lends_its_period(context):
    store, data, _, _ = context
    _charge_without_stay(data, ('2026-07-05', '2026-07-07'))
    data['events'][-1]['refund_status'] = 'none_displayed'
    assert stays.stay_index(store)['t1']['service_period'] == '2026-07-05~2026-07-07'
    data['events'][-1]['refund_status'] = 'refund_requested'
    assert 't1' not in stays.stay_index(store)


def test_a_cancelled_revision_of_the_booking_withholds_the_period(context):
    store, data, _, _ = context
    _charge_without_stay(data, ('2026-07-05', '2026-07-07'))
    data['events'].append(dict(ota_event_id='rc', provider='booking', booking_ref='B1', item='숙박비',
                               event_type='reservation', reservation_status='cancelled', source_digest='dc',
                               service_period={'starts_on': '2026-07-05', 'ends_on': '2026-07-07'}))
    assert 't1' not in stays.stay_index(store)


@pytest.mark.parametrize('item', ['숙박비', '항공료', '렌터카'])
def test_a_refund_without_a_known_date_reads_as_a_refund(onsite, item):
    assert onsite(item=item, amount_krw=-90000, merchant='AGODA.COM') == (
        '취소·환불', '취소·환불 거래라 별도 이용일이 없음')
    # A purchase with the same missing evidence still asks for its date.
    assert onsite(item=item, merchant='AGODA.COM')[0] in ('이용일 확인 필요', '이용일 미확인')


def identical_rooms(data, rooms=3, cards=3):
    agoda_recorded(data)
    base, card_row = data['events'][0], data['transactions'][0]
    data['events'] = [dict(base, ota_event_id=f'a{n}', booking_ref=f'17443994{n:02d}') for n in range(rooms)]
    data['transactions'] = [dict(card_row, transaction_id=f't{n}', source_hash=f's{n}') for n in range(cards)]
    data['results'] = [dict(ota_event_id=f'a{n}', status='HOLD_DATE_UNKNOWN', transaction_id=None) for n in range(rooms)]
    data['links'] = {}


def test_identical_rooms_booked_together_give_every_card_their_shared_stay(context):
    store, data, _, _ = context
    identical_rooms(data)
    before = deepcopy(data)
    found = stays.stay_index(store)
    assert {tid: found[tid]['service_period'] for tid in found} == {f't{n}': '2026-07-08~2026-07-09' for n in range(3)}
    assert found['t0']['booking_ref'] == '' and len(found['t0']['booking_refs']) == 3
    assert data == before


@pytest.mark.parametrize('mutation', [
    lambda d: d['transactions'].pop(),
    lambda d: d['events'][2].update(service_period={'starts_on': '2026-07-09', 'ends_on': '2026-07-10'}),
    lambda d: d['events'][1].update(reservation_status='cancelled'),
    lambda d: d['events'][1].update(refund_status='refund_requested'),
    lambda d: d['links'].update(other={'transaction_id': 't0'}),
])
def test_identical_rooms_stay_unknown_unless_counts_stays_and_status_all_agree(context, mutation):
    store, data, _, _ = context
    identical_rooms(data)
    mutation(data)
    assert stays.stay_index(store) == {}


def test_identical_rooms_read_a_card_foreign_amount_given_without_its_currency(context):
    store, data, _, _ = context
    identical_rooms(data)
    for event in data['events']:
        event.update(currency='JPY', amount=24332, amount_krw=None)
    for row in data['transactions']:
        row.update(amount_krw=211334, foreign_amount='24332.000', foreign_currency='')
    assert len(stays.stay_index(store)) == 3
    data['transactions'][0]['foreign_amount'] = '24333.000'
    assert stays.stay_index(store) == {}


def trip_holds(data, holds, cards):
    data['events'] = [dict(ota_event_id=f'h{n}', provider='trip', booking_ref=f'14008000000000{n:02d}',
        event_type='reservation', evidence_kind='portal_preauthorization', item='숙박비',
        reservation_status='completed', booked_on='2026-07-31', preauthorization_amount_krw=amount,
        preauthorization_refunded_krw=amount, preauthorization_refund='refunded', card_last4='8835',
        service_period={'starts_on': start, 'ends_on': end}, source_digest=f'd{n}')
        for n, (amount, start, end) in enumerate(holds)]
    data['transactions'] = [dict(transaction_id=f't{n}', source_hash=f's{n}', transaction_direction='purchase',
        amount_krw=amount, merchant='트립닷컴(구)_NICE', card_tail='8835', approval_date=day)
        for n, (amount, day) in enumerate(cards)]
    data['results'] = [dict(ota_event_id=f'h{n}', status='NOT_CARD_CHARGE', transaction_id=None) for n in range(len(holds))]
    data['links'] = {}


def preauth_labels(store, tid, **values):
    value = dict(row_id='card-' + tid, source_event_id=tid, item='숙박비', row_kind='expense', reservation_no='',
                 service_period='', occurred_on='2026-07-31', amount_krw=421614, source_merchant='트립닷컴(구)_NICE', **values)
    return scoped(lambda: design._service_date_labels(value))()


def test_a_trip_guarantee_hold_reads_as_a_refunded_pre_authorization(context):
    store, data, _, _ = context
    trip_holds(data, [(421614, '2026-10-22', '2026-10-23')], [(421614, '2026-07-31')])
    found = stays.stay_index(store)
    assert found['t0']['ota_evidence']['kind'] == 'card_preauthorization'
    assert stays.period_for(dict(row_id='card-t0', source_event_id='t0'), found) == ''
    assert preauth_labels(store, 't0') == (
        '10.22–10.23 사전승인', '카드 사전승인(현장 결제 숙박 보증) · 숙박 2026-10-22–2026-10-23 · 환불 완료')


def test_equal_holds_for_two_nights_pair_only_as_a_group(context):
    store, data, _, _ = context
    trip_holds(data, [(140538, '2026-10-21', '2026-10-22'), (140538, '2026-10-22', '2026-10-23')],
               [(140538, '2026-07-31'), (140538, '2026-07-31')])
    compact, full = preauth_labels(store, 't1')
    assert compact == '사전승인' and '2026-10-21–2026-10-22 또는 2026-10-22–2026-10-23' in full


@pytest.mark.parametrize('cards', [
    [(140538, '2026-07-31')],                              # fewer cards than holds
    [(140538, '2026-07-31'), (140538, '2026-10-30')],      # one charged after check-in
    [(140538, '2026-07-31'), (140539, '2026-07-31')],      # different amount
])
def test_holds_without_an_exact_group_are_not_labelled(context, cards):
    store, data, _, _ = context
    trip_holds(data, [(140538, '2026-10-21', '2026-10-22'), (140538, '2026-10-22', '2026-10-23')], cards)
    assert stays.stay_index(store) == {}


def test_a_cancelled_orders_hold_reads_as_a_cancelled_booking_guarantee(context):
    store, data, _, _ = context
    trip_holds(data, [(281076, '2026-10-21', '2026-10-22')], [(281076, '2026-07-31')])
    data['events'][0].update(reservation_status='cancelled', preauthorization_refund='partly_refunded')
    assert preauth_labels(store, 't0') == (
        '사전승인(취소)', '카드 사전승인(취소된 예약 보증) · 원래 숙박 2026-10-21–2026-10-22 · 일부 환불')


def test_an_order_of_unknown_state_is_not_used(context):
    store, data, _, _ = context
    trip_holds(data, [(281076, '2026-10-21', '2026-10-22')], [(281076, '2026-07-31')])
    data['events'][0]['reservation_status'] = 'unknown'
    assert stays.stay_index(store) == {}
