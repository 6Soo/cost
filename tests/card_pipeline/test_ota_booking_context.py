import json

import pytest

from app.ota_payments import build_ota_payment_events, match_ota_payment_events
from tests.card_pipeline.test_booking_mail import message
from tests.card_pipeline.test_ota_payments import card


def load(tmp_path, messages):
    (tmp_path / 'gmail-context.json').write_text(json.dumps({'responses': messages}), encoding='utf-8')
    return build_ota_payment_events({'mail_directories': [tmp_path]})


def receipt(ref='1234567890', domain='booking.com'):
    return message('예약 번호: ' + ref + '\n결제 완료 JPY 52,560',
                   subject='결제가 완료되었습니다', identity='paid', domain=domain)


def confirmation(start='2026-08-14', identity='confirmation'):
    return message('예약 번호: 1234567890\n체크인: ' + start + '\n체크아웃: 2026-08-16',
                   subject='예약 확정 안내', identity=identity, domain='booking.com', sent='2026-02-22')


def test_signed_confirmation_enriches_payment_period_without_changing_payment_identity(tmp_path):
    original = next(e for e in load(tmp_path, [receipt()]) if e['event_type'] == 'charge')
    joined = next(e for e in load(tmp_path, [receipt(), confirmation()]) if e['event_type'] == 'charge')
    assert joined['service_period'] == {'starts_on': '2026-08-14', 'ends_on': '2026-08-16'}
    for key in ('ota_event_id', 'paid_on', 'amount', 'currency', 'source_ids', 'source_digests'):
        assert joined[key] == original[key]
    assert joined['source_digest'] != original['source_digest']
    assert joined['booking_context_source_ids'] == ['mail:confirmation']


def test_conflicting_or_unsigned_period_never_becomes_an_authoritative_stay(tmp_path):
    bad = confirmation()
    bad['payload']['headers'][-1]['value'] = 'dkim=fail'
    paid = next(e for e in load(tmp_path, [receipt(), bad]) if e['event_type'] == 'charge')
    assert not paid['service_period']
    paid = next(e for e in load(tmp_path, [receipt(), confirmation(), confirmation('2026-08-15', 'other')])
                if e['event_type'] == 'charge')
    assert paid['service_period'] is None
    assert paid['service_period_conflict'] is True
    assert len(paid['service_period_candidates']) == 2


def test_trip_cancellation_and_changed_total_preserve_charge_and_refund_request(tmp_path):
    ref = '1111222233334444'
    paid = message('예약 번호: ' + ref + '\n총 금액 온라인 사전 결제 123,000원\n하나카드(신용카드)',
                   subject='결제 완료 안내', identity='charge')
    cancelled = message('예약 번호: ' + ref + '\n환불을 요청했습니다',
                        subject='예약 취소가 완료되었습니다', identity='cancel')
    updated = message('예약 번호: ' + ref + '\n총 금액 온라인 사전 결제 167,572원',
                      subject='예약 업데이트 안내', identity='update')
    events = load(tmp_path, [paid, cancelled, updated])
    charge = next(e for e in events if e['source_ids'] == ['mail:charge'])
    assert charge['reservation_status'] == 'cancelled'
    assert charge['refund_status'] == 'refund_pending'
    assert charge['amount_krw'] == 123000
    assert charge['event_type'] == 'charge'
    assert charge['card_issuer'] == '하나'
    assert charge['booking_changes'][0]['booking_totals_krw'] == [167572]
    assert not any(e['event_type'] == 'refund' for e in events)
    assert sum(e['payment_status'] == 'paid' for e in events) == 1


def test_explicit_issuer_stops_other_issuer_from_being_called_an_amount_mismatch(tmp_path):
    paid = message('예약 번호: 1111222233334444\n총 금액 온라인 사전 결제 90,121원\n하나카드(신용카드)',
                   subject='결제 완료 안내')
    event = next(e for e in load(tmp_path, [paid]) if e['event_type'] == 'charge')
    row = card(issuer='국민', approval_date=event['paid_on'], amount_krw=120000)
    result = match_ota_payment_events([event], [row])[0]
    assert result['status'] == 'HOLD_NO_CARD'
    assert result['reason'] == 'no_exact_amount_date_direction_card'


