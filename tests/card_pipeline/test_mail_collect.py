import json
from datetime import datetime

from app import mail_collect, ota_mail


class FakeGmail:
    def __init__(self, messages):
        self.messages = messages
        self.queries = []

    def list_ids(self, query):
        self.queries.append(query)
        return list(self.messages)

    def get_full(self, message_id):
        return {'id': message_id, 'payload': {'headers': [{'name': 'Subject', 'value': message_id}]}}


def test_owner_collection_is_explicit_scoped_and_keeps_original_authentication():
    original = {'id': 'synthetic', 'payload': {'headers': [
        {'name': 'From', 'value': 'reservation@jejuair.net'},
        {'name': 'Authentication-Results', 'value': 'spf=none'}]}}
    assert mail_collect.owner_directed_record(original) is original
    owned = mail_collect.owner_directed_record(original, ('jejuair.net',))
    assert owned['owner_collected'] is True
    assert owned['payload'] == original['payload']
    assert 'owner_collected' not in original
    spoof = {'payload': {'headers': [{'name': 'From', 'value': 'x@jejuair.net.example'}]}}
    assert mail_collect.owner_directed_record(spoof, ('jejuair.net',)) is spoof


def test_query_always_includes_the_kew2000_recipient_and_the_supplier_domains():
    query = mail_collect.build_query('2026-10-02')
    assert query.startswith('after:2026/10/02 (')
    assert 'to:kew2000@hanmail.net' in query
    assert 'from:toyoko-inn.com' in query
    assert 'from:toyoko-inn.co.jp' in query
    assert 'from:forest.go.kr' in query
    assert 'from:foresttrip.go.kr' in query
    assert 'from:flyasiana.com' in query
    assert 'from:skyticket.com' in query
    assert 'from:jejuair.net' in query
    assert 'from:traveloka.com' in query
    assert 'subject:토요코인' in query
    for domain in mail_collect.SUPPLIER_DOMAINS:
        assert f'from:{domain}' in query


def test_query_preserves_always_collected_recipients_and_after_boundary():
    query = mail_collect.build_query('2026-10-02')
    assert query.startswith('after:2026/10/02 (')
    assert 'to:kew2000@hanmail.net OR cc:kew2000@hanmail.net' in query
    assert 'to:kew2000@daum.net OR cc:kew2000@daum.net' in query
    assert 'subject:토요코인 OR ' + mail_collect.forest_receipt_query() in query
    assert '"산림치유원"' in query and '"숲나들e"' in query
    assert query.endswith(')))')


def test_rest_message_received_timestamp_is_usable_without_rewriting_original():
    message = {'internalDate': '1792242000000'}
    headers = {'date': 'Sat, 17 Oct 2026 12:00:00 +0900'}
    assert ota_mail.sent_day(message, headers).isoformat() == '2026-10-17'
    assert 'internal_date' not in message
    assert ota_mail.sent_day(dict(message, internal_date='1'), headers) is None


def test_collect_keeps_two_day_overlap_and_state_query(tmp_path):
    (tmp_path / 'collection.json').write_text(json.dumps({
        'before': '2026-10-05', 'message_ids': ['seen-id'], 'account': 'owner@example.com'
    }), encoding='utf-8')
    client = FakeGmail([])

    mail_collect.collect(client, tmp_path, datetime(2026, 10, 15, 9, 0))

    assert client.queries == [mail_collect.build_query('2026-10-03')]
    state = json.loads((tmp_path / 'collection.json').read_text(encoding='utf-8'))
    assert state['account'] == 'owner@example.com'
    assert state['after'] == '2026-10-03'
    assert state['query'] == client.queries[0]
    assert state['message_ids'] == ['seen-id']


def test_owner_raw_mail_decodes_declared_charset_and_keeps_original():
    from base64 import urlsafe_b64encode
    from email.message import EmailMessage
    message = EmailMessage()
    message['From'] = 'noreply@wm.toyoko-inn.com'
    message['Subject'] = '토요코인 대구 동성로 예약 확인'
    message.set_content('예약번호: 1234567\n숙박일:2026년 10월 24일 (토) 부터 2 박', charset='euc-kr')
    raw = urlsafe_b64encode(message.as_bytes()).decode('ascii')
    record = mail_collect.owner_raw_record('synthetic-toyoko', raw, internal_date='1792800000000')
    assert record['raw'] == raw
    assert record['owner_collected'] is True
    assert record['internal_date'] == '1792800000000'
    assert '예약번호: 1234567' in ota_mail.body_text(record['payload'])
    assert ota_mail.authenticated_headers(record, ('toyoko-inn.com',)) is not None


