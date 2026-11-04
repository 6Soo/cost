"""Read Traveloka flight reservations without treating an e-ticket as payment."""
import hashlib
import json
import re
from datetime import date

from app import ota_mail


def references(message):
    authenticated = ota_mail.authenticated_headers(message, ('traveloka.com',))
    if not authenticated:
        return set()
    text = authenticated[0].get('subject', '') + '\n' + ota_mail.message_text(message)
    return set(re.findall(r'(?:예약\s*ID|Booking\s*ID)\s*[:：]?\s*(\d{6,20})\b', text, re.I))


def extract(message):
    authenticated = ota_mail.authenticated_headers(message, ('traveloka.com',))
    if not authenticated:
        return None
    subject = authenticated[0].get('subject', '')
    text = ota_mail.message_text(message).translate(ota_mail._format_char_table())
    refs = references(message)
    if len(refs) != 1 or not re.search(r'항공권|e-ticket|flight', subject, re.I):
        return None
    # Requests and cancellation notices never prove a charge or a completed refund.
    cancelled = bool(re.search(r'취소|환불|cancel|refund', subject, re.I))
    completed = bool(re.search(r'결제\s*완료|payment\s*(?:complete|successful)', subject, re.I))
    amounts = set(re.findall(r'(?<![\d,])((?:\d+|[1-9]\d{0,2}(?:,\d{3})+))\s*원\b', text))
    amount = int(next(iter(amounts)).replace(',', '')) if completed and not cancelled and len(amounts) == 1 else None
    if amount is not None and amount <= 0:
        return None
    period = None
    outbound = re.search(r'출발\s*항공편(.+?)(?:귀국\s*항공편|오는편|승객|$)', text, re.S)
    if outbound:
        found = re.search(r'(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일', outbound[1])
        reverse = re.search(r'(\d{1,2})\s+(\d{1,2})월\s+(20\d{2})', outbound[1])
        parts = found.groups() if found else tuple(reversed(reverse.groups())) if reverse else None
        if parts:
            try:
                day = date(*map(int, parts)).isoformat()
                period = {'starts_on': day, 'ends_on': day}
            except ValueError:
                pass
    return dict(provider='traveloka', booking_ref=next(iter(refs)), item='항공료',
                paid_amount_krw=amount, paid_on=None, paid_on_semantics='missing',
                period=period, reserved_dates=[], reservation_status='observed',
                evidence_status='evidence_conflict' if cancelled else 'paid_verified' if amount else 'reservation_observed',
                event_type='charge' if amount else 'reservation',
                source_sha256=hashlib.sha256(json.dumps(message, ensure_ascii=False,
                    sort_keys=True, separators=(',', ':')).encode()).hexdigest())
