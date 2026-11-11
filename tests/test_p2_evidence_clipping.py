import json

from app.p2_source_io import bounded_payload
from app.p2_case import PORTAL_EVIDENCE_FIELDS


def test_large_mail_body_is_bounded_and_marks_omitted_content():
    payload = {'body': {'content': '<style>x</style>' + ('예약번호 ABC123 금액 1000 ' * 20000)}}
    bounded = bounded_payload(payload)
    text = bounded['body']['content']
    assert len(text.encode('utf-8')) < 100 * 1024
    assert '[생략:' in text
    assert '예약번호' in text


def test_portal_evidence_allowlist_excludes_raw_payload():
    record = {'booking_number': 'B', 'payload_json': 'x' * 10_000_000, 'status': 'paid'}
    selected = {key: value for key, value in record.items() if key in PORTAL_EVIDENCE_FIELDS}
    assert selected == {'booking_number': 'B', 'status': 'paid'}
