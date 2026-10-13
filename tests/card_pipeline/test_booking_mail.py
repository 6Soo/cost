"""원화 실제 결제액, 모호한 예약 연결과 취소된 일정의 경계를 검증한다."""
import datetime
import json
from email.utils import format_datetime
from tools.match_booking_mail import extract_mail,match_mail,europe_stays,lodging_mail_matches
from app.ota_mail import load_messages, decimal_amount
import pytest


def message(body,subject='[예약 확정 안내] 합성 숙소 예약이 확정되었습니다',identity='one',domain='trip.com',sent='2026-05-01'):
    when=datetime.datetime.fromisoformat(sent+'T12:00:00+09:00')
    return {'id':identity,'internal_date':str(int(when.timestamp()*1000)),
            'payload':{'headers':[{'name':'From','value':'noreply@'+domain},
                {'name':'Subject','value':subject},{'name':'Date','value':format_datetime(when)},
                {'name':'Authentication-Results','value':'mx.google.com; dkim=pass header.i=@'+domain}],
                'mime_type':'text/plain','body':{'content':body},'parts':None}}


def hotel(ref='1111111111111111',start='2026년 5월 22일',end='2026년 5월 23일',country='이탈리아'):
    return f'예약번호\n{ref}\n체크인\n{start}\n체크아웃\n{end}\n주소\n합성 주소, {country}\n총 금액\n온라인 사전 결제\n123,000원'


def test_klook_uses_online_charge_and_keeps_pickup_balance_separate():
    m=message('예약번호: SYN123456\n총 금액\n₩ 466,506\n온라인 결제 ₩ 150,306\n픽업시 결제 ₩ 316,200',
              subject='[Klook] 클룩 예약내역 안내',domain='klook.com')
    assert extract_mail(m)['paid_amount_krw']==150306
    m['payload']['headers'][-1]['value']='mx.google.com; dkim=fail header.i=@klook.com'
    assert extract_mail(m) is None


def test_paid_train_and_zero_price_guide_are_not_two_paid_bookings(tmp_path):
    receipt=message('예약번호: TRAIN12345\n기차표\n총 금액\n₩ 37,600\n티켓 발급 수수료: ₩ 3,800\n'
                    '예약번호: GUIDE12345\n이딸로 & 트랜이탈리아 티켓 수령 가이드\n'
                    '총 금액\n₩ 0\n합계: ₩ 41,400\n금액: ₩ 41,400',
                    subject='[Klook] 클룩 예약내역 안내',identity='receipt',domain='klook.com')
    confirmation=message('예약번호: TRAIN12345\n기차 티켓',subject='합성 기차 예약확정 안내',
                         identity='confirmation',domain='klook.com')
    (tmp_path/'gmail-synthetic.json').write_text(json.dumps({'responses':[receipt,confirmation]}),encoding='utf-8')
    row=dict(transaction_id='synthetic',source_hash='a'*64,merchant='KLOOK',merchant_normalized='klook',
             card_kind='국내',approval_date='2026-05-01',transaction_direction='purchase',amount_krw=41400)
    result=match_mail(tmp_path,[row])
    assert result['exact_matches']==1
    assert result['matches'][0]['booking_ref']=='TRAIN12345'
    assert result['matches'][0]['ignored_zero_cost_guides']==['GUIDE12345']
    assert result['rules'][0]['effects']['item']=='교통비'
    assert 'booking_period' not in result['rules'][0]['optional']
    receipt['payload']['body']['content']=receipt['payload']['body']['content'].replace('₩ 0','₩ 100')
    assert extract_mail(receipt) is None


def test_same_price_reservations_classify_only_the_common_product(tmp_path):
    mails=[message(hotel(),identity='one'),message(hotel('2222222222222222'),identity='two')]
    (tmp_path/'gmail-synthetic.json').write_text(json.dumps({'responses':mails}),encoding='utf-8')
    row=dict(transaction_id='synthetic',source_hash='a'*64,merchant='TRIP.COM',merchant_normalized='trip.com',
             card_kind='국내',approval_date='2026-05-01',transaction_direction='purchase',amount_krw=123000)
    result=match_mail(tmp_path,[row])
    assert result['exact_matches']==0 and result['type_only_matches']==1
    assert result['rules'][0]['effects']=={'item':'숙박비'}
    assert 'booking_period' not in result['rules'][0]['optional']


