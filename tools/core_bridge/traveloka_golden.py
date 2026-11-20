"""Synthetic-only Traveloka parser vectors. Expected outputs come from the unchanged Python parser.

Run ``python -X utf8 -m tools.core_bridge.traveloka_golden`` to create the golden file. The input
carries what the shared mail helpers compute in Python (authentication, raw text, Cf-stripped text)
so the Rust unit can be compared on the decisions it owns. No customer originals or source
locations are accepted here.
"""
import base64
import hashlib
import json
import unicodedata
from pathlib import Path

from app import ota_mail, traveloka_mail

GOLDEN = Path(__file__).resolve().parents[2] / 'core' / 'golden' / 'synthetic' / 'traveloka_mail.jsonl'


def message(subject, body, sender='Traveloka <no-reply@traveloka.com>', owner=True, extra_headers=()):
    """One synthetic Gmail-shaped message; the body is plain text, base64url encoded as Gmail does."""
    headers = [{'name': 'From', 'value': sender}, {'name': 'Subject', 'value': subject}]
    headers.extend({'name': name, 'value': value} for name, value in extra_headers)
    encoded = base64.urlsafe_b64encode(body.encode('utf-8')).decode('ascii')
    record = {'payload': {'headers': headers, 'body': {'data': encoded}}}
    if owner:
        record['owner_collected'] = True
    return record


def cf_table():
    return {code: None for code in range(0x110000) if unicodedata.category(chr(code)) == 'Cf'}


def stages(record):
    """The bridge payload: what Python's shared mail helpers hand to the Rust unit."""
    authenticated = ota_mail.authenticated_headers(record, ('traveloka.com',))
    raw = ota_mail.message_text(record)
    return {'message': record,
            'subject': authenticated[0].get('subject', '') if authenticated else None,
            'raw_text': raw,
            'stripped_text': raw.translate(cf_table())}


def case(case_id, record):
    payload = stages(record)
    refs = traveloka_mail.references(record)
    fact = traveloka_mail.extract(record)
    text = json.dumps({'references': sorted(refs), 'fact': fact}, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))
    return {'case_id': case_id, 'input': payload,
            'expected': {'references': sorted(refs), 'fact': fact},
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'bytes': len(text.encode('utf-8')), 'chars': len(text)}


def inputs():
    reserve = '예약 ID: 123456789\n항공권 예약이 완료되었습니다.\n출발 항공편 2026년 6월 1일 인천 → 도쿄'
    yield 'reservation-without-fabricated-payment', message('Traveloka 항공권 예약 안내', reserve)
    paid = 'Booking ID: 987654321\n결제 금액 1,234,000원\n출발 항공편 2026년 6월 1일\n귀국 항공편 2026년 6월 5일'
    yield 'explicit-payment-subject-confirms', message('Traveloka payment successful e-ticket', paid)
    yield 'payment-body-without-subject-stays-reservation', message('Traveloka e-ticket', paid)
    yield 'cancel-notice-blocks-prior-charge', message(
        'Traveloka 항공권 결제 완료 취소 안내', paid + '\n취소가 접수되었습니다.')
    yield 'two-amounts-are-ambiguous', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1,200,000원\n300,000원')
    yield 'amount-and-comma-form-are-distinct', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1,230원\n1230원')
    yield 'lookbehind-rejects-inside-longer-number', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1234,567원')
    yield 'lookbehind-rejects-second-run', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1123,456원')
    yield 'unauthenticated-sender-domain', message(
        'Traveloka e-ticket payment complete', paid, sender='Traveloka <no-reply@traveloka.com.example>',
        owner=False, extra_headers=(('Authentication-Results', 'spf=fail dkim=fail'),))
    yield 'dkim-aligned-without-owner-flag', message(
        'Traveloka e-ticket payment complete', paid, owner=False,
        extra_headers=(('Authentication-Results', 'example.com; dkim=pass header.i=@traveloka.com'),))
    yield 'dkim-unaligned-stays-unauthorised', message(
        'Traveloka e-ticket payment complete', paid, owner=False,
        extra_headers=(('Authentication-Results', 'example.com; dkim=pass header.i=@mailer.example.com'),))
    yield 'reversed-date-form', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1,234,000원\n출발 항공편 1 6월 2026')
    yield 'invalid-calendar-date', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1,234,000원\n출발 항공편 2026년 2월 30일')
    yield 'fullwidth-digits', message(
        'Traveloka e-ticket payment complete', 'Booking ID: ９８７６５４３２１\n１２３４，０００원')
    yield 'soft-hyphen-stripped-from-body-only', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1,234,000­원')
    yield 'zero-amount-rejects-whole-fact', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n0원')
    yield 'two-booking-ids-are-ambiguous', message(
        'Traveloka e-ticket', '예약 ID: 123456789\nBooking ID: 987654321')
    yield 'refund-word-in-subject', message('Traveloka refund 완료', paid)
    yield 'no-flight-keyword-subject', message('Traveloka 예약 안내', paid)
    yield 'trailing-newline-stops-at-line-end', message(
        'Traveloka e-ticket payment complete', 'Booking ID: 987654321\n1,234,000원\n출발 항공편 2026년 6월 1일\n')
    yield 'unit-separator-whitespace', message(
        'Traveloka e-ticket payment\x1ccomplete', 'Booking ID:\x1c987654321\n1,234,000원')


def build():
    records = [case(case_id, record) for case_id, record in inputs()]
    lines = ''.join(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n' for record in records)
    if GOLDEN.exists():
        raise SystemExit(f'{GOLDEN} already exists; refusing to overwrite')
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_bytes(lines.encode('utf-8'))
    return len(records), GOLDEN


if __name__ == '__main__':
    count, path = build()
    print(f'{count} cases -> {path}')
