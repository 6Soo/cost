"""Agoda booking-detail API records as portal evidence. Synthetic records only."""
import copy

import pytest

from app import ota_payments
from app.agoda_api_capture import parse_api_detail
from app.ota_store import OtaStore


def record(**changes):
    detail = {
        'BookingDetails': {
            'BookingQueryData': {'CancellationReasonData': {'BookingID': 1234567890}},
            'Dates': {'CheckInDateNonCulture': '2026-10-26', 'CheckOutDateNonCulture': '2026-10-28'},
            'BookingStatus': {'Phase': 'Completed', 'DisplayText': '투숙 완료'},
            'PaymentMethod': {'CreditCard': {'CardNumber': 'xxxx-xxxx-xxxx-1234'}},
            'PaymentDetails': {
                'PaymentModel': 'pay-agoda',
                'NonCancelledPaymentDetails': {'Payments': [
                    {'Description': 'Credit card', 'Amount': {'Currency': 'KRW', 'AmountAsDouble': 225818}}]},
                'CancelledPaymentDetails': None,
            },
            'BookingDate': '2026-10-19T19:36:00.000+07:00',
        }}
    value = {'observed_at': '2026-11-10T03:00:00+00:00',
             'list': {'bookingId': 1234567890, 'productTypeName': 'Hotel'}, 'detail': detail}
    for path, new in changes.items():
        node = value
        keys = path.split('.')
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = new
    return value


def test_a_charged_booking_reads_as_a_verified_paid_portal_fact():
    fact = parse_api_detail(record())
    assert fact['evidence_format'] == 'agoda-api-v1'
    assert (fact['booking_number'], fact['service_start_on'], fact['service_end_on']) == ('1234567890', '2026-10-26', '2026-10-28')
    assert (fact['reservation_status'], fact['payment_status'], fact['card_last4']) == ('completed', 'paid', '1234')
    assert [(p['kind'], p['currency'], p['decimal_text']) for p in fact['price_components']] == [('paid_today', 'KRW', '225818')]
    assert fact['paid_on'] is None and set(fact['roles']) == {
        'identity', 'service_period', 'portal_payment_claim', 'portal_card_observation', 'lifecycle'}


@pytest.mark.parametrize('changes,status,payment,refund', [
    ({'detail.BookingDetails.PaymentDetails.PaymentModel': 'pay-hotel'}, 'completed', 'pay_at_property', 'none_displayed'),
    ({'detail.BookingDetails.BookingStatus': {'Phase': 'Upcoming', 'DisplayText': '자동 결제 예정일: 2026년 11월 18일'}},
     'confirmed', 'scheduled', 'none_displayed'),
    ({'detail.BookingDetails.PaymentDetails.NonCancelledPaymentDetails.Payments': [
        {'Description': 'Credit card', 'Amount': {'Currency': 'JPY', 'AmountAsDouble': 127762}},
        {'Description': 'Credit card', 'Amount': {'Currency': 'JPY', 'AmountAsDouble': -17345}}]},
     'completed', 'unknown', 'refund_pending'),
])
def test_property_payment_schedule_and_adjustment_are_not_a_charge(changes, status, payment, refund):
    fact = parse_api_detail(record(**changes))
    assert (fact['reservation_status'], fact['payment_status'], fact['refund_status']) == (status, payment, refund)
    assert not [p for p in fact['price_components'] if p['kind'] == 'paid_today' and payment != 'unknown']


def test_a_cancelled_booking_keeps_its_charge_and_holds_any_refund():
    cancelled = {'Phase': 'Cancelled', 'DisplayText': '예약 취소일: 2026년 8월 2일'}
    fee_only = parse_api_detail(record(**{
        'detail.BookingDetails.BookingStatus': cancelled,
        'detail.BookingDetails.PaymentDetails.CancelledPaymentDetails': {
            'TotalAmountCharged': {'Currency': 'KRW', 'AmountAsDouble': 170016},
            'CancellationFee': {'Currency': 'KRW', 'AmountAsDouble': 170016},
            'YourRefund': {'Currency': 'KRW', 'AmountAsDouble': 0}}}))
    assert (fee_only['reservation_status'], fee_only['payment_status'], fee_only['refund_status']) == (
        'cancelled', 'paid', 'none_displayed')
    refunded = parse_api_detail(record(**{
        'detail.BookingDetails.BookingStatus': cancelled,
        'detail.BookingDetails.PaymentDetails.CancelledPaymentDetails': {
            'TotalAmountCharged': {'Currency': 'JPY', 'AmountAsDouble': 7624},
            'YourRefund': {'Currency': 'JPY', 'AmountAsDouble': 7624}}}))
    assert (refunded['payment_status'], refunded['refund_status']) == ('unknown', 'refund_pending')


