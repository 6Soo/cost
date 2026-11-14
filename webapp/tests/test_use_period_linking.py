"""Synthetic display coverage of the 2026-11-14 use-period linking rules (LINK-092, LINK-109, LINK-110)."""
from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
import sqlite3

import pytest

from app import ota_property_names
from webapp import ledger_stay_evidence as stays


@pytest.fixture
def context(monkeypatch):
    data = {'events': [], 'transactions': [], 'results': [], 'links': {}}
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT, field TEXT)')
    store = SimpleNamespace(conn=conn, _lock=RLock(), _ota_snapshot_service=SimpleNamespace(
        display_context=lambda: ({'data': data}, {'fresh': True})))
    from webapp import ota_payment_review
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    yield store, data
    conn.close()


def card(tid, merchant, day, amount=1000, **values):
    return dict(transaction_id=tid, source_hash='s' + tid, transaction_direction='purchase', amount_krw=amount,
                merchant=merchant, approval_date=day, card_tail='8835', **values)


# ---- 숲나들e 결제와 예약의 주문번호·금액 결합 (LINK-110) ----

def forest(data, *, amount=105000, order='AD0000000000001', reservation=None, cards=None):
    data['events'] = [
        dict(ota_event_id='pay1', provider='forest', event_type='charge', evidence_status='paid_verified',
             order_number=order, amount_krw=amount),
        dict(ota_event_id='res1', provider='forest', event_type='reservation', booking_ref='sooperang:' + order,
             reservation_amount_krw=amount, reservation_status='completed', source_digest='d1',
             service_period={'starts_on': '2026-08-25', 'ends_on': '2026-08-26'}, **(reservation or {})),
    ]
    data['transactions'] = cards if cards is not None else [card('t1', 'NICE_산림휴양시설', '2026-08-06', amount)]
    data['results'] = [dict(ota_event_id='pay1', status='MATCHED_AUTO', transaction_id='t1')]


def test_a_matched_forest_payment_reads_the_stay_of_its_order_and_amount(context):
    store, data = context
    forest(data)
    before = deepcopy(data)
    found = stays.stay_index(store)
    assert found['t1']['service_period'] == '2026-08-25~2026-08-26'
    assert found['t1']['ota_evidence'] == {'kind': 'reservation_period_inferred', 'payment_verified': False}
    assert data == before


@pytest.mark.parametrize('mutation', [
    lambda d: d['events'][1].update(reservation_amount_krw=105001),                    # amount differs
    lambda d: d['events'][1].update(booking_ref='sooperang:AD0000000000002'),          # another order
    lambda d: d['events'][1].update(reservation_status='cancelled'),
    lambda d: d['events'][1].update(service_period={'starts_on': '2026-08-25', 'ends_on': None}),
    lambda d: d['events'][1].update(period_conflict=True),
    lambda d: d['events'].append(dict(d['events'][1], ota_event_id='res2')),           # two bookings, one order
    lambda d: d['results'].append(dict(ota_event_id='other', status='MATCHED_AUTO', transaction_id='t1')),
    lambda d: d['links'].update(other={'transaction_id': 't1'}),                       # saved link of another event
    lambda d: d['results'][0].update(status='HOLD_AMBIGUOUS'),
    lambda d: d['transactions'][0].update(refund_status='refunded'),
])
def test_forest_order_without_one_exact_matching_booking_reads_nothing(context, mutation):
    store, data = context
    forest(data)
    mutation(data)
    assert stays.stay_index(store) == {}


def test_a_manual_period_override_keeps_the_forest_card_out(context):
    store, data = context
    forest(data)
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1', 'service_period')")
    assert stays.stay_index(store) == {}


# ---- OTA 현장결제 예약의 숙소명·이용기간 대조 (LINK-109) ----

