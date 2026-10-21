"""단일 OTA DB가 원문·결제 ID·출처 충돌을 보존하는지 확인한다."""
import copy
import gc
import json
import sqlite3

import pytest

from app import ota_mail, ota_payments, ota_sources
from app.ota_store import OtaStore, encoded, direct_facts
from webapp.ota_catalog import _database_rows
from tools.consolidate_ota_sources import consolidate, database_digest
from tests.card_pipeline.test_booking_mail import message
from tests.card_pipeline.test_ota_sources_registry import portal_database, write_mail
from tests.card_pipeline.test_agoda_capture import capture


def test_consolidation_keeps_mail_payment_ids_references_and_survives_original_removal(tmp_path):
    mail = write_mail(tmp_path / 'mail', [message('예약번호: BOOK12345\n총 금액 30,000원',
        subject='[Trip.com] 결제 완료 안내', identity='stable-message')])
    portals = [portal_database(tmp_path / 'one.sqlite'), portal_database(tmp_path / 'two.sqlite')]
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps({'BOOK12345': {'amount':30000}}), encoding='utf-8')
    manifest = tmp_path / 'ota-sources.json'
    manifest.write_text(json.dumps({'schema_version':'ota-sources-v1', 'mail_directories':[str(mail)],
        'portal_databases':[str(p) for p in portals], 'reference_documents':[str(reference)]}), encoding='utf-8')
    before = ota_payments.build_ota_payment_events(ota_sources.resolve_sources(tmp_path))
    destination = tmp_path / 'unified.sqlite'
    report = consolidate(manifest, destination)
    assert report['status'] == 'PASS', report
    manifest.write_text(json.dumps(report['candidate_manifest']), encoding='utf-8')
    # 기존 합성 DB 도우미의 연결을 정리한 뒤 Windows에서 원본을 제거한다.
    gc.collect()
    for original in [*portals, reference, mail / 'gmail.json']:
        original.unlink()
    sources = ota_sources.resolve_sources(tmp_path, portal_default=tmp_path / 'unrelated.sqlite')
    assert sources['portal_databases'] == [destination]
    assert sources['mail_directories'] == [destination]
    assert sources['reference_documents'] == [destination]
    assert ota_payments.build_ota_payment_events(sources) == before
    assert not ota_mail.load_reference_documents([destination])['errors']


def test_same_message_id_changed_body_rolls_back_whole_source(tmp_path):
    first = message('예약번호: BOOK12345\n총 금액 30,000원', identity='same')
    one = write_mail(tmp_path / 'one', [first])
    changed = copy.deepcopy(first)
    changed['payload']['body'] = {'content':'다른 원문'}
    two = write_mail(tmp_path / 'two', [changed])
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        store.import_mail(one)
        before = database_digest(store)
        with pytest.raises(ValueError, match='OTA_MESSAGE_CONTENT_CONFLICT'):
            store.import_mail(two)
        assert database_digest(store) == before
    finally:
        store.close()


