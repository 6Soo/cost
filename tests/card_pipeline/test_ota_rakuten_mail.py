import json
from copy import deepcopy

import pytest

from app import ota_payments
from tests.card_pipeline.test_booking_mail import message
from tests.card_pipeline.test_ota_payments import card


BODY=('예약 ID: 12345678901234\n예약 번호: 12345678901234(객실1)\n'
      '결제 방법\n신용카드\nMasterCard **** **** **** 1234 (12/30)\n'
      '예약일\n2026년05월01일(금)\n체크인\n2026년08월14일(금) 15:00\n'
      '체크아웃\n2026년08월16일(일) 10:00\n소계\n₩130,000\n프로모션 할인\n-₩10,000\n'
      '금액 합계\n₩120,000\n현지 통화 환산액\n¥12,000\n입탕세\n¥150')


def mail(body=BODY,identity='rakuten',subject='[라쿠텐 트래블] 예약 확정'):
    return message(body,identity=identity,subject=subject,domain='mail.travel.rakuten.com')


def load(tmp_path,mails):
    (tmp_path/'gmail-rakuten.json').write_text(json.dumps({'responses':mails}),encoding='utf8')
    return ota_payments.build_ota_payment_events({'mail_directories':[tmp_path]})


def row(**changes):
    return card('rakuten-card',merchant='Rakuten Travel Singapore',approval_date='2026-05-01',
                amount_krw=124000,foreign_currency='KRW',foreign_amount='120000',**changes)


def test_confirmation_preserves_dates_and_discounted_quote_without_claiming_payment(tmp_path):
    e=load(tmp_path,[mail()])[0]
    assert e['provider']=='rakuten' and e['item']=='숙박비'
    assert e['service_period']=={'starts_on':'2026-08-14','ends_on':'2026-08-16'}
    assert e['reservation_on']=='2026-05-01' and e['card_last4']=='1234'
    assert e['reservation_amount']=={'currency':'KRW','amount':'120000'}
    assert e['paid_on'] is None and e['payment_event_id'] is None and e['amount_krw'] is None
    assert not ota_payments._event_is_paid(e)
    result=ota_payments.match_ota_payment_events([e],[row()])[0]
    assert result['status']=='RESERVATION_ONLY' and result['transaction_id'] is None


def test_native_quote_candidates_do_not_relax_krw_payment_amount_contract(tmp_path):
    e=load(tmp_path,[mail()])[0]
    trace=ota_payments.search_card_candidates(e,[row()])
    assert trace['status']=='CANDIDATES_FOUND'
    assert trace['candidates'][0]['payment_verified'] is False
    assert trace['candidates'][0]['resolution_allowed'] is False
    payment=dict(e,currency='KRW',amount='120000',amount_krw=120000,event_type='charge')
    assert ota_payments.compare_payment_amount(payment,row())['status']=='MISMATCH'


@pytest.mark.parametrize('changes',[{'source_trust':'sender_domain'},
    {'refund_status':'refund_requested'},{'evidence_changed':True}])
def test_changed_or_untrusted_evidence_cannot_supply_period_candidates(tmp_path,changes):
    e=load(tmp_path,[mail()])[0]
    assert ota_payments.search_card_candidates(dict(e,**changes),[row()])['candidates']==[]


def test_supplier_confirmation_number_is_not_an_additional_rakuten_booking_id(tmp_path):
    e=load(tmp_path,[mail(BODY.replace('예약 번호: 12345678901234','예약 번호: 99887766554433'))])[0]
    assert e['booking_ref']=='12345678901234'
    assert e['supplier_booking_refs']==['99887766554433']


@pytest.mark.parametrize('changes',[{'card_tail':'9999'},{'approval_date':'2026-05-02'},
    {'foreign_currency':'JPY'},{'foreign_amount':'120001'},{'merchant':'Rakuten Market'},
    {'ota_review_held':True},{'reservation_refund_blocked':True},{'duplicate_of':'other'},
    {'parse_error':'bad'},{'refund_status':'refund_requested'},{'transaction_direction':'cancellation'},
    {'conflict_reason':'conflict'},{'source_hash':''}])
def test_candidate_identity_date_amount_and_financial_guards(tmp_path,changes):
    e=load(tmp_path,[mail()])[0]
    assert ota_payments.search_card_candidates(e,[dict(row(),**changes)])['candidates']==[]


@pytest.mark.parametrize('change',['unsigned','spoof','no_booking_date','two_refs','two_totals','no_tail'])
def test_untrusted_or_ambiguous_confirmation_does_not_supply_card_candidate(tmp_path,change):
    m=mail()
    if change=='unsigned':m['payload']['headers'][-1]['value']='dkim=fail'
    elif change=='spoof':m=message(BODY,domain='travel.rakuten.com.example',subject='[라쿠텐 트래블] 예약 확정')
    elif change=='no_booking_date':m['payload']['body']['content']=BODY.replace('2026년05월01일(금)','')
    elif change=='two_refs':m['payload']['body']['content']+='\n예약 ID: 12345678901235'
    elif change=='two_totals':m['payload']['body']['content']+='\n금액 합계 ₩120,001'
    else:m['payload']['body']['content']=BODY.replace('**** **** **** 1234','신용카드')
    events=load(tmp_path,[m])
    assert not any(ota_payments.search_card_candidates(e,[row()])['candidates'] for e in events)


def test_cancellation_conflicting_period_and_search_limit_never_supply_dates(tmp_path):
    e=load(tmp_path,[mail(),mail(identity='cancel',subject='[라쿠텐 트래블] 예약 취소')])
    assert all(x['reservation_status']=='cancelled' for x in e)
    assert all(not ota_payments.search_card_candidates(x,[row()])['candidates'] for x in e)
    events=load(tmp_path,[mail(),mail(BODY.replace('2026년08월14일','2026년08월15일'),identity='changed')])
    assert all(e['service_period'] is None and e['service_period_conflict'] for e in events)
    clean=load(tmp_path,[mail()])[0]
    before=deepcopy(clean)
    trace=ota_payments.search_card_candidates(clean,[row(),dict(row(),transaction_id='other')],max_comparisons=1)
    assert trace['status']=='SEARCH_LIMIT_EXCEEDED' and trace['candidates']==[] and clean==before