def test_parser_version_invalidates_saved_snapshot_and_context_survives_public_projection(monkeypatch):
    from types import SimpleNamespace
    from app import ota_sources
    from webapp import ota_payment_review
    monkeypatch.setattr(ota_sources, 'source_stamps', lambda _sources: {})
    monkeypatch.setattr(ota_payment_review, '_guide_input_digest', lambda _board: 'synthetic')
    backend = SimpleNamespace(board=None, store=SimpleNamespace(), sources={}, _transactions=lambda: [],
                              payments=SimpleNamespace(PARSER_VERSION=1))
    old = ota_payment_review.input_key_for(backend)
    backend.payments.PARSER_VERSION = 2
    assert old != ota_payment_review.input_key_for(backend)
    event = {'ota_event_id': 'synthetic', 'card_issuer': '하나', 'service_period_conflict': True,
             'booking_changes': [{'booking_totals_krw': [167572]}], 'payment_source_digest': 'private'}
    projected = ota_payment_review.public_snapshot({'events': [event]})['events'][0]
    assert projected['card_issuer'] == '하나'
    assert projected['service_period_conflict'] is True
    assert projected['booking_changes'][0]['booking_totals_krw'] == [167572]
    assert 'payment_source_digest' not in projected


def test_refund_instructions_are_not_an_actual_refund_request(tmp_path):
    paid = message('예약 번호: 1111222233334444\n총 금액 온라인 사전 결제 90,121원\n'
                   '환불을 요청하려면 고객센터에 연락하세요', subject='결제 완료 안내')
    event = next(e for e in load(tmp_path, [paid]) if e['event_type'] == 'charge')
    assert event.get('refund_status') != 'refund_pending'


def preauthorization():
    return message('예약 번호: 1111222233334444\n체크인: 2026-11-07\n체크아웃: 2026-11-08\n'
                   '총 금액\n사전 승인\n230,106원', subject='예약 확정 안내', identity='preauth')


def test_trip_preauthorization_retains_booking_without_claiming_payment(tmp_path):
    from app.ota_payments import search_card_candidates, _event_is_paid
    from app.ota_mail import extract_mail
    fact = extract_mail(preauthorization())
    assert fact['paid_amount_krw'] is None
    event = load(tmp_path, [preauthorization()])[0]
    assert event['event_type'] == 'reservation'
    assert event['evidence_status'] == event['payment_status'] == 'preauthorized'
    assert event['preauthorized_amount_krw'] == event['amount'] == 230106
    assert event['preauthorized_on'] == '2026-05-01' and event['paid_on'] is None
    assert event['service_period'] == {'starts_on': '2026-11-07', 'ends_on': '2026-11-08'}
    assert event['payment_event_id'] is None and not _event_is_paid(event)
    rows = [card('one', amount_krw=230106, approval_date='2026-05-01')]
    trace = search_card_candidates(event, rows)
    assert trace['candidates'][0]['transaction_id'] == 'one'
    assert trace['candidates'][0]['payment_verified'] is False
    assert trace['candidates'][0]['resolution_allowed'] is False
    result = match_ota_payment_events([event], rows)[0]
    assert result['status'] == 'RESERVATION_ONLY' and result['transaction_id'] is None


def test_preauthorization_candidates_preserve_card_protections_and_exact_date(tmp_path):
    from app.ota_payments import search_card_candidates
    event = load(tmp_path, [preauthorization()])[0]
    base = card(amount_krw=230106, approval_date='2026-05-01')
    changes = [{'duplicate_of':'original'}, {'parse_error':'bad'}, {'conflict_reason':'hold'},
               {'approval_date':'2026-05-02'}, {'amount_krw':230107}, {'ota_review_held':True},
               {'merchant':'AGODA','merchant_normalized':'agoda'}, {'transaction_direction':'refund'}]
    rows = [dict(base, **changeset, transaction_id='bad-'+str(i)) for i,changeset in enumerate(changes)]
    rows += [dict(base, transaction_id='occupied'), dict(base, transaction_id='free')]
    trace = search_card_candidates(event, rows, existing_links={'other':{'transaction_id':'occupied'}})
    assert [c['transaction_id'] for c in trace['candidates']] == ['free']
    assert search_card_candidates(event, rows, max_comparisons=1)['status'] == 'SEARCH_LIMIT_EXCEEDED'
    assert search_card_candidates(dict(event, card_last4='9999'), rows)['candidates'] == []


