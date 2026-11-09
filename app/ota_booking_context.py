"""인증된 예약 메일의 비금전 근거를 결제 원문과 구분해 연결한다."""
import hashlib
import json
import re
from collections import defaultdict

from app import ota_mail


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def payment_issuer(text):
    # 실제 결제 수단 표기의 카드사만 읽는다. 은행명이나 숙소 안내에서는 추정하지 않는다.
    issuers = {issuer for label, issuer in (
        ('하나', '하나'), ('국민', '국민'), ('기업', '기업'), ('신한', '신한'),
        ('삼성', '삼성'), ('현대', '현대'), ('롯데', '롯데'), ('우리', '우리'))
        if re.search(re.escape(label) + r'\s*카드\s*\(\s*(?:신용|체크)카드\s*\)', text)}
    return next(iter(issuers)) if len(issuers) == 1 else None


def collect(messages):
    groups = defaultdict(list)
    for message in messages.values():
        authenticated = ota_mail.authenticated_headers(message, (
            'trip.com', 'trip.co.kr', 'klook.com', 'agoda.com', 'booking.com', 'agoda-messaging.com'))
        if not authenticated:
            continue
        headers, domain = authenticated
        provider = ('trip' if domain in ('trip.com', 'trip.co.kr') else 'agoda'
                    if domain in ('agoda.com', 'agoda-messaging.com') else domain.split('.')[0])
        text = ota_mail.message_text(message).translate(ota_mail._format_char_table())
        subject = headers.get('subject', '')
        refs = set(re.findall(
            r'(?:예약\s*(?:번호|코드|ID)|booking\s*(?:reference|number|ID)|reservation\s*(?:number|ID))'
            r'\s*[:：#]?\s*([A-Z0-9-]{6,32})', text, re.I))
        if len(refs) != 1:
            continue
        period = ota_mail.service_period(text)
        item = '숙박비' if period else ''
        if provider == 'trip' and '항공권 예약 확정' in subject:
            period = ota_mail.flight_period(text)
            item = '항공료' if period else ''
        elif provider == 'trip' and ota_mail.trip_rental_confirmation(subject):
            period = ota_mail.rental_period(text)
            item = '렌터카' if period else ''
        cancelled = ota_mail.reservation_cancelled(subject)
        refund_pending = bool(re.search(
            r'환불(?:을)?\s*요청(?:했습니다|하였습니다|했|됨|완료|되었습니다)|'
            r'refund\s+(?:requested|request\s+(?:submitted|received|confirmed))',
            subject + '\n' + text, re.I))
        change = bool(re.search(r'예약.*(?:변경|업데이트)|booking.*(?:updated|modified)', subject, re.I))
        totals = []
        if change:
            totals = sorted(set(re.findall(r'총\s*금액\s*(?:온라인\s*사전\s*결제\s*)?([0-9][0-9,]*)\s*원', text)))
        if not (period or cancelled or refund_pending or change):
            continue
        groups[(provider, next(iter(refs)))].append({
            'source_id': 'mail:' + message['id'], 'source_digest': _digest(message),
            'period': period, 'item': item, 'cancelled': cancelled, 'refund_pending': refund_pending,
            'booking_changed': change, 'booking_totals_krw': [int(n.replace(',', '')) for n in totals]})
    return groups


def attach(event, observations):
    if not observations:
        return event
    observations = sorted(observations, key=lambda o: o['source_id'])
    periods = {json.dumps(o['period'], sort_keys=True) for o in observations if o['period']}
    if event.get('service_period'):
        periods.add(json.dumps(event['service_period'], sort_keys=True))
    result = dict(event)
    result['booking_context_source_ids'] = sorted(o['source_id'] for o in observations)
    result['booking_context_source_digests'] = sorted({o['source_digest'] for o in observations})
    if len(periods) == 1:
        result['service_period'] = json.loads(next(iter(periods)))
        if not result.get('item'):
            items = {o.get('item', '숙박비') for o in observations if o['period']}
            if len(items) == 1:
                result['item'] = next(iter(items))
    elif len(periods) > 1:
        result['service_period'] = None
        result['service_period_conflict'] = True
        result['service_period_candidates'] = [json.loads(p) for p in sorted(periods)]
    if any(o['cancelled'] for o in observations):
        result['reservation_status'] = 'cancelled'
    if any(o['refund_pending'] for o in observations) and result.get('refund_status') not in ('refunded', 'refund_completed'):
        result['refund_status'] = 'refund_pending'
    changed = [o for o in observations if o['booking_changed']]
    if changed:
        result['booking_changes'] = changed
    # 결제 ID와 금전 출처 목록은 유지한다. 예약 확인서를 같은 실물 결제의 증거로 합치지 않는다.
    result['payment_source_digest'] = event.get('source_digest')
    result['source_digest'] = _digest({'payment': event.get('source_digest'), 'booking_context': observations})
    return result
