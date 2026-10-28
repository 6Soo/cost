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


def test_unverified_cancellation_never_cancels_another_observation():
    active = notice('active')
    cancel = notice('unverified-cancel', '숲나들e 예약취소 안내')
    cancel.pop('owner_collected', None)
    before = json.dumps([active, cancel], sort_keys=True)
    events = forest_mail.collect({m['id']: m for m in [active, cancel]})
    assert len(events) == 2
    assert {e['reservation_status'] for e in events} == {'observed'}
    untrusted = next(e for e in events if e['source_trust'] == 'unverified_sender')
    assert untrusted['reported_reservation_status'] == 'cancelled'
    assert '발신 미검증' in untrusted['item']
    assert json.dumps([active, cancel], sort_keys=True) == before


def test_nonreservation_and_malformed_notices_are_ignored():
    unrelated = notice(subject='숲나들e 개인정보 이용 안내')
    malformed = {'payload': {'headers': [{'name': 'From', 'value': None}]}}
    assert forest_mail.collect({'one': unrelated, 'two': malformed, 'three': {}}) == []