def onsite(data, *, names=None, cards=None, bookings=1):
    data['events'] = [
        dict(ota_event_id=f'b{n}', provider='agoda', booking_ref=f'A{n}', event_type='reservation',
             evidence_status='not_card_charge', payment_status='unknown', reservation_status='observed',
             item='숙박비', source_digest=f'd{n}',
             service_period={'starts_on': '2026-07-05', 'ends_on': '2026-07-07'})
        for n in range(bookings)]
    data['property_names'] = names if names is not None else {
        f'agoda:A{n}': ['Sample Hotel Alphatown'] for n in range(bookings)}
    data['transactions'] = cards if cards is not None else [
        card('t1', 'SAMPLE HOTEL ALPHATOWN       TOKYO JP', '2026-07-06')]
    data['results'] = []


def test_a_hotel_card_inside_the_stay_of_the_one_named_booking_reads_that_stay(context):
    store, data = context
    onsite(data)
    before = deepcopy(data)
    found = stays.stay_index(store)
    assert found['t1']['service_period'] == '2026-07-05~2026-07-07'
    assert found['t1']['booking_ref'] == 'A0'
    assert found['t1']['ota_evidence']['payment_verified'] is False
    assert data == before


def test_two_bookings_of_the_same_hotel_are_not_guessed_even_with_equal_stays(context):
    store, data = context
    onsite(data, bookings=2)
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('mutation', [
    lambda d: d['transactions'][0].update(approval_date='2026-07-08'),                 # after check-out
    lambda d: d['transactions'][0].update(approval_date='2026-07-04'),                 # before check-in
    lambda d: d['transactions'][0].update(merchant='OTHER HOTEL ALPHATOWN   TOKYO JP'),
    lambda d: d['transactions'][0].update(merchant='HOTEL                   TOKYO JP'),  # no distinctive token
    lambda d: d['transactions'][0].update(merchant='AGODA COMPANY PTE'),               # an OTA's own charge
    lambda d: d['transactions'][0].update(refund_status='refund_pending'),
    lambda d: d['transactions'][0].update(transaction_direction='cancellation'),
    lambda d: d['events'][0].update(reservation_status='cancelled'),
    lambda d: d['events'][0].update(service_period_conflict=True),
    lambda d: d['events'][0].update(refund_status='refund_requested'),
    lambda d: d['events'][0].update(service_period={'starts_on': '2026-07-05', 'ends_on': None}),
    lambda d: d['events'].append(dict(d['events'][0], ota_event_id='c1', event_type='charge',
                                      evidence_status='paid_verified', payment_status='paid')),  # OTA took payment
    lambda d: d['events'].append(dict(d['events'][0], ota_event_id='p1',
                                      service_period={'starts_on': '2026-07-05', 'ends_on': '2026-07-09'})),
    lambda d: d.update(property_names={}),
    lambda d: d.update(property_names={'agoda:A0': ['Sample Other Place']}),
    lambda d: d['results'].append(dict(ota_event_id='x', status='MATCHED_AUTO', transaction_id='t1')),
    lambda d: d['links'].update(x={'transaction_id': 't1'}),
])
def test_a_hotel_card_without_one_exact_named_booking_reads_nothing(context, mutation):
    store, data = context
    onsite(data)
    mutation(data)
    assert stays.stay_index(store) == {}


def test_a_hotel_card_matching_two_different_hotels_stays_unread(context):
    store, data = context
    onsite(data, bookings=2, names={'agoda:A0': ['Sample Hotel Alphatown'],
                                    'agoda:A1': ['Sample Hotel Alphatown Annex']})
    assert stays.stay_index(store) == {}


def test_a_scheduled_charge_is_not_an_ota_payment(context):
    store, data = context
    onsite(data)
    data['events'].append(dict(data['events'][0], ota_event_id='s1', event_type='scheduled_charge',
                               evidence_status='scheduled', payment_status='scheduled'))
    assert stays.stay_index(store)['t1']['service_period'] == '2026-07-05~2026-07-07'


