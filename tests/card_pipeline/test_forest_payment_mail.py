"""Synthetic signed domestic PG receipts and the existing global card matcher."""
from copy import deepcopy
import json
import pytest
from app import forest_payment_mail, ota_payments
from tests.card_pipeline.test_booking_mail import message


BODY = ('결제수단\n신용카드 (국민)\n상점명\n합성자연휴양림\n상품명\n합성 숙박\n'
        '주문번호\nSYNTHETIC12345\n결제일시\n2026-10-01 10:00:00\n'
        '승인번호\n12345678\n결제금액\n30,000 원 (KRW)')


def receipt(body=BODY):
    return message(body, identity='synthetic-pg-receipt', domain='nicepg.co.kr',
                   subject='합성자연휴양림에서 결제하신 내역입니다', sent='2026-10-01')


def card(**changes):
    return dict({'transaction_id': 'card-original', 'source_hash': 'source-original',
        'issuer': '국민', 'card_tail': '1234', 'merchant': '휴양시설 결제',
        'approval_date': '2026-10-01', 'approval_number': '12345678',
        'amount_krw': 30000, 'transaction_direction': 'purchase'}, **changes)


def test_receipt_matches_only_original_card_approval_date_and_amount_without_inventing_booking(tmp_path):
    mail = receipt()
    before = deepcopy(mail)
    (tmp_path / 'gmail-test.json').write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    event, = ota_payments.build_ota_payment_events({'mail_directories': [tmp_path]})
    assert event['booking_ref'] is None and event['service_period'] is None and event['card_last4'] is None
    assert event['amount_krw'] == 30000 and event['paid_on_semantics'] == 'explicit_charge_date'
    result, = ota_payments.match_ota_payment_events([event], [card()])
    assert result['status'] == 'MATCHED_AUTO' and result['transaction_id'] == 'card-original'
    assert mail == before
    assert len(ota_payments.match_ota_payment_events([event], [card()])) == 1


@pytest.mark.parametrize('change', [
    {'approval_number': '99999999'}, {'approval_date': '2026-09-01'}, {'amount_krw': 40000},
    {'issuer': '하나'}, {'card_tail': ''}, {'duplicate_of': 'original'},
    {'parse_error': 'invalid'}, {'conflict_reason': 'invalid'}, {'transaction_direction': 'cancellation'},
])
def test_different_or_invalid_card_never_matches_receipt(change):
    mail = receipt()
    event, = forest_payment_mail.collect({mail['id']: mail})
    result, = ota_payments.match_ota_payment_events([event], [card(**change)])
    assert result['status'] != 'MATCHED_AUTO' and result['transaction_id'] is None


def test_duplicate_candidate_or_existing_owner_cannot_be_overridden():
    mail = receipt()
    event, = forest_payment_mail.collect({mail['id']: mail})
    result, = ota_payments.match_ota_payment_events([event], [card(), card(transaction_id='competing-card')])
    assert result['transaction_id'] is None
    result = ota_payments.match_ota_payment_events([event], [card()], existing_links={'manual-other': 'card-original'})
    assert all(r.get('transaction_id') != 'card-original' for r in result)


@pytest.mark.parametrize('body', [
    BODY.replace('신용카드 (국민)', '계좌이체'), BODY.replace('30,000 원 (KRW)', '30,000 JPY'),
    BODY.replace('30,000 원 (KRW)', '0 원 (KRW)'), BODY.replace('12345678', ''),
    BODY + '\n결제금액\n40,000 원 (KRW)', BODY.replace('합성자연휴양림', '합성상점'),
    BODY.replace('2026-10-01 10:00:00', '2026-99-01 10:00:00'),
])
def test_noncard_ambiguous_or_nonforest_receipt_is_not_a_payment_event(body):
    mail = receipt(body)
    assert forest_payment_mail.collect({mail['id']: mail}) == []


