"""Mail source loading keeps one canonical body per ID and bounded source lifetime."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from app import ota_mail, ota_payments, ota_store
from tests.card_pipeline.test_booking_mail import message
from tests.card_pipeline.test_ota_sources_registry import write_mail


@pytest.fixture(autouse=True)
def reset_mail_cache():
    ota_mail._MESSAGES_MEMO.clear()
    ota_mail._BODY_TEXT.clear()
    ota_payments._MAIL_EVENT_MEMO.clear()
    yield
    ota_mail._MESSAGES_MEMO.clear()
    ota_mail._BODY_TEXT.clear()
    ota_payments._MAIL_EVENT_MEMO.clear()


def test_duplicate_message_body_cache_keeps_only_the_canonical_message(tmp_path):
    one = message('예약번호: BOOK12345\n총 금액 30,000원', identity='same')
    enriched = copy.deepcopy(one)
    enriched['attachment_metadata'] = 'additional metadata'
    directories = [write_mail(tmp_path / 'first', [one]), write_mail(tmp_path / 'second', [enriched])]
    messages, inventory = ota_mail.load_messages_from(directories)
    assert len(messages) == 1 and sum(row['messages'] for row in inventory) == 2
    assert messages['same']['attachment_metadata'] == 'additional metadata'
    assert set(ota_mail._BODY_TEXT) == {id(messages['same'])}
    assert ota_mail.message_text(messages['same']) == ota_mail.body_text(one['payload'])


def test_conflicting_body_does_not_retain_a_partial_failed_load(tmp_path):
    first = message('original', identity='same')
    changed = message('changed', identity='same')
    directories = [write_mail(tmp_path / 'first', [first]), write_mail(tmp_path / 'second', [changed])]
    with pytest.raises(ValueError, match='OTA_MESSAGE_CONTENT_CONFLICT'):
        ota_mail.load_messages_from(directories)
    assert not ota_mail._BODY_TEXT
    assert not ota_mail._MESSAGES_MEMO


def test_changed_source_replaces_cached_messages_and_bodies(tmp_path):
    directory = write_mail(tmp_path / 'mail', [message('original', identity='one')])
    first, _ = ota_mail.load_messages_from([directory])
    write_mail(directory, [message('a different longer body', identity='two')])
    second, _ = ota_mail.load_messages_from([directory])
    assert set(first) == {'one'} and set(second) == {'two'}
    assert set(ota_mail._BODY_TEXT) == {id(second['two'])}
    # A caller still reading the old snapshot falls back to its own payload.
    assert ota_mail.message_text(first['one']) == ota_mail.body_text(first['one']['payload'])


def test_failed_payment_parse_retries_and_invalidates_on_source_change(tmp_path, monkeypatch):
    directory = write_mail(tmp_path / 'mail', [message('body', identity='one')])
    calls = []

    def parse(directories):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError('synthetic failure')
        return [{'source_ids': [f'parse-{len(calls)}']}]

    monkeypatch.setattr(ota_payments, '_parse_mail_events', parse)
    with pytest.raises(ValueError, match='synthetic failure'):
        ota_payments._mail_events([directory])
    assert not ota_payments._MAIL_EVENT_MEMO
    assert ota_payments._mail_events([directory])[0]['source_ids'] == ['parse-2']
    assert ota_payments._mail_events([directory])[0]['source_ids'] == ['parse-2']
    write_mail(directory, [message('changed source', identity='two')])
    assert ota_payments._mail_events([directory])[0]['source_ids'] == ['parse-3']


def test_simultaneous_identical_mail_loads_share_one_parse(tmp_path, monkeypatch):
    directory = write_mail(tmp_path / 'mail', [message('synthetic', identity='one')])
    original = ota_mail._load_messages_uncached
    calls = []
    start = threading.Barrier(2)

    def slow_load(directories):
        calls.append(1)
        time.sleep(.05)
        return original(directories)

    monkeypatch.setattr(ota_mail, '_load_messages_uncached', slow_load)

    def load():
        start.wait(timeout=5)
        return ota_mail.load_messages_from([directory])

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(load) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert len(calls) == 1
    assert results[0] is results[1]


def test_store_mail_iterator_verifies_each_source_and_keeps_legacy_result(tmp_path):
    path = tmp_path / 'store.sqlite'
    store = ota_store.OtaStore(path)
    try:
        for number in range(2):
            directory = write_mail(tmp_path / str(number), [message('body', identity=f'id-{number}')])
            store.import_mail(directory)
        expected = ota_store.mail_bundles(path)
        assert list(ota_store.iter_mail_bundles(path)) == expected
        # Corrupt the second source: iteration must verify it before publishing it.
        source = store.conn.execute('SELECT current_revision FROM ota_sources ORDER BY ordinal DESC LIMIT 1').fetchone()[0]
        store.conn.execute("UPDATE ota_raw_entries SET payload_json=? WHERE revision_id=? AND entry_key='collection'",
                           (ota_store.encoded({'fetched': 99}), source))
        store.conn.commit()
        iterator = ota_store.iter_mail_bundles(path)
        assert next(iterator) == expected[0]
        with pytest.raises(ValueError, match='OTA_STORE_RAW_HASH_MISMATCH'):
            next(iterator)
    finally:
        store.close()


def test_simultaneous_payment_event_loads_share_parse_and_return_safe_copies(tmp_path, monkeypatch):
    directory = write_mail(tmp_path / 'mail', [message('synthetic', identity='one')])
    start = threading.Barrier(2)
    calls = []

    def parse(directories):
        calls.append(1)
        time.sleep(.05)
        return [{'ota_event_id': 'synthetic', 'source_ids': ['mail:one']}]

    monkeypatch.setattr(ota_payments, '_parse_mail_events', parse)

    def load():
        start.wait(timeout=5)
        return ota_payments._mail_events([directory])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in [pool.submit(load) for _ in range(2)]]
    assert len(calls) == 1
    results[0][0]['source_ids'].append('changed')
    assert results[1][0]['source_ids'] == ['mail:one']
    assert ota_payments._mail_events([directory], read_only=True)[0]['source_ids'] == ['mail:one']


@pytest.mark.parametrize('value', [None, [True, False, 1, 1.25],
    {'한글': ['quotation "', '\n', 'emoji 🌲'], 'a': {'nested': None}}])
def test_streamed_source_digest_is_identical_to_existing_canonical_digest(value):
    assert ota_store.encoded_sha256(value) == ota_store.sha(ota_store.encoded(value))
