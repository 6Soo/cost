"""Synthetic-only Airbnb parser vectors. Expected outputs come from the unchanged Python parser.

Run ``python -X utf8 -m tools.core_bridge.airbnb_golden`` to create the golden file. The input
carries what the shared mail helpers compute in Python (authentication subject, body text, the
KST send date) so the Rust slice can be compared on the decisions it owns. No customer originals
or source locations are accepted here; inventory in the golden is synthetic.
"""
import hashlib
import json
from pathlib import Path

from app import airbnb_mail, mail_collect, ota_mail

GOLDEN = Path(__file__).resolve().parents[2] / 'core' / 'golden' / 'synthetic' / 'airbnb_mail.jsonl'


def message(subject, body, sender='automated@airbnb.com', date='Wed, 13 May 2026 02:38:11 +0000'):
    return mail_collect.owner_record('synthetic', {'From': sender, 'Subject': subject, 'Date': date}, body)


def confirmed(code='HMSYNTH001', subject='예약 확정: 5월 16일~17일 여행에 대한 에어비앤비 영수증', **values):
    return message(subject, f'체크인 체크아웃 5월 16일 (토) 5월 17일 (일)\n확인 코드 {code}', **values)


def stages(record):
    """What the Python shared helpers hand to the Rust slice."""
    auth = ota_mail.authenticated_headers(record, ('airbnb.com',))
    headers = auth[0] if auth else None
    subject = str(headers.get('subject') or '') if headers else None
    sent = ota_mail.sent_day(record, headers) if headers else None
    return {'message': record, 'subject': subject,
            'raw_text': ota_mail.message_text(record),
            'sent_day': sent.isoformat() if sent else None}


