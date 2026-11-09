import itertools
import json

from app import ota_mail, ota_payments, mail_collect

_COUNTER = itertools.count()
SENDER = 'KR_HTL_NoReply@trip.com'
STAY = '체크인 2026년 8월 3일 15:00~18:00 체크아웃 2026년 8월 4일 10:00 이전 '


def mail(subject, body, day, ref='1400827497521086'):
    record = mail_collect.owner_record('synthetic', {
        'From': SENDER, 'Subject': subject, 'Date': f'{day} 09:44:00 +0900'}, f'예약번호 {ref} ' + body)
    record['id'] = f'synthetic-{next(_COUNTER)}'
    return record


def confirmation(amount, day='Sat, 11 Jul 2026'):
    return mail('[예약 확정 안내] 케리 산장 예약이 확정되었습니다-NoReply',
                STAY + f'요금 정보 객실 1개 × 1박 {amount:,}원 온라인 사전 결제 결제 완료 {amount:,}원 총 금액 온라인 사전 결제 {amount:,}원', day)


def update(total, day='Sat, 11 Jul 2026'):
    return mail('케리 산장 예약이 업데이트되었습니다-NoReply',
                STAY + f'요금 정보 객실 1개 × 1박 {total:,}원 온라인 사전 결제 결제 완료 {total:,}원 총 금액 온라인 사전 결제{total:,}원', day)


def events_for(tmp_path, *messages):
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': list(messages)}), encoding='utf-8')
    return ota_payments._parse_mail_events([tmp_path])


def charges(events):
    return sorted(e['amount_krw'] for e in events if e['event_type'] == 'charge' and e['amount_krw'])


def test_update_notice_reports_its_new_total_and_never_a_charge():
    fact = ota_mail.extract_mail(update(167572))
    assert fact['updated_total_krw'] == 167572 and fact['paid_amount_krw'] is None
    assert fact['period'] == {'starts_on': '2026-08-03', 'ends_on': '2026-08-04'}


def test_rise_after_a_confirmed_payment_is_charged_only_for_the_difference(tmp_path):
    events = events_for(tmp_path, confirmation(119965), update(167572, 'Sat, 11 Jul 2026'))
    assert charges(events) == [47607, 119965]
    delta = next(e for e in events if e['amount_krw'] == 47607)
    assert delta['service_period'] == {'starts_on': '2026-08-03', 'ends_on': '2026-08-04'}
    assert delta['paid_on'] == '2026-07-11' and delta['booking_ref'] == '1400827497521086'


def test_repeated_lower_or_unconfirmed_updates_never_create_a_charge(tmp_path):
    repeated = update(167572)
    repeated['id'] = 'synthetic-repeat'
    assert charges(events_for(tmp_path, confirmation(119965), update(167572), repeated)) == [47607, 119965]
    assert charges(events_for(tmp_path, confirmation(119965), update(100000))) == [119965]
    assert charges(events_for(tmp_path, update(167572))) == []


def test_a_cancelled_booking_or_a_different_stay_never_creates_a_difference_charge(tmp_path):
    cancelled = mail('케리 산장 예약이 무료로 취소되었습니다-NoReply', STAY + '예약이 취소되었습니다', 'Sat, 11 Jul 2026')
    assert charges(events_for(tmp_path, confirmation(119965), update(167572), cancelled)) == [119965]
    other = mail('케리 산장 예약이 업데이트되었습니다-NoReply',
                 STAY.replace('8월 3일', '8월 5일') + '총 금액 온라인 사전 결제167,572원', 'Sat, 11 Jul 2026')
    assert charges(events_for(tmp_path, confirmation(119965), other)) == [119965]
