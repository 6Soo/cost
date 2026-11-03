import json
from app import airline_payment_mail, flight_evidence, mail_collect, ota_payments


def message(sender, subject, body):
    return mail_collect.owner_record('synthetic', {
        'From': sender, 'Subject': subject,
        'Date': 'Thu, 17 Sep 2026 21:42:00 +0900',
    }, body)


def test_authenticated_synthetic_airline_payment_and_merchant_guard():
    m = message('noreply@flyasiana.com', '[아시아나항공] 항공권 발급이 완료 되었습니다.',
                '예약번호 ABC123\n예약일자(GMT) 2026-09-17\n출발\n도쿄 (NRT)\n2026.11.09 (월) 13:20\n총 지불금액 (결제완료) KRW 131,800')
    fact = airline_payment_mail.extract(m)
    assert (fact['provider'], fact['booking_ref'], fact['paid_amount_krw']) == ('asiana', 'ABC123', 131800)
    assert fact['paid_on'] is None
    assert fact['reserved_dates'] == ['2026-09-17']
    assert fact['period'] == {'starts_on': '2026-11-09', 'ends_on': '2026-11-09'}
    assert ota_payments.provider_compatible(fact, {'merchant': '아시아나항공'})
    assert not ota_payments.provider_compatible(fact, {'merchant': '다른 가맹점'})
    assert airline_payment_mail.extract(message('x@flyasiana.com.example', m['payload']['headers'][1]['value'], '')) is None


def test_synthetic_skyticket_and_cancel_and_ambiguous_amount():
    m = message('info@skyticket.com', '【skyticket】구입 완료 안내【신청번호：12345678】',
                '신청번호 12345678\n2026-11-09 아오모리 출발 - 도쿄 도착\n결제 금액：KRW 106,999')
    fact = airline_payment_mail.extract(m)
    assert fact['provider'] == 'skyticket'
    assert fact['paid_amount_krw'] == 106999
    assert fact['period']['starts_on'] == '2026-11-09'
    assert ota_payments.provider_compatible(fact, {'merchant': '인터넷상거래_1-주식회사 어드벤처코리아'})
    assert airline_payment_mail.extract(message('info@skyticket.com', '취소 완료', '신청번호 12345678')) is None
    assert airline_payment_mail.extract(message('info@skyticket.com', '구입 완료 안내 신청번호:12345678',
           '신청번호 12345678\n결제 금액: KRW 106,999\n결제 금액: KRW 100,000')) is None


def test_cancellation_notice_blocks_automatic_payment_match(tmp_path):
    purchase = message('info@skyticket.com', '구입 완료 안내 신청번호:12345678',
                       '신청번호 12345678\n결제 금액: KRW 106,999')
    cancel = message('info@skyticket.com', '취소 접수 신청번호:12345678', '신청번호 12345678')
    cancel['id'] = 'synthetic-cancel'
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [purchase, cancel]}), encoding='utf-8')
    events = ota_payments._parse_mail_events([tmp_path])
    assert len(events) == 1
    assert events[0]['evidence_status'] == 'evidence_conflict'
    assert not ota_payments._event_is_paid(events[0])


def test_airline_mail_does_not_treat_received_day_as_payment_date(tmp_path):
    purchase = message('noreply@flyasiana.com', '항공권 발급이 완료 되었습니다.',
                       '예약번호 ABC123\n총 지불금액 (결제완료) KRW 131,800')
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [purchase]}), encoding='utf-8')
    event, = ota_payments._parse_mail_events([tmp_path])
    assert event['paid_on'] is None
    card = {'merchant': '아시아나항공', 'approval_date': '2026-09-17', 'amount_krw': 131800,
            'transaction_direction': 'purchase', 'card_tail': '1234'}
    assert ota_payments.pair_check(event, card) == 'payment_date_unknown'


