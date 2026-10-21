import json

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