def test_collect_writes_new_messages_once_and_records_state(tmp_path):
    (tmp_path / 'collection.json').write_text(json.dumps({'before': '2026-10-05', 'message_ids': ['old-1']}), encoding='utf-8')
    (tmp_path / 'gmail-existing.json').write_text(json.dumps({'responses': [{'id': 'old-1'}]}), encoding='utf-8')
    client = FakeGmail(['old-1', 'new-1', 'new-2'])
    result = mail_collect.collect(client, tmp_path, datetime(2026, 10, 15, 9, 0))
    assert result == {'matched': 3, 'fetched': 2, 'query': client.queries[0]}
    assert client.queries[0].startswith('after:2026/10/03 ')
    state = json.loads((tmp_path / 'collection.json').read_text(encoding='utf-8'))
    assert state['before'] == '2026-10-15' and state['fetched'] == 2
    assert set(state['message_ids']) == {'old-1', 'new-1', 'new-2'}

    again = mail_collect.collect(FakeGmail(['old-1', 'new-1', 'new-2']), tmp_path, datetime(2026, 10, 15, 10, 0))
    assert again['fetched'] == 0
    written = sorted(tmp_path.glob('gmail-auto-*.json'))
    assert len(written) == 1
    assert [m['id'] for m in json.loads(written[0].read_text(encoding='utf-8'))['responses']] == ['new-1', 'new-2']


def test_listed_id_without_original_is_fetched_again(tmp_path):
    (tmp_path / 'collection.json').write_text(json.dumps({
        'before': '2026-10-05', 'message_ids': ['missing'],
    }), encoding='utf-8')
    result = mail_collect.collect(FakeGmail(['missing']), tmp_path, datetime(2026, 10, 15, 9, 0))
    assert result['fetched'] == 1
    assert json.loads(next(tmp_path.glob('gmail-auto-*.json')).read_text(encoding='utf-8'))['responses'][0]['id'] == 'missing'


def test_historical_window_is_idempotent_and_preserves_recurring_watermark(tmp_path):
    state = '{"before":"2026-10-31","message_ids":[]}'
    (tmp_path / 'collection.json').write_text(state, encoding='utf-8')
    client = FakeGmail(['historic', 'historic'])
    result = mail_collect.collect_window(client, tmp_path, '2026-09-16', '2026-09-19')
    assert result['fetched'] == 1
    assert 'before:2026/09/19' in client.queries[0]
    assert (tmp_path / 'collection.json').read_text(encoding='utf-8') == state
    assert mail_collect.collect_window(client, tmp_path, '2026-09-16', '2026-09-19')['fetched'] == 0


def test_forest_recovery_fetches_only_scoped_receipts_and_keeps_originals_and_watermark(tmp_path):
    state = '{"before":"2026-10-31","message_ids":["existing"]}'
    (tmp_path / 'collection.json').write_text(state, encoding='utf-8')
    original = json.dumps({'responses': [{'id': 'existing'}]})
    (tmp_path / 'gmail-existing.json').write_text(original, encoding='utf-8')
    client = FakeGmail(['existing', 'missing', 'missing'])
    result = mail_collect.collect_window(client, tmp_path, '2026-06-30', '2026-09-01', forest_only=True)
    assert result['matched'] == 2 and result['fetched'] == 1
    assert client.queries == ['after:2026/06/30 ' + mail_collect.forest_receipt_query() + ' before:2026/09/01']
    assert 'to:' not in client.queries[0] and 'subject:토요코인' not in client.queries[0]
    assert (tmp_path / 'gmail-existing.json').read_text(encoding='utf-8') == original
    assert (tmp_path / 'collection.json').read_text(encoding='utf-8') == state
    assert mail_collect.collect_window(client, tmp_path, '2026-06-30', '2026-09-01', forest_only=True)['fetched'] == 0


