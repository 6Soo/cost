import sqlite3
from contextlib import closing

import pytest

from app.ota_store import OtaStore
from tools import reindex_reservation_observations as tool
from webapp.tests.test_forest_catalog import mail,write_mail


def legacy(tmp_path):
    path=tmp_path/'ota.sqlite'
    store=OtaStore(path)
    store.import_mail(write_mail(tmp_path/'mail',[mail('synthetic-one'),mail('synthetic-two',cancelled=True)]))
    store.conn.execute('DROP TABLE ota_reservation_observations');store.conn.commit();store.close()
    return path


def copies(path):
    paths=[path.with_name('backup.sqlite'),path.with_name('restored.sqlite')]
    with closing(sqlite3.connect(path)) as source:
        for p in paths:
            with closing(sqlite3.connect(p)) as target:source.backup(target)
    return paths


def test_reindex_requires_matching_separate_restore_and_preserves_all_originals(tmp_path):
    path=legacy(tmp_path);backup,restored=copies(path)
    conn=tool.connect(path,True)
    try:
        before=tool.states(conn)
        with closing(sqlite3.connect(restored)) as bad:
            bad.execute('DELETE FROM ota_messages');bad.commit()
        with pytest.raises(ValueError,match='RESERVATION_INDEX_RESTORE_MISMATCH'):
            tool.apply(conn,tool.fingerprint(before),backup,restored)
        assert tool.states(conn)==before
        restored.unlink();copies(path)
        report=tool.apply(conn,tool.fingerprint(before),backup,restored)
        assert report['distinct_observations']==2 and report['inserted_evidence_rows']==2
        assert report['replay_writes']==0 and report['original_tables_unchanged']
        assert {k:v for k,v in tool.states(conn).items() if k!=tool.TABLE}==before
    finally:conn.close()


def test_reindex_rejects_stale_source_before_schema_or_data_writes(tmp_path):
    path=legacy(tmp_path);backup,restored=copies(path)
    conn=tool.connect(path,True)
    try:
        before=tool.states(conn)
        with pytest.raises(ValueError,match='RESERVATION_INDEX_SOURCE_CHANGED'):
            tool.apply(conn,'wrong-digest',backup,restored)
        assert tool.states(conn)==before
    finally:conn.close()
