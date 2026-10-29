from app import participant_roster as roster
from app.participant_runtime import verify_paths


def test_runtime_identity_is_fail_closed_and_read_only(tmp_path, monkeypatch):
    db = tmp_path / "participant.sqlite"
    store = roster.ParticipantStore.open(db)
    store.close()
    monkeypatch.setenv("WEBLEDGER_PARTICIPANT_DB", str(db))
    before = db.stat().st_mtime_ns
    result = verify_paths(db)
    assert result["status"] == "ok"
    assert result["checks"]["same_file_identity"]
    assert result["schema_present"]
    assert result["write_performed"] is False
    assert db.stat().st_mtime_ns == before


def test_runtime_mismatch_is_blocked(tmp_path, monkeypatch):
    cli = tmp_path / "cli.sqlite"
    web = tmp_path / "web.sqlite"
    for path in (cli, web):
        store = roster.ParticipantStore.open(path)
        store.close()
    monkeypatch.setenv("WEBLEDGER_PARTICIPANT_DB", str(web))
    result = verify_paths(cli)
    assert result["status"] == "blocked"
    assert result["checks"]["same_resolved_path"] is False
    assert result["schema_present"] is False


def test_missing_and_wrong_schema_are_blocked_without_creating_anything(tmp_path):
    import sqlite3
    missing = tmp_path / 'missing.sqlite'
    assert verify_paths(missing, missing)['status'] == 'blocked'
    assert not missing.exists()
    empty = tmp_path / 'empty.sqlite'
    sqlite3.connect(empty).close()
    before = empty.read_bytes()
    result = verify_paths(empty, empty)
    assert result['status'] == 'blocked' and not result['schema_present']
    assert empty.read_bytes() == before


def test_receipt_requires_actual_recorded_batch_and_matching_counts(tmp_path):
    import json
    db = tmp_path / 'receipt.sqlite'
    store = roster.ParticipantStore.open(db)
    receipt = dict(batch_id='synthetic-batch',trip_id='synthetic-trip',google_trip_key='synthetic-key',
                   new_participants=2,reused_participants=0,status='registered')
    store.conn.execute("INSERT INTO roster_batches(batch_id,roster_id,revision,fingerprint,authority,status,result_json,created_at,updated_at) VALUES ('synthetic-batch','synthetic-roster',1,'synthetic','owner_confirmed_insurance','registered',?,'synthetic','synthetic')",
                       (json.dumps(receipt),))
    store.close()
    before = db.read_bytes()
    assert verify_paths(db, db, receipt=receipt)['receipt_matches_recorded_batch']
    wrong = dict(receipt, new_participants=3)
    assert verify_paths(db, db, receipt=wrong)['status'] == 'blocked'
    assert verify_paths(db, db, receipt=dict(receipt,batch_id='missing'))['status'] == 'blocked'
    assert db.read_bytes() == before


def test_cli_mismatch_is_rejected_before_creating_participant_database(tmp_path, monkeypatch, capsys):
    import sys
    from tools import ingest_participant_roster
    destination = tmp_path / 'cli.sqlite'
    monkeypatch.setattr(sys,'argv',['ingest','--db',str(destination),'--batch-dir',str(tmp_path),
                                  '--expected-web-db',str(tmp_path/'web.sqlite')])
    assert ingest_participant_roster.main() == 2
    assert 'PARTICIPANT_DB_MISMATCH' in capsys.readouterr().out
    assert not destination.exists()
