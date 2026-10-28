"""직접 수집한 숲나들e 메일의 예약 사실과 읽기 전용 대사 후보."""
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from email.utils import parseaddr

from app import ota_mail

DOMAINS = ('forest.go.kr', 'foresttrip.go.kr')
_NOTICE = re.compile(r'예약\s*(?:완료|취소|안내)|결제\s*(?:완료|기한|안내)')
_DAY = r'\d{4}-\d{2}-\d{2}'


def _facts(text):
    # This is the service date in the provider's room-reservation sentence,
    # not the unrelated payment-deadline date elsewhere in the mail.
    stays = set()
    for day, facility, room in re.findall(
            r'(' + _DAY + r')\s+([^\n]{1,70}?자연휴양림)\s+([^\n]{1,100}?)\s+객실\s*(?:이?\s*)?예약', text):
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        stays.add((day, facility.strip(), room.strip()))
    period = ota_mail.service_period(text)
    regions = set(re.findall(
        r'(?:충북|충남|전북|전남|경북|경남|경기|강원|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|경기도|강원도|강원특별자치도)\s+([가-힣]{1,8}[군시])\s', text))
    refs = set(re.findall(r'예약\s*번호\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9-]{3,39})(?![A-Za-z0-9-])', text))
    amounts = set()
    for raw in re.findall(r'(?:결제\s*금액|예약\s*금액|총\s*이용\s*요금)\s*[:：]?\s*([0-9][0-9,]*)\s*원', text):
        if ',' in raw and not re.fullmatch(r'\d{1,3}(?:,\d{3})+', raw):
            continue
        value = int(raw.replace(',', ''))
        if value > 0:
            amounts.add(value)
    conflict = (len(stays) > 1 or len(refs) > 1 or len(amounts) > 1
                or bool(re.search(r'체크\s*(?:인|아웃)|check[ -]*(?:in|out)', text, re.I) and not period))
    day, facility, room = next(iter(stays)) if len(stays) == 1 else (None, '', '')
    if period and day and period['starts_on'] != day:
        conflict = True
    return {'hotel_name': facility, 'room_name': room,
            'operator_region': next(iter(regions)) if len(regions) == 1 else '',
            'service_period': period or ({'starts_on': day, 'ends_on': None} if day else None),
            'service_period_semantics': 'explicit_period' if period else 'start_only' if day else 'missing',
            'booking_ref': next(iter(refs)) if len(refs) == 1 else None,
            'amount_krw': next(iter(amounts)) if len(amounts) == 1 else None,
            'extraction_conflict': conflict}


def _authentication(headers):
    """Descriptive metadata only; do not turn missing DKIM into a work hold."""
    results = headers.get('authentication-results', '')
    return ' / '.join(('SPF 통과' if re.search(r'\bspf=pass\b', results, re.I) else 'SPF 통과 기록 없음',
                       'DKIM 통과 기록 있음' if re.search(r'\bdkim=pass\b', results, re.I)
                       else 'DKIM 통과 기록 없음'))


def collect(messages, inventory=()):
    """번호 없는 메일끼리는 합치지 않으며 추적 URL의 ID를 예약번호로 쓰지 않는다.

    본문 문장의 날짜가 숙박일인지 예약일인지 확인되지 않으면 service_period로
    승격하지 않는다. 금액이나 결제 완료 문구도 카드 결제 사건을 만들지 않는다.
    기존 원문은 source_ids/digest로 참조하고 고객명이나 본문을 복사하지 않는다.
    """
    from app import ota_payments as core

    events = []
    for message_id, message in sorted(messages.items()):
        if not isinstance(message, dict) or not isinstance(message.get('payload'), dict):
            continue
        values = message['payload'].get('headers', [])
        if not isinstance(values, list) or any(
                not isinstance(h, dict) or not isinstance(h.get('name'), str) or
                not isinstance(h.get('value'), str) for h in values):
            continue
        headers = {h['name'].lower(): h['value'] for h in values}
        domain = parseaddr(headers.get('from', ''))[1].split('@')[-1].lower()
        if not any(domain == base or domain.endswith('.' + base) for base in DOMAINS):
            continue
        subject = headers.get('subject', '')
        if not _NOTICE.search(subject):
            continue
        # These are already collected mailbox records. Authentication describes
        # the mail, while financial authority stays with the card ledger.
        facts = _facts(ota_mail.message_text(message))
        cancelled = bool(re.search(r'예약\s*취소', subject))
        source_id = 'mail:' + message_id
        digest = core._digest(message)
        identity = 'forest:notice:' + core._digest(source_id)
        events.append({
            'provider': 'forest', 'booking_ref': facts['booking_ref'],
            'event_type': 'reservation', 'paid_on': None, 'paid_on_semantics': 'missing',
            'amount': facts['amount_krw'], 'amount_krw': facts['amount_krw'],
            'currency': 'KRW' if facts['amount_krw'] is not None else '',
            'card_last4': None, 'card_issuer': None,
            'item': ' · '.join(v for v in ('숲나들e 숙박', facts['hotel_name'], facts['room_name']) if v),
            'hotel_name': facts['hotel_name'], 'room_name': facts['room_name'],
            'operator_region': facts['operator_region'],
            'service_period': facts['service_period'],
            'service_period_semantics': facts['service_period_semantics'],
            'service_period_conflict': facts['extraction_conflict'],
            'reservation_status': 'cancelled' if cancelled else 'observed',
            'reported_reservation_status': 'cancelled' if cancelled else 'observed',
            'payment_status': 'unknown',
            'evidence_status': 'evidence_conflict' if facts['extraction_conflict'] else 'reservation_only',
            'evidence_kind': 'collected_reservation_mail',
            'evidence_confidence': 'MEDIUM' if facts['hotel_name'] else 'LOW',
            'source_trust': 'collected_sender_domain',
            'mail_authentication': _authentication(headers),
            'reservation_observed_on': [ota_mail.sent_day(message, headers).isoformat()]
                if ota_mail.sent_day(message, headers) else [],
            'payment_event_id': None, 'individual_payment_evidence': False,
            'source_ids': [source_id], 'identity_source_ids': [identity],
            'source_digest': digest, 'source_digests': [digest],
            'source_lineage_ids': [identity],
            'observation_ids': ['obs_' + core._digest([identity, source_id])],
            'source_inventory': list(inventory), 'ota_event_id': core._event_id([identity]),
        })
    return events


