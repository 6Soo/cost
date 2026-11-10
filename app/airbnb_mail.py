"""Airbnb confirmation mails as reservation-only facts; a booking notice never proves a card charge."""
from __future__ import annotations

import re
from datetime import date, timedelta

from app import ota_mail

DOMAINS = ('airbnb.com',)
CODE = re.compile(r'\bHM[A-Z0-9]{8}\b')
CONFIRMED = re.compile(r'^예약 확정(?: 안내)?\s*:\s*(\d{1,2})월\s*(\d{1,2})일\s*~\s*(?:(\d{1,2})월\s*)?(\d{1,2})일')
CANCELLED = re.compile(r'예약이 취소되었습니다')


def _period(match, sent):
    """The subject omits the year: a stay is after its confirmation, allowing a month of late receipts."""
    start_month, start_day, end_month, end_day = (int(v) if v else None for v in match.groups())
    try:
        start = date(sent.year, start_month, start_day)
        if start < sent - timedelta(days=31):
            start = date(sent.year + 1, start_month, start_day)
        end_month = end_month or start_month
        end = date(start.year + (end_month < start_month), end_month, end_day)
    except ValueError:
        return None
    if not 0 < (end - start).days <= 60:
        return None
    return {'starts_on': start.isoformat(), 'ends_on': end.isoformat()}


def collect(messages, inventory=()):
    from app import ota_payments as core

    observed, cancelled = {}, set()
    for message_id, message in sorted(messages.items()):
        auth = ota_mail.authenticated_headers(message, DOMAINS)
        if not auth:
            continue
        headers, _domain = auth
        subject = str(headers.get('subject') or '')
        confirmed, withdrawn = CONFIRMED.search(subject), CANCELLED.search(subject)
        if not confirmed and not withdrawn:
            continue
        codes = set(CODE.findall(ota_mail.message_text(message)))
        if len(codes) != 1:
            continue
        code = next(iter(codes))
        if withdrawn:
            cancelled.add(code)
            continue
        sent = ota_mail.sent_day(message, headers)
        period = _period(confirmed, sent) if sent else None
        if period:
            observed.setdefault(code, []).append((message_id, period, core._digest(message)))
    events = []
    for code, rows in sorted(observed.items()):
        periods = {tuple(p.values()) for _, p, _ in rows}
        source_ids = ['mail:' + message_id for message_id, _, _ in rows]
        event = {
            'provider': 'airbnb', 'booking_ref': code, 'event_type': 'reservation', 'item': '숙박비',
            'paid_on': None, 'amount': None, 'currency': None, 'amount_krw': None, 'card_last4': None,
            'service_period': rows[-1][1] if len(periods) == 1 else None,
            'service_period_conflict': len(periods) != 1,
            'reservation_status': 'cancelled' if code in cancelled else 'observed',
            'payment_status': 'unknown', 'evidence_status': 'reservation_observed',
            'evidence_kind': 'authenticated_reservation_mail',
            'source_digest': rows[-1][2], 'source_digests': [d for _, _, d in rows],
            'source_ids': source_ids, 'identity_source_ids': source_ids,
            'source_inventory': list(inventory), 'paid_on_semantics': 'missing',
        }
        # One code is one reservation: later confirmation or cancellation mails keep its identity.
        identity = 'airbnb:' + code
        event['source_lineage_ids'] = [identity]
        event['observation_ids'] = sorted('obs_' + core._digest([identity, source]) for source in source_ids)
        event['ota_event_id'] = core._event_id([identity])
        events.append(event)
    return events
