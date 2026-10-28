"""숲나들e 메일을 예약 식별과 결제 확정 권한이 없는 개별 관측으로 읽는다."""
import re
from email.utils import parseaddr

from app import ota_mail

DOMAINS = ('forest.go.kr', 'foresttrip.go.kr')
_NOTICE = re.compile(r'예약\s*(?:완료|취소|안내)|결제\s*(?:완료|기한|안내)')


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
        # Match the established mail authentication/owner-collected policy.
        trusted = ota_mail.authenticated_headers(message, DOMAINS) is not None
        cancelled = bool(re.search(r'예약\s*취소', subject))
        source_id = 'mail:' + message_id
        digest = core._digest(message)
        identity = 'forest:notice:' + core._digest(source_id)
        events.append({
            'provider': 'forest', 'booking_ref': None,
            'event_type': 'reservation', 'paid_on': None, 'paid_on_semantics': 'missing',
            'amount': None, 'amount_krw': None, 'currency': '',
            'card_last4': None, 'card_issuer': None,
            'item': ('숲나들e 예약 안내' if trusted else '숲나들e 발신 미검증 예약 안내')
                    + ' · 예약번호·금액·이용기간 미확인',
            'service_period': None,
            'reservation_status': 'cancelled' if trusted and cancelled else 'observed',
            'reported_reservation_status': 'cancelled' if cancelled else 'observed',
            'payment_status': 'unknown', 'evidence_status': 'reservation_only',
            'evidence_kind': 'sender_domain_reservation_notice' if trusted else 'unverified_reservation_notice',
            'evidence_confidence': 'LOW',
            'source_trust': 'sender_domain' if trusted else 'unverified_sender',
            'payment_event_id': None, 'individual_payment_evidence': False,
            'source_ids': [source_id], 'identity_source_ids': [identity],
            'source_digest': digest, 'source_digests': [digest],
            'source_lineage_ids': [identity],
            'observation_ids': ['obs_' + core._digest([identity, source_id])],
            'source_inventory': list(inventory), 'ota_event_id': core._event_id([identity]),
        })
    return events
