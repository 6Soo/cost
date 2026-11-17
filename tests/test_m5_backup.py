"""Synthetic coverage for M5 snapshot, restore, and scheduled pull behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from urllib.parse import quote

import pytest

from tools import m5_backup


def _make_sources(root: Path):
    database = root / "source" / "ledger.sqlite"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE entries (entry_id TEXT PRIMARY KEY, amount INTEGER NOT NULL)")
    connection.executemany(
        "INSERT INTO entries(entry_id, amount) VALUES (?, ?)",
        [("syn-1", 1200), ("syn-2", -300)],
    )
    connection.commit()

    originals = root / "originals"
    (originals / "receipts").mkdir(parents=True)
    (originals / "receipts" / "syn-1.txt").write_bytes(b"synthetic receipt one\n")
    (originals / "mail.txt").write_bytes(b"synthetic mail body\n")
    return database, originals, connection


def _create_snapshot(root: Path):
    database, originals, connection = _make_sources(root)
    snapshot = root / "snapshot"
    try:
        result = m5_backup.create_snapshot(
            {"ledger": database}, {"records": originals}, snapshot
        )
    finally:
        connection.close()
    return database, originals, snapshot, result


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_snapshot_and_restore_include_wal_rows_and_preserve_sources(tmp_path, request):
    database, originals, connection = _make_sources(tmp_path)
    request.addfinalizer(connection.close)
    snapshot = tmp_path / "snapshot"
    wal = Path(str(database) + "-wal")
    assert wal.is_file() and wal.stat().st_size > 0
    source_db_before = database.read_bytes()
    source_wal_before = wal.read_bytes()
    originals_before = _snapshot_tree(originals)

    created = m5_backup.create_snapshot(
        {"ledger": database}, {"records": originals}, snapshot
    )
    assert created["ok"] is True
    assert m5_backup.verify_snapshot(snapshot) == created

    restored = tmp_path / "restored"
    restored_result = m5_backup.restore_snapshot(snapshot, restored)
    assert restored_result == created
    assert m5_backup.verify_snapshot(restored) == created
    assert (restored / "databases" / "ledger.sqlite").read_bytes() == (
        snapshot / "databases" / "ledger.sqlite"
    ).read_bytes()
    assert _snapshot_tree(restored / "originals") == _snapshot_tree(snapshot / "originals")

    with sqlite3.connect(restored / "databases" / "ledger.sqlite") as restored_db:
        assert restored_db.execute(
            "SELECT entry_id, amount FROM entries ORDER BY entry_id"
        ).fetchall() == [("syn-1", 1200), ("syn-2", -300)]

    assert database.read_bytes() == source_db_before
    assert wal.read_bytes() == source_wal_before
    assert _snapshot_tree(originals) == originals_before


def test_tampered_snapshot_manifest_and_file_are_rejected(tmp_path):
    _database, _originals, snapshot, _created = _create_snapshot(tmp_path / "base")

    bad_file = tmp_path / "bad-file"
    shutil.copytree(snapshot, bad_file)
    with (bad_file / "databases" / "ledger.sqlite").open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(m5_backup.BackupError, match="SNAPSHOT_INVALID"):
        m5_backup.verify_snapshot(bad_file)

    bad_manifest = tmp_path / "bad-manifest"
    shutil.copytree(snapshot, bad_manifest)
    manifest_path = bad_manifest / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at_utc"] = "2026-11-17T00:00:00Z"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(m5_backup.BackupError):
        m5_backup.verify_snapshot(bad_manifest)


def test_path_traversal_reparse_and_existing_destination_are_rejected(tmp_path, monkeypatch):
    _database, _originals, snapshot, _created = _create_snapshot(tmp_path / "base")

    traversal = tmp_path / "traversal"
    shutil.copytree(snapshot, traversal)
    manifest_path = traversal / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "databases/../../escaped.sqlite"
    body = {key: manifest[key] for key in ("schema", "created_at_utc", "files")}
    manifest["snapshot_id"] = hashlib.sha256(
        m5_backup._canonical_bytes(body)
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    escaped = tmp_path / "escaped.sqlite"
    with pytest.raises(m5_backup.BackupError, match="PATH_INVALID"):
        m5_backup.restore_snapshot(traversal, tmp_path / "traversal-restore")
    assert not escaped.exists()

    database_file = snapshot / "databases" / "ledger.sqlite"
    actual_is_reparse = m5_backup._is_reparse

    def synthetic_reparse(path: Path) -> bool:
        if Path(path) == database_file:
            return True
        return actual_is_reparse(path)

    monkeypatch.setattr(m5_backup, "_is_reparse", synthetic_reparse)
    with pytest.raises(m5_backup.BackupError, match="PATH_INVALID"):
        m5_backup.verify_snapshot(snapshot)
    monkeypatch.setattr(m5_backup, "_is_reparse", actual_is_reparse)

    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_bytes(b"keep existing destination")
    with pytest.raises(m5_backup.BackupError, match="DESTINATION_EXISTS"):
        m5_backup.restore_snapshot(snapshot, destination)
    assert sentinel.read_bytes() == b"keep existing destination"
    with pytest.raises(m5_backup.BackupError, match="DESTINATION_EXISTS"):
        m5_backup.create_snapshot(
            {"ledger": _database}, {"records": _originals}, destination
        )
    assert sentinel.read_bytes() == b"keep existing destination"


class _SyntheticDownloadClient:
    def __init__(self, snapshot: Path):
        self.manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.files = {
            f"/v1/backup/files/{quote(row['path'], safe='')}": (
                snapshot / Path(*row["path"].split("/"))
            ).read_bytes()
            for row in self.manifest["files"]
        }
        self.manifest_calls = 0
        self.download_calls: list[str] = []

    def get_json(self, path: str):
        assert path == "/v1/backup/manifest"
        self.manifest_calls += 1
        return json.loads(json.dumps(self.manifest))

    def download(self, path: str, target: Path):
        self.download_calls.append(path)
        target.write_bytes(self.files[path])


def test_pull_publishes_then_waits_until_24_hours_and_pulls_again(tmp_path):
    _database, _originals, snapshot, created = _create_snapshot(tmp_path / "source")
    client = _SyntheticDownloadClient(snapshot)
    destination = tmp_path / "node-backups"
    first_time = datetime(2026, 11, 17, 2, 30, tzinfo=timezone.utc)

    first = m5_backup.pull_snapshot(client, destination, now=first_time)
    assert first["ok"] is True
    assert first["skipped"] is False
    assert first["snapshot_id"] == created["snapshot_id"]
    first_generation = destination / first["generation"]
    assert m5_backup.verify_snapshot(first_generation) == created
    assert len(client.download_calls) == len(client.manifest["files"])

    not_due = m5_backup.pull_snapshot(
        client, destination, now=first_time + timedelta(hours=23, minutes=59)
    )
    assert not_due["ok"] is True
    assert not_due["skipped"] is True
    assert not_due["code"] == "NOT_DUE"
    assert client.manifest_calls == 1
    assert len(client.download_calls) == len(client.manifest["files"])

    due = m5_backup.pull_snapshot(
        client, destination, now=first_time + timedelta(hours=24)
    )
    assert due["ok"] is True
    assert due["skipped"] is False
    assert due["snapshot_id"] == created["snapshot_id"]
    assert (destination / due["generation"]).is_dir()
    assert first_generation.is_dir()
    assert client.manifest_calls == 2
    assert len(client.download_calls) == 2 * len(client.manifest["files"])
