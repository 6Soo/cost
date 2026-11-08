"""Authenticated NICE forest card receipts, separate from reservation notices."""
from datetime import datetime, timedelta
import re
from app import ota_mail

DOMAINS = ('nicepg.co.kr',)
LABELS = ('결제수단', '상점명', '상품명', '주문번호', '결제일시', '승인번호', '결제금액', '취소금액')
IDENTITY_LABELS = LABELS[:-2]


def _fields(text):
    pattern = '|'.join('(' + r'\s*'.join(label) + ')' for label in LABELS)
    markers = list(re.finditer(pattern, text))
    fields = {}
    for index, marker in enumerate(markers):
        name = LABELS[next(i for i, value in enumerate(marker.groups()) if value is not None)]
        segment = text[marker.end():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
        value = segment.strip(' \t\r\n:：')
        fields.setdefault(name, set()).add(value)
    return fields


def collect(messages, inventory=()):
    from app import ota_payments as core
    events = []
    for message_id, message in sorted(messages.items()):
        auth = ota_mail.authenticated_headers(message, DOMAINS)
        if auth is None:
            continue
        subject = auth[0].get('subject', '')
        cancelled = bool(re.search(r'취소', subject))
        if '환불' in subject and not cancelled:
            continue
        text = ota_mail.message_text(message)
        fields = _fields(text)
        if any(len(fields.get(label, ())) != 1 for label in IDENTITY_LABELS):
            continue
        # A cancellation can show both the original payment and a partial
        # cancellation amount. Only the latter describes this notice.
        amount_label = '취소금액' if cancelled and fields.get('취소금액') else '결제금액'
        if not fields.get(amount_label) or (not cancelled and fields.get('취소금액')):
            continue
        values = {label: next(iter(fields[label])) for label in IDENTITY_LABELS}
        if any(not value for value in values.values()):
            continue
        merchant = values['상점명'].splitlines()[0].strip()
        if not re.search(r'자연\s*휴양림|휴양시설|산림\s*치유원|숲나들e', merchant):
            continue
        method = values['결제수단']
        if not re.search(r'신용\s*카드|체크\s*카드', method):
            continue
        amounts = [re.match(r'([0-9][0-9,]*)\s*원\b', raw, re.I) for raw in fields[amount_label]]
        approval = re.fullmatch(r'[0-9]{6,12}', values['승인번호'].splitlines()[0].strip())
        order = re.fullmatch(r'[A-Za-z0-9_-]{6,64}', values['주문번호'].splitlines()[0].strip())
        stamp = re.fullmatch(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', values['결제일시'].splitlines()[0].strip())
        if not all((approval, order, stamp)) or not all(amounts):
            continue
        if set(approval[0]) == {'0'}:
            continue
        try:
            parsed_amounts = {ota_mail.decimal_amount(amount[1]) for amount in amounts}
            if len(parsed_amounts) != 1 and not cancelled:
                continue
            value = next(iter(parsed_amounts)) if len(parsed_amounts) == 1 else None
            paid_on = datetime.fromisoformat(stamp[0]).date()
        except (ValueError, ArithmeticError):
            continue
        sent = ota_mail.sent_day(message, auth[0])
        if ((not cancelled and (value is None or value <= 0 or value != value.to_integral_value()))
                or (sent and paid_on > sent + timedelta(days=1))):
            continue
        issuers = {name for name in ('국민', '하나', '기업', '신한', '삼성', '현대', '롯데', '우리')
                   if name in method}
        source = 'mail:' + message_id
        payment = 'nice-forest:' + core._digest([merchant, order[0], approval[0], paid_on.isoformat()])
        digest = core._digest(message)
        event = {
            'provider': 'forest', 'booking_ref': None, 'event_type': 'charge',
            'amount': int(value) if value is not None else None,
            'amount_krw': int(value) if value is not None else None, 'currency': 'KRW',
            'paid_on': paid_on.isoformat(), 'paid_on_semantics': 'explicit_charge_date',
            'approval_number': approval[0], 'authorization_scheme': 'issuer_card_approval',
            'card_issuer': next(iter(issuers)) if len(issuers) == 1 else None, 'card_last4': None,
            'item': '숲나들e 숙박 · 카드 결제 영수증', 'service_period': None,
            'reservation_status': 'unknown', 'payment_status': 'paid', 'evidence_status': 'paid_verified',
            'evidence_kind': 'authenticated_forest_pg_card_receipt', 'refund_status': 'none_displayed',
            'payment_evidence_basis': 'NICE 인증 카드 영수증 · 명시 승인번호·결제일·원화 금액 대조',
            'payment_id': payment, 'payment_event_id': 'pay_' + core._digest(payment),
            'source_ids': [source], 'identity_source_ids': [source],
            'source_digest': digest, 'source_digests': [digest],
            'source_lineage_ids': ['mail_' + core._digest(source)],
            'observation_ids': ['obs_' + core._digest([source, 'forest_pg_card_receipt'])],
            'source_inventory': list(inventory), 'ota_event_id': core._event_id([source]),
        }
        if cancelled:
            # A gateway cancellation notice is evidence, not proof that the
            # bank has refunded or that the accommodation was cancelled.
            cancelled_on = None
            explicit = set(re.findall(r'취소\s*(?:요청\s*)?일시\s*[:：]?\s*(\d{4}-\d{2}-\d{2})', text))
            if len(explicit) == 1:
                try:
                    cancelled_on = datetime.fromisoformat(next(iter(explicit))).date().isoformat()
                except ValueError:
                    pass
            event.update(event_type='cancellation_notice', paid_on=None,
                         paid_on_semantics='missing', cancelled_on=cancelled_on,
                         cancellation_notice_sent_on=sent.isoformat() if sent else None,
                         item='숲나들e 카드 취소 영수증 · 은행 환급 별도 확인',
                         payment_status='unknown', evidence_status='not_card_charge',
                         evidence_kind='authenticated_forest_pg_cancellation_notice',
                         payment_evidence_basis='NICE 인증 카드 취소 안내 · 예약 취소/은행 환급은 별도 확인')
        events.append(event)
    return events
