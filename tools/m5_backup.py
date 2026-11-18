"""Provider-independent, content-verified snapshots for the M5 node pull path.

This module never deletes prior snapshots or overwrites a restore destination.
Source paths and file contents are kept out of errors and return summaries.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import stat
import uuid
from urllib.parse import quote


SCHEMA = "m5-backup-v1"
STATE_SCHEMA = "m5-backup-pull-state-v1"
_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GENERATION = re.compile(r"^snapshot-\d{8}T\d{6}Z-([0-9a-f]{16})-([0-9a-f]{8})$")
_CHUNK_SIZE = 1024 * 1024
_BUSY_TIMEOUT_MS = 10_000


class BackupError(ValueError):
    """A stable, content-free failure code suitable for caller logs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str):
    raise BackupError(code)


def _utc(value: datetime | None = None) -> datetime:
    value = datetime.now(timezone.utc) if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail("TIME_INVALID")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_stamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("MANIFEST_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("MANIFEST_INVALID")
    if _stamp(parsed) != value:
        _fail("MANIFEST_INVALID")
    return parsed


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction is not None and isjunction(path):
            return True
        info = path.lstat()
        flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(flag and getattr(info, "st_file_attributes", 0) & flag)
    except FileNotFoundError:
        return False
    except OSError:
        _fail("PATH_INVALID")


def _absolute(path: str | os.PathLike, code: str = "PATH_INVALID") -> Path:
    try:
        value = Path(path)
        if not value.is_absolute():
            _fail(code)
        return Path(os.path.abspath(value))
    except BackupError:
        raise
    except Exception:
        _fail(code)


def _reject_reparse_components(path: Path, *, include_self: bool = True) -> None:
    current = path if include_self else path.parent
    existing = []
    while True:
        if os.path.lexists(current):
            existing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(existing):
        if _is_reparse(component):
            _fail("PATH_INVALID")


def _safe_label(value: object) -> str:
    if not isinstance(value, str) or not _LABEL.fullmatch(value):
        _fail("LABEL_INVALID")
    return value


def _portable_part(part: str) -> bool:
    if (not part or part in (".", "..") or part[-1:] in (".", " ") or
            any(char in part for char in '<>:"|?*\\\x00')):
        return False
    stem = part.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"}:
        return False
    if re.fullmatch(r"COM[1-9]|LPT[1-9]", stem):
        return False
    return True


def _safe_relpath(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _fail("PATH_INVALID")
    win = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if (posix.is_absolute() or win.is_absolute() or win.drive or value.startswith("/") or
            posix.as_posix() != value or any(not _portable_part(part) for part in posix.parts)):
        _fail("PATH_INVALID")
    return value


def _validate_manifest(manifest: object) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "created_at_utc", "files", "snapshot_id"}:
        _fail("MANIFEST_INVALID")
    if manifest["schema"] != SCHEMA:
        _fail("MANIFEST_INVALID")
    _parse_stamp(manifest["created_at_utc"])
    rows = manifest["files"]
    if not isinstance(rows, list) or not rows:
        _fail("MANIFEST_INVALID")
    seen: dict[str, str] = {}
    expected_dirs: set[str] = set()
    database_count = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256", "kind"}:
            _fail("MANIFEST_INVALID")
        rel = _safe_relpath(row["path"])
        if type(row["size"]) is not int or row["size"] < 0:
            _fail("MANIFEST_INVALID")
        if not isinstance(row["sha256"], str) or not _SHA256.fullmatch(row["sha256"]):
            _fail("MANIFEST_INVALID")
        kind = row["kind"]
        if kind == "database":
            if not rel.startswith("databases/") or not rel.endswith(".sqlite"):
                _fail("MANIFEST_INVALID")
            database_count += 1
        elif kind == "original":
            if not rel.startswith("originals/"):
                _fail("MANIFEST_INVALID")
        else:
            _fail("MANIFEST_INVALID")

        folded = rel.casefold()
        if folded in seen:
            _fail("PATH_COLLISION")
        seen[folded] = rel
        parts = rel.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            parent_folded = parent.casefold()
            existing = seen.get(parent_folded)
            if existing is not None and existing != parent:
                _fail("PATH_COLLISION")
            seen[parent_folded] = parent
            expected_dirs.add(parent)
        # A file may not also be an ancestor of another file.
        if any(other.startswith(folded + "/") for other in seen if other != folded):
            _fail("PATH_COLLISION")
    if database_count == 0:
        _fail("MANIFEST_INVALID")

    supplied_id = manifest["snapshot_id"]
    if not isinstance(supplied_id, str) or not _SHA256.fullmatch(supplied_id):
        _fail("MANIFEST_INVALID")
    body = {key: manifest[key] for key in ("schema", "created_at_utc", "files")}
    expected_id = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    if supplied_id != expected_id:
        _fail("MANIFEST_INVALID")
    return manifest


def _manifest_for(rows: list[dict], created_at: datetime | None = None) -> dict:
    rows = sorted(rows, key=lambda row: row["path"])
    body = {"schema": SCHEMA, "created_at_utc": _stamp(created_at), "files": rows}
    return {**body, "snapshot_id": hashlib.sha256(_canonical_bytes(body)).hexdigest()}


def _read_manifest(folder: Path) -> dict:
    manifest_path = folder / "manifest.json"
    _reject_reparse_components(manifest_path)
    if not manifest_path.is_file():
        _fail("MANIFEST_INVALID")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        _fail("MANIFEST_INVALID")
    return _validate_manifest(value)


def _contained(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _member_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    relative = _safe_relpath(relative)
    path = root.joinpath(*relative.split("/"))
    if not _contained(root, path):
        _fail("PATH_INVALID")
    _reject_reparse_components(path)
    if must_exist and not path.is_file():
        _fail("SNAPSHOT_INVALID")
    return path


def _walk_files(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        _reject_reparse_components(directory)
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError:
            _fail("SNAPSHOT_INVALID")
        for entry in entries:
            child = Path(entry.path)
            if _is_reparse(child):
                _fail("PATH_INVALID")
            rel = f"{prefix}/{entry.name}" if prefix else entry.name
            if rel == "manifest.json":
                continue
            if entry.is_dir(follow_symlinks=False):
                safe = _safe_relpath(rel)
                directories.add(safe)
                pending.append((child, safe))
            elif entry.is_file(follow_symlinks=False):
                files.add(_safe_relpath(rel))
            else:
                _fail("PATH_INVALID")
    return files, directories


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(block)
                size += len(block)
    except OSError:
        _fail("FILE_READ_FAILED")
    return digest.hexdigest(), size


def _sqlite_integrity(path: Path) -> None:
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            result = connection.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            _fail("SQLITE_INTEGRITY_FAILED")
    except BackupError:
        raise
    except Exception:
        _fail("SQLITE_INTEGRITY_FAILED")


def verify_snapshot(folder: str | os.PathLike) -> dict:
    """Verify manifest, exact file inventory, hashes, and SQLite integrity."""
    try:
        root = _absolute(folder)
        _reject_reparse_components(root)
        if not root.is_dir():
            _fail("SNAPSHOT_INVALID")
        manifest = _read_manifest(root)
        expected = {row["path"] for row in manifest["files"]}
        actual, directories = _walk_files(root)
        if actual != expected:
            _fail("SNAPSHOT_INVALID")
        expected_dirs = {
            "/".join(path.split("/")[:index])
            for path in expected
            for index in range(1, len(path.split("/")))
        }
        if directories != expected_dirs:
            _fail("SNAPSHOT_INVALID")
        total = 0
        for row in manifest["files"]:
            path = _member_path(root, row["path"], must_exist=True)
            digest, size = _hash_file(path)
            if digest != row["sha256"] or size != row["size"]:
                _fail("SNAPSHOT_INVALID")
            if row["kind"] == "database":
                _sqlite_integrity(path)
            total += size
        return {"ok": True, "snapshot_id": manifest["snapshot_id"],
                "files": len(expected), "total_bytes": total}
    except BackupError as exc:
        if exc.code in {"PATH_INVALID", "PATH_COLLISION"}:
            raise BackupError(exc.code) from None
        raise BackupError("SNAPSHOT_INVALID") from None
    except Exception:
        _fail("SNAPSHOT_INVALID")


def _copy_file(source: Path, target: Path) -> tuple[str, int]:
    _reject_reparse_components(source)
    if not source.is_file():
        _fail("SOURCE_INVALID")
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_components(target.parent)
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as src, target.open("xb") as dst:
            for block in iter(lambda: src.read(_CHUNK_SIZE), b""):
                dst.write(block)
                digest.update(block)
                size += len(block)
            dst.flush()
            os.fsync(dst.fileno())
    except BackupError:
        raise
    except Exception:
        _fail("FILE_COPY_FAILED")
    return digest.hexdigest(), size


def _prepare_parent(path: Path) -> None:
    _reject_reparse_components(path.parent)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        _fail("DESTINATION_INVALID")
    _reject_reparse_components(path.parent)
    if not path.parent.is_dir():
        _fail("DESTINATION_INVALID")


def _new_stage(parent: Path, prefix: str) -> Path:
    for _ in range(10):
        candidate = parent / f".{prefix}-{uuid.uuid4().hex}.tmp"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
        except OSError:
            _fail("DESTINATION_INVALID")
    _fail("DESTINATION_INVALID")


def _publish(stage: Path, destination: Path) -> None:
    _reject_reparse_components(destination.parent)
    if os.path.lexists(destination):
        _fail("DESTINATION_EXISTS")
    try:
        os.rename(stage, destination)
    except FileExistsError:
        _fail("DESTINATION_EXISTS")
    except OSError:
        _fail("PUBLISH_FAILED")


def _prepare_databases(databases: dict[str, Path]) -> list[tuple[str, Path]]:
    if not isinstance(databases, dict) or not databases:
        _fail("DATABASES_REQUIRED")
    entries = []
    seen_labels: set[str] = set()
    seen_paths: set[str] = set()
    for label, raw_path in databases.items():
        safe = _safe_label(label)
        folded = safe.casefold()
        if folded in seen_labels:
            _fail("LABEL_COLLISION")
        seen_labels.add(folded)
        path = _absolute(raw_path, "DATABASE_INVALID")
        _reject_reparse_components(path)
        if not path.is_file():
            _fail("DATABASE_INVALID")
        resolved = str(path.resolve(strict=True)).casefold()
        if resolved in seen_paths:
            _fail("DATABASE_COLLISION")
        seen_paths.add(resolved)
        entries.append((safe, path))
    return sorted(entries)


def _prepare_original_roots(originals: dict[str, Path]) -> list[tuple[str, Path]]:
    if not isinstance(originals, dict):
        _fail("ORIGINALS_INVALID")
    entries = []
    seen_labels: set[str] = set()
    seen_paths: set[str] = set()
    for label, raw_path in originals.items():
        safe = _safe_label(label)
        folded = safe.casefold()
        if folded in seen_labels:
            _fail("LABEL_COLLISION")
        seen_labels.add(folded)
        path = _absolute(raw_path, "ORIGINAL_INVALID")
        _reject_reparse_components(path)
        if not (path.is_file() or path.is_dir()):
            _fail("ORIGINAL_INVALID")
        resolved = str(path.resolve(strict=True)).casefold()
        if resolved in seen_paths:
            _fail("ORIGINAL_COLLISION")
        seen_paths.add(resolved)
        entries.append((safe, path))
    return sorted(entries)


def _check_no_overlap(destination: Path, databases: list[tuple[str, Path]],
                      originals: list[tuple[str, Path]]) -> None:
    target = destination.resolve(strict=False)
    for _label, source in [*databases, *originals]:
        resolved = source.resolve(strict=True)
        if target == resolved or _contained(resolved, target) or _contained(target, resolved):
            _fail("DESTINATION_OVERLAPS_SOURCE")


def _original_inventory(originals: list[tuple[str, Path]]) -> dict[str, tuple[Path, str, int]]:
    inventory: dict[str, tuple[Path, str, int]] = {}
    for label, root in originals:
        _reject_reparse_components(root)
        if root.is_file():
            source_files = [(root.name, root)]
        elif root.is_dir():
            source_files = []
            pending = [(root, "")]
            while pending:
                directory, prefix = pending.pop()
                _reject_reparse_components(directory)
                try:
                    children = sorted(directory.iterdir(), key=lambda child: child.name.casefold())
                except OSError:
                    _fail("ORIGINAL_INVALID")
                for child in children:
                    if _is_reparse(child):
                        _fail("PATH_INVALID")
                    relative = f"{prefix}/{child.name}" if prefix else child.name
                    _safe_relpath(relative)
                    if child.is_dir():
                        pending.append((child, relative))
                    elif child.is_file():
                        source_files.append((relative, child))
                    else:
                        _fail("ORIGINAL_INVALID")
        else:
            _fail("ORIGINAL_INVALID")

        for relative, source in source_files:
            rel = _safe_relpath(f"originals/{label}/{relative}")
            if rel.casefold() in (key.casefold() for key in inventory):
                _fail("PATH_COLLISION")
            digest, size = _hash_file(source)
            inventory[rel] = (source, digest, size)
    return inventory


def _guarded_database_backups(databases: list[tuple[str, Path]], stage: Path) -> None:
    guard = sqlite3.connect(":memory:", isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
    try:
        guard.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        for index, (_label, source) in enumerate(databases):
            guard.execute(f"ATTACH DATABASE ? AS source_{index}", (str(source.resolve()),))
        guard.execute("BEGIN IMMEDIATE")
        for label, source in databases:
            relative = f"databases/{label}.sqlite"
            target = _member_path(stage, relative)
            _backup_sqlite(source, target)
    except BackupError:
        raise
    except Exception:
        _fail("DATABASE_SNAPSHOT_FAILED")
    finally:
        try:
            guard.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        guard.close()


def _backup_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_components(target.parent)
    src = dest = None
    try:
        uri = source.resolve(strict=True).as_uri() + "?mode=ro"
        src = sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_MS / 1000)
        src.execute("PRAGMA query_only=ON")
        dest = sqlite3.connect(target)
        src.backup(dest, pages=256, sleep=0.05)
        # The backup API copies the source's WAL journal mode into the snapshot.
        # Normalize the closed snapshot file so verification does not create
        # extra -wal/-shm members beside the manifest-listed database.
        journal_mode = dest.execute("PRAGMA journal_mode=DELETE").fetchone()
        if journal_mode != ("delete",):
            _fail("DATABASE_SNAPSHOT_FAILED")
        dest.close()
        dest = None
        src.close()
        src = None
        _sqlite_integrity(target)
        # Windows requires a writable descriptor for FlushFileBuffers/fsync.
        with target.open("r+b") as handle:
            os.fsync(handle.fileno())
    except BackupError:
        raise
    except Exception:
        _fail("DATABASE_SNAPSHOT_FAILED")
    finally:
        if dest is not None:
            dest.close()
        if src is not None:
            src.close()


def _write_json_exclusive(path: Path, value: dict) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(_canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        _fail("MANIFEST_WRITE_FAILED")


def _manifest_rows(folder: Path) -> list[dict]:
    rows = []
    files, _directories = _walk_files(folder)
    for relative in sorted(files):
        path = _member_path(folder, relative, must_exist=True)
        digest, size = _hash_file(path)
        kind = "database" if relative.startswith("databases/") else "original"
        rows.append({"path": relative, "size": size, "sha256": digest, "kind": kind})
    return rows


def create_snapshot(databases: dict[str, Path], originals: dict[str, Path],
                    destination: str | os.PathLike) -> dict:
    """Create a new immutable snapshot, holding database writer locks as one set."""
    target = _absolute(destination, "DESTINATION_INVALID")
    if os.path.lexists(target):
        _fail("DESTINATION_EXISTS")
    database_entries = _prepare_databases(databases)
    original_entries = _prepare_original_roots(originals)
    _check_no_overlap(target, database_entries, original_entries)
    _prepare_parent(target)
    if os.path.lexists(target):
        _fail("DESTINATION_EXISTS")
    stage = _new_stage(target.parent, f"{target.name}-snapshot")
    try:
        original_before = _original_inventory(original_entries)
        _guarded_database_backups(database_entries, stage)
        for relative, (source, _digest, _size) in sorted(original_before.items()):
            copied_digest, copied_size = _copy_file(source, _member_path(stage, relative))
            if copied_digest != original_before[relative][1] or copied_size != original_before[relative][2]:
                _fail("ORIGINAL_CHANGED")
        original_after = _original_inventory(original_entries)
        if original_before.keys() != original_after.keys():
            _fail("ORIGINAL_CHANGED")
        for relative, (_source, digest, size) in original_before.items():
            if original_after[relative][1:] != (digest, size):
                _fail("ORIGINAL_CHANGED")

        manifest = _manifest_for(_manifest_rows(stage))
        _validate_manifest(manifest)
        _write_json_exclusive(stage / "manifest.json", manifest)
        verified = verify_snapshot(stage)
        _publish(stage, target)
        return verified
    except BackupError:
        raise
    except Exception:
        _fail("SNAPSHOT_CREATE_FAILED")
    finally:
        _cleanup_owned_directory(
            target.parent,
            stage,
            name_prefix=f".{target.name}-snapshot-",
            name_suffix=".tmp",
        )


def _check_restore_no_overlap(source: Path, target: Path) -> None:
    """Refuse a restore destination that is inside the snapshot or covers it."""
    try:
        root = source.resolve(strict=True)
    except OSError:
        _fail("SNAPSHOT_INVALID")
    probe = target.resolve(strict=False)
    if probe == root or _contained(root, probe) or _contained(probe, root):
        _fail("DESTINATION_OVERLAPS_SOURCE")


def _copy_manifest_and_files(source: Path, manifest: dict, stage: Path) -> None:
    for row in manifest["files"]:
        src = _member_path(source, row["path"], must_exist=True)
        dst = _member_path(stage, row["path"])
        digest, size = _copy_file(src, dst)
        if digest != row["sha256"] or size != row["size"]:
            _fail("RESTORE_HASH_MISMATCH")
    _write_json_exclusive(stage / "manifest.json", manifest)


def restore_snapshot(folder: str | os.PathLike, destination: str | os.PathLike) -> dict:
    """Restore to a new path, validating copied hashes and SQLite integrity."""
    source = _absolute(folder)
    manifest = _read_manifest(source)
    verify_snapshot(source)
    target = _absolute(destination, "DESTINATION_INVALID")
    _check_restore_no_overlap(source, target)
    if os.path.lexists(target):
        _fail("DESTINATION_EXISTS")
    _prepare_parent(target)
    if os.path.lexists(target):
        _fail("DESTINATION_EXISTS")
    stage = _new_stage(target.parent, f"{target.name}-restore")
    try:
        _copy_manifest_and_files(source, manifest, stage)
        result = verify_snapshot(stage)
        _publish(stage, target)
        return result
    except BackupError:
        raise
    except Exception:
        _fail("RESTORE_FAILED")
    finally:
        _cleanup_owned_directory(
            target.parent,
            stage,
            name_prefix=f".{target.name}-restore-",
            name_suffix=".tmp",
        )


STATE_REQUIRED_KEYS = frozenset({"schema", "last_success_at_utc", "snapshot_id"})
STATE_OPTIONAL_KEYS = frozenset({
    "gap_days", "gap_from_utc", "missed_days_total",
    "state_reset_count", "state_reset_reason", "complete",
})
# Fixed reason vocabulary, matching the #1001 request-count summary so both
# tools name the same failure the same way.
STATE_RESET_REASONS = frozenset({"corrupt", "unreadable", "rejected"})


def _read_pull_state(path: Path) -> dict | None:
    """Read the pull state, accepting both current and legacy (3-key) files.

    The key set is checked as "required keys present, only known keys allowed"
    rather than exact equality: the previous exact-match rule made any added
    field look corrupt, which silently turned every run into a new backup.
    """
    if not os.path.lexists(path):
        return None
    _reject_reparse_components(path)
    if not path.is_file():
        _fail("PULL_STATE_INVALID")
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return {"reset_reason": "unreadable"}
    try:
        value = json.loads(raw)
    except Exception:
        return {"reset_reason": "corrupt"}
    try:
        if not isinstance(value, dict) or not STATE_REQUIRED_KEYS <= set(value):
            return {"reset_reason": "rejected"}
        unknown = set(value) - STATE_REQUIRED_KEYS - STATE_OPTIONAL_KEYS
        if unknown or value["schema"] != STATE_SCHEMA:
            return {"reset_reason": "rejected"}
        if not isinstance(value["snapshot_id"], str) or \
                not _SHA256.fullmatch(value["snapshot_id"]):
            return {"reset_reason": "rejected"}
        last_success = _parse_stamp(value["last_success_at_utc"])
        missed = value.get("missed_days_total", 0)
        if type(missed) is not int or missed < 0:
            return {"reset_reason": "rejected"}
        resets = value.get("state_reset_count", 0)
        if type(resets) is not int or resets < 0:
            return {"reset_reason": "rejected"}
        gap_from = value.get("gap_from_utc")
        if gap_from is not None:
            _parse_stamp(gap_from)
        return {
            "last_success": last_success,
            "snapshot_id": value["snapshot_id"],
            "missed_days_total": missed,
            "state_reset_count": resets,
            "state_reset_reason": None,
        }
    except BackupError:
        return {"reset_reason": "rejected"}
    except Exception:
        return {"reset_reason": "rejected"}


def _generation_dates(root: Path) -> list[date]:
    """Dates from published generation directory names under the pull root.

    The state file keeps only the last success, so a multi-day outage is only
    observable by comparing consecutive generation dates.
    """
    try:
        entries = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        _fail("DESTINATION_INVALID")
    dates: list[date] = []
    for entry in entries:
        match = _GENERATION.fullmatch(entry.name)
        if match is None or not entry.is_dir(follow_symlinks=False):
            continue
        if _is_reparse(Path(entry.path)):
            continue
        dates.append(datetime.strptime(entry.name[9:17], "%Y%m%d").date())
    return dates


def _gap_judgement(root: Path, current: datetime) -> dict:
    """Judge missing daily generations from what is actually on disk.

    ``gap_days`` is the empty interval immediately before this pull, so a
    catch-up after an outage reports 0 while ``missed_days_total`` still counts
    the unrepaired holes in the stored history.
    """
    dates = _generation_dates(root)
    today = current.date()
    previous = max(dates) if dates else None
    # The hole immediately before this generation: 0 when yesterday's backup
    # exists, 3 when the PC was off for three days.
    gap_days = 0 if previous is None else max(0, (today - previous).days - 1)
    gap_from = (previous + timedelta(days=1)) if gap_days else None
    # Every hole still present in the stored history, including this one.
    missed = 0
    for before, after in zip([*dates, today], [*dates, today][1:]):
        missed += max(0, (after - before).days - 1)
    return {
        "gap_days": gap_days,
        "gap_from_utc": (None if gap_from is None else
                         f"{gap_from.isoformat()}T00:00:00Z"),
        "missed_days_total": missed,
        "previous_generation_date": (None if previous is None else previous.isoformat()),
    }


def _remove_owned_state_temporary(path: Path) -> None:
    """Remove only the state temporary this call created; keep everything else."""
    try:
        if path.is_file() and not _is_reparse(path):
            path.unlink()
    except Exception:
        return


def _write_pull_state(path: Path, now: datetime, snapshot_id: str, *,
                      gap: dict | None = None, state_resets: int = 0,
                      state_reset_reason: str | None = None) -> None:
    """Write the pull state. The original three keys keep their meaning."""
    if state_reset_reason is not None and state_reset_reason not in STATE_RESET_REASONS:
        _fail("PULL_STATE_INVALID")
    gap = gap or {"gap_days": 0, "gap_from_utc": None, "missed_days_total": 0}
    missed = gap["missed_days_total"]
    value = {
        # Existing keys, unchanged: readers that only know these still work.
        "schema": STATE_SCHEMA,
        "last_success_at_utc": _stamp(now),
        "snapshot_id": snapshot_id,
        # Added judgement. `complete=false` means some daily generations are
        # missing, using the same name as the #1001 request-count summary.
        "gap_days": gap["gap_days"],
        "gap_from_utc": gap["gap_from_utc"],
        "missed_days_total": missed,
        "state_reset_count": state_resets,
        "state_reset_reason": state_reset_reason,
        "complete": (state_resets == 0 and missed == 0
                     and state_reset_reason is None),
    }
    _reject_reparse_components(path.parent)
    if os.path.lexists(path):
        _reject_reparse_components(path)
        if not path.is_file():
            _fail("PULL_STATE_INVALID")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(_canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        if os.path.lexists(path):
            _reject_reparse_components(path)
            if not path.is_file():
                _fail("PULL_STATE_INVALID")
        os.replace(temporary, path)
    except BackupError:
        _remove_owned_state_temporary(temporary)
        raise
    except Exception:
        _remove_owned_state_temporary(temporary)
        _fail("PULL_STATE_WRITE_FAILED")


def _pull_manifest(client) -> dict:
    try:
        manifest = client.get_json("/v1/backup/manifest")
    except Exception:
        _fail("PULL_FAILED")
    return _validate_manifest(manifest)


def _download_snapshot(client, manifest: dict, stage: Path) -> None:
    for row in manifest["files"]:
        relative = row["path"]
        target = _member_path(stage, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse_components(target.parent)
        encoded = quote(relative, safe="")
        try:
            client.download(f"/v1/backup/files/{encoded}", target)
        except Exception:
            _fail("PULL_FAILED")
        _reject_reparse_components(target)
        if not target.is_file():
            _fail("PULL_FAILED")
        digest, size = _hash_file(target)
        if digest != row["sha256"] or size != row["size"]:
            _fail("PULL_HASH_MISMATCH")
    _write_json_exclusive(stage / "manifest.json", manifest)


def _cleanup_owned_directory(root: Path, path: Path, *,
                             name_prefix: str, name_suffix: str = "") -> None:
    """Remove only a named, freshly created temporary directory under root."""
    try:
        _reject_reparse_components(root)
        _reject_reparse_components(path)
        if path.parent.resolve(strict=True) != root.resolve(strict=True):
            return
        if (path.name.startswith(name_prefix) and path.name.endswith(name_suffix)
                and path.is_dir()):
            shutil.rmtree(path)
    except Exception:
        # A failed cleanup leaves prior snapshots and unrelated files untouched.
        return


def _cleanup_owned_restore(root: Path, path: Path) -> None:
    """Remove only a freshly created restore rehearsal under the supplied root."""
    _cleanup_owned_directory(root, path, name_prefix=".restore-check-")


def _cleanup_owned_pull_stage(root: Path, path: Path) -> None:
    """Remove only a freshly created incoming pull stage under the supplied root."""
    _cleanup_owned_directory(
        root, path, name_prefix=".incoming-", name_suffix=".tmp"
    )


def _cleanup_owned_generation(root: Path, path: Path, *, expected_name: str,
                              snapshot_id: str) -> None:
    """Remove only this failed pull's verified generation under the pull root."""
    try:
        _reject_reparse_components(root)
        _reject_reparse_components(path)
        if path.parent.resolve(strict=True) != root.resolve(strict=True):
            return
        match = _GENERATION.fullmatch(path.name)
        if (path.name != expected_name or match is None or
                match.group(1) != snapshot_id[:16] or not path.is_dir()):
            return
        if verify_snapshot(path).get("snapshot_id") != snapshot_id:
            return
        shutil.rmtree(path)
    except Exception:
        # Keep anything whose ownership or content cannot be re-verified.
        return


def pull_snapshot(client, destination_root: str | os.PathLike,
                  now: datetime | None = None) -> dict:
    """Pull, validate, restore-rehearse, and publish one new snapshot generation.

    The 24-hour interval is measured from the last successfully published pull.
    Failed attempts do not update that state and are therefore retryable.
    """
    root = None
    stage = None
    rehearsal = None
    published_generation = None
    published_snapshot_id = None
    state_written = False
    try:
        root = _absolute(destination_root, "DESTINATION_INVALID")
        _reject_reparse_components(root)
        root.mkdir(parents=True, exist_ok=True)
        _reject_reparse_components(root)
        if not root.is_dir():
            _fail("DESTINATION_INVALID")
        current = _utc(now)
        state_path = root / "pull-state.json"
        previous = _read_pull_state(state_path)
        reset_reason = (previous["reset_reason"] if previous is not None
                        and "reset_reason" in previous else None)
        prior_resets = (previous["state_reset_count"] if previous is not None
                        and "reset_reason" not in previous else 0)
        if previous is not None and "reset_reason" not in previous and \
                current - previous["last_success"] < timedelta(hours=24):
            skipped = _gap_judgement(root, current)
            skipped["skipped"] = True
            skipped["complete"] = prior_resets == 0 and skipped["missed_days_total"] == 0
            return {"ok": True, **skipped, "code": "NOT_DUE",
                    "state_reset_count": prior_resets,
                    "state_reset_reason": None,
                    "last_success_at_utc": _stamp(previous["last_success"])}

        manifest = _pull_manifest(client)
        stage = _new_stage(root, "incoming")
        _download_snapshot(client, manifest, stage)
        verified = verify_snapshot(stage)
        rehearsal = root / f".restore-check-{uuid.uuid4().hex}"
        restore_snapshot(stage, rehearsal)
        rehearsal_result = verify_snapshot(rehearsal)
        if rehearsal_result["snapshot_id"] != verified["snapshot_id"]:
            _fail("RESTORE_HASH_MISMATCH")

        generation = root / (
            f"snapshot-{current.strftime('%Y%m%dT%H%M%SZ')}-"
            f"{verified['snapshot_id'][:16]}-{uuid.uuid4().hex[:8]}"
        )
        # Judge gaps from the generation names already on disk, before this
        # generation is published; the previous state file alone cannot show
        # a multi-day outage.
        gap = _gap_judgement(root, current)
        _publish(stage, generation)
        stage = None
        published_generation = generation
        published_snapshot_id = verified["snapshot_id"]
        resets = prior_resets + (1 if reset_reason is not None else 0)
        _write_pull_state(state_path, current, verified["snapshot_id"],
                          gap=gap, state_resets=resets,
                          state_reset_reason=reset_reason)
        state_written = True
        return {**verified, **gap, "skipped": False, "generation": generation.name,
                "state_reset_count": resets,
                "state_reset_reason": reset_reason,
                "complete": gap["missed_days_total"] == 0 and resets == 0,
                "last_success_at_utc": _stamp(current)}
    except BackupError as exc:
        return {"ok": False, "code": exc.code}
    except Exception:
        return {"ok": False, "code": "PULL_FAILED"}
    finally:
        if root is not None:
            if rehearsal is not None:
                _cleanup_owned_restore(root, rehearsal)
            if stage is not None:
                _cleanup_owned_pull_stage(root, stage)
            if (published_generation is not None and published_snapshot_id is not None
                    and not state_written):
                _cleanup_owned_generation(
                    root,
                    published_generation,
                    expected_name=published_generation.name,
                    snapshot_id=published_snapshot_id,
                )
