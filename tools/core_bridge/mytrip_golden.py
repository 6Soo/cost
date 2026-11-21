"""Synthetic-only Mytrip/Gotogate parser vectors. Expected outputs come from the unchanged Python parser.

Run ``python -X utf8 -m tools.core_bridge.mytrip_golden`` to create the golden file. The input
carries what the shared mail helpers compute in Python (subject, body text, KST send date), so
the Rust slice is compared on the decisions it owns. Synthetic only; no customer originals.
"""
import hashlib
import json
from pathlib import Path

from app import mail_collect, mytrip_mail, ota_mail
from tools.core_bridge.synthetic_golden import write_jsonl

GOLDEN = Path(__file__).resolve().parents[2] / 'core' / 'golden' / 'synthetic' / 'mytrip_mail.jsonl'


def message(subject, body, sender='noreply@mytrip.com', date='Wed, 13 May 2026 02:38:11 +0000'):
    return mail_collect.owner_record('synthetic', {'From': sender, 'Subject': subject, 'Date': date}, body)


def confirmed(order='1234-567-890', body=None, **values):
    body = body if body is not None else (
        f'가는 편 • 2026년 5월 16일\n오는 편 • 2026년 5월 20일\n합계 250,000.00 KRW\n주문 번호 {order}')
    return message(f'여행이 확정되었습니다. 주문 번호 {order}', body, **values)


def stages(record):
    auth = ota_mail.authenticated_headers(record, mytrip_mail.DOMAINS)
    headers = auth[0] if auth else None
    subject = str(headers.get('subject') or '') if headers else None
    sent = ota_mail.sent_day(record, headers) if headers else None
    return {'message': record, 'subject': subject,
            'raw_text': ota_mail.message_text(record),
            'sent_day': sent.isoformat() if sent else None}


def case(case_id, messages, inventory=()):
    payload = {'messages': {mid: stages(record) for mid, record in messages.items()},
               'inventory': list(inventory)}
    events = mytrip_mail.collect(messages, inventory)
    text = json.dumps({'events': events}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {'case_id': case_id, 'input': payload, 'expected': {'events': events},
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'bytes': len(text.encode('utf-8')), 'chars': len(text)}


def inputs():
    yield 'confirmation', {'m1': confirmed()}
    yield 'single-leg', {'m1': message(
        '여행이 확정되었습니다. 주문 번호 1234-567-890',
        '가는 편 • 2026년 5월 16일\n합계 250,000.00 KRW\n주문 번호 1234-567-890')}
    yield 'invalid-leg-rejects-message', {'m1': confirmed(body=(
        '가는 편 • 2026년 2월 30일\n오는 편 • 2026년 3월 2일\n합계 250,000 KRW\n주문 번호 1234-567-890'))}
    yield 'year-zero-rejects-message', {'m1': confirmed(body=(
        '가는 편 • 0000년 5월 16일\n합계 1 KRW\n주문 번호 1234-567-890'))}
    yield 'span-366-allowed', {'m1': confirmed(body=(
        '가는 편 • 2026년 1월 1일\n오는 편 • 2027년 1월 2일\n합계 250,000 KRW\n주문 번호 1234-567-890'))}
    yield 'span-367-rejected', {'m1': confirmed(body=(
        '가는 편 • 2026년 1월 1일\n오는 편 • 2027년 1월 3일\n합계 250,000 KRW\n주문 번호 1234-567-890'))}
    yield 'total-without-decimals', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 1234-567-890'))}
    yield 'total-with-cents-rejected', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 250,000.50 KRW\n주문 번호 1234-567-890'))}
    yield 'two-spellings-reject-message', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 224,682 KRW\n합계 224682 KRW\n주문 번호 1234-567-890'))}
    yield 'other-currency-rejected', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 250,000.00 USD\n주문 번호 1234-567-890'))}
    yield 'zero-amount-rejected', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 0.00 KRW\n주문 번호 1234-567-890'))}
    yield 'no-order-in-body', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW'))}
    yield 'two-orders-in-body', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 1234-567-890 9999-888-777'))}
    yield 'withdrawal-propagates-and-sticks', {
        'm1': confirmed(),
        'm2': message('예약 취소 안내', '주문 번호 1234-567-890', date='Thu, 14 May 2026 02:38:11 +0000'),
        'm3': confirmed(date='Fri, 15 May 2026 02:38:11 +0000')}
    yield 'withdrawal-only-has-no-event', {'m1': message(
        '예약 취소 안내', '주문 번호 1234-567-890')}
    yield 'conflict-clears-amount-and-period', {
        'm1': confirmed(),
        'm2': confirmed(body=(
            '가는 편 • 2026년 5월 17일\n합계 250,000 KRW\n주문 번호 1234-567-890'),
            date='Thu, 14 May 2026 02:38:11 +0000')}
    yield 'same-amount-two-rows-no-conflict', {
        'm1': confirmed(),
        'm2': confirmed(date='Thu, 14 May 2026 02:38:11 +0000')}
    yield 'fullwidth-order-in-body', {'m1': confirmed(body=(
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 １２３４-５６７-８９０'))}
    yield 'night-bullet-rejected', {'m1': confirmed(body=(
        '가는 편 ・ 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 1234-567-890'))}
    yield 'unit-separator-whitespace', {'m1': message(
        '여행이\x1c확정되었습니다.\x1c주문\x1c번호\x1c1234-567-890',
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 1234-567-890')}
    yield 'unanauthenticated-sender', {'m1': message(
        '여행이 확정되었습니다. 주문 번호 1234-567-890',
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 1234-567-890',
        sender='x@mytrip.com.example')}
    yield 'leading-noise-in-subject', {'m1': message(
        ' 안내: 여행이 확정되었습니다. 주문 번호 1234-567-890',
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 1234-567-890')}
    yield 'trailing-newline-in-subject', {'m1': message(
        '여행이 확정되었습니다. 주문 번호 1234-567-890\n',
        '가는 편 • 2026년 5월 16일\n합계 250,000 KRW\n주문 번호 1234-567-890')}
    yield 'message-order-m2-before-m10', {
        'm2': confirmed(date='Tue, 12 May 2026 02:38:11 +0000'),
        'm10': confirmed(date='Thu, 14 May 2026 02:38:11 +0000')}
    yield 'inventory-passthrough', {'m1': confirmed()}, \
        [{'kind': 'mail_directory', 'path': 'synthetic/inbox', 'messages': 1, 'collection': {}}]
    yield 'two-orders-both-observed', {
        'm1': confirmed(order='1234-567-890'),
        'm2': confirmed(order='2345-678-901', date='Thu, 14 May 2026 02:38:11 +0000')}


def build():
    records = [case(case_id, messages, inventory) for case_id, messages, *rest in inputs()
               for inventory in [rest[0] if rest else ()]]
    return write_jsonl(GOLDEN, records)


if __name__ == '__main__':
    count, path = build()
    print(f'{count} cases -> {path}')
