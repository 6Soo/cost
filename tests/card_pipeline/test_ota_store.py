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


@pytest.mark.parametrize('registered_lineage', [False, True])
def test_consolidation_keeps_mail_payment_ids_references_and_survives_original_removal(tmp_path, registered_lineage):
    mail = write_mail(tmp_path / 'mail', [message('예약번호: BOOK12345\n총 금액 30,000원',
        subject='[Trip.com] 결제 완료 안내', identity='stable-message')])
    portals = [portal_database(tmp_path / 'one.sqlite'), portal_database(tmp_path / 'two.sqlite')]
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps({'BOOK12345': {'amount':30000}}), encoding='utf-8')
    manifest = tmp_path / 'ota-sources.json'
    configuration = {'schema_version':'ota-sources-v1', 'mail_directories':[str(mail)],
        'portal_databases':[str(p) for p in portals], 'reference_documents':[str(reference)]}
    if registered_lineage:
        configuration['source_lineage_ids'] = {str(p.resolve()): 'portal-source-' + str(index)
                                               for index,p in enumerate(portals)}
    manifest.write_text(json.dumps(configuration), encoding='utf-8')
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


def test_refetched_gmail_copy_without_the_archived_date_spelling_is_the_same_original(tmp_path):
    archived = message('예약번호: BOOK12345\n총 금액 30,000원', identity='same')
    archived.update(internal_date='1788942857000', internalDate='1788942857000')
    refetched = copy.deepcopy(archived)
    del refetched['internal_date']
    refetched['labelIds'] = ['INBOX']
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        store.import_mail(write_mail(tmp_path / 'one', [archived]))
        store.import_mail(write_mail(tmp_path / 'two', [refetched]))
        assert store.conn.execute("SELECT COUNT(*) FROM ota_messages WHERE message_id='same'").fetchone()[0] == 1
        # Two different receipt times remain a conflict.
        # Another extractor's header folding and address quoting are the same original.
        refolded = copy.deepcopy(refetched)
        for header in refolded['payload']['headers']:
            if header['name'].lower() == 'from':
                header['value'] = '<' + header['value'].split('<')[-1].rstrip('>') + '>'
            header['value'] = header['value'].replace(' ', '\t', 1)
        store.import_mail(write_mail(tmp_path / 'refolded', [refolded]))
        # Two copies in one source differing only in header folding load as one message.
        folded = copy.deepcopy(refetched)
        folded['payload']['headers'] = [dict(h, value=h['value'].replace(' ', '\r\n\t', 1))
                                        for h in folded['payload']['headers']]
        both = write_mail(tmp_path / 'both', [refetched, folded])
        assert list(ota_mail.load_messages_from([both])[0]) == ['same']
        moved = copy.deepcopy(refetched)
        moved['internalDate'] = '1788999999000'
        with pytest.raises(ValueError, match='OTA_MESSAGE_CONTENT_CONFLICT'):
            ota_mail.load_messages_from([write_mail(tmp_path / 'pair', [refetched, moved])])
        with pytest.raises(ValueError, match='OTA_MESSAGE_CONTENT_CONFLICT'):
            store.import_mail(write_mail(tmp_path / 'three', [moved]))
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


def test_later_agoda_cancellation_mail_keeps_original_payment_and_rejects_later_conflict(tmp_path):
    from app.agoda_capture import parse_detail

    raw = capture()
    raw['observed_at'] = '2026-10-21T02:54:54Z'
    booking = parse_detail(raw)['booking_number']
    direct = tmp_path / 'direct.json'
    direct.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    mail_dir = tmp_path / 'mail'
    mail_dir.mkdir()
    mail = {'id': 'agoda-cancel-verified', 'internal_date': '1792587733653',
            'owner_collected': True, 'payload': {'headers': [
                {'name': 'From', 'value': 'customerservice@agoda.com'},
                {'name': 'Subject', 'value': '취소된 예약 - 아고다 예약 번호: ' + booking},
                {'name': 'Date', 'value': 'Wed, 21 Oct 2026 13:02:13 +0000'}],
                'body': {'content': '예약 번호: ' + booking + '\n예약 취소일: October 21, 2026'}}}
    (mail_dir / 'gmail-cancel.json').write_text(
        json.dumps({'responses': [mail]}, ensure_ascii=False), encoding='utf-8')
    store = OtaStore(tmp_path / 'unified.sqlite')
    try:
        store.import_capture(direct)
        original = next(f for _, f, _ in direct_facts(store.conn)
                        if f['booking_number'] == booking)
        store.import_mail(mail_dir)
        row, revised, conflicts = next((r, f, c) for r, f, c in direct_facts(store.conn)
                                       if f['booking_number'] == booking)
        assert conflicts == []
        assert revised['reservation_status'] == 'cancelled'
        assert revised['cancellation_mail_message_id'] == 'agoda-cancel-verified'
        for field in ('payment_status', 'refund_status', 'price_components', 'card_last4'):
            assert revised[field] == original[field]
        assert store.summary()['ota_messages'] == 1
        first_digest = database_digest(store)
        store.import_mail(mail_dir)
        assert database_digest(store) == first_digest
        raw['observed_at'] = '2026-10-21T14:00:00Z'
        direct.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
        store.import_capture(direct)
        _, _, later_conflicts = next((r, f, c) for r, f, c in direct_facts(store.conn)
                                       if f['booking_number'] == booking)
        assert 'active_after_cancellation' in later_conflicts
    finally:
        store.close()