def test_cancelled_trip_with_invalid_received_date_retains_cancellation_and_refund_request(tmp_path):
    cancellation = message('예약 번호: 1111222233334444\n환불을 요청했습니다 230,106원',
                           subject='예약 취소가 완료되었습니다', identity='cancel')
    cancellation['internal_date'] = '0'
    events = load(tmp_path, [preauthorization(), cancellation])
    assert len(events) == 2
    assert all(e['reservation_status'] == 'cancelled' and e['refund_status'] == 'refund_pending' for e in events)
    assert all(e['payment_status'] != 'paid' and e['event_type'] != 'refund' for e in events)
    assert next(e for e in events if e['source_ids'] == ['mail:cancel'])['paid_on'] is None


def test_lodging_without_online_payment_or_unambiguous_preauthorization_stays_unpaid(tmp_path):
    mail = preauthorization()
    mail['payload']['body']['content'] += '\n사전 승인 230,107원'
    event = load(tmp_path, [mail])[0]
    assert event['preauthorized_amount_krw'] is None and event['amount'] is None
    assert event['payment_status'] != 'paid'
    mail['payload']['headers'][-1]['value'] = 'dkim=fail'
    assert load(tmp_path, [mail]) == []


def test_flight_confirmation_enriches_existing_payment_without_changing_its_amount(tmp_path):
    paid = message('예약번호: 1234567890123456\n총 금액 145,000원\n운임',
                   subject='[트립닷컴] 결제 완료 안내', identity='flight-paid')
    confirmed = message('예약번호: 1234567890123456\n가는편: 합성노선 | 2026년 6월 4일\n'
                        '오는편: 합성노선 | 2026년 6월 8일',
                        subject='[트립닷컴] 항공권 예약 확정 안내', identity='flight-confirmation')
    original = next(e for e in load(tmp_path, [paid]) if e['event_type'] == 'charge')
    joined = next(e for e in load(tmp_path, [paid, confirmed]) if e['source_ids'] == ['mail:flight-paid'])
    assert joined['service_period'] == {'starts_on': '2026-06-04', 'ends_on': '2026-06-08'}
    assert joined['item'] == '항공료'
    for key in ('amount_krw', 'paid_on', 'source_ids', 'ota_event_id'):
        assert joined[key] == original[key]


def flight_refund(subject='환불 완료: 합성출발 - 합성도착'):
    return message('예약번호: 1234567890123456\n취소 요청이 처리되어 환불이 완료되었습니다.\n'
                   '환불 금액: 41,234원\n항공편 정보\n'
                   '합성출발 - 합성도착 | 2026년 6월 4일\n합성도착 - 합성출발 | 2026년 6월 8일\n'
                   '탑승객 정보', subject=subject, identity='flight-refund', sent='2026-06-04')


def test_completed_flight_refund_preserves_actual_amount_and_itinerary(tmp_path):
    refund = next(e for e in load(tmp_path, [flight_refund()]) if e['event_type'] == 'refund')
    assert refund['amount_krw'] == 41234
    assert refund['evidence_status'] == 'refund_verified'
    assert refund['refund_status'] == 'refunded'
    assert refund['paid_on'] == '2026-06-04'
    assert refund['item'] == '항공료'
    assert refund['service_period'] == {'starts_on': '2026-06-04', 'ends_on': '2026-06-08'}


@pytest.mark.parametrize('change', ['unsigned', 'requested', 'ambiguous_amount'])
def test_flight_refund_requires_completed_authenticated_unique_amount(tmp_path, change):
    mail = flight_refund()
    if change == 'unsigned':
        mail['payload']['headers'][-1]['value'] = 'dkim=fail'
    elif change == 'requested':
        mail = flight_refund('항공권 취소 요청 접수')
        mail['payload']['body']['content'] = mail['payload']['body']['content'].replace(
            '취소 요청이 처리되어 환불이 완료되었습니다.', '환불을 요청했습니다.')
    else:
        mail['payload']['body']['content'] += '\n환불 금액: 41,235원'
    assert not any(e['event_type'] == 'refund' for e in load(tmp_path, [mail]))


