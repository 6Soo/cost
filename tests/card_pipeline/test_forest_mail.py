"""Synthetic notices only; no customer mail or tracking URLs."""
import json

import pytest

from app import forest_mail, mail_collect, ota_payments
from app.ota_reservation_groups import project_reservation_groups


def notice(identity='synthetic-forest', subject='숲나들e 예약완료 안내',
           sender='notice@foresttrip.go.kr'):
    return mail_collect.owner_record(identity, {
        'From': sender, 'Subject': subject, 'Date': 'Thu, 01 Oct 2026 10:00:00 +0900'},
        '고객님께서 신청하신 2026-10-05 합성휴양림 객실 예약완료. '
        '결제기한 2026-10-02. 결제가 완료되었습니다. 30,000원 '
        '<iframe src="https://example.invalid/WEOMTRACK.html?CPSQ=1234567"></iframe>')


def test_notices_enter_core_without_inventing_reservations_or_financial_events(tmp_path):
    messages = [notice(), notice('synthetic-cancel', '숲나들e 예약취소 안내')]
    (tmp_path / 'gmail-synthetic.json').write_text(
        json.dumps({'responses': messages}), encoding='utf-8')
    events = ota_payments.build_ota_payment_events({'mail_directories': [str(tmp_path)]})
    assert len(events) == 2
    assert all(e['provider'] == 'forest' and e['event_type'] == 'reservation' for e in events)
    assert all(e['booking_ref'] is None and e['service_period'] is None for e in events)
    assert all(e['amount'] is None and e['amount_krw'] is None and e['paid_on'] is None for e in events)
    assert all(not ota_payments._event_is_paid(e) for e in events)
    assert len({e['ota_event_id'] for e in events}) == 2
    grouped = project_reservation_groups(events)
    assert grouped['verified_group_count'] == 0 and grouped['singleton_fallback_count'] == 2
    results = ota_payments.match_ota_payment_events(events, [{
        'transaction_id': 'synthetic-card', 'merchant': '합성휴양림', 'amount_krw': 30000,
        'approval_date': '2026-10-01', 'transaction_direction': 'purchase'}])
    assert {r['status'] for r in results} == {'RESERVATION_ONLY'}
    assert all(r['transaction_id'] is None and not r.get('reserved_card_ids') for r in results)
    assert events == ota_payments.build_ota_payment_events({'mail_directories': [str(tmp_path)]})


@pytest.mark.parametrize('sender', ['notice@foresttrip.go.kr.example.invalid',
                                  'notice@notforest.go.kr', 'notice@example.invalid'])
def test_sender_domain_boundaries(sender):
    message = notice(sender=sender)
    assert forest_mail.collect({message['id']: message}) == []


def test_collected_cancellation_is_used_without_cancelling_another_observation():
    active = notice('active')
    cancel = notice('unverified-cancel', '숲나들e 예약취소 안내')
    cancel.pop('owner_collected', None)
    before = json.dumps([active, cancel], sort_keys=True)
    events = forest_mail.collect({m['id']: m for m in [active, cancel]})
    assert len(events) == 2
    assert events[0]['reservation_status'] == 'observed'
    cancelled = next(e for e in events if e['reservation_status'] == 'cancelled')
    assert cancelled['reported_reservation_status'] == 'cancelled'
    assert all(e['source_trust'] == 'collected_sender_domain' for e in events)
    assert all('발신 미검증' not in e['item'] for e in events)
    assert json.dumps([active, cancel], sort_keys=True) == before


def test_nonreservation_and_malformed_notices_are_ignored():
    unrelated = notice(subject='숲나들e 개인정보 이용 안내')
    malformed = {'payload': {'headers': [{'name': 'From', 'value': None}]}}
    assert forest_mail.collect({'one': unrelated, 'two': malformed, 'three': {}}) == []


def body_notice(body, **kwargs):
    message = notice(**kwargs)
    message['payload']['body'] = {'content': body}
    message.pop('owner_collected', None)  # Gmail full records need not carry this flag.
    return message


def test_extracts_provider_service_sentence_and_keeps_checkout_unknown():
    mail = body_notice('고객님께서 요청 하신 2026-10-05 합성자연휴양림 [산림동]가상실,4인실 객실이 예약되었습니다. '
                       '\n결제기한 2026년 10월 02일 23시까지\n'
                       '<iframe src="https://example.invalid/?예약번호=123456"></iframe>')
    original = json.dumps(mail, sort_keys=True)
    event, = forest_mail.collect({mail['id']: mail})
    assert event['hotel_name'] == '합성자연휴양림'
    assert event['room_name'] == '[산림동]가상실,4인실'
    assert event['service_period'] == {'starts_on': '2026-10-05', 'ends_on': None}
    assert event['service_period_semantics'] == 'start_only'
    assert event['booking_ref'] is None and event['paid_on'] is None
    assert event['amount_krw'] is None and not ota_payments._event_is_paid(event)
    assert 'DKIM 통과 기록 없음' in event['mail_authentication']
    assert json.dumps(mail, sort_keys=True) == original