def case(case_id, messages, inventory=()):
    payload = {'messages': {mid: stages(record) for mid, record in messages.items()},
               'inventory': list(inventory)}
    events = airbnb_mail.collect(messages, inventory)
    text = json.dumps({'events': events}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {'case_id': case_id, 'input': payload, 'expected': {'events': events},
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'bytes': len(text.encode('utf-8')), 'chars': len(text)}


def inputs():
    yield 'confirmation', {'m1': confirmed()}
    yield 'year-crossing-subject', {'m1': message(
        '예약 확정: 12월 28일~1월 3일 여행에 대한 에어비앤비 영수증',
        '확인 코드 HMSYNTH002', date='Wed, 13 Dec 2026 02:38:11 +0000')}
    yield 'late-receipt-next-year', {'m1': message(
        '예약 확정: 1월 3일~1월 9일 여행에 대한 에어비앤비 영수증',
        '확인 코드 HMSYNTH003', date='Wed, 13 Dec 2026 02:38:11 +0000')}
    yield 'exactly-31-days-stays-in-year', {'m1': message(
        '예약 확정: 4월 12일~4월 14일', '확인 코드 HMSYNTH029', date='Wed, 13 May 2026 02:38:11 +0000')}
    yield 'exactly-32-days-rolls-to-next-year', {'m1': message(
        '예약 확정: 4월 11일~4월 14일', '확인 코드 HMSYNTH030', date='Wed, 13 May 2026 02:38:11 +0000')}
    yield 'exactly-60-days-allowed', {'m1': message(
        '예약 확정: 5월 16일~7월 15일', '확인 코드 HMSYNTH031', date='Wed, 13 May 2026 02:38:11 +0000')}
    yield 'leap-start-follows-send-year', {'m1': message(
        '예약 확정: 2월 29일~3월 2일', '확인 코드 HMSYNTH032', date='Thu, 13 Jan 2028 02:38:11 +0000')}
    yield 'same-day-rejected', {'m1': message('예약 확정: 5월 16일~16일', '확인 코드 HMSYNTH004')}
    yield 'over-sixty-days-rejected', {'m1': message('예약 확정: 5월 16일~7월 20일', '확인 코드 HMSYNTH005')}
    yield 'zero-end-month-falls-back', {'m1': message(
        '예약 확정: 5월 16일~０월 20일', '확인 코드 HMSYNTH006')}
    yield 'february-29-non-leap', {'m1': message(
        '예약 확정: 2월 29일~3월 2일', '확인 코드 HMSYNTH007', date='Sat, 13 Feb 2027 02:38:11 +0000')}
    yield 'february-29-leap', {'m1': message(
        '예약 확정: 2월 29일~3월 2일', '확인 코드 HMSYNTH008', date='Sun, 13 Feb 2028 02:38:11 +0000')}
    yield 'february-29-year-plus-one-also-invalid', {'m1': message(
        '예약 확정: 2월 29일~3월 2일', '확인 코드 HMSYNTH028', date='Wed, 13 Jan 2027 02:38:11 +0000')}
    yield 'cancellation-marks-same-code', {'m1': confirmed(), 'm2': message(
        '예약이 취소되었습니다 - HMSYNTH001', '확인 코드 HMSYNTH001', date='Thu, 14 May 2026 02:38:11 +0000')}
    yield 'reconfirmed-after-cancel-stays-cancelled', {
        'm1': confirmed(), 'm2': message('예약이 취소되었습니다 - HMSYNTH001', '확인 코드 HMSYNTH001'),
        'm3': confirmed(subject='예약 확정 안내: 6월 1일~6월 3일', date='Fri, 15 May 2026 02:38:11 +0000')}
    yield 'cancel-only-code-has-no-event', {'m1': message(
        '예약이 취소되었습니다 - HMSYNTH009', '확인 코드 HMSYNTH009')}
    yield 'cancel-wins-when-both-match', {'m1': message(
        '예약 확정: 5월 16일~17일 예약이 취소되었습니다', '확인 코드 HMSYNTH010')}
    yield 'two-confirmations-conflict', {
        'm1': confirmed(code='HMSYNTH011'),
        'm2': confirmed(code='HMSYNTH011', subject='예약 확정 안내: 6월 1일~6월 3일',
                        date='Fri, 15 May 2026 02:38:11 +0000')}
    yield 'same-period-two-mails-no-conflict', {
        'm1': confirmed(code='HMSYNTH012'),
        'm2': confirmed(code='HMSYNTH012', date='Thu, 14 May 2026 02:38:11 +0000')}
    yield 'two-codes-in-body-ignored', {'m1': message(
        '예약 확정: 5월 16일~17일', '확인 코드 HMSYNTH013 HMSYNTH014')}
    yield 'subject-code-does-not-count', {'m1': message(
        '예약 확정: 5월 16일~17일 HMSYNTH015', '본문에 코드 없음')}
    yield 'lowercase-code-ignored', {'m1': message('예약 확정: 5월 16일~17일', '확인 코드 hmsynth016')}
    yield 'nl-neighbour-blocks-code', {'m1': message('예약 확정: 5월 16일~17일', 'ⅣHMSYNTH017')}
    yield 'fullwidth-month-day', {'m1': message('예약 확정: ５月 １６일~１７일', '확인 코드 HMSYNTH018')}
    yield 'unit-separator-in-subject', {'m1': message(
        '예약 확정\x1c:\x1c5월 16일~17일', '확인 코드 HMSYNTH019')}
    yield 'unauthenticated-sender', {'m1': message(
        '예약 확정: 5월 16일~17일', '확인 코드 HMSYNTH020', sender='x@airbnb.com.example')}
    yield 'invalid-subject-not-confirmed', {'m1': message('안내: 예약 확정: 5월 16일~17일', '확인 코드 HMSYNTH021')}
    yield 'duplicate-digest-rows', {
        'm1': confirmed(code='HMSYNTH022'),
        'm2': confirmed(code='HMSYNTH022', date='Thu, 14 May 2026 02:38:11 +0000')}
    yield 'message-order-m2-before-m10', {
        'm2': confirmed(code='HMSYNTH023', date='Tue, 12 May 2026 02:38:11 +0000'),
        'm10': confirmed(code='HMSYNTH023', date='Thu, 14 May 2026 02:38:11 +0000')}
    yield 'inventory-passthrough', {'m1': confirmed(code='HMSYNTH024')}, \
        [{'kind': 'mail_directory', 'path': 'synthetic/inbox', 'messages': 1, 'collection': {}}]
    yield 'two-codes-both-observed', {
        'm1': confirmed(code='HMSYNTH025'),
        'm2': confirmed(code='HMSYNTH026', date='Thu, 14 May 2026 02:38:11 +0000')}


def build():
    records = [case(case_id, messages, inventory) for case_id, messages, *rest in inputs()
               for inventory in [rest[0] if rest else ()]]
    lines = ''.join(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n' for record in records)
    if GOLDEN.exists():
        raise SystemExit(f'{GOLDEN} already exists; refusing to overwrite')
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_bytes(lines.encode('utf-8'))
    return len(records), GOLDEN


if __name__ == '__main__':
    count, path = build()
    print(f'{count} cases -> {path}')