def test_a_response_for_another_booking_is_refused():
    with pytest.raises(ValueError, match='AGODA_API_BOOKING_IDENTITY_MISMATCH'):
        parse_api_detail(record(**{'detail.BookingDetails.BookingQueryData.CancellationReasonData.BookingID': 999}))


def test_an_imported_api_fact_becomes_one_undated_verified_portal_charge(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        raw = record()
        fact = parse_api_detail(raw)
        assert store.import_direct(provider='agoda', account_key='aside-u0', source_key='agoda-api:1234567890',
                                   snapshot=copy.deepcopy(raw), facts=[fact])
        events = ota_payments._portal_events([store.path])
        assert len(events) == 1
        event = events[0]
        assert (event['amount'], event['currency'], event['card_last4'], event['paid_on']) == ('225818', 'KRW', '1234', None)
        assert event['service_period'] == {'starts_on': '2026-10-26', 'ends_on': '2026-10-28'}
        assert event['verified_portal_snapshot'] is True and event['item'] == '숙박비'
        # The same observation again changes nothing.
        assert not store.import_direct(provider='agoda', account_key='aside-u0', source_key='agoda-api:1234567890',
                                       snapshot=copy.deepcopy(raw), facts=[fact])
        assert len(ota_payments._portal_events([store.path])) == 1
    finally:
        store.close()


def test_a_scheduled_api_observation_creates_no_charge(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        raw = record(**{'detail.BookingDetails.BookingStatus': {'Phase': 'Upcoming', 'DisplayText': '자동 결제 예정일'}})
        store.import_direct(provider='agoda', account_key='aside-u0', source_key='agoda-api:1234567890',
                            snapshot=raw, facts=[parse_api_detail(raw)])
        assert ota_payments._portal_events([store.path]) == []
    finally:
        store.close()


def test_the_import_tool_writes_nothing_when_any_record_is_unreadable(tmp_path):
    import json
    from tools import import_agoda_api_details as tool
    folder = tmp_path / 'details'
    folder.mkdir()
    (folder / '1.json').write_text(json.dumps(record()), encoding='utf-8')
    broken = record(**{'detail.BookingDetails.BookingQueryData.CancellationReasonData.BookingID': 999})
    (folder / '2.json').write_text(json.dumps(broken), encoding='utf-8')
    store = tmp_path / 'store.sqlite'
    assert tool.main(['--directory', str(folder), '--store', str(store), '--apply']) == 1
    assert not store.exists() or ota_payments._portal_events([store]) == []
    (folder / '2.json').unlink()
    assert tool.main(['--directory', str(folder), '--store', str(store), '--apply']) == 0
    assert len(ota_payments._portal_events([store])) == 1
    # Re-running the same directory adds nothing.
    assert tool.main(['--directory', str(folder), '--store', str(store), '--apply']) == 0
    assert len(ota_payments._portal_events([store])) == 1


def test_a_failure_part_way_through_the_import_leaves_the_store_unchanged(tmp_path, monkeypatch):
    import json
    from app.ota_store import OtaStore as Store
    from tools import import_agoda_api_details as tool
    folder = tmp_path / 'details'
    folder.mkdir()
    for number in ('1234567890', '1234567891'):
        raw = record(**{'list.bookingId': int(number),
                        'detail.BookingDetails.BookingQueryData.CancellationReasonData.BookingID': int(number)})
        (folder / f'{number}.json').write_text(json.dumps(raw), encoding='utf-8')
    original = Store.import_direct
    calls = []

    def flaky(self, **kwargs):
        calls.append(kwargs['source_key'])
        if len(calls) == 2:
            raise RuntimeError('disk full')
        return original(self, **kwargs)

    monkeypatch.setattr(Store, 'import_direct', flaky)
    store = tmp_path / 'store.sqlite'
    with pytest.raises(RuntimeError):
        tool.main(['--directory', str(folder), '--store', str(store), '--apply'])
    assert len(calls) == 2 and ota_payments._portal_events([store]) == []
