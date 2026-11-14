"""통합 OTA DB 감시는 파일 바이트가 아니라 커밋된 상태를 본다."""
import json

import pytest

from app import ota_sources
from app.ota_store import OtaStore, commit_state
from tests.card_pipeline.test_agoda_capture import capture
from tests.card_pipeline.test_ota_sources_registry import portal_database
from tests.card_pipeline.test_ota_store_dedupe import forest, trip, write


def stamp(store):
    return ota_sources.source_stamps({'portal_databases': [store.path], 'mail_directories': [store.path],
                                      'reference_documents': [store.path]})


def test_committed_import_changes_state_and_stamp(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        before = stamp(store)
        store.import_mail(write(tmp_path / 'mail', [forest(1)]))
        after = stamp(store)
        assert after != before and 'ota_store_state' in after[0] and len(after) == 1
        assert stamp(store) == after
    finally:
        store.close()


def test_uncommitted_write_keeps_state_and_commit_changes_it(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        store.import_mail(write(tmp_path / 'mail', [forest(1)]))
        before = stamp(store)
        wal = store.path.with_name(store.path.name + '-wal')
        store.conn.execute('BEGIN IMMEDIATE')
        store.import_mail(write(tmp_path / 'mail2', [forest(1), trip(1), forest(2)]))
        store.conn.execute('CREATE TABLE IF NOT EXISTS scratch(x)')
        assert wal.exists()
        assert stamp(store) == before
        store.conn.commit()
        assert stamp(store) != before
    finally:
        store.close()


def test_rolled_back_write_keeps_state(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        store.import_mail(write(tmp_path / 'mail', [forest(1)]))
        before = stamp(store)
        store.conn.execute('BEGIN IMMEDIATE')
        store.import_direct(provider='booking', account_key='one', source_key='x', snapshot={},
                            facts=[{'provider': 'booking', 'booking_number': '8765432100'}])
        store.conn.rollback()
        assert stamp(store) == before
    finally:
        store.close()


def _mail(store, tmp_path):
    store.import_mail(write(tmp_path / 'm', [forest(1)]))


def _mail_changed(store, tmp_path):
    store.import_mail(write(tmp_path / 'm', [forest(1)]))
    store.import_mail(write(tmp_path / 'm', [forest(1), trip(1)]))


def _portal(store, tmp_path):
    store.import_portal(portal_database(tmp_path / 'portal.sqlite'))


def _reference(store, tmp_path):
    ref = tmp_path / 'reference.json'
    ref.write_text(json.dumps({'BOOK1': {'amount': 1}}), encoding='utf-8')
    store.import_reference(ref)


def _capture(store, tmp_path):
    path = tmp_path / 'detail.json'
    path.write_text(json.dumps(capture()), encoding='utf-8')
    store.import_capture(path)


def _direct(store, tmp_path):
    store.import_direct(provider='trip', account_key='a', source_key='s', snapshot={'t': 1},
                        facts=[{'provider': 'trip', 'booking_number': 'T1'}])


def _direct_second_fact(store, tmp_path):
    store.import_direct(provider='trip', account_key='a', source_key='s', snapshot={'t': 2},
                        facts=[{'provider': 'trip', 'booking_number': 'T2'}])


@pytest.mark.parametrize('write_path, prepare', [
    (_mail, None), (_mail_changed, _mail), (_portal, None), (_reference, None), (_capture, None),
    (_direct, None), (_direct_second_fact, _direct)])
def test_every_write_path_changes_the_stamp(tmp_path, write_path, prepare):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        if prepare:
            prepare(store, tmp_path)
        before = stamp(store)
        write_path(store, tmp_path)
        store.conn.commit()
        assert stamp(store) != before
    finally:
        store.close()


def test_reindex_and_scheduled_rebuild_differ_from_the_deleted_state(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        _mail_changed(store, tmp_path)
        _portal(store, tmp_path)
        store.conn.execute('DELETE FROM ota_reservation_observations')
        store.conn.execute('DELETE FROM ota_scheduled_rows')
        store.conn.commit()
        deleted = stamp(store)
        assert store.rebuild_reservation_observations()
        reindexed = stamp(store)
        assert reindexed != deleted
        store.rebuild_scheduled_index()
        rebuilt = stamp(store)
        assert rebuilt != reindexed
    finally:
        store.close()


def test_read_cost_does_not_depend_on_file_size_and_unrelated_files_still_hash(tmp_path):
    store = OtaStore(tmp_path / 'store.sqlite')
    try:
        _mail(store, tmp_path)
        store.conn.execute('CREATE TABLE ballast(x BLOB)')
        store.conn.execute('INSERT INTO ballast VALUES(zeroblob(40000000))')
        store.conn.commit()
        size = store.path.stat().st_size
        assert size > 40_000_000
        reads = []
        import pathlib
        real = pathlib.Path.open

        def counting(self, *args, **kwargs):
            handle = real(self, *args, **kwargs)
            reads.append(self.name)
            return handle
        pathlib.Path.open = counting
        try:
            first = ota_sources.content_stamp(store.path)
        finally:
            pathlib.Path.open = real
        assert 'ota_store_state' in first
        assert reads == ['store.sqlite']
        before = ota_sources.content_stamp(store.path)
        store.conn.execute('UPDATE ballast SET x=zeroblob(40000000)')
        store.conn.commit()
        assert ota_sources.content_stamp(store.path) == before
    finally:
        store.close()
    plain = tmp_path / 'plain.json'
    plain.write_text('{}', encoding='utf-8')
    assert 'sha256' in ota_sources.content_stamp(plain)
    assert commit_state(plain) is None