def search_candidates(event, transactions, *, max_comparisons=250000):
    """Facility + observed/service date evidence; never occupy or resolve a card."""
    from app import ota_payments as core
    result = {'status': 'NO_CANDIDATE', 'candidates': [], 'comparisons': 0,
              'date_status': 'UNKNOWN', 'reservation_only': True}
    if event.get('reservation_status') == 'cancelled' or event.get('service_period_conflict'):
        return dict(result, status='RESERVATION_CANCELLED_OR_CONFLICT')
    facility = re.sub(r'\W', '', event.get('hotel_name') or '').casefold()
    region = event.get('operator_region') or ''
    if not facility:
        return dict(result, status='RESERVATION_EVIDENCE_INCOMPLETE')
    days = list(event.get('reservation_observed_on') or [])
    start = (event.get('service_period') or {}).get('starts_on')
    if start:
        days.append(start)
    dates = [date.fromisoformat(day) for day in days]
    if not dates:
        return dict(result, status='RESERVATION_EVIDENCE_INCOMPLETE')
    for row in transactions:
        merchant = re.sub(r'\W', '', row.get('merchant') or row.get('merchant_normalized') or '').casefold()
        facility_match = facility in merchant
        municipality_match = bool(region and (region + '청') in merchant)
        if not facility_match and not municipality_match:
            continue
        result['comparisons'] += 1
        if result['comparisons'] > max_comparisons:
            return dict(result, status='SEARCH_LIMIT_EXCEEDED', candidates=[])
        if (any(row.get(k) for k in ('duplicate_of', 'parse_error', 'conflict_reason', 'ota_review_held'))
                or core._direction(row) != 'purchase' or not core._strict_card_identity(event, row)
                or row.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        try:
            value = Decimal(str(row.get('amount_krw')))
            card_day = date.fromisoformat(str(row.get('transaction_date') or row.get('approval_date') or '')[:10])
            if not value.is_finite() or value <= 0:
                continue
        except (InvalidOperation, ValueError, TypeError):
            continue
        if not any(abs((card_day - day).days) <= 7 for day in dates):
            continue
        currency = str(row.get('foreign_currency') or row.get('currency') or 'KRW').upper()
        if currency != 'KRW':
            continue
        expected = event.get('amount_krw')
        amount_status = 'UNKNOWN' if expected is None else 'MATCH' if value == Decimal(str(expected)) else 'MISMATCH'
        result['candidates'].append({'transaction_id': row.get('transaction_id'),
            'date_status': 'UNKNOWN', 'resolution_allowed': False,
            'basis': 'FOREST_FACILITY_AND_OBSERVED_DATE' if facility_match else 'FOREST_MUNICIPALITY_AND_OBSERVED_DATE',
            'amount_status': amount_status, 'branch_status': 'MATCH' if facility_match else 'UNKNOWN',
            'confidence': 'LOW' if not facility_match or amount_status != 'MATCH' else 'MEDIUM'})
    result['status'] = 'CANDIDATES_FOUND' if result['candidates'] else 'NO_CANDIDATE'
    return result
