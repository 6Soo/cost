"""Trip.com hotel-order details as reservation and pre-authorization evidence. Synthetic only."""
import pytest

from app import ota_payments
from app.ota_store import OtaStore
from app.trip_api_capture import parse_hotel_detail


def record(order_id=1400800000000001, preauth=421614, refunds=((421614, 'SUCCESS'),), pay_type=5,
           status=2005, check_in='20261022', check_out='20261023'):
    return {
        'observed_at': '2026-11-10T06:00:00+00:00',
        'order': {'OrderID': order_id, 'BookingDate': '/Date(1785427200000+0800)/'},
        'detail': {
            'orderCommonInfo': {'orderId': order_id, 'orderStatusCode': status, 'checkInDate': check_in, 'checkOutDate': check_out},
            'priceInfo': {
                'tripPriceDetail': {'additionalInfo': {'payType': pay_type},
                                    'preAuthorizationInfo': {'currency': 'KRW', 'amount': preauth}},
                'refundInfo': {'refundProgressModalParam': {'orderID': order_id},
                               'refundDetialInfo': {'itemInfo': [
                                   {'title': '합성카드(신용카드)(1234)로 환불 예정', 'amount': f'{amount:,}원', 'status': state}
                                   for amount, state in refunds]}}},
        },
    }


def test_a_pay_at_property_order_reads_its_guarantee_hold_and_refund():
    fact = parse_hotel_detail(record())
    assert fact['evidence_format'] == 'trip-api-v1' and fact['booking_number'] == '1400800000000001'
    assert (fact['service_start_on'], fact['service_end_on'], fact['reservation_status']) == ('2026-10-22', '2026-10-23', 'completed')
    assert (fact['preauthorization_amount_krw'], fact['preauthorization_refunded_krw'], fact['preauthorization_refund']) == (421614, 421614, 'refunded')
    assert fact['card_last4'] == '1234' and fact['booked_on'] == '2026-07-31'


@pytest.mark.parametrize('kwargs,refund', [
    ({'refunds': ((267022, 'SUCCESS'),), 'preauth': 281076, 'status': 2006}, 'partly_refunded'),
    ({'refunds': ()}, 'not_refunded'),
    ({'refunds': ((421614, 'PROCESSING'),)}, 'not_refunded'),
    ({'pay_type': 1}, None),
])
def test_refund_progress_and_prepaid_orders(kwargs, refund):
    fact = parse_hotel_detail(record(**kwargs))
    assert fact['preauthorization_refund'] == refund
    if refund is None:
        assert fact['preauthorization_amount_krw'] is None


@pytest.mark.parametrize('break_identity', [
    lambda d: d['priceInfo']['refundInfo']['refundProgressModalParam'].update(orderID=1),
    lambda d: d['orderCommonInfo'].update(orderId=1),
    lambda d: (d['orderCommonInfo'].pop('orderId'), d['priceInfo'].pop('refundInfo')),
])
def test_a_response_for_another_order_or_without_its_order_is_refused(break_identity):
    raw = record()
    break_identity(raw['detail'])
    with pytest.raises(ValueError, match='TRIP_API_ORDER_IDENTITY_MISMATCH'):
        parse_hotel_detail(raw)


def test_an_imported_order_becomes_a_reservation_event_that_claims_no_payment(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        raw = record()
        store.import_direct(provider='trip', account_key='trip-owner', source_key='trip-api:1400800000000001',
                            snapshot=raw, facts=[parse_hotel_detail(raw)])
        events = ota_payments._trip_reservation_events([store.path])
        assert ota_payments._portal_events([store.path]) == []
    finally:
        store.close()
    assert len(events) == 1
    event = events[0]
    assert (event['event_type'], event['evidence_kind'], event['amount'], event['amount_krw']) == (
        'reservation', 'portal_preauthorization', None, None)
    assert event['service_period'] == {'starts_on': '2026-10-22', 'ends_on': '2026-10-23'}
    assert (event['preauthorization_amount_krw'], event['preauthorization_refund']) == (421614, 'refunded')