def test_agoda_cancellation_does_not_cross_ambiguous_direct_accounts(tmp_path):
    from app.agoda_capture import parse_detail

    raw = capture()
    raw['observed_at'] = '2026-10-21T02:54:54Z'
    booking = parse_detail(raw)['booking_number']
    original_status = parse_detail(raw)['reservation_status']
    first = tmp_path / 'first.json'
    second = tmp_path / 'second.json'
    first.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    other = {**raw, 'account_key': 'other-agoda-account'}
    second.write_text(json.dumps(other, ensure_ascii=False), encoding='utf-8')
    mail_dir = tmp_path / 'mail'
    mail_dir.mkdir()
    mail = {'id': 'verified-cancel', 'internal_date': '1792587733653',
            'owner_collected': True, 'payload': {'headers': [
                {'name': 'From', 'value': 'customerservice@agoda.com'},
                {'name': 'Subject', 'value': '취소된 예약 - 아고다 예약 번호: ' + booking}],
                'body': {'content': '예약 번호: ' + booking + '\n예약 취소일: October 21, 2026'}}}
    (mail_dir / 'gmail-cancel.json').write_text(json.dumps({'responses': [mail]},
                                                        ensure_ascii=False), encoding='utf-8')
    store = OtaStore(tmp_path / 'unified.sqlite')
    try:
        store.import_capture(first)
        store.import_capture(second)
        store.import_mail(mail_dir)
        matches = [(r, fact, conflicts) for r, fact, conflicts in direct_facts(store.conn)
                   if r['booking_number'] == booking]
        assert len(matches) == 2
        assert all('cancellation_account_ambiguous' in conflicts for _, _, conflicts in matches)
        assert all(fact['reservation_status'] == original_status for _, fact, _ in matches)
    finally:
        store.close()


def test_unauthenticated_agoda_cancellation_is_preserved_but_not_applied(tmp_path):
    from app.agoda_capture import parse_detail

    raw = capture()
    raw['observed_at'] = '2026-10-21T02:54:54Z'
    booking = parse_detail(raw)['booking_number']
    original_status = parse_detail(raw)['reservation_status']
    path = tmp_path / 'direct.json'
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    mail_dir = tmp_path / 'mail'
    mail_dir.mkdir()
    message = {'id': 'unverified-cancel', 'internal_date': '1792587733653',
               'payload': {'headers': [
                   {'name': 'From', 'value': 'customerservice@agoda.com'},
                   {'name': 'Subject', 'value': '취소된 예약 - 아고다 예약 번호: ' + booking}],
                   'body': {'content': '예약 번호: ' + booking + '\n예약 취소일: October 21, 2026'}}}
    (mail_dir / 'gmail-cancel.json').write_text(json.dumps({'responses': [message]},
                                                        ensure_ascii=False), encoding='utf-8')
    store = OtaStore(tmp_path / 'unified.sqlite')
    try:
        store.import_capture(path)
        store.import_mail(mail_dir)
        assert store.summary()['ota_messages'] == 1
        assert all(r['entry_key'] != 'unverified-cancel' for r in store.conn.execute(
            'SELECT entry_key FROM ota_booking_evidence'))
        assert next(f for _, f, _ in direct_facts(store.conn)
                    if f['booking_number'] == booking)['reservation_status'] == original_status
    finally:
        store.close()


@pytest.mark.parametrize('target', [None, '', 'relative.sqlite'])
def test_invalid_unified_target_never_silently_falls_back_to_legacy(tmp_path, target):
    (tmp_path / 'ota-sources.json').write_text(json.dumps({'schema_version':'ota-sources-v1',
        'unified_database':target}), encoding='utf-8')
    with pytest.raises(ota_sources.OtaSourcesError):
        ota_sources.resolve_sources(tmp_path, mail_default=tmp_path / 'old-mail',
                                    portal_default=tmp_path / 'old-portal.sqlite')


def test_a_kept_rest_copy_still_conflicts_with_a_different_receipt_time(tmp_path):
    kept = message('예약번호: BOOK12345 총 금액 30,000원', identity='rest')
    del kept['internal_date']
    kept['internalDate'] = '1788942857000'
    moved = copy.deepcopy(kept)
    moved['internalDate'] = '1788999999000'
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        store.import_mail(write_mail(tmp_path / 'one', [kept]))
        with pytest.raises(ValueError, match='OTA_MESSAGE_CONTENT_CONFLICT'):
            store.import_mail(write_mail(tmp_path / 'two', [moved]))
    finally:
        store.close()
