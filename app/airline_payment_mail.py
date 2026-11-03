"""Extract narrowly labelled airline payment notices from authenticated mail."""
import hashlib
import json
import re
from datetime import date

from app import ota_mail


def cancellation_references(message):
    authenticated = ota_mail.authenticated_headers(message, ('flyasiana.com', 'skyticket.com', 'jejuair.net'))
    if not authenticated:
        return set()
    headers, domain = authenticated
    subject = headers.get('subject', '')
    if not re.search(r'취소|환불|cancel|refund', subject, re.I):
        return set()
    text = subject + '\n' + ota_mail.message_text(message)
    pattern = (r'예약번호\s*[:：]?\s*([A-Z0-9]{6})\b' if domain in ('flyasiana.com', 'jejuair.net')
               else r'신청번호\s*[:：]?\s*([0-9]{6,20})')
    refs = set(re.findall(pattern, text, re.I))
    provider = {'flyasiana.com': 'asiana', 'skyticket.com': 'skyticket', 'jejuair.net': 'jeju'}[domain]
    return {(provider, ref) for ref in refs}


def jeju_payment_facts(message):
    """Retain each labelled charge in an e-ticket, including amendment payments.

    A masked airline token is not assumed to be the issuer's physical card tail.
    Explicit charge dates and approval IDs identify the payment observations.
    Only outbound departure is used for trip attribution; returns may change.
    """
    authenticated = ota_mail.authenticated_headers(message, ('jejuair.net',))
    if not authenticated or not re.search(r'여정확인서\s*\(e-ticket\)', authenticated[0].get('subject', ''), re.I):
        return []
    text = ota_mail.message_text(message)
    refs = set(re.findall(r'예약번호\s*[:：]?\s*([A-Z0-9]{6})\b', text))
    if len(refs) != 1:
        return []
    compact = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
    reserved = re.findall(r'^예약일\s*\n(20\d{2}\.\d{2}\.\d{2})', compact, re.M)
    outbound = re.search(r'가는편\b(?:(?!오는편).)*?\b(20\d{2}\.\d{2}\.\d{2})', compact, re.S)
    blocks = re.split(r'(?=^승인번호\s*$)', compact, flags=re.M)[1:]
    digest = hashlib.sha256(json.dumps(message, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()
    result = []
    try:
        reserved = sorted({date.fromisoformat(value.replace('.', '-')).isoformat() for value in reserved})
        day = date.fromisoformat(outbound[1].replace('.', '-')).isoformat() if outbound else None
        for block in blocks:
            approval = re.search(r'^승인번호\s*\n([A-Za-z0-9-]{4,32})\s*$', block, re.M)
            paid = re.search(r'^결제일\s*\n(20\d{2}\.\d{2}\.\d{2})\s*$', block, re.M)
            amounts = set(re.findall(r'^결제금액\s*\n((?:\d+|[1-9]\d{0,2}(?:,\d{3})+))\s*원\s*$', block, re.M))
            if not approval or not paid or len(amounts) != 1:
                return []
            amount = int(next(iter(amounts)).replace(',', ''))
            if amount <= 0:
                return []
            result.append(dict(provider='jeju', booking_ref=next(iter(refs)), item='항공료',
                paid_amount_krw=amount, paid_on=date.fromisoformat(paid[1].replace('.', '-')).isoformat(),
                payment_id=next(iter(refs)) + ':' + approval[1],
                period={'starts_on': day, 'ends_on': day} if day else None,
                reserved_dates=reserved, source_sha256=digest, reservation_status='observed',
                paid_on_semantics='explicit_charge_date'))
    except ValueError:
        return []
    return result


def extract(message):
    jeju = jeju_payment_facts(message)
    if jeju:
        return jeju[0]
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
