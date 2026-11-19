import json
import sqlite3

import pytest

from app.ota_store import OtaStore, commit_state, merge_portal_projections, packed, portal_rows, unpacked
from tests.card_pipeline.test_ota_portal import portal_database
from tools.merge_ota_portal_projections import main


@pytest.fixture
def store(tmp_path):
    source = portal_database(tmp_path / 'portal.sqlite')
    with sqlite3.connect(source) as conn:
        conn.execute('ALTER TABLE booking_source_evidence ADD COLUMN conflict_json TEXT')
        conn.execute("UPDATE booking_source_evidence SET conflict_json=? WHERE evidence_role='identity'",
                     ('[{"reason":"synthetic"}]',))
    ota = OtaStore(tmp_path / 'ota.sqlite')
    try:
        assert ota.import_portal(source)
        yield ota
    finally:
        ota.close()


def table_names(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def originals(conn):
    tables = ('ota_raw_entries', 'ota_raw_blobs', 'ota_sources', 'ota_source_revisions')
    return {t: [tuple(row) for row in conn.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}


@pytest.mark.parametrize('partial', [False, True])
def test_merge_preserves_outputs_and_reopen(store, tmp_path, partial):
    conn = store.conn
    if partial:
        conn.execute('DELETE FROM ota_scheduled_rows WHERE row_no>0')
        conn.commit()
    legacy_tables = table_names(conn)
    raw = originals(conn)
    base = portal_rows(store.path, 0)
    scheduled = portal_rows(store.path, 0, scheduled=True)
    assert any(row['conflict_json'] is not None for row in scheduled)
    before = commit_state(store.path)

    preview = merge_portal_projections(conn)
    assert preview == {'status': 'PREVIEW', 'rows_merged': len(scheduled)}
    assert table_names(conn) == legacy_tables
    assert commit_state(store.path) == before

    assert merge_portal_projections(conn, apply=True)['rows_merged'] == len(scheduled)
    assert table_names(conn) == legacy_tables - {'ota_scheduled_rows'}
    assert originals(conn) == raw
    assert portal_rows(store.path, 0) == base
    assert portal_rows(store.path, 0, scheduled=True) == scheduled
    assert merge_portal_projections(conn, apply=True) == {'status': 'ALREADY_UNIFIED', 'rows_merged': 0}

    reopened = OtaStore(store.path)
    try:
        source = portal_database(tmp_path / 'new-portal.sqlite', [{'booking_number': 'second'}])
        assert reopened.import_portal(source)
        assert table_names(reopened.conn) == legacy_tables - {'ota_scheduled_rows'}
        rows = portal_rows(store.path, 0, scheduled=True)
        assert any(row['booking_number'] == 'second' and row['conflict_json'] is None for row in rows)
    finally:
        reopened.close()


@pytest.mark.parametrize('fault, error', [('type', 'MISMATCH'), ('missing', 'MISSING')])
def test_merge_refuses_mismatched_projection(store, fault, error):
    conn = store.conn
    if fault == 'type':
        data = unpacked(conn.execute('SELECT payload_json FROM ota_scheduled_rows WHERE row_no=0').fetchone()[0])
        data['conflict_count'] = float(data['conflict_count'])
        conn.execute('UPDATE ota_scheduled_rows SET payload_json=? WHERE row_no=0', (packed(data),))
    else:
        conn.execute('DELETE FROM ota_portal_rows WHERE row_no=0')
    conn.commit()
    before = list(conn.iterdump())
    with pytest.raises(ValueError, match=error):
        merge_portal_projections(conn, apply=True)
    assert list(conn.iterdump()) == before


def test_unified_fallback_and_rebuild_update_stamp(store):
    conn = store.conn
    conn.execute('DELETE FROM ota_scheduled_rows')
    conn.commit()
    fallback = portal_rows(store.path, 0, scheduled=True)
    assert fallback and all('_source_locator' not in row for row in fallback)
    merge_portal_projections(conn, apply=True)
    assert portal_rows(store.path, 0, scheduled=True) == fallback

    before = commit_state(store.path)
    conn.execute('BEGIN')
    store.rebuild_scheduled_index()
    assert conn.in_transaction
    assert commit_state(store.path) == before
    conn.commit()
    assert commit_state(store.path) != before
    stored = portal_rows(store.path, 0, scheduled=True)
    assert [{k: v for k, v in row.items() if k != '_source_locator'} for row in stored] == fallback


def test_cli_preview_apply_and_refuse_protected_root(store, monkeypatch, capsys):
    path = str(store.path)
    assert main(['--db', path]) == 0
    assert json.loads(capsys.readouterr().out)['result']['status'] == 'PREVIEW'
    monkeypatch.setenv('WEBLEDGER_DATA_ROOT', str(store.path.parent))
    assert main(['--db', path, '--apply']) == 5
    assert json.loads(capsys.readouterr().out)['code'] == 'OPERATIONAL_ROOT_REFUSED'
    monkeypatch.delenv('WEBLEDGER_DATA_ROOT')
    assert main(['--db', path, '--apply']) == 0
    assert json.loads(capsys.readouterr().out)['result']['status'] == 'APPLIED'



def test_mixed_layout_is_refused(store):
    conn = store.conn
    merge_portal_projections(conn, apply=True)
    conn.execute('CREATE TABLE ota_scheduled_rows(revision_id, row_no, payload_json)')
    conn.commit()
    with pytest.raises(ValueError, match='LAYOUT_MIXED'):
        portal_rows(store.path, 0, scheduled=True)
    with pytest.raises(ValueError, match='LAYOUT_MIXED'):
        OtaStore(store.path)
