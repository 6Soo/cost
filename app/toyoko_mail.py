"""토요코인 예약 원문을 중앙 대사의 비금전 예약 근거로 연결한다."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

from app import booking_evidence, ota_mail

DOMAINS = ('toyoko-inn.com', 'toyoko-inn.co.jp')
REFERENCE = re.compile(r'예약\s*번호\s*[:：]\s*([0-9]{7,20})(?![0-9])')
SUBJECT_KEYWORD = re.compile(r'토요코인|toyoko', re.I)


def _headers(message):
    if not isinstance(message, dict):
        return None
    payload = message.get('payload')
    if not isinstance(payload, dict):
        return None
    headers = payload.get('headers')
    if not isinstance(headers, list):
        return None
    result = {}
    for header in headers:
        if (not isinstance(header, dict) or not isinstance(header.get('name'), str)
                or not isinstance(header.get('value'), str)):
            return None
        result[header['name'].lower()] = header['value']
    return result


def _amounts(text, label):
    values = set()
    for number, unit in re.findall(label + r'\s*[:：]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(원|엔)', text):
        if ',' in number and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', number):
            continue
        try:
            number = Decimal(number.replace(',', ''))
        except InvalidOperation:
            continue
        if number.is_finite() and number > 0:
            values.add(('KRW' if unit == '원' else 'JPY', str(number)))
    return values


def _cancelled_subject(subject):
    return bool(re.search(r'(?:취소\s*(?:확인|완료|접수)|취소\s*되었습니다|cancel(?:led|ed|lation\s+confirmed))',
                          subject, re.I))


def _room_facts(text):
    room_type = ''
    guests = None
    for pattern in (r'(?:객실\s*타입|객실\s*종류|룸\s*타입)\s*[:：]\s*([^\r\n]{1,80})',
                    r'(?:Room\s*type)\s*[:：]\s*([^\r\n]{1,80})'):
        match = re.search(pattern, text, re.I)
        if match:
            room_type = match[1].strip()
            break
    match = re.search(r'(?:투숙\s*인원|인원)\s*[:：]\s*(\d+)\s*명?', text)
    if match:
        guests = int(match[1])
    nightly = []
    for label, number, unit in re.findall(
            r'((?:\d+\s*박째\s*금액|박별\s*금액|1박\s*금액))\s*[:：]\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(원|엔)',
            text):
        if ',' in number and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', number):
            continue
        try:
            value = Decimal(number.replace(',', ''))
        except InvalidOperation:
            continue
        if value.is_finite() and value > 0:
            nightly.append({'label': re.sub(r'\s+', '', label),
                            'amount': str(value), 'currency': 'KRW' if unit == '원' else 'JPY'})
    return {'room_type': room_type, 'guest_count': guests, 'nightly_amounts': nightly}


def collect(messages, inventory=()):
    """객실별 소계와 묶음 합계를 분리하며 예약 확인을 결제로 승격하지 않는다."""
    from app import ota_payments as core

    groups = defaultdict(list)
    for message_id, message in sorted(messages.items()):
        raw_headers = _headers(message)
        if raw_headers is None:
            continue
        subject = raw_headers.get('subject', '')
        if not isinstance(subject, str):
            continue
        auth = ota_mail.authenticated_headers(message, DOMAINS)
        if not auth and not SUBJECT_KEYWORD.search(subject):
            continue
        # A subject hit can be retained as untrusted reservation evidence. It never
        # passes through the payment parser or grants a card-link resolution.
        headers = auth[0] if auth else raw_headers
        text = ota_mail.message_text(message)
        parse_subject = subject if SUBJECT_KEYWORD.search(subject) else '토요코인 예약 확인'
        summary = booking_evidence.summarize(parse_subject, booking_evidence._sent_day(headers), text)
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
                  'cancelled': bool(auth and _cancelled_subject(subject)),
                  'reported_cancelled': _cancelled_subject(subject),
                  'source_trust': 'sender_domain' if auth else 'subject_only_unverified'}
        for index, marker in enumerate(markers):
            part = text[marker.start():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
            detail = booking_evidence.summarize(parse_subject, None, part)
            period = {k: detail[k] for k in ('starts_on', 'ends_on')}
            if not period['starts_on']:
                period = {k: summary[k] for k in ('starts_on', 'ends_on')}
            amounts = _amounts(part, r'소계\s*금액')
            if not amounts and len(references) == 1:
                amounts = _amounts(text, r'합계\s*금액')
            groups[(hotel_key, (marker[1],))].append(dict(common, period=period, amounts=amounts,
                                                           room_facts=_room_facts(part)))
        if len(references) > 1:
            groups[(hotel_key, tuple(references))].append(dict(common,
                period={k: summary[k] for k in ('starts_on', 'ends_on')},
                amounts=_amounts(text, r'합계\s*금액'), room_facts=_room_facts(text)))

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
            'reservation_status': 'cancelled' if cancellations else 'observed',
            'reported_reservation_status': 'cancelled' if latest['reported_cancelled'] else 'reservation_received',
            'payment_status': 'unknown', 'evidence_status': 'evidence_conflict' if after_cancel else 'reservation_only',
            'evidence_kind': 'subject_only_unverified_reservation' if latest['source_trust'] == 'subject_only_unverified'
                             else 'sender_domain_reservation_mail',
            'evidence_confidence': 'LOW' if latest['source_trust'] == 'subject_only_unverified' else 'MEDIUM',
            'source_trust': latest['source_trust'],
            'room_facts': latest['room_facts'], 'payment_event_id': None,
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
            krw_value = Decimal(str(row.get('amount_krw')))
            if not krw_value.is_finite() or krw_value <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            counts['CARD_INVALID_KRW_AMOUNT'] += 1
            continue
        try:
            card_day = date.fromisoformat(str(row.get('approval_date') or row.get('posting_date'))[:10])
        except ValueError:
            continue
        in_stay = start - timedelta(days=1) <= card_day <= end + timedelta(days=1)
        stay_match = start <= card_day <= end
        if not in_stay and not any(abs((card_day - sent).days) <= booking_evidence.WINDOW_DAYS for sent in sent_days):
            continue
        comparisons += 1
        if comparisons > max_comparisons:
            return {'status': 'SEARCH_LIMIT_EXCEEDED', 'candidates': [], 'comparisons': comparisons}
        card_currency = str(row.get('foreign_currency') or '').upper()
        has_foreign_amount = row.get('foreign_amount') not in (None, '')
        native_currency_incomplete = has_foreign_amount and not card_currency
        declared_currency = card_currency or str(row.get('currency') or '').upper()
        if declared_currency == 'KRW' and currency != 'KRW':
            declared_currency = ''
        currency_known = bool(declared_currency)
        try:
            actual_raw = row.get('amount_krw') if currency == 'KRW' else row.get('foreign_amount')
            actual = Decimal(str(actual_raw)) if actual_raw not in (None, '') else None
            # 해외 결제의 원화 환산액을 예약 원문 외화 금액과 비교하지 않는다.
            currency_known = bool(declared_currency)
            same_currency = ((branch_known and declared_currency in ('', 'KRW')) if currency == 'KRW'
                             else not currency_known or declared_currency == currency)
            valid_actual = actual is not None and actual.is_finite() and actual > 0
            matches = (amount_known and same_currency and valid_actual and actual == expected
                       and not native_currency_incomplete)
        except InvalidOperation:
            same_currency = False
            valid_actual = False
            matches = False
        comparable_currency = ((currency == 'KRW' and branch_known and declared_currency in ('', 'KRW'))
                               or (currency != 'KRW' and currency is not None
                                   and declared_currency == currency))
        explicit_currency_conflict = bool(currency and card_currency and card_currency != currency)
        if explicit_currency_conflict:
            counts['NATIVE_CURRENCY_MISMATCH'] += 1
            continue
        period_only = not matches and in_stay
        if not branch_known and not stay_match:
            counts['BRANCHLESS_OUTSIDE_STAY'] += 1
            continue
        if not matches and not period_only:
            counts['NATIVE_AMOUNT_MISMATCH_OR_MISSING'] += 1
            continue
        identity = str(row.get('transaction_id') or '')
        if event.get('reservation_status') == 'cancelled':
            rejected.append({'transaction_id': identity, 'reason': 'RESERVATION_CANCELLED'})
            continue
        candidates.append({'transaction_id': identity, 'date_status': 'UNKNOWN', 'resolution_allowed': False,
            'basis': ('RESERVATION_GROUP_TOTAL_ONLY' if event.get('reservation_group_only') else
                      'PROVIDER_AND_STAY_ONLY' if not branch_known else
                      'HOTEL_BRANCH_AND_STAY_ONLY' if period_only else 'RESERVATION_NATIVE_AMOUNT'),
            'amount_status': ('UNKNOWN' if not amount_known or not valid_actual or not comparable_currency
                              or native_currency_incomplete
                              else 'MISMATCH' if period_only else 'MATCH'),
            'branch_status': 'MATCH' if branch_known else 'UNKNOWN',
            'confidence': 'LOW' if period_only or not branch_known or not stay_match else 'HIGH',
            'stay_date_status': 'MATCH' if stay_match else 'UNKNOWN'})
    return {'status': 'CANDIDATES_FOUND' if candidates else 'NO_CANDIDATE',
            'candidates': candidates, 'rejected': rejected, 'comparisons': comparisons,
            'date_status': 'UNKNOWN', 'rejection_counts': dict(counts), 'reservation_only': True}