def test_untrusted_receipt_is_ignored_and_cancelled_receipt_cannot_create_a_paid_charge():
    mail = receipt()
    mail['payload']['headers'][-1]['value'] = 'dkim=fail header.i=@nicepg.co.kr'
    assert forest_payment_mail.collect({mail['id']: mail}) == []
    mail = receipt()
    next(h for h in mail['payload']['headers'] if h['name'].lower() == 'subject')['value'] = '결제취소 안내'
    event, = forest_payment_mail.collect({mail['id']: mail})
    assert event['event_type'] == 'cancellation_notice'
    assert not ota_payments._event_is_paid(event) and event['reservation_status'] == 'unknown'
    assert event['paid_on'] is None and event['cancelled_on'] is None
    assert event['cancellation_notice_sent_on'] == '2026-10-01'


def test_cancellation_uses_only_explicit_cancel_date_and_does_not_guess_ambiguous_amount():
    mail = receipt(BODY + '\n결제금액\n20,000 원\n취소일시: 2026-10-02 11:00:00')
    next(h for h in mail['payload']['headers'] if h['name'].lower() == 'subject')['value'] = '결제취소 안내'
    event, = forest_payment_mail.collect({mail['id']: mail})
    assert event['cancelled_on'] == '2026-10-02'
    assert event['paid_on'] is None and event['amount'] is None
    assert event['reservation_status'] == 'unknown'
    result, = ota_payments.match_ota_payment_events([event], [card()])
    assert result['status'] == 'NOT_CARD_CHARGE' and result['transaction_id'] is None


@pytest.mark.parametrize('merchant', ['합성산림치유원', '합성 산림 치유원'])
def test_healing_center_receipt_reads_payment_amount_instead_of_zero_safety_fee(merchant):
    body = BODY.replace('합성자연휴양림', merchant).replace(
        '결제금액\n30,000', '안심결제 수수료\n0 원\n결제금액\n30,000')
    mail = receipt(body)
    original = deepcopy(mail)
    event, = forest_payment_mail.collect({mail['id']: mail})
    assert event['amount_krw'] == 30000
    assert event['service_period'] is None and event['booking_ref'] is None
    assert ota_payments.match_ota_payment_events([event], [card()])[0]['status'] == 'MATCHED_AUTO'
    assert mail == original


def test_nice_cancellation_amount_and_request_time_preserve_original_payment_identity():
    charge = receipt(BODY.replace('합성자연휴양림', '합성산림치유원'))
    body = BODY.replace('합성자연휴양림', '합성산림치유원').replace(
        '결제금액', '취소금액') + '\n취소요청일시\n2026-10-02 11:00:00'
    cancellation = receipt(body)
    next(h for h in cancellation['payload']['headers'] if h['name'].lower() == 'subject')['value'] = '결제취소 안내'
    paid, = forest_payment_mail.collect({charge['id']: charge})
    cancelled, = forest_payment_mail.collect({cancellation['id']: cancellation})
    assert cancelled['payment_id'] == paid['payment_id']
    assert cancelled['amount_krw'] == 30000 and cancelled['cancelled_on'] == '2026-10-02'
    assert cancelled['paid_on'] is None and cancelled['reservation_status'] == 'unknown'
    assert cancelled['event_type'] == 'cancellation_notice'
    assert not ota_payments._event_is_paid(cancelled)
    assert ota_payments.match_ota_payment_events([cancelled], [card()])[0]['status'] == 'NOT_CARD_CHARGE'


def test_partial_cancel_uses_cancellation_amount_and_conflicting_dates_stay_unknown():
    body = BODY + '\n취소금액\n10,000 원\n취소요청일시\n2026-10-02 11:00:00\n취소일시\n2026-10-03 11:00:00'
    mail = receipt(body)
    next(h for h in mail['payload']['headers'] if h['name'].lower() == 'subject')['value'] = '결제취소 안내'
    event, = forest_payment_mail.collect({mail['id']: mail})
    assert event['amount_krw'] == 10000 and event['cancelled_on'] is None
    assert event['refund_status'] == 'none_displayed' and event['reservation_status'] == 'unknown'
    assert not ota_payments._event_is_paid(event)
