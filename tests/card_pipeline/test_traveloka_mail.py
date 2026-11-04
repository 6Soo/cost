import json

from app import airline_payment_mail, flight_evidence, mail_collect, ota_payments, traveloka_mail


def message(subject, body, sender='booking@traveloka.com', identity='synthetic'):
    result = mail_collect.owner_record(identity, {'From': sender, 'Subject': subject,
        'Date': 'Thu, 17 Sep 2026 21:42:00 +0900'}, body)
    return result


def test_ticket_is_reservation_without_fabricated_payment_or_airline_pnr_identity(tmp_path):
    m = message('항공권 - 예약 ID 1234567890',
        '출발 항공편\nICN - NRT\n항공사 예약 코드 (PNR):\nABC123\n2026년 11월 09일 월요일\n'
        '귀국 항공편\n항공사 예약 코드 (PNR): XYZ987\n2026년 11월 12일\n예약 ID: 1234567890')
    fact = traveloka_mail.extract(m)
    assert (fact['booking_ref'], fact['paid_amount_krw'], fact['event_type']) == ('1234567890', None, 'reservation')
    assert fact['period'] == {'starts_on': '2026-11-09', 'ends_on': '2026-11-09'}
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [m]}), encoding='utf-8')
    event = ota_payments._parse_mail_events([tmp_path])[0]
    assert event['evidence_status'] == 'reservation_observed'
    assert event['amount'] is None and event['paid_on'] is None
    flight = flight_evidence.collect_flight_evidence([tmp_path])[('traveloka', '1234567890')]
    assert flight['booking_date_status'] == 'FIRST_RECEIVED'
    assert flight['legs'][0]['departure_on'] == '2026-11-09'


def test_explicit_payment_is_distinct_from_unpaid_notice_and_unknown_day():
    m = message('[Traveloka] 결제 완료, 항공권 발권 중 - 예약 ID 1234567890',
        '예약 ID: 1234567890\n결제 내역\n결제 수단\n토스 페이\n123,000원')
    fact = airline_payment_mail.extract(m)
    assert fact['paid_amount_krw'] == 123000 and fact['paid_on'] is None
    assert ota_payments.provider_compatible(fact, {'merchant': 'Traveloka'})
    assert not ota_payments.provider_compatible(fact, {'merchant': '다른 항공사'})
    assert not ota_payments.provider_compatible(fact, {'merchant': '제주항공'})
    pending = message('항공권 예약 ID 1234567890 결제 요청', '예약 ID: 1234567890\n123,000원')
    assert traveloka_mail.extract(pending)['paid_amount_krw'] is None
    ambiguous = message('[Traveloka] 결제 완료 항공권 예약 ID 1234567890', '123,000원\n124,000원')
    assert traveloka_mail.extract(ambiguous)['paid_amount_krw'] is None


def test_authentication_reference_conflict_foreign_currency_and_marketing_guards():
    subject = '항공권 예약 ID 1234567890'
    assert traveloka_mail.extract(message(subject, '', 'x@traveloka.com.example')) is None
    unauthenticated = message(subject, '')
    unauthenticated.pop('owner_collected')
    assert traveloka_mail.extract(unauthenticated) is None
    assert traveloka_mail.extract(message(subject, '예약 ID 9999999999')) is None
    assert traveloka_mail.extract(message('광고 항공권 50% 할인', '')) is None
    fact = traveloka_mail.extract(message('결제 완료 ' + subject, 'USD 100.00'))
    assert fact['paid_amount_krw'] is None


def test_cancel_notice_blocks_prior_charge_without_claiming_refund(tmp_path):
    paid = message('결제 완료 항공권 예약 ID 1234567890', '123,000원', identity='paid')
    cancelled = message('취소 요청 예약 ID 1234567890', '', identity='cancel')
    assert airline_payment_mail.cancellation_references(cancelled) == {('traveloka', '1234567890')}
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [paid, cancelled]}), encoding='utf-8')
    events = ota_payments._parse_mail_events([tmp_path])
    assert events[0]['evidence_status'] == 'evidence_conflict'
    assert flight_evidence.collect_flight_evidence([tmp_path])[('traveloka', '1234567890')]['cancellation_status'] == 'CONFLICT'


def test_repeated_ticket_and_payment_share_only_reservation_identity(tmp_path):
    ticket = message('항공권 예약 ID 1234567890', '항공사 예약 코드 (PNR): ABC123', identity='ticket')
    paid = message('결제 완료 항공권 예약 ID 1234567890', '123,000원', identity='paid')
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [ticket, paid]}), encoding='utf-8')
    events = ota_payments._parse_mail_events([tmp_path])
    assert len(events) == 2 and len({e['ota_event_id'] for e in events}) == 2
    assert len({e['reservation_identity_attestation']['identity'] for e in events}) == 1
    assert sorted(e['event_type'] for e in events) == ['charge', 'reservation']


def test_jeju_foreign_ticket_stays_reservation_and_pg_token_is_preserved():
    subject = '고객님의 제주항공 여정확인서(e-ticket) 입니다.'
    body = '예약번호 ABC123\n승인번호\nPAY_TOKEN1234567890123456789012345\n결제일\n2026.07.20\n결제금액\n123,000 원'
    fact = airline_payment_mail.jeju_payment_facts(message(subject, body, 'reservation@jejuair.net'))[0]
    assert fact['payment_id'] == 'ABC123:PAY_TOKEN1234567890123456789012345'
    foreign = airline_payment_mail.extract(message(subject, body.replace('123,000 원', 'JPY 12,300'), 'reservation@jejuair.net'))
    assert foreign['event_type'] == 'reservation' and foreign['paid_amount_krw'] is None