def test_flight_index_reads_provider_format_and_guards_cancellation(tmp_path):
    purchase = message('info@skyticket.com', '구입 완료 안내 신청번호:12345678',
                       '신청번호 12345678\n2026-11-09 아오모리 출발 - 도쿄 도착\n결제 금액: KRW 106,999')
    cancel = message('info@skyticket.com', '취소 접수 신청번호:12345678', '신청번호 12345678')
    cancel['id'] = 'synthetic-cancel'
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [purchase, cancel]}), encoding='utf-8')
    result = flight_evidence.collect_flight_evidence([tmp_path])[('skyticket', '12345678')]
    assert result['legs'][0]['departure_on'] == '2026-11-09'
    assert result['booking_date_status'] == 'FIRST_RECEIVED'
    assert result['cancellation_status'] == 'CONFLICT'
    assert result['passengers'] == []


def test_explicit_gmt_booking_date_takes_precedence_over_received_date(tmp_path):
    purchase = message('noreply@flyasiana.com', '항공권 발급이 완료 되었습니다.',
        '예약번호 ABC123\n예약일자(GMT) 2026-09-16\n출발 2026.11.09 (월) 13:20\n'
        '총 지불금액 (결제완료) KRW 131,800')
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [purchase]}), encoding='utf-8')
    result = flight_evidence.collect_flight_evidence([tmp_path])[('asiana', 'ABC123')]
    assert result['booking_date_status'] == 'EXPLICIT_LABEL'
    assert result['reserved_on'] == '2026-09-16'
    assert result['booking_card_day'] == ''


def test_jeju_amendment_keeps_two_charges_and_repeated_original_observation(tmp_path):
    body = ('예약번호 ABC123\n예약일\n2026.07.20 (월)\n가는편\nSTANDARD\n편명 7C1601\n'
            '2026.08.06 (목) 07:05\n오는편\n2026.08.12 (수) 10:00\n'
            '카드번호\n050204*****1923\n승인번호\n30107803\n결제일\n2026.07.20\n결제금액\n311,600 원\n')
    first = message('reservation@jejuair.net', '고객님의 제주항공 여정확인서(e-ticket) 입니다.', body)
    subject = '고객님의 제주항공 여정확인서(e-ticket) 입니다.'
    changed = message('reservation@jejuair.net', subject,
                      body.replace('2026.08.12', '2026.08.11') +
                      '카드번호\n050204*****1923\n승인번호\n30109119\n결제일\n2026.07.31\n결제금액\n85,600 원\n')
    changed['id'] = 'amended'
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': [first, changed]}), encoding='utf-8')
    events = ota_payments._parse_mail_events([tmp_path])
    assert len(events) == 3
    assert len({e['ota_event_id'] for e in events}) == 3
    assert len({e['payment_event_id'] for e in events}) == 2
    assert sorted(e['amount_krw'] for e in events) == [85600, 311600, 311600]
    assert all(e['card_last4'] is None for e in events)
    assert all(e['service_period'] == {'starts_on': '2026-08-06', 'ends_on': '2026-08-06'} for e in events)
    assert all(ota_payments.provider_compatible(e, {'merchant': '(주)제주항공(ISP)'}) for e in events)
    assert all(not ota_payments.provider_compatible(e, {'merchant': '다른항공사'}) for e in events)
    card = dict(merchant='(주)제주항공(ISP)', approval_date='2026-07-31', amount_krw=85600,
                transaction_direction='purchase', card_tail='8835')
    extra = next(e for e in events if e['amount_krw'] == 85600)
    assert ota_payments.pair_check(extra, card) is None
    from webapp.ota_catalog import PROVIDERS
    assert PROVIDERS['jeju'] == '제주항공'
    assert airline_payment_mail.jeju_payment_facts(message('x@jejuair.net.example', subject, body)) == []


def test_jeju_rejects_ambiguous_charge_and_cancellation_blocks_payment(tmp_path):
    body = '예약번호 ABC123\n승인번호\n12345678\n결제일\n2026.07.20\n결제금액\n311,600 원\n결제금액\n1,000 원'
    subject = '제주항공 여정확인서(e-ticket) 입니다.'
    assert airline_payment_mail.jeju_payment_facts(message('reservation@jejuair.net', subject, body)) == []
    assert airline_payment_mail.cancellation_references(message('reservation@jejuair.net', '취소 완료', '예약번호 ABC123')) == {('jeju', 'ABC123')}
