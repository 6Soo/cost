"""Import a complete Reservation access snapshot into an explicit COST DB.

Both paths are mandatory so this command cannot silently select a production
database or another default state file. The target database file must already
exist: `sqlite3.connect` would otherwise create an empty file with only the
access tables and no ledger in it, and report that as a successful import
(same rule as `cmd_ops_reservation_sync`'s RESERVATION_TARGET_MISSING).

Safety order on the apply path: validate input -> back up the target with
the SQLite backup API BEFORE opening it writable (WAL included) -> open with
mode=rw (a missing target is refused atomically, never created) -> apply
twice (the second pass proves the whole-directory revision guard is
idempotent) -> report counts only, never person ids or nicknames.
`--dry-run` copies with the same backup API to a throwaway file and leaves
the original (including -wal/-shm sidecars) byte-identical.

Exit codes are stable for operators and scripts:

* 0: success (a stale snapshot that changed nothing is also 0, with
  ``stale: true``; a dry run that ran is 0 with ``dry_run: true``)
* 2: CLI usage error (argparse)
* 3: input snapshot unreadable or refused by the strict parser
* 4: target DB missing or not a usable database
* 5: snapshot refused by a sync guard (conflict, empty/large-drop override
  missing, unknown trip, invalid validity)
* 6: backup failed, nothing was applied
* 7: database busy/locked (retry the same snapshot later)
* 1: unexpected internal failure

Every failure prints ONE structured JSON object to stdout
(``{"ok": false, "code": ..., "message": ...}``) and never a traceback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.reservation_access_snapshot import (
    parse_reservation_access_snapshot,
)
from webapp.access_control import (
    SNAPSHOT_CONFLICT,
    SNAPSHOT_EMPTY_REQUIRES_OVERRIDE,
    SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE,
    TEMPORARILY_UNAVAILABLE,
    UNKNOWN_TRIP,
    AccessError,
    AccessStore,
)

EXIT_USAGE = 2
EXIT_SNAPSHOT_INVALID = 3
EXIT_DB_UNUSABLE = 4
EXIT_SYNC_REFUSED = 5
EXIT_BACKUP_FAILED = 6
EXIT_TRANSIENT = 7
EXIT_INTERNAL = 1

MAX_SNAPSHOT_BYTES = 5_000_000
CONNECT_TIMEOUT_S = 10.0
REFUSAL_CODES = {
    SNAPSHOT_CONFLICT,
    SNAPSHOT_EMPTY_REQUIRES_OVERRIDE,
    SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE,
    UNKNOWN_TRIP,
    "INVALID_VALUE",
}


def _fail(code: str, message: str, exit_code: int, *, detail: str = "") -> int:
    body: dict = {"ok": False, "code": code, "message": message}
    if detail:
        body["detail"] = detail
    print(json.dumps(body, ensure_ascii=False, sort_keys=True))
    return exit_code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_snapshot(path: Path) -> tuple[dict | None, str, str]:
    """Return (snapshot, error_code, error_detail). Never raises."""
    try:
        if not path.is_file():
            return None, "SNAPSHOT_INPUT_MISSING", str(path)
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None, "SNAPSHOT_TOO_LARGE", f"{path.stat().st_size} bytes"
        raw = path.read_bytes()
    except OSError as exc:
        return None, "SNAPSHOT_INPUT_UNREADABLE", str(exc)
    try:
        return parse_reservation_access_snapshot(raw), "", ""
    except ValueError as exc:
        # The parser's message is a machine code like
        # reservation_access_revision_time_mismatch: safe to surface.
        return None, "SNAPSHOT_INVALID", str(exc)


def _uri_rw(db_path: Path) -> str:
    """A mode=rw URI that refuses a missing file instead of creating it."""
    return f"file:{db_path.resolve().as_posix()}?mode=rw"


def _uri_ro(db_path: Path) -> str:
    """A mode=ro URI: the backup source is never opened writable."""
    return f"file:{db_path.resolve().as_posix()}?mode=ro"


def _is_transient_text(text: str) -> bool:
    lowered = text.lower()
    return "locked" in lowered or "busy" in lowered


def _sqlite_backup_copy(src_path: Path, dest_path: Path) -> str:
    """Copy one SQLite database with the backup API. Returns error or ''.

    The backup API reads a transactionally consistent snapshot, so WAL
    content that `shutil.copy2` of the main file alone would miss is
    included. The source is opened mode=ro, so this step never mutates it.
    """
    src_conn = None
    dest_conn = None
    try:
        src_conn = sqlite3.connect(
            _uri_ro(src_path), uri=True, timeout=CONNECT_TIMEOUT_S)
        dest_conn = sqlite3.connect(str(dest_path), timeout=CONNECT_TIMEOUT_S)
        src_conn.backup(dest_conn)
        return ""
    except sqlite3.Error as exc:
        return str(exc)
    finally:
        for handle in (dest_conn, src_conn):
            try:
                if handle is not None:
                    handle.close()
            except sqlite3.Error:
                pass


def _verify_backup(dest: Path) -> str:
    """Check a backup is a usable SQLite database. Returns error or ''."""
    try:
        if not dest.is_file() or dest.stat().st_size <= 0:
            return "backup is missing or empty"
        with open(dest, "rb") as handle:
            header = handle.read(16)
        if header != b"SQLite format 3\x00":
            return "backup header is not SQLite"
        conn = sqlite3.connect(_uri_ro(dest), uri=True, timeout=CONNECT_TIMEOUT_S)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row is None or str(row[0]).lower() != "ok":
                return f"backup integrity_check failed: {row}"
            count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
            if int(count) < 0:
                return "backup catalog unreadable"
            return ""
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    except (OSError, sqlite3.Error) as exc:
        return str(exc)


def _open_store(db_path: Path) -> tuple[AccessStore | None, sqlite3.Connection | None, str]:
    """Open the target writable without ever creating it. Never raises.

    mode=rw makes a missing target an atomic open failure: no empty file is
    left behind. Callers map that failure to RESERVATION_TARGET_MISSING.
    """
    try:
        conn = sqlite3.connect(_uri_rw(db_path), uri=True,
                               timeout=CONNECT_TIMEOUT_S)
    except sqlite3.Error as exc:
        return None, None, str(exc)
    try:
        conn.execute("SELECT 1")
        return AccessStore(conn), conn, ""
    except sqlite3.Error as exc:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        return None, None, str(exc)


def _backup_database(db_path: Path, backup_dir: Path, revision: int) -> tuple[str, str, bool]:
    """Back up the target BEFORE any writable open. Returns (path, error, transient).

    Unique name (UTC microseconds + random suffix) so two backups in the
    same second never overwrite each other. Verified with header +
    integrity_check, not just size.
    """
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return "", str(exc), False
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    dest = backup_dir / (f"{db_path.stem}.reservation-backup-"
                         f"{stamp}-{revision}-{suffix}.sqlite")
    if dest.exists():
        return "", f"backup destination already exists: {dest}", False
    copy_err = _sqlite_backup_copy(db_path, dest)
    if copy_err:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return "", copy_err, _is_transient_text(copy_err)
    check_err = _verify_backup(dest)
    if check_err:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return "", check_err, False
    return str(dest), "", False


def _sync_guards(args) -> dict:
    return {"allow_empty": bool(args.allow_empty),
            "allow_large_drop": bool(args.allow_large_drop)}


def _apply(conn_path_note: str, store: AccessStore, snapshot: dict,
           guards: dict) -> dict:
    first = store.sync_reservation_access_snapshot(snapshot=snapshot, **guards)
    second = store.sync_reservation_access_snapshot(snapshot=snapshot, **guards)
    return {
        "ok": True,
        "database": conn_path_note,
        "digest": snapshot["digest"],
        "snapshot_revision": snapshot["snapshot_revision"],
        "persons_seen": first["persons_seen"],
        "persons_deactivated": first["persons_deactivated"],
        "connections_revoked": first["connections_revoked"],
        "sessions_bumped": first["sessions_bumped"],
        "connected_persons_synced": first["connected_persons_synced"],
        "assignments_applied": first["assignments_applied"],
        "assignments_ignored_older": first["assignments_ignored_older"],
        "stale": bool(first["ignored_stale_or_equal"]),
        "idempotent": bool(second["ignored_stale_or_equal"]),
    }


def _sidecar_hash(path: Path) -> str:
    """Hash a sidecar, treating missing/empty as unchanged.

    Opening a WAL-mode database mode=ro creates an empty -wal and a -shm
    file. Those are not mutations: -shm is ephemeral and ignored, and a
    0-byte -wal/-journal counts as "".
    """
    if not path.is_file():
        return ""
    try:
        if path.stat().st_size == 0:
            return ""
    except OSError:
        return ""
    return _sha256_file(path)


def _fingerprint_db(db_path: Path) -> dict:
    """Hash the main file plus durable WAL/journal sidecars (-shm ignored)."""
    base = str(db_path)
    return {
        db_path.name: _sha256_file(db_path),
        "wal": _sidecar_hash(Path(base + "-wal")),
        "journal": _sidecar_hash(Path(base + "-journal")),
    }


def _run_dry_run(db_path: Path, snapshot: dict, guards: dict) -> int:
    before = _fingerprint_db(db_path)
    before_main = _sha256_file(db_path)
    staging = Path(tempfile.mkdtemp(prefix="reservation-import-dryrun-"))
    try:
        copy = staging / db_path.name
        copy_err = _sqlite_backup_copy(db_path, copy)
        if copy_err:
            if _is_transient_text(copy_err):
                return _fail(TEMPORARILY_UNAVAILABLE,
                             "DB가 바빠요. 같은 스냅샷으로 잠시 뒤 다시 시도해 주세요",
                             EXIT_TRANSIENT)
            return _fail("DRYRUN_COPY_FAILED",
                         "연습용 복사본을 만들지 못했어요. 원본은 그대로예요",
                         EXIT_INTERNAL, detail=copy_err[:200])
        check_err = _verify_backup(copy)
        if check_err:
            return _fail("DRYRUN_COPY_FAILED",
                         "연습용 복사본이 깨졌어요. 원본은 그대로예요",
                         EXIT_INTERNAL, detail=check_err[:200])
        conn = sqlite3.connect(str(copy), timeout=CONNECT_TIMEOUT_S)
        try:
            store = AccessStore(conn)
            report = _apply(str(db_path), store, snapshot, guards)
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        after = _fingerprint_db(db_path)
        after_main = _sha256_file(db_path)
        if after != before:
            return _fail("DRYRUN_MUTATED_SOURCE",
                         "연습이 원본 DB를 바꿨어요. 이 결과는 신뢰하지 마세요",
                         EXIT_INTERNAL)
        report.update({"dry_run": True, "applied_to_real_database": False,
                       "source_unchanged": True,
                       "source_sha256_before": before_main,
                       "source_sha256_after": after_main})
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _map_access_error(exc: AccessError) -> tuple[str, str, int]:
    if exc.code == TEMPORARILY_UNAVAILABLE:
        return (exc.code, "DB가 바빠요. 같은 스냅샷으로 잠시 뒤 다시 시도해 주세요",
                EXIT_TRANSIENT)
    if exc.code in REFUSAL_CODES:
        return exc.code, str(exc.message or exc.code), EXIT_SYNC_REFUSED
    return exc.code or "SYNC_FAILED", str(exc.message or exc.code), EXIT_SYNC_REFUSED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a Reservation access snapshot into a COST DB.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="Rehearse on a throwaway copy; change nothing.")
    parser.add_argument("--allow-empty", action="store_true",
                        help="Explicitly confirm applying an empty person list.")
    parser.add_argument("--allow-large-drop", action="store_true",
                        help="Explicitly confirm a directory shrunk below half.")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="Where to store the pre-apply backup"
                             " (default: the DB's own directory).")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip the pre-apply backup (not recommended).")
    args = parser.parse_args(argv)

    snapshot, err_code, err_detail = _read_snapshot(args.input)
    if snapshot is None:
        if err_code in ("SNAPSHOT_INPUT_MISSING", "SNAPSHOT_INPUT_UNREADABLE",
                        "SNAPSHOT_TOO_LARGE"):
            message = {"SNAPSHOT_INPUT_MISSING": "입력 스냅샷이 없어요",
                       "SNAPSHOT_INPUT_UNREADABLE": "입력 스냅샷을 읽지 못했어요",
                       "SNAPSHOT_TOO_LARGE": "입력 스냅샷이 너무 커요"}[err_code]
        else:
            message = "예약 접근 스냅샷이 거부됐어요"
        return _fail(err_code, message, EXIT_SNAPSHOT_INVALID, detail=err_detail)

    db_path = args.db
    guards = _sync_guards(args)

    if args.dry_run:
        if not db_path.is_file():
            return _fail("RESERVATION_TARGET_MISSING",
                         "연습할 DB가 없어요. 적용 대상은 이미 존재하는 장부 DB여야 해요",
                         EXIT_DB_UNUSABLE, detail=db_path.name)
        try:
            return _run_dry_run(db_path, snapshot, guards)
        except AccessError as exc:
            code, message, exit_code = _map_access_error(exc)
            return _fail(code, message, exit_code)
        except sqlite3.Error as exc:
            text = str(exc).lower()
            if "unable to open" in text or "no such file" in text:
                return _fail("RESERVATION_TARGET_MISSING",
                             "연습할 DB가 없어요. 적용 대상은 이미 존재하는 장부 DB여야 해요",
                             EXIT_DB_UNUSABLE, detail=db_path.name)
            if _is_transient_text(text):
                return _fail(TEMPORARILY_UNAVAILABLE,
                             "DB가 바빠요. 같은 스냅샷으로 잠시 뒤 다시 시도해 주세요",
                             EXIT_TRANSIENT)
            return _fail("DB_UNAVAILABLE", "DB를 사용하지 못했어요",
                         EXIT_DB_UNUSABLE, detail=text[:200])
        except Exception as exc:  # never a traceback on the surface
            return _fail("IMPORT_FAILED", "가져오기에 실패했어요",
                         EXIT_INTERNAL, detail=type(exc).__name__)

    # Backup BEFORE any writable open: the source is read mode=ro through
    # the backup API, so the original (including WAL) is preserved and a
    # missing target is refused here without creating anything.
    backup_path = ""
    if not args.no_backup:
        backup_path, backup_err, backup_transient = _backup_database(
            db_path, args.backup_dir or db_path.parent,
            int(snapshot["snapshot_revision"]))
        if not backup_path:
            if "unable to open" in backup_err.lower() or (
                    "no such file" in backup_err.lower()
                    and not db_path.is_file()):
                return _fail("RESERVATION_TARGET_MISSING",
                             "적용할 DB가 없어요. 빈 파일이 새로 만들어지면 장부가 없는"
                             " 빈 DB가 됩니다. 적용 대상은 이미 존재하는 장부 DB여야 해요",
                             EXIT_DB_UNUSABLE, detail=db_path.name)
            if backup_transient:
                return _fail(TEMPORARILY_UNAVAILABLE,
                             "DB가 바빠요. 같은 스냅샷으로 잠시 뒤 다시 시도해 주세요",
                             EXIT_TRANSIENT)
            return _fail("BACKUP_FAILED",
                         "백업을 만들지 못해서 적용하지 않았어요",
                         EXIT_BACKUP_FAILED, detail=backup_err[:200])

    store, conn, db_err = _open_store(db_path)
    if store is None:
        lowered = (db_err or "").lower()
        if "unable to open" in lowered or not db_path.is_file():
            return _fail("RESERVATION_TARGET_MISSING",
                         "적용할 DB가 없어요. 빈 파일이 새로 만들어지면 장부가 없는"
                         " 빈 DB가 됩니다. 적용 대상은 이미 존재하는 장부 DB여야 해요",
                         EXIT_DB_UNUSABLE, detail=db_path.name)
        return _fail("DB_UNUSABLE", "DB를 열지 못했어요",
                     EXIT_DB_UNUSABLE, detail=db_err[:200])

    try:
        report = _apply(str(db_path), store, snapshot, guards)
    except AccessError as exc:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        code, message, exit_code = _map_access_error(exc)
        return _fail(code, message, exit_code)
    except sqlite3.OperationalError as exc:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        text = str(exc).lower()
        if "locked" in text or "busy" in text:
            return _fail(TEMPORARILY_UNAVAILABLE,
                         "DB가 바빠요. 같은 스냅샷으로 잠시 뒤 다시 시도해 주세요",
                         EXIT_TRANSIENT)
        return _fail("DB_UNAVAILABLE", "DB를 사용하지 못했어요",
                     EXIT_DB_UNUSABLE, detail=text[:200])
    except Exception as exc:  # never a traceback on the surface
        try:
            conn.close()
        except sqlite3.Error:
            pass
        return _fail("IMPORT_FAILED", "가져오기에 실패했어요",
                     EXIT_INTERNAL, detail=type(exc).__name__)

    try:
        conn.close()
    except sqlite3.Error:
        pass
    if backup_path:
        report["backup"] = backup_path
    else:
        report["backup"] = None
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
