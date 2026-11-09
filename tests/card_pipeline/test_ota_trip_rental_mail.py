"""Synthetic rental confirmations keep paid KRW, service dates and deposit limits separate."""
import json

import pytest

from app import ota_mail, ota_payments
from tests.card_pipeline.test_booking_mail import message
from tests.card_pipeline.test_ota_payments import card


BODY = ('예약번호: 1234567890123456\n렌터카 예약이 확정되었습니다 '
        '(인수: 2026-08-04 12:00:00, 반납: 2026-08-09 12:00:00).\n'
        '인수 시간:\n2026-08-04 12:00\n반납일시:\n2026-08-09 12:00\n'
        '총 금액\nKRW 123456.00\n온라인 선결제\nKRW 123456.00\n'
        '자차 손해 면책 자기부담금: JPY100000\n운휴 손실 비용 자기부담금: JPY50000')
SUBJECT = '[트립닷컴] 렌터카 예약이 확정되었습니다 (합성도시)-회신하지 마십시오'


def rental(body=BODY, subject=SUBJECT):
    return message(body, subject=subject, identity='synthetic-rental', sent='2026-07-10')


def load(tmp_path, mail):
    (tmp_path/'gmail-rental.json').write_text(json.dumps({'responses':[mail]}),encoding='utf8')
    return ota_payments.build_ota_payment_events({'mail_directories':[tmp_path]})


def test_trip_rental_explicit_prepaid_amount_and_pickup_return_reach_matching(tmp_path):
    fact = ota_payments.extract_payment_fact(rental())
    assert fact['item'] == '렌터카' and fact['paid_amount_krw'] == 123456
    assert fact['period'] == {'starts_on':'2026-08-04','ends_on':'2026-08-09'}
    event = load(tmp_path, rental())[0]
    assert event['item'] == '렌터카' and event['amount_krw'] == 123456
    assert event['service_period'] == fact['period']
    result = ota_payments.match_ota_payment_events([event], [card('rental',
        merchant='트립닷컴(구)_NICE', merchant_normalized='트립닷컴(구)_nice',
        approval_date='2026-07-10', amount_krw=123456)])[0]
    assert result['status'] == 'MATCHED_AUTO' and result['transaction_id'] == 'rental'


@pytest.mark.parametrize('change', ['no_prepaid','scheduled','fractional_krw','two_online_amounts','cancelled','unsigned',
                                  'future_confirmation','bad_comma','two_refs'])
def test_rental_total_or_deposit_never_claims_an_actual_payment(tmp_path, change):
    mail=rental()
    body=BODY
    if change=='no_prepaid':body=body.replace('온라인 선결제\nKRW 123456.00','현장 결제\nKRW 123456.00')
    elif change=='scheduled':body+='\n결제 예정: 2026-08-01'
    elif change=='fractional_krw':body=body.replace('123456.00','123456.50')
    elif change=='two_online_amounts':body+='\n온라인 선결제\nKRW 123457.00'
    elif change=='cancelled':mail=rental(subject='렌터카 예약 취소 완료')
    elif change=='future_confirmation':mail=rental(subject='렌터카 예약확정 예정')
    elif change=='bad_comma':body=body.replace('123456.00','123,45.00')
    elif change=='two_refs':body+='\n예약번호: 1234567890123457'
    else:mail['payload']['headers'][-1]['value']='dkim=fail'
    mail['payload']['body']['content']=body
    assert not any(ota_payments._event_is_paid(e) for e in load(tmp_path, mail))


@pytest.mark.parametrize('body', [BODY.replace('2026-08-09','2026-08-03'),
    BODY.replace('2026-08-09','2026-02-30'), BODY+'\n반납: 2026-08-10 12:00'])
def test_rental_invalid_or_conflicting_dates_are_not_guessed(body):
    fact=ota_payments.extract_payment_fact(rental(body=body))
    assert fact['item']=='렌터카' and fact['period'] is None


def test_rental_context_enriches_separate_receipt_without_altering_charge(tmp_path):
    receipt=message('예약번호: 1234567890123456\n총 금액 123,456원',
                     subject='결제 완료 안내',identity='rental-paid',sent='2026-07-10')
    (tmp_path/'gmail-rental.json').write_text(json.dumps({'responses':[receipt,rental()]}),encoding='utf8')
    event=next(e for e in ota_payments.build_ota_payment_events({'mail_directories':[tmp_path]})
               if e['source_ids']==['mail:rental-paid'])
    assert event['item']=='렌터카' and event['amount_krw']==123456
    assert event['service_period']=={'starts_on':'2026-08-04','ends_on':'2026-08-09'}


@pytest.mark.parametrize('wording',['결제 실패','결제 미완료','결제되지 않았습니다','결제가 취소되었습니다',
    '결제가 완료되지 않았습니다','결제가 이루어지지 않았습니다','결제 처리 중',
    'payment not completed','payment unsuccessful','payment pending'])
def test_prepaid_amount_does_not_override_payment_failure(tmp_path,wording):
    assert not any(ota_payments._event_is_paid(e) for e in load(tmp_path,rental(BODY+'\n'+wording)))