def test_an_agoda_scheduled_auto_charge_is_the_otas_payment_not_the_hotels(context):
    store, data = context
    onsite(data)
    data['events'].append(dict(data['events'][0], ota_event_id='s1', event_type='scheduled_charge',
                               evidence_status='scheduled', payment_status='scheduled', scheduled_for='2026-07-06'))
    assert stays.stay_index(store) == {}


def test_the_merchant_name_reading_is_linear_on_worst_case_whitespace():
    import time
    start = time.perf_counter()
    for tail in ('x\ny', '\n', 'x'):
        assert stays._same_lodging('SAMPLE HOTEL ALPHATOWN' + ' ' * 20000 + tail, 'Sample Hotel Alphatown')
    assert time.perf_counter() - start < 1


def test_an_existing_exact_stay_is_never_replaced_by_the_name_reading(context):
    store, data = context
    onsite(data)
    data['events'].append(dict(ota_event_id='e9', provider='agoda', booking_ref='X9', item='숙박비',
                               reservation_status='completed', source_digest='d9',
                               service_period={'starts_on': '2026-07-01', 'ends_on': '2026-07-03'}))
    data['results'] = [dict(ota_event_id='e9', transaction_id='t1', status='MATCHED_AUTO')]
    assert stays.stay_index(store)['t1']['service_period'] == '2026-07-01~2026-07-03'


# ---- Trip 확정 메일의 사전승인 금액 (LINK-092) ----

def mail_holds(data, holds, cards):
    data['events'] = [dict(ota_event_id=f'm{n}', provider='trip', booking_ref=f'14009000000000{n:02d}',
        event_type='reservation', evidence_kind='authenticated_payment_mail', evidence_status='preauthorized',
        item='숙박비', reservation_status=status, preauthorized_amount_krw=amount, preauthorized_on=day,
        service_period={'starts_on': '2026-10-22', 'ends_on': '2026-10-23'}, source_digest=f'd{n}')
        for n, (amount, day, status) in enumerate(holds)]
    data['transactions'] = [card(f't{n}', '트립닷컴(구)_NICE', day, amount) for n, (amount, day) in enumerate(cards)]
    data['results'] = [dict(ota_event_id=f'm{n}', status='RESERVATION_ONLY', transaction_id=None)
                       for n in range(len(holds))]


@pytest.mark.parametrize('card_day', ['2026-07-30', '2026-07-31', '2026-08-01'])
def test_a_mail_pre_authorization_labels_the_card_within_one_day(context, card_day):
    store, data = context
    mail_holds(data, [(70269, '2026-07-31', 'confirmed')], [(70269, card_day)])
    evidence = stays.stay_index(store)['t0']['ota_evidence']
    assert evidence['kind'] == 'card_preauthorization' and evidence['payment_verified'] is False
    assert evidence['refund'] == 'unknown' and evidence['periods'] == ['2026-10-22~2026-10-23']
    assert stays.period_for(dict(row_id='card-t0', source_event_id='t0'), stays.stay_index(store)) == ''


@pytest.mark.parametrize('holds, cards', [
    ([(70269, '2026-07-31', 'confirmed')], [(70269, '2026-07-29')]),                    # two days apart
    ([(70269, '2026-07-31', 'confirmed')], [(70270, '2026-07-31')]),                    # amount differs
    ([(70269, '2026-07-31', 'confirmed'), (70269, '2026-07-31', 'cancelled')], [(70269, '2026-07-31')]),  # 2 holds, 1 card
    ([(70269, '2026-07-31', 'confirmed')], [(70269, '2026-07-31'), (70269, '2026-07-31')]),               # 1 hold, 2 cards
    ([(70269, '2026-07-31', 'unknown')], [(70269, '2026-07-31')]),
])
def test_a_mail_pre_authorization_without_an_exact_group_labels_nothing(context, holds, cards):
    store, data = context
    mail_holds(data, holds, cards)
    assert stays.stay_index(store) == {}


