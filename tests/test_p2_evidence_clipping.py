import json

import pytest

from app.p2_source_io import bounded_payload
from app.p2_case import PORTAL_EVIDENCE_FIELDS
from webapp.tests.test_autonomous_cleanup import setup
from tests.test_p2_case import prepared


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


def test_guarded_mail_load_detects_conflict_beyond_clipping_boundary(tmp_path):
    from app import ota_mail, p2_source_io
    messages = [dict(id='same', internal_date='1', payload={
        'headers': [], 'body': {'content': 'A' * 100000 + suffix * 30000}})
        for suffix in ('X', 'Y')]
    (tmp_path / 'gmail-test.json').write_text(json.dumps({'responses': messages}), encoding='utf-8')
    before = (tmp_path / 'gmail-test.json').read_bytes()
    with p2_source_io.guarded(lambda: None, lambda *a, **kw: None):
        with pytest.raises(ValueError, match='OTA_MESSAGE_CONTENT_CONFLICT'):
            ota_mail._load_messages_uncached([tmp_path])
    assert (tmp_path / 'gmail-test.json').read_bytes() == before


def test_guarded_large_base64_mail_keeps_original_text(tmp_path):
    import base64
    from app import ota_mail, p2_source_io
    text = '가나다' * 40000 + ' 예약번호 TAIL123 금액 10000'
    message = dict(id='same', internal_date='1', payload={'headers': [], 'body': {
        'data': base64.urlsafe_b64encode(text.encode()).decode()}})
    (tmp_path / 'gmail-test.json').write_text(json.dumps({'responses': [message, message]}), encoding='utf-8')
    with p2_source_io.guarded(lambda: None, lambda *a, **kw: None):
        messages, _ = ota_mail._load_messages_uncached([tmp_path])
    assert len(messages) == 1
    assert ota_mail.message_text(messages['same']).strip() == text


def test_real_mail_assembly_keeps_tail_evidence_and_marks_truncation(setup, tmp_path):
    import base64
    from app import p2_case
    request, trips = prepared(setup)
    tail = 'AUTONOMY 예약번호 TAIL123 금액 KRW 10000 이용일 2026-10-01'
    text = '소개 문장입니다. ' * 30000 + tail
    message = dict(id='large', internal_date='1', payload={'headers': [], 'body': {
        'data': base64.urlsafe_b64encode(text.encode()).decode()}})
    path = tmp_path / 'gmail-test.json'
    path.write_text(json.dumps({'responses': [message]}), encoding='utf-8')
    before = path.read_bytes()
    bundle = p2_case.assemble(setup.conn, trips, request,
        repository=p2_case.Repository(setup.conn, {'mail_directories': [tmp_path]}))
    mail = [e for e in bundle['evidence'] if e['kind'] == 'mail']
    assert len(mail) == 1
    assert all(word in mail[0]['content'] for word in ('TAIL123', '10000', '2026-10-01', '[생략:'))
    assert mail[0]['truncated'] and bundle['truncated']
    assert len(p2_case.prompt(bundle).encode()) <= p2_case.MAX_BYTES
    assert path.read_bytes() == before


def test_portal_raw_payload_cannot_select_unrelated_record(setup, tmp_path, monkeypatch):
    from app import p2_case, ota_portal
    request, trips = prepared(setup)
    path = tmp_path / 'portal.json'
    path.write_text('[]', encoding='utf-8')
    monkeypatch.setattr(ota_portal, '_read_records', lambda *a: [
        {'booking_number': 'UNRELATED', 'payload_json': json.dumps({'raw_html': 'AUTONOMY 10000 2026-10-01'})}])
    repo = p2_case.Repository(setup.conn, {'portal_databases': [path]})
    bundle = p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert not any(e['kind'] == 'portal' for e in bundle['evidence'])


def test_portal_nested_decision_fields_are_searchable_without_raw_payload(setup, tmp_path, monkeypatch):
    from app import p2_case, ota_portal
    request, trips = prepared(setup)
    path = tmp_path / 'portal.json'
    path.write_text('[]', encoding='utf-8')
    fact = {'provider': 'AUTONOMY', 'card_last4': '1234', 'payment_status': 'paid',
            'price_components': [{'kind': 'paid_today', 'currency': 'KRW', 'decimal_text': '10000',
                                  'scale': 0, 'minor_units': 10000, 'raw_html': 'PRIVATE_RAW'}],
            'raw_html': 'PRIVATE_RAW'}
    monkeypatch.setattr(ota_portal, '_read_records', lambda *a: [
        {'booking_number': 'B', 'status': 'confirmed', 'payload_json': json.dumps(fact)}])
    bundle = p2_case.assemble(setup.conn, trips, request,
        repository=p2_case.Repository(setup.conn, {'portal_databases': [path]}))
    items = [e for e in bundle['evidence'] if e['kind'] == 'portal']
    assert len(items) == 1
    assert '10000' in items[0]['content'] and 'paid' in items[0]['content']
    assert 'PRIVATE_RAW' not in p2_case.prompt(bundle)
    assert 'payload_json' not in items[0]['content']


def test_real_portal_loader_projects_nested_payment_facts(setup, tmp_path):
    from app import p2_case, ota_portal
    from tests.card_pipeline.test_ota_portal import portal_database
    request, trips = prepared(setup)
    path = portal_database(tmp_path / 'portal.sqlite', facts=[{
        'provider': 'AUTONOMY', 'raw_html': 'PRIVATE_RAW',
        'price_components': [{'kind': 'paid_today', 'currency': 'KRW',
            'decimal_text': '10000', 'minor_units': 10000, 'scale': 0}]}])
    before = path.read_bytes()
    records = ota_portal._read_records(path, 0)
    assert records and 'provider' not in records[0]
    bundle = p2_case.assemble(setup.conn, trips, request,
        repository=p2_case.Repository(setup.conn, {'portal_databases': [path]}))
    items = [e for e in bundle['evidence'] if e['kind'] == 'portal']
    assert items and all('10000' in e['content'] and 'paid' in e['content'] for e in items)
    assert 'PRIVATE_RAW' not in p2_case.prompt(bundle)
    assert path.read_bytes() == before


def test_malformed_portal_payload_preserves_only_top_level_facts():
    from app.p2_case import portal_content
    assert portal_content({'booking_number': 'B', 'payload_json': 'raw text'}) == {'booking_number': 'B'}
