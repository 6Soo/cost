"""Extract narrowly labelled airline payment notices from authenticated mail."""
import hashlib
import json
import re
from datetime import date

from app import ota_mail


def cancellation_references(message):
    authenticated = ota_mail.authenticated_headers(message, ('flyasiana.com', 'skyticket.com'))
    if not authenticated:
        return set()
    headers, domain = authenticated
    subject = headers.get('subject', '')
    if not re.search(r'취소|환불|cancel|refund', subject, re.I):
        return set()
    text = subject + '\n' + ota_mail.message_text(message)
    pattern = (r'예약번호\s*[:：]?\s*([A-Z0-9]{6})\b' if domain == 'flyasiana.com'
               else r'신청번호\s*[:：]?\s*([0-9]{6,20})')
    refs = set(re.findall(pattern, text, re.I))
    return {(('asiana' if domain == 'flyasiana.com' else 'skyticket'), ref) for ref in refs}


def extract(message):
    authenticated = ota_mail.authenticated_headers(message, ('flyasiana.com', 'skyticket.com'))
    if not authenticated:
        return None
    headers, domain = authenticated
    subject = headers.get('subject', '')
    text = ota_mail.message_text(message)
    if domain == 'flyasiana.com':
        if not re.search(r'항공권\s*발급이\s*완료', subject):
            return None
        refs = set(re.findall(r'예약번호\s*[:：]?\s*([A-Z0-9]{6})\b', text))
        amounts = set(re.findall(r'총\s*지불금액\s*\(결제완료\)\s*KRW\s*([0-9,]+)', text))
        days = set(re.findall(r'\b(20\d{2})\.(\d{1,2})\.(\d{1,2})\s*\(', text))
        reserved_dates = set(re.findall(r'예약일자\s*\(GMT\)\s*[:：]?\s*(20\d{2}-\d{2}-\d{2})', text))
        provider = 'asiana'
    else:
        if not re.search(r'구입\s*완료\s*안내', subject):
            return None
        refs = set(re.findall(r'신청번호\s*[:：]?\s*([0-9]{6,20})', subject + '\n' + text))
        amounts = set(re.findall(r'결제\s*금액\s*[:：]\s*KRW\s*([0-9,]+)', text, re.I))
        days = set(re.findall(r'\b(20\d{2})-(\d{1,2})-(\d{1,2})\s+[^\n]{0,80}출발\s*-', text))
        reserved_dates = set()
        provider = 'skyticket'
    if len(refs) != 1 or len(amounts) != 1:
        return None
    try:
        amount_text = next(iter(amounts))
        if not re.fullmatch(r'(?:\d+|[1-9]\d{0,2}(?:,\d{3})+)', amount_text):
            return None
        amount = int(amount_text.replace(',', ''))
        paid_on = ota_mail.sent_day(message, headers)
        parsed_days = {date(*map(int, d)).isoformat() for d in days}
        reserved_dates = {date.fromisoformat(value).isoformat() for value in reserved_dates}
    except (TypeError, ValueError):
        return None
    if amount <= 0 or paid_on is None:
        return None
    # More than one date is retained without a fabricated journey period.
    day = next(iter(parsed_days)) if len(parsed_days) == 1 else None
    return {'provider': provider, 'booking_ref': next(iter(refs)), 'item': '항공료',
            'paid_amount_krw': amount, 'paid_on': None,
            'period': {'starts_on': day, 'ends_on': day} if day else None,
            'reserved_dates': sorted(reserved_dates),
            'source_sha256': hashlib.sha256(json.dumps(message, ensure_ascii=False, sort_keys=True,
                                                       separators=(',', ':')).encode()).hexdigest(),
            'reservation_status': 'observed', 'paid_on_semantics': 'missing'}
