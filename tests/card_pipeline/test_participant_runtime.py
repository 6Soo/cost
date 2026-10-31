from app import participant_roster as roster
from app.participant_runtime import verify_paths


def test_runtime_identity_is_fail_closed_and_read_only(tmp_path, monkeypatch):
    db = tmp_path / "participant.sqlite"
    store = roster.ParticipantStore.open(db)
    store.close()
    monkeypatch.setenv("WEBLEDGER_PARTICIPANT_DB", str(db))
    before = db.stat().st_mtime_ns
    result = verify_paths(db)
    assert result["status"] == "ready_for_receipt_check"
    assert result["code"] == "REGISTRATION_RECEIPT_REQUIRED"
    assert result["checks"]["same_file_identity"]
    assert result["schema_present"]
    assert result["write_performed"] is False
    assert str(db) not in str(result)
    assert "'file_id':" not in str(result)
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
    with sqlite3.connect(empty) as connection:
        connection.executescript('CREATE TABLE roster_batches(wrong TEXT); CREATE TABLE trip_participants(wrong TEXT);')
    assert verify_paths(empty, empty)['status'] == 'blocked'


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
    accepted = verify_paths(db, db, receipt=receipt)
    assert accepted['receipt_matches_recorded_batch']
    assert accepted['status'] == 'accepted'
    assert accepted['code'] == 'DB_AND_RECEIPT_MATCH'
    wrong = dict(receipt, new_participants=3)
    assert verify_paths(db, db, receipt=wrong)['status'] == 'blocked'
    assert verify_paths(db, db, receipt=dict(receipt,new_participants=True))['status'] == 'blocked'
    assert verify_paths(db, db, receipt=dict(receipt,batch_id='missing'))['status'] == 'blocked'
    assert db.read_bytes() == before

    # Corrupt JSON shapes must produce a blocked result, not an AttributeError.
    store = roster.ParticipantStore.open(db)
    for malformed in ('[]', 'null', '"unexpected"'):
        store.conn.execute('UPDATE roster_batches SET result_json=?', (malformed,))
        store.conn.commit()
        assert verify_paths(db, db, receipt=receipt)['status'] == 'blocked'
    store.close()


def test_cli_mismatch_is_rejected_before_creating_participant_database(tmp_path, monkeypatch, capsys):
    import sys
    from tools import ingest_participant_roster
    destination = tmp_path / 'cli.sqlite'
    monkeypatch.setattr(sys,'argv',['ingest','--db',str(destination),'--batch-dir',str(tmp_path),
                                  '--expected-web-db',str(tmp_path/'web.sqlite')])
    assert ingest_participant_roster.main() == 2
    assert 'PARTICIPANT_DB_MISMATCH' in capsys.readouterr().out
    assert not destination.exists()


def test_runtime_cli_exit_contract_with_and_without_receipt(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    db = tmp_path / 'cli-participant.sqlite'
    store = roster.ParticipantStore.open(db)
    receipt = dict(batch_id='cli-batch', trip_id='cli-trip', google_trip_key='cli-key',
                   new_participants=1, reused_participants=0, status='registered')
    store.conn.execute(
        "INSERT INTO roster_batches(batch_id,roster_id,revision,fingerprint,authority,status,result_json,created_at,updated_at) "
        "VALUES ('cli-batch','cli-roster',1,'synthetic','owner_confirmed_insurance','registered',?,'synthetic','synthetic')",
        (json.dumps(receipt),))
    store.close()
    receipt_path = tmp_path / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
    env = dict(os.environ, WEBLEDGER_PARTICIPANT_DB=str(db))
    script = Path(__file__).resolve().parents[2] / 'tools' / 'verify_participant_runtime.py'

    preflight = subprocess.run([sys.executable, str(script), '--db', str(db)],
                               capture_output=True, text=True, env=env, check=False)
    assert preflight.returncode == 0
    assert json.loads(preflight.stdout)['status'] == 'ready_for_receipt_check'

    accepted = subprocess.run([sys.executable, str(script), '--db', str(db), '--receipt', str(receipt_path)],
                              capture_output=True, text=True, env=env, check=False)
    assert accepted.returncode == 0
    assert json.loads(accepted.stdout)['status'] == 'accepted'

    receipt_path.write_text('{malformed', encoding='utf-8')
    malformed = subprocess.run([sys.executable, str(script), '--db', str(db), '--receipt', str(receipt_path)],
                               capture_output=True, text=True, env=env, check=False)
    assert malformed.returncode == 2
    assert json.loads(malformed.stdout)['code'] == 'PARTICIPANT_RECEIPT_INVALID'

    mismatch = subprocess.run([sys.executable, str(script), '--db', str(db), '--web-db', str(tmp_path / 'other.sqlite')],
                              capture_output=True, text=True, env=env, check=False)
    assert mismatch.returncode == 2
    assert json.loads(mismatch.stdout)['status'] == 'blocked'

    # Receipt file size limit (fail-closed)
    large_receipt = tmp_path / 'large_receipt.json'
    large_receipt.write_text('{"x": "' + 'a' * 200000 + '"}', encoding='utf-8')
    oversized = subprocess.run([sys.executable, str(script), '--db', str(db), '--receipt', str(large_receipt)],
                               capture_output=True, text=True, env=env, check=False)
    assert oversized.returncode == 2
    assert json.loads(oversized.stdout)['code'] == 'PARTICIPANT_RECEIPT_TOO_LARGE'
