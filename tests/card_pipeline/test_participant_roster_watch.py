import hashlib
import json

from app import participant_roster as pr
from app.participant_sync import scan_inbox


def _write_batch(root, *, batch_id='batch-watch-001'):
    batch = root / batch_id
    source_dir = batch / 'sources'
    source_dir.mkdir(parents=True)
    source = source_dir / 'page-01.png'
    source.write_bytes(b'watch-source')
    manifest = {
        'schema_version': 1,
        'batch_id': batch_id,
        'roster_id': 'roster-watch-001',
        'revision': 1,
        'authority': 'owner_confirmed_insurance',
        'trip_ref': {'cost_trip_id': 'trip-watch', 'google_trip_key': 'watch-trip'},
        'submitted_by': 'test',
        'submitted_at': '2026-10-31T00:00:00+09:00',
        'coverage': {'scope': 'complete', 'received_pages': [1],
                     'expected_pages': 1, 'declared_people': 1},
        'sources': [{'source_id': 'source-watch-001', 'path': 'sources/page-01.png',
                     'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
    }
    participants = {
        'schema_version': 1,
        'items': [{'source_item_id': 'item-watch-001', 'source_id': 'source-watch-001',
                   'page': 1, 'row_label': '1', 'name': 'Test Person',
                   'nickname': '', 'english_name': '', 'transcription_status': 'verified'}],
    }
    (batch / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    (batch / 'participants.json').write_text(json.dumps(participants, ensure_ascii=False), encoding='utf-8')
    return batch


def test_inbox_scan_registers_new_batch_and_is_idempotent(tmp_path):
    inbox = tmp_path / 'inbox'
    _write_batch(inbox)
    store = pr.ParticipantStore.open(tmp_path / 'participant.sqlite')
    try:
        first = scan_inbox(inbox, store, mapping={'watch-trip': 'trip-watch'})
        second = scan_inbox(inbox, store, mapping={'watch-trip': 'trip-watch'})
        assert first[0]['status'] == 'registered'
        assert second[0]['reused'] is True
        assert len(store.participants('trip-watch')) == 1
    finally:
        store.close()


def test_inbox_scan_does_not_register_incomplete_copy(tmp_path):
    inbox = tmp_path / 'inbox'
    pending = inbox / 'batch-pending'
    pending.mkdir(parents=True)
    (pending / 'manifest.json').write_text('{}', encoding='utf-8')
    store = pr.ParticipantStore.open(tmp_path / 'participant.sqlite')
    try:
        result = scan_inbox(inbox, store, mapping={})
        assert result == [{'batch_dir': 'batch-pending', 'status': 'pending_input'}]
        assert store.batches() == []
    finally:
        store.close()
