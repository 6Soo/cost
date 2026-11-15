"""Gotogate/Mytrip flight confirmation mails as reservation-only facts; a confirmation never proves a card charge."""
from __future__ import annotations

import re
from datetime import date

from app import ota_mail

DOMAINS = ('mytrip.com', 'gotogate.com')
ORDER = r'\d{4}-\d{3}-\d{3}'
CONFIRMED = re.compile(r'^여행이\s*확정되었습니다\.\s*주문\s*번호\s*(' + ORDER + r')\s*$')
WITHDRAWN = re.compile(r'취소|환불|cancel|refund', re.I)
LEG = re.compile(r'(?:가는|오는)\s*편\s*[•·]\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일')
TOTAL = re.compile(r'합계\s*([0-9][0-9,]*)(?:\.00)?\s*KRW\b')


def _facts(text, order):
    if set(re.findall(ORDER, text)) != {order}:
        return None
    legs = set()
    for year, month, day in LEG.findall(text):
        try:
            legs.add(date(int(year), int(month), int(day)))
        except ValueError:
            return None
    totals = set(TOTAL.findall(text))
    if not legs or len(totals) != 1 or (max(legs) - min(legs)).days > 366:
        return None
    amount = int(next(iter(totals)).replace(',', ''))
    if amount <= 0:
        return None
    return {'starts_on': min(legs).isoformat(), 'ends_on': max(legs).isoformat()}, amount


def collect(messages, inventory=()):
    from app import ota_payments as core

    observed, withdrawn = {}, set()
    for message_id, message in sorted(messages.items()):
        auth = ota_mail.authenticated_headers(message, DOMAINS)
        if not auth:
            continue
        headers = auth[0]
        subject = str(headers.get('subject') or '')
        text = ota_mail.message_text(message)
        confirmed = CONFIRMED.match(subject.strip())
        if not confirmed:
            if WITHDRAWN.search(subject):
                withdrawn.update(re.findall(ORDER, text))
            continue
        order = confirmed[1]
        facts = _facts(text, order)
        sent = ota_mail.sent_day(message, headers)
        if facts and sent:
            observed.setdefault(order, []).append((message_id, facts, sent, core._digest(message)))
    events = []
    for order, rows in sorted(observed.items()):
        distinct = {(tuple(f[0].values()), f[1]) for _, f, _, _ in rows}
        source_ids = ['mail:' + message_id for message_id, _, _, _ in rows]
        period, amount = rows[-1][1]
        conflict = len(distinct) != 1
        event = {
            'provider': 'gotogate', 'booking_ref': order, 'event_type': 'reservation', 'item': '항공료',
            'paid_on': None, 'paid_on_semantics': 'missing', 'card_last4': None,
            'amount': None if conflict else amount, 'amount_krw': None if conflict else amount,
            'currency': None if conflict else 'KRW',
            'service_period': None if conflict else period, 'service_period_conflict': conflict,
            'reservation_status': 'cancelled' if order in withdrawn else 'observed',
            'payment_status': 'unknown', 'evidence_status': 'reservation_only',
            'evidence_kind': 'authenticated_reservation_mail',
            'reservation_observed_on': sorted({sent.isoformat() for _, _, sent, _ in rows}),
            'source_digest': rows[-1][3], 'source_digests': [d for _, _, _, d in rows],
            'source_ids': source_ids, 'identity_source_ids': source_ids,
            'source_inventory': list(inventory),
        }
        identity = 'gotogate:' + order
        event['source_lineage_ids'] = [identity]
        event['observation_ids'] = sorted('obs_' + core._digest([identity, source]) for source in source_ids)
        event['ota_event_id'] = core._event_id([identity])
        events.append(event)
    return events