def test_cancelled_early_hotel_does_not_extend_europe_trip(tmp_path):
    old=message(hotel(start='2026년 5월 17일',end='2026년 5월 19일',country='오스트리아'),identity='old')
    cancel=message('예약번호: 1111111111111111',subject='합성 숙소 예약이 무료로 취소되었습니다',identity='cancel',sent='2026-05-03')
    active=message(hotel('2222222222222222'),identity='active')
    (tmp_path/'gmail-synthetic.json').write_text(json.dumps({'responses':[old,cancel,active]}),encoding='utf-8')
    result=europe_stays(tmp_path)
    assert result['starts_on']=='2026-05-22' and result['ends_on']=='2026-05-23'
    assert result['cancelled_booking_refs']==['1111111111111111']
    assert len(result['stays'])==1


def test_foreign_receipt_requires_currency_unique_card_row_and_one_service_period(tmp_path):
    receipt=message('예약번호: 6536628563\n총 지불 금액\n¥48,000',subject='결제가 완료되었습니다',
                    domain='booking.com',identity='paid',sent='2026-07-14')
    stay=message('예약번호: 6536628563\n체크인: 2026-07-22\n체크아웃: 2026-07-25',
                 subject='숙박 예약이 확정되었습니다',domain='booking.com',identity='stay',sent='2026-07-10')
    path=tmp_path/'gmail-synthetic.json'
    path.write_text(json.dumps({'responses':[receipt,stay]}),encoding='utf-8')
    row=dict(merchant='BKG*BOOKING.COM HOTEL',source_hash='a'*64,approval_date='2026-07-14',
             transaction_direction='purchase',foreign_currency='JPY',foreign_amount='48000')
    result=lodging_mail_matches(tmp_path,[row])
    assert len(result)==1 and result[0]['period']=={'starts_on':'2026-07-22','ends_on':'2026-07-25'}
    assert result[0]['strict_service_period'] and result[0]['confidence']=='중간'
    assert lodging_mail_matches(tmp_path,[dict(row,foreign_currency='USD')])==[]
    assert lodging_mail_matches(tmp_path,[row,dict(row,source_hash='b'*64)])==[]
    receipt['payload']['headers'][-1]['value']='dkim=fail header.i=@booking.com'
    path.write_text(json.dumps({'responses':[receipt,stay]}),encoding='utf-8')
    assert lodging_mail_matches(tmp_path,[row])==[]


def test_scheduled_agoda_charge_is_not_a_paid_receipt(tmp_path):
    mail=message('예약번호: 1738864710\n총 금액 ¥48,000\n체크인: 2026-07-22\n체크아웃: 2026-07-25',
                 subject='Agoda 예약 확정서',domain='agoda.com')
    (tmp_path/'gmail-synthetic.json').write_text(json.dumps({'responses':[mail]}),encoding='utf-8')
    row=dict(merchant='AGODA',source_hash='a'*64,approval_date='2026-05-01',transaction_direction='purchase',
             foreign_currency='JPY',foreign_amount='48000')
    assert lodging_mail_matches(tmp_path,[row])==[]


def test_sender_signature_domain_suffix_is_not_trusted():
    mail=message(hotel())
    mail['payload']['headers'][-1]['value']='dkim=pass header.i=@trip.com.example'
    assert extract_mail(mail) is None