def test_a_mail_hold_never_claims_an_occupied_card_or_duplicates_its_portal_hold(context):
    store, data = context
    mail_holds(data, [(70269, '2026-07-31', 'confirmed')], [(70269, '2026-07-31')])
    data['results'].append(dict(ota_event_id='z', status='MATCHED_AUTO', transaction_id='t0'))
    assert stays.stay_index(store) == {}
    data['results'].pop()
    data['events'].append(dict(ota_event_id='h0', provider='trip', booking_ref=data['events'][0]['booking_ref'],
        event_type='reservation', evidence_kind='portal_preauthorization', item='숙박비',
        reservation_status='completed', booked_on='2026-07-31', preauthorization_amount_krw=70269,
        preauthorization_refund='refunded', service_period={'starts_on': '2026-10-22', 'ends_on': '2026-10-23'}))
    evidence = stays.stay_index(store)['t0']['ota_evidence']
    assert evidence['refund'] == 'refunded'


def portal_hold(data, n, amount, refs_day='2026-07-31'):
    data['events'].append(dict(ota_event_id=f'h{n}', provider='trip', booking_ref=f'1400900000000{n:03d}',
        event_type='reservation', evidence_kind='portal_preauthorization', item='숙박비',
        reservation_status='completed', booked_on=refs_day, preauthorization_amount_krw=amount,
        preauthorization_refund='refunded', service_period={'starts_on': '2026-10-22', 'ends_on': '2026-10-23'}))


@pytest.mark.parametrize('cards', [1, 2])
def test_a_mail_hold_never_joins_or_widens_a_portal_group(context, cards):
    store, data = context
    mail_holds(data, [(70269, '2026-08-01', 'confirmed')], [(70269, '2026-07-31')] * cards)
    data['events'][0]['booking_ref'] = '1400900000000999'
    portal_hold(data, 1, 70269)
    before = stays.stay_index(store)
    # the portal alone: one card is labelled by the portal hold only, two cards are no 1:1 group
    if cards == 1:
        evidence = before['t0']['ota_evidence']
        assert before['t0']['booking_refs'] == ['1400900000000001'] and evidence['refund'] == 'refunded'
        assert evidence['periods'] == ['2026-10-22~2026-10-23']
    else:
        assert before == {}


# ---- 숙소명 색인 ----

def booking_mail(subject, body, sender='no-reply@agoda.com'):
    return {'id': subject, 'owner_collected': True, 'internal_date': '1782604800000', 'payload': {
        'headers': [{'name': 'From', 'value': sender}, {'name': 'Subject', 'value': subject},
                    {'name': 'Date', 'value': 'Sun, 28 Jun 2026 09:00:00 +0900'}],
        'body': {'content': body}}}


def test_property_names_come_only_from_authenticated_booking_mails(monkeypatch):
    agoda = booking_mail('Agoda 예약 확정서 - 예약 번호: 1700000001',
                         '<p>예약 관리하기</p><p>예약 관리하기</p><p>&nbsp;</p><p>Sample Inn Alpha ホテル 1-2-3 Street</p>'
                         '<p>숙소 위치 확인</p>')
    trip = booking_mail('[예약 확정 안내] Sample Hotel Beta 예약이 확정되었습니다',
                        '예약 번호: 1400900000000001 체크인 2026-07-05 체크아웃 2026-07-07', 'no-reply@trip.com')
    other = booking_mail('Agoda 예약 확정서 - 예약 번호: 1700000002',
                         '예약 관리하기 Fake Hotel 숙소 위치 확인', 'no-reply@example.com')
    monkeypatch.setattr(ota_property_names.ota_mail, 'load_messages_from',
                        lambda _: ({'a': agoda, 't': trip, 'o': other}, []))
    names = ota_property_names.collect([])
    assert names['agoda:1700000001'] == ['Sample Inn Alpha']
    assert names['trip:1400900000000001'] == ['Sample Hotel Beta']
    assert 'agoda:1700000002' not in names
