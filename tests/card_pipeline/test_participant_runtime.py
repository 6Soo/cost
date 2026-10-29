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
