"""Synthetic coverage for M5 snapshot, restore, and scheduled pull behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
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


class _FailingDownloadClient(_SyntheticDownloadClient):
    def __init__(self, snapshot: Path, failure_mode: str):
        super().__init__(snapshot)
        self.failure_mode = failure_mode

    def download(self, path: str, target: Path):
        self.download_calls.append(path)
        content = self.files[path]
        if self.failure_mode == "partial_download":
            target.write_bytes(content[:max(1, len(content) // 2)])
            raise OSError("synthetic interrupted download")
        if self.failure_mode == "hash_mismatch":
            target.write_bytes(content + b"synthetic corruption")
            return
        target.write_bytes(content)


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


@pytest.mark.parametrize(
    ("failure_mode", "expected_code", "retries"),
    [
        ("partial_download", "PULL_FAILED", 3),
        ("hash_mismatch", "PULL_HASH_MISMATCH", 1),
        ("restore_publish", "PUBLISH_FAILED", 1),
        ("rehearsal_verify", "SNAPSHOT_INVALID", 1),
    ],
)
def test_failed_pull_retries_clean_only_owned_staging_and_preserve_data(
    tmp_path, monkeypatch, failure_mode, expected_code, retries
):
    _database, _originals, snapshot, created = _create_snapshot(tmp_path / "source")
    destination = tmp_path / "node-backups"
    first_time = datetime(2026, 11, 17, 2, 30, tzinfo=timezone.utc)
    first = m5_backup.pull_snapshot(
        _SyntheticDownloadClient(snapshot), destination, now=first_time
    )
    assert first["ok"] is True
    published = destination / first["generation"]
    state_before = (destination / "pull-state.json").read_bytes()
    user_file = destination / "keep-user-file.txt"
    user_file.write_bytes(b"user-owned synthetic note")

    if failure_mode == "restore_publish":
        actual_publish = m5_backup._publish

        def fail_rehearsal_publish(stage: Path, target: Path):
            if target.name.startswith(".restore-check-"):
                raise m5_backup.BackupError("PUBLISH_FAILED")
            actual_publish(stage, target)

        monkeypatch.setattr(m5_backup, "_publish", fail_rehearsal_publish)
    elif failure_mode == "rehearsal_verify":
        actual_verify = m5_backup.verify_snapshot

        def fail_rehearsal_verify(path: Path):
            if Path(path).name.startswith(".restore-check-"):
                raise m5_backup.BackupError("SNAPSHOT_INVALID")
            return actual_verify(path)

        monkeypatch.setattr(m5_backup, "verify_snapshot", fail_rehearsal_verify)

    for _attempt in range(retries):
        client = _FailingDownloadClient(snapshot, failure_mode)
        result = m5_backup.pull_snapshot(
            client, destination, now=first_time + timedelta(hours=24)
        )
        assert result == {"ok": False, "code": expected_code}
        assert client.manifest_calls == 1
        assert list(destination.glob(".incoming-*.tmp")) == []
        assert not any(
            child.is_dir() and "restore-check-" in child.name
            for child in destination.iterdir()
        )
        assert (destination / "pull-state.json").read_bytes() == state_before
        assert user_file.read_bytes() == b"user-owned synthetic note"
        assert published.is_dir()
        assert m5_backup.verify_snapshot(published) == created


def test_pull_state_write_failures_remove_only_new_generation(tmp_path, monkeypatch):
    _database, _originals, snapshot, created = _create_snapshot(tmp_path / "source")
    destination = tmp_path / "node-backups"
    first_time = datetime(2026, 11, 17, 2, 30, tzinfo=timezone.utc)
    first = m5_backup.pull_snapshot(
        _SyntheticDownloadClient(snapshot), destination, now=first_time
    )
    assert first["ok"] is True
    existing_generation = destination / first["generation"]
    existing_names = sorted(
        path.name for path in destination.iterdir()
        if path.is_dir() and path.name.startswith("snapshot-")
    )
    state_before = (destination / "pull-state.json").read_bytes()
    user_file = destination / "keep-user-file.txt"
    user_file.write_bytes(b"user-owned synthetic note")

    def fail_state_write(_path: Path, _now: datetime, _snapshot_id: str):
        raise m5_backup.BackupError("PULL_STATE_WRITE_FAILED")

    monkeypatch.setattr(m5_backup, "_write_pull_state", fail_state_write)

    for _attempt in range(3):
        client = _SyntheticDownloadClient(snapshot)
        result = m5_backup.pull_snapshot(
            client, destination, now=first_time + timedelta(hours=24)
        )
        assert result == {"ok": False, "code": "PULL_STATE_WRITE_FAILED"}
        assert client.manifest_calls == 1
        assert sorted(
            path.name for path in destination.iterdir()
            if path.is_dir() and path.name.startswith("snapshot-")
        ) == existing_names
        assert (destination / "pull-state.json").read_bytes() == state_before
        assert user_file.read_bytes() == b"user-owned synthetic note"
        assert list(destination.glob(".incoming-*.tmp")) == []
        assert not any(
            child.is_dir() and "restore-check-" in child.name
            for child in destination.iterdir()
        )
        assert existing_generation.is_dir()
        assert m5_backup.verify_snapshot(existing_generation) == created


def test_failed_create_cleans_owned_stage_and_retry_succeeds(tmp_path, monkeypatch):
    database, originals, connection = _make_sources(tmp_path)
    try:
        destination = tmp_path / "snapshots" / "daily"
        destination.parent.mkdir(parents=True)
        user_file = destination.parent / "keep-user-file.txt"
        user_file.write_bytes(b"user-owned synthetic note")
        database_before = database.read_bytes()
        originals_before = _snapshot_tree(originals)
        actual_copy = m5_backup._copy_file

        def fail_copy(_source: Path, _target: Path):
            raise m5_backup.BackupError("FILE_COPY_FAILED")

        monkeypatch.setattr(m5_backup, "_copy_file", fail_copy)
        with pytest.raises(m5_backup.BackupError, match="FILE_COPY_FAILED"):
            m5_backup.create_snapshot(
                {"ledger": database}, {"records": originals}, destination
            )
        assert not destination.exists()
        assert list(destination.parent.glob(".*.tmp")) == []
        assert user_file.read_bytes() == b"user-owned synthetic note"
        assert database.read_bytes() == database_before
        assert _snapshot_tree(originals) == originals_before

        monkeypatch.setattr(m5_backup, "_copy_file", actual_copy)
        created = m5_backup.create_snapshot(
            {"ledger": database}, {"records": originals}, destination
        )
        assert created["ok"] is True
        assert m5_backup.verify_snapshot(destination) == created
    finally:
        connection.close()


def test_failed_restore_cleans_owned_stage_and_retry_succeeds(tmp_path, monkeypatch):
    _database, _originals, snapshot, created = _create_snapshot(tmp_path / "base")
    destination = tmp_path / "restored"
    user_file = tmp_path / "keep-user-file.txt"
    user_file.write_bytes(b"user-owned synthetic note")
    actual_copy = m5_backup._copy_file

    def fail_copy(_source: Path, _target: Path):
        raise m5_backup.BackupError("FILE_COPY_FAILED")

    monkeypatch.setattr(m5_backup, "_copy_file", fail_copy)
    with pytest.raises(m5_backup.BackupError, match="FILE_COPY_FAILED"):
        m5_backup.restore_snapshot(snapshot, destination)
    assert not destination.exists()
    assert list(tmp_path.glob(".*.tmp")) == []
    assert user_file.read_bytes() == b"user-owned synthetic note"
    assert m5_backup.verify_snapshot(snapshot) == created

    monkeypatch.setattr(m5_backup, "_copy_file", actual_copy)
    assert m5_backup.restore_snapshot(snapshot, destination) == created
    assert m5_backup.verify_snapshot(destination) == created


def test_pull_state_replace_failure_cleans_temp_and_generation_then_retry_succeeds(
    tmp_path, monkeypatch
):
    _database, _originals, snapshot, created = _create_snapshot(tmp_path / "source")
    destination = tmp_path / "node-backups"
    first_time = datetime(2026, 11, 17, 2, 30, tzinfo=timezone.utc)
    first = m5_backup.pull_snapshot(
        _SyntheticDownloadClient(snapshot), destination, now=first_time
    )
    assert first["ok"] is True
    existing_generation = destination / first["generation"]
    state_before = (destination / "pull-state.json").read_bytes()
    user_file = destination / "keep-user-file.txt"
    user_file.write_bytes(b"user-owned synthetic note")
    actual_replace = os.replace

    def fail_state_replace(src, dst):
        if Path(dst).name == "pull-state.json":
            raise OSError("synthetic state replace failure")
        return actual_replace(src, dst)

    monkeypatch.setattr(m5_backup.os, "replace", fail_state_replace)
    result = m5_backup.pull_snapshot(
        _SyntheticDownloadClient(snapshot), destination,
        now=first_time + timedelta(hours=24),
    )
    assert result == {"ok": False, "code": "PULL_STATE_WRITE_FAILED"}
    assert list(destination.glob(".pull-state.json.*.tmp")) == []
    assert list(destination.glob(".incoming-*.tmp")) == []
    assert sorted(
        path.name for path in destination.iterdir()
        if path.is_dir() and path.name.startswith("snapshot-")
    ) == [existing_generation.name]
    assert (destination / "pull-state.json").read_bytes() == state_before
    assert user_file.read_bytes() == b"user-owned synthetic note"
    assert m5_backup.verify_snapshot(existing_generation) == created

    monkeypatch.setattr(m5_backup.os, "replace", actual_replace)
    retry_time = first_time + timedelta(hours=48)
    retry = m5_backup.pull_snapshot(
        _SyntheticDownloadClient(snapshot), destination, now=retry_time
    )
    assert retry["ok"] is True
    assert retry["skipped"] is False
    assert retry["snapshot_id"] == created["snapshot_id"]
    assert retry["generation"].startswith(
        "snapshot-" + retry_time.strftime("%Y%m%dT%H%M%SZ") + "-"
    )
    assert m5_backup.verify_snapshot(destination / retry["generation"]) == created
    assert existing_generation.is_dir()
    state = json.loads((destination / "pull-state.json").read_text(encoding="utf-8"))
    assert state["snapshot_id"] == created["snapshot_id"]
    assert state["last_success_at_utc"] == "2026-11-19T02:30:00Z"
    manifest = json.loads(
        (destination / retry["generation"] / "manifest.json").read_text(encoding="utf-8")
    )
    m5_backup._parse_stamp(manifest["created_at_utc"])


def test_create_destination_overlapping_sources_is_rejected(tmp_path):
    database, originals, connection = _make_sources(tmp_path)
    try:
        with pytest.raises(m5_backup.BackupError, match="DESTINATION_OVERLAPS_SOURCE"):
            m5_backup.create_snapshot(
                {"ledger": database}, {"records": originals},
                originals / "nested-snapshot",
            )
        assert not (originals / "nested-snapshot").exists()
        # An existing source ancestor hits the existence guard before overlap.
        with pytest.raises(m5_backup.BackupError, match="DESTINATION_EXISTS"):
            m5_backup.create_snapshot(
                {"ledger": database}, {"records": originals}, database.parent
            )
        assert database.is_file()
    finally:
        connection.close()


def test_restore_destination_overlapping_snapshot_is_rejected_before_any_path(tmp_path):
    _database, _originals, snapshot, created = _create_snapshot(tmp_path / "base")
    before = _snapshot_tree(snapshot)

    nested = snapshot / "nested"
    with pytest.raises(m5_backup.BackupError, match="DESTINATION_OVERLAPS_SOURCE"):
        m5_backup.restore_snapshot(snapshot, nested)
    assert not nested.exists()
    assert list(snapshot.glob(".*-restore-*.tmp")) == []
    assert _snapshot_tree(snapshot) == before
    assert m5_backup.verify_snapshot(snapshot) == created

    with pytest.raises(m5_backup.BackupError, match="DESTINATION_OVERLAPS_SOURCE"):
        m5_backup.restore_snapshot(snapshot, snapshot)
    assert _snapshot_tree(snapshot) == before
    assert m5_backup.verify_snapshot(snapshot) == created

    with pytest.raises(m5_backup.BackupError, match="DESTINATION_OVERLAPS_SOURCE"):
        m5_backup.restore_snapshot(snapshot, tmp_path / "base")
    assert (tmp_path / "base").is_dir()
    assert _snapshot_tree(snapshot) == before
    assert m5_backup.verify_snapshot(snapshot) == created

    sibling = tmp_path / "sibling-restore"
    assert m5_backup.restore_snapshot(snapshot, sibling) == created
    assert m5_backup.verify_snapshot(sibling) == created


def test_corrupt_pull_state_is_replaced_without_touching_generations(tmp_path):
    _database, _originals, snapshot, created = _create_snapshot(tmp_path / "source")
    destination = tmp_path / "node-backups"
    first_time = datetime(2026, 11, 17, 2, 30, tzinfo=timezone.utc)
    first = m5_backup.pull_snapshot(
        _SyntheticDownloadClient(snapshot), destination, now=first_time
    )
    assert first["ok"] is True
    existing_generation = destination / first["generation"]
    (destination / "pull-state.json").write_text("corrupt", encoding="utf-8")

    result = m5_backup.pull_snapshot(
        _SyntheticDownloadClient(snapshot), destination,
        now=first_time + timedelta(hours=1),
    )
    assert result["ok"] is True
    assert result["skipped"] is False
    assert result["snapshot_id"] == created["snapshot_id"]
    assert m5_backup.verify_snapshot(destination / result["generation"]) == created
    assert m5_backup.verify_snapshot(existing_generation) == created
    state = json.loads((destination / "pull-state.json").read_text(encoding="utf-8"))
    assert state["last_success_at_utc"] == "2026-11-17T03:30:00Z"
