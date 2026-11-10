"""Agoda booking-detail API responses read in the owner's signed-in browser, as portal evidence.

The detail endpoint (`/api/<lang>/mmbc/eb/details`) returns the same facts the booking page shows:
identity, stay dates, status, card ending and charged amounts. One record is the list entry the
booking token came from plus its detail response. The fact has the shape `agoda_capture.parse_detail`
produces, so the unified store and the reconciliation read both formats the same way.
"""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.agoda_capture import digest, dump, money, utc

FORMAT = 'agoda-api-v1'
PARSER_VERSION = 1
PHASES = {'Upcoming': 'confirmed', 'Completed': 'completed', 'Cancelled': 'cancelled'}


def _amount(node, kind):
    """A money component from an API amount node, or None when absent or zero."""
    if not isinstance(node, dict) or node.get('Currency') in (None, ''):
        return None
    try:
        value = Decimal(str(node.get('AmountAsDouble')))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('AGODA_API_INVALID_MONEY')
    if not value.is_finite() or value < 0:
        raise ValueError('AGODA_API_INVALID_MONEY')
    if value == 0:
        return None
    text = format(value.normalize(), 'f')
    return money(str(node['Currency']).upper(), f'{Decimal(text):,}' if '.' not in text else text, kind)


def _day(value):
    try:
        return date.fromisoformat(str(value or '')).isoformat()
    except ValueError:
        return None


def parse_api_detail(record):
    """One saved {observed_at, list, detail} record as a portal fact. Identity mismatches raise."""
    listed, response = record.get('list') or {}, record.get('detail') or {}
    details = response.get('BookingDetails') or {}
    query = details.get('BookingQueryData') or {}
    booking = str(listed.get('bookingId') or '')
    if not re.fullmatch(r'\d{6,20}', booking):
        raise ValueError('AGODA_API_BOOKING_REQUIRED')
    if str((query.get('CancellationReasonData') or {}).get('BookingID')) != booking:
        raise ValueError('AGODA_API_BOOKING_IDENTITY_MISMATCH')
    dates = details.get('Dates') or {}
    start, end = _day(dates.get('CheckInDateNonCulture')), _day(dates.get('CheckOutDateNonCulture'))
    if start and end and end < start:
        raise ValueError('AGODA_API_INVALID_SERVICE_PERIOD')
    state = details.get('BookingStatus') or {}
    status = PHASES.get(state.get('Phase'), 'unknown')
    display = str(state.get('DisplayText') or '')
    card = str(((details.get('PaymentMethod') or {}).get('CreditCard') or {}).get('CardNumber') or '')
    last4 = card[-4:] if re.fullmatch(r'[xX*•\d -]*\d{4}', card) else None
    payment = details.get('PaymentDetails') or {}
    live = payment.get('NonCancelledPaymentDetails') or {}
    cancelled = payment.get('CancelledPaymentDetails') or {}
    scheduled = bool(re.search(r'결제\s*예정', display)) or bool(payment.get('PayLaterInfo'))
    # 'pay-hotel' is paid to the property at check-in; Agoda charges nothing.
    at_property = payment.get('PaymentModel') == 'pay-hotel'
    paid, refund, fee, adjusted = [], None, None, False
    if status == 'cancelled':
        charged = _amount(cancelled.get('TotalAmountCharged'), 'paid_today')
        refund = _amount(cancelled.get('YourRefund'), 'refund_expected')
        fee = _amount(cancelled.get('CancellationFee'), 'cancellation_fee')
        paid = [charged] if charged else []
        scheduled = False
    elif not scheduled and not at_property:
        lines = [p for p in live.get('Payments') or [] if 'card' in str(p.get('Description') or '').lower()]
        # A negative card line is a later partial refund or adjustment; the net charge needs review.
        adjusted = any(float((p.get('Amount') or {}).get('AmountAsDouble') or 0) < 0 for p in lines)
        paid = [] if adjusted else [_amount(p.get('Amount'), 'paid_today') for p in lines]
        paid = [p for p in paid if p]
    paid = list({dump(p): p for p in paid}.values())
    diagnostics = []
    if status == 'unknown':
        diagnostics.append('reservation_status_unknown')
    if not start or not end:
        diagnostics.append('service_period_missing')
    if not last4:
        diagnostics.append('card_observation_missing')
    if len(paid) > 1:
        diagnostics.append('amount_ambiguous')
    if scheduled:
        diagnostics.append('scheduled_payment')
    if status == 'cancelled':
        diagnostics.append('cancelled_booking')
    if refund or adjusted:
        diagnostics.append('refund_layout_requires_review')
    if at_property:
        diagnostics.append('pay_at_property_not_an_ota_charge')
    # The API carries no charge date for a paid-later booking, so the date stays unknown.
    diagnostics.append('payment_date_unknown')
    observed_paid = len(paid) == 1 and not scheduled and not refund and not adjusted
    roles = ['identity']
    if start and end:
        roles.append('service_period')
    if paid or scheduled:
        roles.append('portal_payment_claim')
    if last4:
        roles.append('portal_card_observation')
    if status != 'unknown':
        roles.append('lifecycle')
    snapshot = dump(response)
    return {'provider': 'agoda', 'booking_number': booking,
            'service_start_on': start, 'service_end_on': end, 'reservation_status': status,
            'status': status, 'evidence_format': FORMAT, 'parser_version': PARSER_VERSION,
            'product_type': 'lodging' if listed.get('productTypeName') == 'Hotel' else 'unknown',
            'payment_status': ('pay_at_property' if at_property else 'scheduled' if scheduled
                               else 'paid' if observed_paid and last4
                               else 'paid_observed_without_card' if observed_paid else 'unknown'),
            'portal_payment_state': 'paid_observed' if observed_paid else 'unverified',
            'refund_status': 'refund_pending' if refund or adjusted else 'none_displayed',
            'card_last4': last4, 'price_components': paid + [p for p in (refund, fee) if p],
            'paid_on': None, 'paid_on_semantics': 'missing',
            'scheduled_for': None, 'source_namespace': FORMAT, 'snapshot_sha256': digest(snapshot),
            'observed_at': utc(record['observed_at']), 'roles': roles, 'diagnostics': diagnostics}


def records(directory):
    """Saved records in a directory, one JSON file per booking, in file-name order."""
    from pathlib import Path
    for path in sorted(Path(directory).glob('*.json')):
        yield path, json.loads(path.read_text(encoding='utf-8'))