def test_all_providers_share_store_but_accounts_and_real_observations_stay_separate(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        for provider in ('agoda', 'booking', 'trip', 'klook'):
            kwargs = dict(provider=provider, account_key='owner-one', source_key='observation',
                          snapshot={'text':'직접 확인한 예약'}, facts=[{'provider':provider,
                          'booking_number':'1234567890', 'payment_status':'unknown'}])
            assert store.import_direct(**kwargs)
            assert not store.import_direct(**kwargs)
            assert store.import_direct(**{**kwargs, 'account_key':'owner-two'})
        assert store.summary()['ota_bookings'] == 8
        assert {row['provider'] for row in _database_rows(store.conn)} == {'agoda', 'booking', 'trip', 'klook'}
        assert ota_payments.build_ota_payment_events({'portal_databases':[store.path],
            'mail_directories':[store.path], 'reference_documents':[store.path]}) == []
    finally:
        store.close()


def test_unrelated_database_is_never_modified_and_tampered_raw_is_rejected(tmp_path):
    unrelated = tmp_path / 'board.sqlite'
    with sqlite3.connect(unrelated) as conn:
        conn.execute('CREATE TABLE owner_data(id TEXT)')
    before = unrelated.read_bytes()
    with pytest.raises(ValueError, match='OTA_STORE_REFUSE_UNRELATED_DATABASE'):
        OtaStore(unrelated)
    assert unrelated.read_bytes() == before
    mail = write_mail(tmp_path / 'mail', [message('합성 본문', identity='id-one')])
    store = OtaStore(tmp_path / 'store.sqlite')
    store.import_mail(mail)
    store.conn.execute("UPDATE ota_raw_entries SET payload_json=? WHERE entry_key='collection'",
                       (encoded({'fetched':999}),))
    store.conn.commit()
    store.close()
    with pytest.raises(ValueError, match='OTA_STORE_RAW_HASH_MISMATCH'):
        ota_mail.load_messages_from([tmp_path / 'store.sqlite'])


def test_direct_capture_is_read_from_same_db_and_conflicting_history_is_held(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    raw = capture()
    path = tmp_path / 'detail.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    try:
        store.import_capture(path)
        events = ota_payments._portal_events([store.path])
        assert len(events) == 1 and events[0]['paid_on'] is None
        assert 'aside-v1:' in events[0]['source_ids'][0]
        before = database_digest(store)
        store.conn.execute('BEGIN IMMEDIATE')
        store.import_direct(provider='booking', account_key='one', source_key='x', snapshot={},
                            facts=[{'provider':'booking', 'booking_number':'8765432100'}])
        store.conn.rollback()
        assert before == database_digest(store)
        raw['snapshot_text'] = raw['snapshot_text'].replace('30,000', '31,000')
        raw['observed_at'] = '2026-10-21T08:00:00Z'
        path.write_text(json.dumps(raw), encoding='utf-8')
        store.import_capture(path)
        assert ota_payments._portal_events([store.path]) == []
        assert store.summary()['ota_source_revisions'] == 2
    finally:
        store.close()


def test_full_card_report_keeps_scheduled_links_and_explicit_cancellation_still_blocks(tmp_path):
    from app import ota_portal
    from tests.card_pipeline.test_ota_portal_scheduled_card_date import portal_database as scheduled_db, card, PROGRESSION
    original = scheduled_db(tmp_path / 'scheduled.sqlite', [({'booking_number':'1234567890'}, PROGRESSION)])
    transactions = [card()]
    before = ota_portal.extend_report({'matches':[], 'rules':[]}, [original], transactions)
    assert len(before['matches']) == 1
    store = OtaStore(tmp_path / 'unified.sqlite')
    try:
        store.import_portal(original)
        after = ota_portal.extend_report({'matches':[], 'rules':[]}, [store.path], transactions)
        assert before['matches'] == after['matches']
        direct = capture()
        direct['snapshot_text'] = direct['snapshot_text'].replace('2026년 8월 1일', '2026년 10월 5일').replace(
            '2026년 8월 2일', '2026년 10월 8일').replace('30,000', '225,498').replace('•••• 1234', '•••• 8835')
        path = tmp_path / 'direct.json'
        path.write_text(json.dumps(direct), encoding='utf-8')
        store.import_capture(path)
        assert ota_portal.scheduled_card_date_matches([store.path], transactions) == before['matches']
        assert ota_portal.extend_report({'matches':[], 'rules':[]}, [store.path], transactions)['matches'] == before['matches']
        direct['snapshot_text'] = direct['snapshot_text'].replace('투숙 완료', '예약 취소됨')
        direct['observed_at'] = '2026-10-21T08:00:00Z'
        path.write_text(json.dumps(direct), encoding='utf-8')
        store.import_capture(path)
        assert ota_portal.scheduled_card_date_matches([store.path], transactions) == []
    finally:
        store.close()


def test_collection_metadata_updates_do_not_copy_unchanged_mail_files(tmp_path):
    mail = write_mail(tmp_path / 'mail', [message('합성 원문', identity='unchanged')])
    state = mail / 'collection.json'
    state.write_text(json.dumps({'last_run':'first', 'fetched':1}), encoding='utf-8')
    store = OtaStore(tmp_path / 'unified.sqlite')
    try:
        store.import_mail(mail)
        before = store.summary()
        state.write_text(json.dumps({'last_run':'second', 'fetched':0}), encoding='utf-8')
        store.import_mail(mail)
        after = store.summary()
        assert after['ota_raw_blobs'] == before['ota_raw_blobs'] + 1
        assert after['ota_messages'] == before['ota_messages'] == 1
        assert set(ota_mail.load_messages_from([store.path])[0]) == {'unchanged'}
    finally:
        store.close()


def test_parser_upgrade_preserves_original_observation_and_uses_new_fact_version(tmp_path):
    raw = capture()
    raw['snapshot_text'] = raw['snapshot_text'].replace('투숙 완료', '예약 취소일: 2026년 7월 31일')
    path = tmp_path / 'cancelled.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    store = OtaStore(tmp_path / 'unified.sqlite')
    try:
        store.import_capture(path)
        old = json.loads(store.conn.execute('SELECT fact_json FROM ota_booking_evidence').fetchone()[0])
        old.pop('parser_version')
        old['reservation_status'] = 'unknown'
        store.conn.execute("UPDATE ota_booking_evidence SET entry_key='detail',fact_json=?", (encoded(old),))
        store.conn.commit()
        store.import_capture(path)
        assert store.summary()['ota_source_revisions'] == 1
        assert store.summary()['ota_booking_evidence'] == 2
        assert direct_facts(store.conn)[0][1]['reservation_status'] == 'cancelled'
        before = database_digest(store)
        store.import_capture(path)
        assert before == database_digest(store)
    finally:
        store.close()
