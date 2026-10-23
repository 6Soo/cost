import json

import pytest

from app import mail_collect, ota_payments, toyoko_mail


def message(identity='synthetic-1', *, hotel='토요코인 울산삼산동', refs=('1234567',),
            currency='원', amount=37000, cancelled=False, subtotal=True, day=1):
    text = hotel + '\n숙박일:2026년 10월 1일 (목) 부터 2 박\n'
    for ref in refs:
        text += f'예약번호: {ref}\n숙박일:2026년 10월 1일 (목) 부터 2 박\n'
        if subtotal:
            text += f'소계금액: {amount:,}{currency}\n'
    text += f'합계금액: {amount * len(refs):,}{currency}\n'
    return mail_collect.owner_record(identity, {
        'From': 'reservation@wm.toyoko-inn.com',
        'Subject': '토요코인 코퍼레이트 ' + ('취소 확인' if cancelled else '예약 확인'),
        'Date': f'Thu, {day:02d} Oct 2026 10:00:00 +0900'}, text)


def card(identity='card-1', **updates):
    return {'transaction_id': identity, 'source_hash': identity,
            'merchant': '토요코인 울산삼산동', 'amount_krw': 37000,
            'approval_date': '2026-10-01', 'transaction_direction': 'purchase', **updates}


def test_corporate_rooms_and_group_total_enter_core_without_claiming_cards(tmp_path):
    mail = message(refs=('1234567', '2345678'), amount=12000, currency='엔')
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    events = ota_payments.build_ota_payment_events({'mail_directories': [str(tmp_path)]})
    assert len(events) == 3
    rooms = [event for event in events if not event['reservation_group_only']]
    group = next(event for event in events if event['reservation_group_only'])
    assert {room['amount'] for room in rooms} == {'12000'}
    assert group['amount'] == '24000'
    assert all(event['paid_on'] is None and not ota_payments._event_is_paid(event) for event in events)
    cards = [card('one', merchant='TOYOKO INN', foreign_currency='JPY', foreign_amount='12000'),
             card('two', merchant='TOYOKO INN', foreign_currency='JPY', foreign_amount='12000')]
    results = ota_payments.match_ota_payment_events(events, cards)
    assert {result['status'] for result in results} == {'RESERVATION_ONLY'}
    assert all(not result.get('transaction_id') and not result.get('reserved_card_ids') for result in results)
    for room in rooms:
        trace = ota_payments.search_card_candidates(room, cards)
        assert {c['transaction_id'] for c in trace['candidates']} == {'one', 'two'}
        assert all(c['resolution_allowed'] is False for c in trace['candidates'])
    # 2:3이어도 예약 확인서가 실제 금융 N:M 확정이나 카드 점유를 만들지 않는다.
    assert all(r['status'] == 'RESERVATION_ONLY' for r in
               ota_payments.match_ota_payment_events(events, cards + [card('three')]))


def test_group_total_is_never_copied_to_each_room_and_cancellation_is_hotel_scoped():
    group = message(refs=('1234567', '2345678'), subtotal=False)
    events = toyoko_mail.collect({group['id']: group})
    assert all(e['amount'] is None for e in events if not e['reservation_group_only'])
    assert next(e for e in events if e['reservation_group_only'])['amount'] == '74000'
    active = message('active')
    other_hotel = message('other-cancel', hotel='토요코인 창원', cancelled=True, day=2)
    events = toyoko_mail.collect({m['id']: m for m in (active, other_hotel)})
    assert len(events) == 2
    ours = next(e for e in events if e['hotel_name'] == '토요코인 울산삼산동')
    assert ours['reservation_status'] == 'confirmed'
    assert len(toyoko_mail.search_candidates(ours, [card()])['candidates']) == 1
    cancelled = message('cancel', cancelled=True, day=2)
    after = toyoko_mail.collect({m['id']: m for m in (active, cancelled)})[0]
    assert after['ota_event_id'] == ours['ota_event_id']
    trace = toyoko_mail.search_candidates(after, [card()])
    assert trace['candidates'] == []
    assert trace['rejected'][0]['reason'] == 'RESERVATION_CANCELLED'


def test_cancelled_room_blocks_its_group_without_hiding_other_active_room():
    group = message(refs=('1234567', '2345678'))
    cancel = message('cancel', refs=('1234567',), cancelled=True, day=2)
    events = toyoko_mail.collect({m['id']: m for m in (group, cancel)})
    total = next(e for e in events if e['reservation_group_only'])
    assert total['reservation_status'] == 'cancelled'
    remaining = next(e for e in events if e['booking_numbers'] == ['2345678'])
    assert remaining['reservation_status'] == 'confirmed'


@pytest.mark.parametrize('guard', [dict(duplicate_of='old'), dict(parse_error='bad'),
                                  dict(conflict_reason='collision'), dict(ota_review_held=True),
                                  dict(transaction_direction='refund'), dict(refund_status='refund_pending'),
                                  dict(amount_krw=0), dict(amount_krw=-37000), dict(amount_krw='NaN')])
def test_financial_guards_and_pins_cannot_be_bypassed(guard):
    mail = message()
    event = toyoko_mail.collect({mail['id']: mail})[0]
    assert not ota_payments.search_card_candidates(event, [card(**guard)])['candidates']
    assert ota_payments.search_card_candidates(event, [card()],
        existing_links={event['ota_event_id']: 'old-card'})['status'] == 'USER_PINNED'


def test_foreign_original_amount_required_without_exchange_rate_guess():
    mail = message(currency='엔', amount=12000)
    event = toyoko_mail.collect({mail['id']: mail})[0]
    assert not toyoko_mail.search_candidates(event, [card(amount_krw=12000)])['candidates']
    assert not toyoko_mail.search_candidates(event,
        [card(foreign_currency='USD', foreign_amount=12000)])['candidates']
    domestic = message('domestic')
    won_event = toyoko_mail.collect({domestic['id']: domestic})[0]
    assert not toyoko_mail.search_candidates(won_event,
        [card(merchant='TOYOKO INN', foreign_currency='JPY', foreign_amount=12000)])['candidates']
    assert not toyoko_mail.search_candidates(won_event,
        [card(merchant='TOYOKO INN Tokyo JP')])['candidates']


def test_branch_and_stay_can_explain_amount_difference_but_never_confirm_payment():
    mail = message()
    event = toyoko_mail.collect({mail['id']: mail})[0]
    trace = toyoko_mail.search_candidates(event, [card(amount_krw=185000)])
    assert trace['candidates'][0]['basis'] == 'HOTEL_BRANCH_AND_STAY_ONLY'
    assert trace['candidates'][0]['amount_status'] == 'MISMATCH'
    assert trace['candidates'][0]['resolution_allowed'] is False
    assert not toyoko_mail.search_candidates(event,
        [card(amount_krw=185000, merchant='TOYOKO INN')])['candidates']
    assert not toyoko_mail.search_candidates(event,
        [card(amount_krw=185000, merchant='토요코인 창원')])['candidates']
