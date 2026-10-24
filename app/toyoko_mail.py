"""토요코인 예약 원문을 중앙 대사의 비금전 예약 근거로 연결한다."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from app import booking_evidence, ota_mail

DOMAINS = ('toyoko-inn.com', 'toyoko-inn.co.jp')
REFERENCE = re.compile(r'예약\s*번호\s*[:：]\s*([0-9]{7,20})(?![0-9])')


def _amounts(text, label):
    values = set()
    for number, unit in re.findall(label + r'\s*[:：]\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(원|엔)', text):
        number = Decimal(number.replace(',', ''))
        if number > 0:
            values.add(('KRW' if unit == '원' else 'JPY', str(number)))
    return values


def collect(messages, inventory=()):
    """객실별 소계와 묶음 합계를 분리하며 예약 확인을 결제로 승격하지 않는다."""
    from app import ota_payments as core

    groups = defaultdict(list)
    for message_id, message in sorted(messages.items()):
        auth = ota_mail.authenticated_headers(message, DOMAINS)
        if not auth:
            continue
        headers, _ = auth
        text = ota_mail.message_text(message)
        subject = headers.get('subject', '')
        summary = booking_evidence.summarize(subject, booking_evidence._sent_day(headers), text)
        hotel = summary.get('hotel_name')
        markers = list(REFERENCE.finditer(text))
        if not hotel or not markers:
            continue
        hotel_key = booking_evidence._direct_hotel_key(hotel)
        references = sorted({m[1] for m in markers})
        sent = summary['sent']
        try:
            order = int(message.get('internal_date') or 0)
        except (TypeError, ValueError):
            order = 0
        common = {'hotel_name': hotel, 'sent': sent, 'order': (order, sent, message_id),
                  'source_id': 'mail:' + message_id, 'digest': core._digest(message),
                  'cancelled': '취소' in subject}
        for index, marker in enumerate(markers):
            part = text[marker.start():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
            detail = booking_evidence.summarize(subject, None, part)
            period = {k: detail[k] for k in ('starts_on', 'ends_on')}
            if not period['starts_on']:
                period = {k: summary[k] for k in ('starts_on', 'ends_on')}
            amounts = _amounts(part, '소계금액')
            if not amounts and len(references) == 1:
                amounts = _amounts(text, '합계금액')
            groups[(hotel_key, (marker[1],))].append(dict(common, period=period, amounts=amounts))
        if len(references) > 1:
            groups[(hotel_key, tuple(references))].append(dict(common,
                period={k: summary[k] for k in ('starts_on', 'ends_on')},
                amounts=_amounts(text, '합계금액')))

    events = []
    for (hotel_key, references), observations in sorted(groups.items()):
        observations.sort(key=lambda o: o['order'])
        latest = observations[-1]
        cancellations = [o for o in observations if o['cancelled']]
        if len(references) > 1:
            cancellations += [o for ref in references for o in groups.get((hotel_key, (ref,)), ()) if o['cancelled']]
        after_cancel = bool(cancellations and not latest['cancelled']
                            and latest['order'] > max(o['order'] for o in cancellations))
        amount = next(iter(latest['amounts'])) if len(latest['amounts']) == 1 else ('', None)
        currency, value = amount
        identity = 'toyoko:reservation:' + core._digest([hotel_key, references])
        source_ids = sorted({o['source_id'] for o in observations})
        source_digests = sorted({o['digest'] for o in observations})
        group = len(references) > 1
        events.append({
            'provider': 'toyoko', 'booking_ref': latest['hotel_name'] + ' / ' + ', '.join(references),
            'booking_numbers': list(references), 'hotel_name': latest['hotel_name'],
            'event_type': 'reservation', 'paid_on': None, 'paid_on_semantics': 'missing',
            'amount': value, 'currency': currency,
            'amount_krw': int(Decimal(value)) if currency == 'KRW' and value is not None
                          and Decimal(value) == Decimal(value).to_integral_value() else None,
            'card_last4': None, 'card_issuer': None, 'item': '숙박비',
            'service_period': latest['period'] if latest['period']['starts_on'] else None,
            'reservation_status': 'cancelled' if cancellations else 'confirmed',
            'payment_status': 'unknown', 'evidence_status': 'evidence_conflict' if after_cancel else 'reservation_only',
            'evidence_kind': 'owner_reservation_mail', 'payment_event_id': None,
            'source_ids': source_ids, 'identity_source_ids': [identity],
            'source_digest': core._digest(source_digests), 'source_digests': source_digests,
            'source_lineage_ids': [identity],
            'observation_ids': sorted({'obs_' + core._digest([identity, o['source_id']]) for o in observations}),
            'source_inventory': list(inventory), 'ota_event_id': core._event_id([identity]),
            'reservation_group_only': group, 'individual_payment_evidence': False,
            'reservation_observed_on': sorted({o['sent'] for o in observations if o['sent']}),
        })
    return events


def search_candidates(event, transactions, *, max_comparisons=250000):
    """원문 통화·소계/합계·지점·시점을 비교하는 읽기 전용 후보. 점유나 확정 권한은 없다."""
    from app import ota_payments as core

    if event.get('evidence_status') == 'evidence_conflict' or not event.get('service_period'):
        return {'status': 'RESERVATION_EVIDENCE_INCOMPLETE', 'candidates': [], 'comparisons': 0}
    amount_known = event.get('amount') not in (None, '') and bool(event.get('currency'))
    try:
        expected = Decimal(str(event.get('amount'))) if amount_known else None
        start = date.fromisoformat(event['service_period']['starts_on'])
        end = date.fromisoformat(event['service_period']['ends_on'])
        if (amount_known and (not expected.is_finite() or expected <= 0)) or end <= start:
            raise ValueError
    except (InvalidOperation, ValueError, KeyError, TypeError):
        return {'status': 'RESERVATION_AMOUNT_OR_PERIOD_UNKNOWN', 'candidates': [], 'comparisons': 0}
    currency = event.get('currency')
    candidates, rejected = [], []
    counts = Counter()
    comparisons = 0
    sent_days = [date.fromisoformat(day) for day in event.get('reservation_observed_on', ())]
    for row in transactions:
        merchant = row.get('merchant') or row.get('merchant_normalized') or ''
        compact = re.sub(r'[^a-z가-힣0-9]', '', merchant.casefold())
        if not compact.startswith(('toyokoinn', '토요코인')):
            continue
        branch_known = compact.startswith('토요코인') and bool(booking_evidence._direct_hotel_key(merchant))
        if compact.startswith('토요코인') and not booking_evidence.direct_hotel_branch_matches(event, merchant):
            continue
        if row.get('duplicate_of') or row.get('parse_error') or row.get('conflict_reason') or row.get('ota_review_held'):
            counts['CARD_FINANCIAL_HOLD'] += 1
            continue
        if core._direction(row) != 'purchase' or not core._strict_card_identity(event, row):
            continue
        if row.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed'):
            counts['CARD_REFUND_HOLD'] += 1
            continue
        try:
            card_day = date.fromisoformat(str(row.get('approval_date') or row.get('posting_date'))[:10])
        except ValueError:
            continue
        in_stay = start - timedelta(days=1) <= card_day <= end + timedelta(days=1)
        if not in_stay and not any(abs((card_day - sent).days) <= booking_evidence.WINDOW_DAYS for sent in sent_days):
            continue
        comparisons += 1
        if comparisons > max_comparisons:
            return {'status': 'SEARCH_LIMIT_EXCEEDED', 'candidates': [], 'comparisons': comparisons}
        try:
            actual_raw = row.get('amount_krw') if currency == 'KRW' else row.get('foreign_amount')
            actual = Decimal(str(actual_raw)) if actual_raw not in (None, '') else None
            card_currency = str(row.get('foreign_currency') or '').upper()
            # 해외 결제의 원화 환산액을 국내 호텔 예약금액과 비교하지 않는다.
            same_currency = ((branch_known and card_currency in ('', 'KRW')) if currency == 'KRW'
                             else card_currency == currency)
            valid_actual = actual is not None and actual.is_finite() and actual > 0
            matches = amount_known and same_currency and valid_actual and actual == expected
        except InvalidOperation:
            same_currency = False
            valid_actual = False
            matches = False
        period_only = (not matches and branch_known and in_stay and
                       (not amount_known or (valid_actual and same_currency)))
        if not matches and not period_only:
            counts['NATIVE_AMOUNT_MISMATCH_OR_MISSING'] += 1
            continue
        identity = str(row.get('transaction_id') or '')
        if event.get('reservation_status') == 'cancelled':
            rejected.append({'transaction_id': identity, 'reason': 'RESERVATION_CANCELLED'})
            continue
        candidates.append({'transaction_id': identity, 'date_status': 'UNKNOWN', 'resolution_allowed': False,
            'basis': ('HOTEL_BRANCH_AND_STAY_ONLY' if period_only else 'RESERVATION_GROUP_TOTAL_ONLY'
                      if event.get('reservation_group_only') else 'RESERVATION_NATIVE_AMOUNT'),
            'amount_status': ('UNKNOWN' if not amount_known else 'MISMATCH' if period_only else 'MATCH'),
            'confidence': 'LOW' if period_only else 'HIGH',
            'stay_date_status': 'MATCH' if in_stay else 'UNKNOWN'})
    return {'status': 'CANDIDATES_FOUND' if candidates else 'NO_CANDIDATE',
            'candidates': candidates, 'rejected': rejected, 'comparisons': comparisons,
            'date_status': 'UNKNOWN', 'rejection_counts': dict(counts), 'reservation_only': True}