def test_explicit_fields_are_read_without_granting_payment_authority():
    mail = body_notice('예약번호: SYN-1234\n결제금액: 30,000원\n'
                       '체크인: 2026-10-05\n체크아웃: 2026-10-07')
    event, = forest_mail.collect({mail['id']: mail})
    assert event['booking_ref'] == 'SYN-1234' and event['amount_krw'] == 30000
    assert event['service_period']['ends_on'] == '2026-10-07'
    result, = ota_payments.match_ota_payment_events([event], [])
    assert result['status'] == 'RESERVATION_ONLY' and result['transaction_id'] is None


def test_conflicting_body_facts_block_candidates_and_never_merge_observations():
    mail = body_notice('2026-10-05 합성자연휴양림 가상실 객실 예약완료\n'
                       '2026-10-06 합성자연휴양림 다른실 객실 예약완료\n'
                       '결제금액: 30,000원\n결제금액: 40,000원')
    event, = forest_mail.collect({mail['id']: mail})
    assert event['service_period_conflict'] and event['amount_krw'] is None
    result, = ota_payments.match_ota_payment_events([event], [])
    assert result['status'] == 'HOLD_EVIDENCE_CONFLICT'
    assert forest_mail.search_candidates(event, [])['candidates'] == []


def test_facility_date_candidates_preserve_amount_uncertainty_and_financial_holds():
    mail = body_notice('2026-10-05 합성자연휴양림 가상실 객실 예약완료\n결제금액: 30,000원')
    event, = forest_mail.collect({mail['id']: mail})
    card = {'transaction_id': 'synthetic-card', 'merchant': '합성자연휴양림',
            'approval_date': '2026-10-01', 'amount_krw': 30000, 'transaction_direction': 'purchase'}
    trace = ota_payments.search_card_candidates(event, [card])
    assert trace['candidates'][0]['amount_status'] == 'MATCH'
    assert trace['candidates'][0]['resolution_allowed'] is False
    assert ota_payments.search_card_candidates(event, [card], existing_links={event['ota_event_id']: 'pin'})['status'] == 'USER_PINNED'
    mismatch = ota_payments.search_card_candidates(event, [dict(card, amount_krw=40000)])
    assert mismatch['candidates'][0]['amount_status'] == 'MISMATCH'
    for change in ({'duplicate_of': 'original'}, {'ota_review_held': True}, {'parse_error': 'invalid'},
                   {'refund_status': 'refunded'}, {'transaction_direction': 'refund'},
                   {'foreign_currency': 'JPY'}, {'merchant': '다른자연휴양림'},
                   {'approval_date': '2025-01-01'}):
        assert ota_payments.search_card_candidates(event, [dict(card, **change)])['candidates'] == []
    event['reservation_status'] = 'cancelled'
    assert ota_payments.search_card_candidates(event, [card])['candidates'] == []


def test_municipal_merchant_is_only_a_low_confidence_candidate_from_explicit_address():
    mail = body_notice('2026-10-05 합성자연휴양림 가상실 객실 예약완료\n충북 가상군 산림로 1')
    event, = forest_mail.collect({mail['id']: mail})
    card = {'transaction_id': 'municipal-card', 'merchant': '가상군청',
            'approval_date': '2026-10-01', 'amount_krw': 30000, 'transaction_direction': 'purchase'}
    trace = ota_payments.search_card_candidates(event, [card])
    candidate, = trace['candidates']
    assert candidate['branch_status'] == 'UNKNOWN' and candidate['confidence'] == 'LOW'
    assert candidate['basis'] == 'FOREST_MUNICIPALITY_AND_OBSERVED_DATE'
    assert not candidate['resolution_allowed']
    assert ota_payments.search_card_candidates(event, [dict(card, merchant='다른군청')])['candidates'] == []
    event.pop('operator_region')
    assert ota_payments.search_card_candidates(event, [card])['candidates'] == []


def test_common_forest_merchant_keeps_unknown_facility_and_never_confirms_payment():
    mail = body_notice('2026-10-05 합성자연휴양림 가상실 객실 예약완료')
    event, = forest_mail.collect({mail['id']: mail})
    card = {'transaction_id': 'common-forest-card', 'merchant': '국립자연휴양림',
            'approval_date': '2026-10-01', 'amount_krw': 30000, 'transaction_direction': 'purchase'}
    candidate, = ota_payments.search_card_candidates(event, [card])['candidates']
    assert candidate['basis'] == 'FOREST_PROVIDER_AND_OBSERVED_DATE'
    assert candidate['branch_status'] == 'UNKNOWN' and candidate['confidence'] == 'LOW'
    assert candidate['amount_status'] == 'UNKNOWN' and not candidate['resolution_allowed']
    generic, = ota_payments.search_card_candidates(event, [dict(card, merchant='휴양시설 결제')])['candidates']
    assert generic['branch_status'] == 'UNKNOWN' and not generic['resolution_allowed']
    assert ota_payments.search_card_candidates(event, [dict(card, reservation_refund_blocked=True)])['candidates'] == []
    assert ota_payments.search_card_candidates(event, [dict(card, merchant='산림조합')])['candidates'] == []


def test_explicit_subject_room_is_used_when_body_does_not_state_a_service_date():
    mail = body_notice('결제기한 2026년 10월 02일', subject='합성자연휴양림 가상실 예약신청 후 결제 안내')
    event, = forest_mail.collect({mail['id']: mail})
    assert event['hotel_name'] == '합성자연휴양림' and event['room_name'] == '가상실'
    assert event['service_period'] is None