@pytest.mark.parametrize('change', ['extra_leg', 'reversed', 'invalid', 'not_reciprocal'])
def test_refund_does_not_guess_invalid_or_ambiguous_flight_dates(tmp_path, change):
    mail = flight_refund()
    body = mail['payload']['body']['content']
    if change == 'extra_leg':
        body = body.replace('탑승객 정보', '합성다른출발 - 합성다른도착 | 2026년 6월 9일\n탑승객 정보')
    elif change == 'reversed':
        body = body.replace('2026년 6월 8일', '2026년 6월 3일')
    elif change == 'invalid':
        body = body.replace('2026년 6월 8일', '2026년 6월 31일')
    else:
        body = body.replace('합성도착 - 합성출발 |', '합성도착 - 합성다른도착 |')
    mail['payload']['body']['content'] = body
    refund = next(e for e in load(tmp_path, [mail]) if e['event_type'] == 'refund')
    assert refund['amount_krw'] == 41234 and refund['service_period'] is None


def test_refund_and_confirmation_read_format_characters_in_booking_number(tmp_path):
    mail = flight_refund()
    mail['payload']['body']['content'] = mail['payload']['body']['content'].replace(
        '1234567890123456', '1234\u200c5678\u200c90123456')
    refund = next(e for e in load(tmp_path, [mail]) if e['event_type'] == 'refund')
    assert refund['booking_ref'] == '1234567890123456'


def test_conflicting_flight_confirmations_do_not_choose_one_itinerary(tmp_path):
    paid = message('예약번호: 1234567890123456\n총 금액 145,000원\n운임',
                   subject='결제 완료 안내', identity='flight-paid')
    confirmations = [message('예약번호: 1234\u200c567890123456\n가는편: 합성노선 | 2026년 6월 '
                             + day + '일\n오는편: 합성노선 | 2026년 6월 8일',
                             subject='항공권 예약 확정 안내', identity='flight-'+day)
                     for day in ['4', '5']]
    event = next(e for e in load(tmp_path, [paid, *confirmations])
                 if e['source_ids'] == ['mail:flight-paid'])
    assert event['service_period'] is None and event['service_period_conflict']
    assert event['amount_krw'] == 145000


def test_completed_refund_retains_explicit_reservation_cancellation(tmp_path):
    refund = next(e for e in load(tmp_path, [flight_refund('예약 취소 완료 · 환불 완료')])
                  if e['event_type'] == 'refund')
    assert refund['reservation_status'] == 'cancelled'
    assert refund['evidence_status'] == 'refund_verified' and refund['amount_krw'] == 41234


@pytest.mark.parametrize('wording', ['환불 처리 중입니다.', '환불 처리 예정입니다.',
    '환불 처리 대기 중입니다.', '환불 완료 예정입니다.', '환불이 완료되지 않았습니다.',
    '환불이 완료될 예정입니다.', '환불 완료 요청입니다.', '환불 완료 전입니다.',
    '환불 완료가 아닙니다.', '환불 완료 시 알려드립니다.', '환불 완료\n예정입니다.'])
def test_pending_or_negated_refund_never_becomes_completed_payment(tmp_path, wording):
    from app.ota_payments import _extract_signed_payment_message
    mail = flight_refund('예약 취소 완료 · 환불 안내')
    mail['payload']['body']['content'] = mail['payload']['body']['content'].replace(
        '취소 요청이 처리되어 환불이 완료되었습니다.', wording)
    direct = _extract_signed_payment_message(mail)
    assert direct is None or direct['evidence_status'] != 'refund_verified'
    events = load(tmp_path, [mail])
    assert not any(e['event_type'] == 'refund' or e.get('refund_status') == 'refunded' for e in events)
    assert not any(e['payment_status'] == 'paid' for e in events)


def test_explicit_refund_processing_completed_is_still_a_completed_refund(tmp_path):
    mail = flight_refund('예약 취소 완료 · 환불 안내')
    mail['payload']['body']['content'] = mail['payload']['body']['content'].replace(
        '취소 요청이 처리되어 환불이 완료되었습니다.', '환불 처리 완료')
    event = next(e for e in load(tmp_path, [mail]) if e['event_type'] == 'refund')
    assert event['evidence_status'] == 'refund_verified' and event['amount_krw'] == 41234