def test_duplicate_message_enrichment_is_allowed_but_changed_body_is_rejected(tmp_path):
    original=message(hotel())
    enriched=json.loads(json.dumps(original))
    enriched['payload']['parts']=[]
    (tmp_path/'gmail-a.json').write_text(json.dumps({'responses':[original]}),encoding='utf-8')
    path=tmp_path/'gmail-b.json'
    path.write_text(json.dumps({'responses':[enriched]}),encoding='utf-8')
    assert len(load_messages(tmp_path))==1
    enriched['payload']['body']['content']+=' changed'
    path.write_text(json.dumps({'responses':[enriched]}),encoding='utf-8')
    with pytest.raises(ValueError,match='OTA_MESSAGE_CONTENT_CONFLICT'):
        load_messages(tmp_path)


def test_conflicting_service_periods_keep_payment_but_do_not_choose_first_period(tmp_path):
    mails=[message(hotel(),identity='one'),
           message(hotel(start='2026년 5월 24일',end='2026년 5월 25일'),identity='two')]
    (tmp_path/'gmail-a.json').write_text(json.dumps({'responses':mails}),encoding='utf-8')
    row=dict(transaction_id='synthetic',source_hash='a'*64,merchant='TRIP.COM',merchant_normalized='trip.com',
             card_kind='국내',approval_date='2026-05-01',transaction_direction='purchase',amount_krw=123000)
    result=match_mail(tmp_path,[row])
    assert result['exact_matches']==1
    assert result['matches'][0]['period'] is None
    assert result['matches'][0]['period_conflict']
    assert 'booking_period' not in result['rules'][0]['optional']


def test_domestic_agoda_receipt_uses_same_matching_path_and_payment_day(tmp_path):
    mail=message('예약번호: 1738864710\n총 금액 KRW 48,000\n체크인: 2026-07-22\n체크아웃: 2026-07-25',
                 subject='결제가 완료되었습니다',domain='agoda.com')
    (tmp_path/'gmail-a.json').write_text(json.dumps({'responses':[mail]}),encoding='utf-8')
    row=dict(transaction_id='synthetic',merchant='아고다_나이스',merchant_normalized='아고다_나이스',
             source_hash='a'*64,approval_date='2026-05-01',transaction_direction='purchase',amount_krw=48000,card_kind='국내')
    result=match_mail(tmp_path,[row])
    assert result['exact_matches']==1 and len(result['rules'])==1
    assert result['matches'][0]['source_hash']==result['rules'][0]['optional']['source_hash']
    assert lodging_mail_matches(tmp_path,[dict(row,approval_date='2026-05-02')])==[]
    # 같은 원문 해시여도 두 실제 거래를 한 예약으로 합치지 않는다.
    assert lodging_mail_matches(tmp_path,[row,dict(row,transaction_id='second')])==[]


def test_cancelled_lodging_does_not_supply_an_active_service_period(tmp_path):
    receipt=message('예약번호: 1738864710\n총 금액 ¥48,000\n체크인: 2026-07-22\n체크아웃: 2026-07-25',
                    subject='결제가 완료되었습니다',domain='agoda.com')
    cancelled=message('예약번호: 1738864710',subject='예약 취소 완료',domain='agoda.com',identity='cancel',sent='2026-05-02')
    (tmp_path/'gmail-a.json').write_text(json.dumps({'responses':[receipt,cancelled]}),encoding='utf-8')
    row=dict(merchant='AGODA',source_hash='a'*64,approval_date='2026-05-01',transaction_direction='purchase',
             foreign_currency='JPY',foreign_amount='48000')
    assert lodging_mail_matches(tmp_path,[row])==[]


def test_cancelled_trip_receipt_keeps_original_charge_but_blocks_travel_period(tmp_path):
    mails=[message(hotel()),message('예약번호: 1111111111111111',subject='예약 취소 완료',identity='cancel',sent='2026-05-02')]
    (tmp_path/'gmail-a.json').write_text(json.dumps({'responses':mails}),encoding='utf-8')
    row=dict(transaction_id='synthetic',source_hash='a'*64,merchant='TRIP.COM',merchant_normalized='trip.com',
             card_kind='국내',approval_date='2026-05-01',transaction_direction='purchase',amount_krw=123000)
    result=match_mail(tmp_path,[row])
    assert result['exact_matches']==1
    assert result['matches'][0]['reservation_status']=='cancelled'
    assert result['matches'][0]['period'] is None
    assert result['matches'][0]['paid_amount_krw']==123000