def test_historical_window_retries_import_without_replacing_original(tmp_path, monkeypatch):
    import pytest
    client = FakeGmail(['historic'])
    def fail(_directory):
        raise ValueError('synthetic import failure')
    monkeypatch.setattr(mail_collect, 'sync_unified_store', fail)
    with pytest.raises(ValueError, match='synthetic import failure'):
        mail_collect.collect_window(client, tmp_path, '2026-09-16', '2026-09-19')
    original, = tmp_path.glob('gmail-window-*.json')
    before = original.read_bytes()
    called = []
    monkeypatch.setattr(mail_collect, 'sync_unified_store', lambda directory: called.append(directory))
    result = mail_collect.collect_window(client, tmp_path, '2026-09-16', '2026-09-19')
    assert result['fetched'] == 0 and called == [tmp_path]
    assert original.read_bytes() == before


def test_collected_file_is_read_by_the_mail_loader(tmp_path):
    client = FakeGmail(['m-1'])
    mail_collect.collect(client, tmp_path, datetime(2026, 10, 15, 9, 0))
    assert ota_mail.collection_of(tmp_path)['fetched'] == 1


def test_owner_collected_mail_is_used_without_dkim_but_the_sender_domain_still_has_to_match(tmp_path):
    headers = {'From': 'Trip.com <kr_noreply@trip.com>', 'To': 'kew2000@hanmail.net', 'Date': 'Wed, 14 Oct 2026 05:24:44 +0000',
               'Subject': '합성 예약', 'Message-Id': '<owner-1@trip.com>'}
    record = mail_collect.owner_record('owner-1', headers, '예약번호 1400000000000000\n기간 2026-11-05 ~ 2026-11-06\n')
    assert ota_mail.authenticated_headers(record, ('trip.com',))[1] == 'trip.com'
    unauthenticated = dict(record, owner_collected=False)
    assert ota_mail.authenticated_headers(unauthenticated, ('trip.com',)) is None
    spoof = mail_collect.owner_record('owner-2', dict(headers, From='x@trip.com.example.net'), 'x')
    assert ota_mail.authenticated_headers(spoof, ('trip.com',)) is None


def test_owner_batch_is_loaded_and_never_rewritten(tmp_path):
    headers = {'From': 'Agoda <CUSTOMER-SERVICE@agoda.com>', 'To': 'kew2000@hanmail.net', 'Date': 'Wed, 14 Oct 2026 05:24:44 +0000',
               'Subject': '합성 아고다', 'Message-Id': '<owner-3@agoda.com>'}
    records = [mail_collect.owner_record('owner-3', headers, 'Booking ID 1 Check in October 13, 2026')]
    now = datetime(2026, 10, 15, 11, 0)
    assert mail_collect.write_owner_batch(tmp_path, records, now) is not None
    assert mail_collect.write_owner_batch(tmp_path, records, now) is None
    messages = ota_mail.load_messages_from(tmp_path)[0]
    assert set(messages) == {'owner-3'}
    assert 'Booking ID 1' in ota_mail.message_text(messages['owner-3'])


def test_new_and_owner_mail_are_automatically_added_to_configured_unified_db(tmp_path):
    from app.ota_store import OtaStore
    directory = tmp_path / 'ota-mail'
    directory.mkdir()
    store = OtaStore(tmp_path / 'ota.sqlite')
    store.close()
    (tmp_path / 'ota-sources.json').write_text(json.dumps({'schema_version':'ota-sources-v1',
        'unified_database':str(tmp_path / 'ota.sqlite')}), encoding='utf-8')
    mail_collect.collect(FakeGmail(['new-auto']), directory, datetime(2026, 10, 15, 9, 0))
    record = mail_collect.owner_record('new-owner', {'From':'Trip.com <kr_noreply@trip.com>',
        'Subject':'합성 예약'}, '예약번호: BOOK12345')
    mail_collect.write_owner_batch(directory, [record], datetime(2026, 10, 15, 10, 0))
    messages, _ = ota_mail.load_messages_from([tmp_path / 'ota.sqlite'])
    assert set(messages) == {'new-auto', 'new-owner'}
