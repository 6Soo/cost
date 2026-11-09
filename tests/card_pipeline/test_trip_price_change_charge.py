import itertools
import json

from app import mail_collect, ota_mail, ota_payments

_COUNTER = itertools.count()
SENDER = 'KR_HTL_NoReply@trip.com'
STAY = '체크인 2026년 8월 3일 15:00~18:00 체크아웃 2026년 8월 4일 10:00 이전 '
OTHER_STAY = STAY.replace('8월 3일', '8월 5일').replace('8월 4일', '8월 6일')


def mail(subject, body, day, ref='1400827497521086'):
    record = mail_collect.owner_record('synthetic', {
        'From': SENDER, 'Subject': subject, 'Date': f'{day} 09:44:00 +0900'}, f'예약번호 {ref} ' + body)
    record['id'] = f'synthetic-{next(_COUNTER)}'
    return record


def confirmation(amount, day='Sat, 11 Jul 2026', stay=STAY, ref='1400827497521086'):
    return mail('[예약 확정 안내] 케리 산장 예약이 확정되었습니다-NoReply',
                stay + f'요금 정보 객실 1개 × 1박 {amount:,}원 온라인 사전 결제 결제 완료 {amount:,}원 총 금액 온라인 사전 결제 {amount:,}원',
                day, ref)


def update(total, day='Sat, 11 Jul 2026', stay=STAY):
    return mail('케리 산장 예약이 업데이트되었습니다-NoReply',
                stay + f'요금 정보 객실 1개 × 1박 {total:,}원 온라인 사전 결제 결제 완료 {total:,}원 총 금액 온라인 사전 결제{total:,}원', day)


def events_for(tmp_path, *messages):
    folder = tmp_path / f'mail-{next(_COUNTER)}'
    folder.mkdir()
    (folder / 'gmail-synthetic.json').write_text(json.dumps({'responses': list(messages)}), encoding='utf-8')
    return ota_payments._parse_mail_events([folder])


def charges(events):
    return sorted(e['amount_krw'] for e in events if e['event_type'] == 'charge' and e['amount_krw'])


def rises(events):
    return sorted(e['price_change_amount_krw'] for e in events if e.get('price_change_amount_krw'))


def test_update_notice_reports_its_new_total_and_never_a_charge():
    fact = ota_mail.extract_mail(update(167572))
    assert fact['updated_total_krw'] == 167572 and fact['paid_amount_krw'] is None
    assert fact['period'] == {'starts_on': '2026-08-03', 'ends_on': '2026-08-04'}


def test_rise_after_a_confirmed_payment_is_reservation_evidence_not_a_payment(tmp_path):
    events = events_for(tmp_path, confirmation(119965), update(167572))
    assert charges(events) == [119965] and rises(events) == [47607]
    rise = next(e for e in events if e.get('price_change_amount_krw'))
    assert (rise['event_type'], rise['evidence_status'], rise['paid_on']) == ('reservation', 'reservation_only', None)
    assert rise['price_change_on'] == '2026-07-11'
    assert rise['service_period'] == {'starts_on': '2026-08-03', 'ends_on': '2026-08-04'}


def test_rises_follow_the_latest_stated_total_of_the_same_stay(tmp_path):
    assert rises(events_for(tmp_path, confirmation(100000), update(150000, 'Sun, 12 Jul 2026'),
                            update(120000, 'Mon, 13 Jul 2026'), update(140000, 'Tue, 14 Jul 2026'))) == [20000, 50000]
    repeated = update(167572)
    assert rises(events_for(tmp_path, confirmation(119965), update(167572), repeated)) == [47607]
    assert rises(events_for(tmp_path, update(167572))) == []


def test_a_cancelled_booking_or_any_change_of_stay_yields_no_rise(tmp_path):
    cancelled = mail('케리 산장 예약이 무료로 취소되었습니다-NoReply', STAY + '예약이 취소되었습니다', 'Sat, 11 Jul 2026')
    assert rises(events_for(tmp_path, confirmation(119965), update(167572), cancelled)) == []
    assert rises(events_for(tmp_path, confirmation(100000), update(150000, 'Sun, 12 Jul 2026', OTHER_STAY),
                            update(180000, 'Mon, 13 Jul 2026'))) == []


def test_a_rise_never_links_and_another_booking_card_of_the_same_amount_makes_it_ambiguous(tmp_path):
    events = events_for(tmp_path, confirmation(119965), update(167572))
    card = dict(transaction_id='rise', source_hash='h1', transaction_direction='purchase', merchant='트립닷컴(구)_NICE',
                approval_date='2026-07-11', amount_krw=47607, card_tail='8835')
    other = dict(card, transaction_id='other', source_hash='h2')
    results = ota_payments.match_ota_payment_events(events, [card])
    rise = next(e for e in events if e.get('price_change_amount_krw'))
    record = next(r for r in results if r['ota_event_id'] == rise['ota_event_id'])
    assert record['status'] == 'RESERVATION_ONLY' and record['transaction_id'] is None
    one = ota_payments.search_card_candidates(rise, [card])
    assert one['status'] == 'CANDIDATES_FOUND' and [c['transaction_id'] for c in one['candidates']] == ['rise']
    assert len(ota_payments.search_card_candidates(rise, [card, other])['candidates']) == 2