@pytest.mark.parametrize('text,expected',[('1,234.56','1234.56'),('1.234,56','1234.56'),
                                        ('12,34','12.34'),('48,000','48000')])
def test_currency_amount_keeps_decimal_separator(text,expected):
    from decimal import Decimal
    assert decimal_amount(text)==Decimal(expected)


def test_ambiguous_currency_separator_is_not_silently_removed():
    from decimal import InvalidOperation
    with pytest.raises(InvalidOperation):decimal_amount('1,2,3')


def test_exact_booking_description_overrides_empty_historical_description_only():
    from app.classify import classify_transaction
    from app.rules import normalize_rule
    broad=normalize_rule({'conditions':{'merchant_normalized':'BOOKING.COM'},
                          'effects':{'item':'숙박비'},'origin':'history-recovery-20261003'})
    exact=normalize_rule({'conditions':{'merchant_normalized':'BOOKING.COM'},
                          'optional':{'source_hash':'a'*64},
                          'effects':{'item':'숙박비','description':'예약 12345678'}})
    row=dict(merchant='BOOKING.COM',source_hash='a'*64)
    assert classify_transaction(row,rules=[broad,exact])['description']=='예약 12345678'
    changed=dict(broad,effects={'item':'항공료'})
    assert classify_transaction(row,rules=[changed,exact])['classification_source']=='rule_conflict'
    assert classify_transaction(row,rules=[dict(broad,version=2),exact])['classification_source']=='rule_conflict'


def test_agreeing_inference_evidence_is_not_a_financial_conflict():
    from app.classify import classify_transaction
    from app.rules import normalize_rule
    def rule(description,confidence,basis,target=''):
        return normalize_rule({'conditions':{'merchant_normalized':'BOOKING.COM'},
            'optional':{'source_hash':'a'*64,'inferred_assignment':{
                'trip_id':target,'confidence':confidence,'basis':basis}},
            'effects':{'item':'숙박비','description':description}})
    old=rule('숙박비','높음','과거 장부')
    fresh=rule('예약 12345678','중간','예약 메일')
    row=dict(merchant='BOOKING.COM',source_hash='a'*64)
    verdict=classify_transaction(row,rules=[old,fresh])
    assert verdict['classification_state']=='classified'
    assert '높음' in verdict['classification_basis'] and '과거 장부' in verdict['classification_basis']
    disagreement=rule('예약 12345678','중간','예약 메일','other-trip')
    assert classify_transaction(row,rules=[old,disagreement])['classification_source']=='inference_conflict'


def test_flight_confirmation_gives_its_outbound_and_return_dates_and_is_confirmed():
    body='예약번호 1400826610904891\n가는편: 서울 - 고마쓰 | 2026년 8월 1일\n07:30 ICN\n오는편: 고마쓰 - 서울 | 2026년 8월 5일 10:15 KMQ'
    fact=extract_mail(message(body,subject='[트립닷컴] 항공권 예약 확정 안내: 서울 - 고마쓰, 고마쓰 - 서울'))
    assert fact['item']=='항공료' and fact['reservation_status']=='confirmed'
    assert fact['period']=={'starts_on':'2026-08-01','ends_on':'2026-08-05'}
    cancelled=message(body,subject='[트립닷컴] 항공권 예약 확정 안내: 서울 - 고마쓰 취소 완료')
    assert extract_mail(cancelled)['reservation_status']=='cancelled'


def test_a_hotel_confirmation_mail_is_a_confirmed_booking_and_a_payment_mail_is_not():
    confirmed=extract_mail(message(hotel(),subject='[예약 확정 안내] 합성 숙소 예약이 확정되었습니다'))
    assert confirmed['reservation_status']=='confirmed' and confirmed['period']=={'starts_on':'2026-05-22','ends_on':'2026-05-23'}
    paid=extract_mail(message(hotel(),subject='결제 완료 안내'))
    assert paid['reservation_status']=='observed'
