"""Trip.com hotel-order details read in the owner's signed-in browser, as reservation evidence.

A record is {observed_at, order: getAllOrders entry, detail: GetOrderDetailOnline response}. The
fact keeps the stay, the order status and, for pay-at-property orders (`payType` 5), the KRW card
pre-authorization Trip holds as a guarantee and how much of it was refunded. A pre-authorization
is not a lodging payment: the property is paid on site.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from app.agoda_capture import digest, dump, utc

FORMAT = 'trip-api-v1'
PARSER_VERSION = 1
KST = timezone(timedelta(hours=9))
# Trip order status codes seen on hotel orders.
STATUSES = {2001: 'confirmed', 2002: 'confirmed', 2003: 'confirmed', 2004: 'confirmed',
            2005: 'completed', 2006: 'cancelled'}
PAY_AT_PROPERTY_WITH_GUARANTEE = 5


def _ymd(value):
    text = str(value or '')
    return f'{text[:4]}-{text[4:6]}-{text[6:8]}' if re.fullmatch(r'\d{8}', text) else None


def _booked_on(value):
    found = re.search(r'/Date\((\d+)', str(value or ''))
    return datetime.fromtimestamp(int(found[1]) / 1000, KST).date().isoformat() if found else None


def _won(value):
    try:
        number = int(str(value).replace(',', '').replace('원', '').strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def parse_hotel_detail(record):
    """One saved record as a Trip reservation fact. A response for another order raises."""
    order, detail = record.get('order') or {}, record.get('detail') or {}
    number = str(order.get('OrderID') or '')
    if not re.fullmatch(r'\d{8,20}', number):
        raise ValueError('TRIP_API_ORDER_REQUIRED')
    price = detail.get('priceInfo') or {}
    refund_param = ((price.get('refundInfo') or detail.get('refundInfo') or {}).get('refundProgressModalParam') or {})
    hotel_map = ((detail.get('hotelMapInfo') or {}).get('hotelMapParam') or {})
    identities = {str(v) for v in (refund_param.get('orderID'),) if v}
    if identities and identities != {number}:
        raise ValueError('TRIP_API_ORDER_IDENTITY_MISMATCH')
    common = detail.get('orderCommonInfo') or {}
    if not common:
        raise ValueError('TRIP_API_DETAIL_REQUIRED')
    start, end = _ymd(common.get('checkInDate') or hotel_map.get('checkInDate')), _ymd(common.get('checkOutDate') or hotel_map.get('checkOutDate'))
    if start and end and end < start:
        raise ValueError('TRIP_API_INVALID_SERVICE_PERIOD')
    trip = price.get('tripPriceDetail') or {}
    pay_type = (trip.get('additionalInfo') or {}).get('payType')
    pre = trip.get('preAuthorizationInfo') or {}
    preauth = _won(pre.get('amount')) if str(pre.get('currency') or '').upper() == 'KRW' else None
    refunds, last4 = [], set()
    for item in (((price.get('refundInfo') or detail.get('refundInfo') or {}).get('refundDetialInfo') or {}).get('itemInfo')) or []:
        found = re.search(r'\((\d{4})\)', str(item.get('title') or ''))
        if found:
            last4.add(found[1])
        if str(item.get('status') or '').upper() == 'SUCCESS':
            amount = _won(item.get('amount'))
            if amount:
                refunds.append(amount)
    status = STATUSES.get(common.get('orderStatusCode'), 'unknown')
    refunded = sum(refunds)
    guarantee = pay_type == PAY_AT_PROPERTY_WITH_GUARANTEE and bool(preauth)
    return {
        'provider': 'trip', 'booking_number': number, 'evidence_format': FORMAT, 'parser_version': PARSER_VERSION,
        'product_type': 'lodging', 'item': '숙박비',
        'service_start_on': start, 'service_end_on': end, 'reservation_status': status,
        'booked_on': _booked_on(order.get('BookingDate')),
        'pay_at_property': pay_type == PAY_AT_PROPERTY_WITH_GUARANTEE,
        'preauthorization_amount_krw': preauth if guarantee else None,
        'preauthorization_refunded_krw': refunded if guarantee else None,
        'preauthorization_refund': (None if not guarantee else 'refunded' if refunded >= preauth
                                    else 'partly_refunded' if refunded else 'not_refunded'),
        'card_last4': next(iter(last4)) if len(last4) == 1 else None,
        'snapshot_sha256': digest(dump(detail)), 'observed_at': utc(record['observed_at']),
    }


def records(directory, orders_path):
    """Saved detail files joined with their order list entries."""
    from pathlib import Path
    orders = {str(o.get('OrderID')): o for o in json.loads(Path(orders_path).read_text(encoding='utf-8'))}
    for path in sorted(Path(directory).glob('*.json')):
        saved = json.loads(path.read_text(encoding='utf-8'))
        yield path, {'observed_at': saved['observed_at'], 'order': orders.get(path.stem) or {}, 'detail': saved['detail']}
