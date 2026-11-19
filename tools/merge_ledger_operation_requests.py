# -*- coding: utf-8 -*-
"""owner_profile_requests + receipt_apply_requests → ledger_operation_requests 오프라인 병합.

기본은 dry-run이다. `--apply`를 줘야 쓴다. 운영 DB에 직접 쓰지 않는다:
명시된 오프라인 사본만 변환하고, 키·응답·시각 100% 대조가 통과한 뒤에만
옛 두 이름을 호환 읽기 뷰로 남긴다(물리 2→1). 운영 경로·별칭은 거부한다.

    python -I tools/merge_ledger_operation_requests.py --db <사본 경로>           # 예행
    python -I tools/merge_ledger_operation_requests.py --db <사본 경로> --apply   # 적용

적용 전 보호 백업(`<db>.pre-merge-backup`)을 만들고, 변환 중 실패하면 백업에서
복원한다. 백업은 덮어쓰지 않는다. 두 저널이 모두 비었으면 NO_DATA로 거부한다
(양성 증거 없는 일치는 통과가 아니다). 출력은 집계와 고정 코드뿐이며
응답 원문·traceback은 내보내지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp.ledger_operation_requests import (  # noqa: E402
    COMPAT_VIEW_SQL,
    OWNER_PROFILE_DOMAIN,
    RECEIPT_APPLY_DOMAIN,
    UNIFIED_TABLE_SQL,
    insert_operation_request,
    journal_is_unified,
)

EXIT_OK = 0
EXIT_REFUSED = 2

CODE_INVALID_ARGUMENT = "INVALID_ARGUMENT"
CODE_DB_NOT_FOUND = "DB_NOT_FOUND"
CODE_PATH_REFUSED = "PATH_REFUSED"
CODE_DB_BUSY = "DB_BUSY"
CODE_BACKUP_EXISTS = "BACKUP_EXISTS"
CODE_ALREADY_UNIFIED = "ALREADY_UNIFIED"
CODE_LEGACY_SHAPE = "LEGACY_SHAPE"
CODE_NO_DATA = "NO_DATA"
CODE_VERIFY_FAILED = "VERIFY_FAILED"
CODE_IO_ERROR = "IO_ERROR"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"

_SIDECARS = ("-wal", "-shm")
_SAVEPOINT = "cost_request_journal_merge"


class _CliError(Exception):
    """A refusal reduced to a stable, printable code."""

    def __init__(self, code: str, **extra):
        super().__init__(code)
        self.code = code
        self.extra = extra


def _norm(path: Path) -> str:
    return os.path.normcase(str(path))


def _check_path(raw: str) -> Path:
    """Refuse production paths and aliases before anything is opened for write."""
    if not raw or not raw.strip():
        raise _CliError(CODE_INVALID_ARGUMENT)
    absolute = Path(os.path.abspath(raw))
    try:
        resolved = absolute.resolve()
    except OSError:
        raise _CliError(CODE_PATH_REFUSED) from None
    if _norm(resolved) != _norm(absolute):
        raise _CliError(CODE_PATH_REFUSED)
    for parent in (absolute, *absolute.parents):
        if parent.is_symlink():
            raise _CliError(CODE_PATH_REFUSED)
    try:
        info = os.lstat(absolute)
    except OSError:
        raise _CliError(CODE_DB_NOT_FOUND) from None
    if not stat.S_ISREG(info.st_mode):
        raise _CliError(CODE_DB_NOT_FOUND)
    if info.st_nlink > 1:
        raise _CliError(CODE_PATH_REFUSED)
    data_root = os.environ.get("WEBLEDGER_DATA_ROOT")
    if data_root:
        root = Path(data_root).resolve()
        if _norm(resolved) == _norm(root) or root in resolved.parents:
            raise _CliError(CODE_PATH_REFUSED)
    for name in ("WEBLEDGER_DB", "WEBLEDGER_DATA_DB"):
        value = os.environ.get(name)
        if value and _norm(Path(value).resolve()) == _norm(resolved):
            raise _CliError(CODE_PATH_REFUSED)
    return resolved


def _backup_path(raw: str | None, db: Path) -> Path:
    backup = Path(raw) if raw else Path(str(db) + ".pre-merge-backup")
    if _norm(Path(os.path.abspath(backup))) == _norm(db):
        raise _CliError(CODE_PATH_REFUSED)
    try:
        if _norm(backup.resolve()) == _norm(db):
            raise _CliError(CODE_PATH_REFUSED)
    except OSError:
        raise _CliError(CODE_PATH_REFUSED) from None
    return backup


def _create_backup(db: Path, backup: Path) -> None:
    if backup.exists() or any(Path(str(backup) + s).exists() for s in _SIDECARS):
        raise _CliError(CODE_BACKUP_EXISTS)
    try:
        shutil.copy2(db, backup)
        for suffix in _SIDECARS:
            side = Path(str(db) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(backup) + suffix))
    except OSError:
        raise _CliError(CODE_IO_ERROR) from None


def _restore_backup(db: Path, backup: Path) -> bool:
    try:
        shutil.copy2(backup, db)
        for suffix in _SIDECARS:
            source = Path(str(backup) + suffix)
            target = Path(str(db) + suffix)
            if source.exists():
                shutil.copy2(source, target)
            elif target.exists():
                target.unlink()
        return True
    except OSError:
        return False


def _check_legacy_shape(conn) -> None:
    if journal_is_unified(conn):
        raise _CliError(CODE_ALREADY_UNIFIED)
    for name in ("owner_profile_requests", "receipt_apply_requests"):
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if row is None or row[0] != "table":
            raise _CliError(CODE_LEGACY_SHAPE)


def _snapshot_journal(conn) -> dict:
    rows = {}
    for request_id, digest, result_json, created_at in conn.execute(
            "SELECT client_request_id, input_digest, result_json, created_at"
            " FROM owner_profile_requests"):
        rows[(OWNER_PROFILE_DOMAIN, request_id)] = (digest, result_json, created_at)
    for request_id, digest, result_json, created_at in conn.execute(
            "SELECT request_id, request_hash, result_json, created_at"
            " FROM receipt_apply_requests"):
        rows[(RECEIPT_APPLY_DOMAIN, request_id)] = (digest, result_json, created_at)
    return rows


def _other_table_counts(conn) -> dict:
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT IN ('owner_profile_requests','receipt_apply_requests',"
        "'ledger_operation_requests') ORDER BY name")]
    return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in names}


def _verify_unified(conn, snapshot: dict) -> None:
    stored = {(domain, request_id): (digest, result_json, created_at)
              for domain, request_id, digest, result_json, created_at in conn.execute(
                  "SELECT domain, request_id, input_digest, result_json, created_at"
                  " FROM ledger_operation_requests")}
    if stored != snapshot:
        raise _CliError(CODE_VERIFY_FAILED)


def _verify_views(conn, snapshot: dict) -> None:
    via_views = {}
    for request_id, digest, result_json, created_at in conn.execute(
            "SELECT client_request_id, input_digest, result_json, created_at"
            " FROM owner_profile_requests"):
        via_views[(OWNER_PROFILE_DOMAIN, request_id)] = (digest, result_json, created_at)
    for request_id, digest, result_json, created_at in conn.execute(
            "SELECT request_id, request_hash, result_json, created_at"
            " FROM receipt_apply_requests"):
        via_views[(RECEIPT_APPLY_DOMAIN, request_id)] = (digest, result_json, created_at)
    if via_views != snapshot:
        raise _CliError(CODE_VERIFY_FAILED)


def convert(conn, *, apply: bool) -> dict:
    """Merge the two journals inside one SAVEPOINT; dry-run rolls it all back."""
    _check_legacy_shape(conn)
    snapshot = _snapshot_journal(conn)
    if not snapshot:
        raise _CliError(CODE_NO_DATA)
    before_counts = _other_table_counts(conn)
    conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        conn.execute(UNIFIED_TABLE_SQL)
        for (domain, request_id), (digest, result_json, created_at) in sorted(snapshot.items()):
            insert_operation_request(
                conn, unified=True, domain=domain, request_id=request_id,
                input_digest=digest, result_json=result_json, created_at=created_at)
        _verify_unified(conn, snapshot)
        conn.execute("DROP TABLE owner_profile_requests")
        conn.execute("DROP TABLE receipt_apply_requests")
        for statement in COMPAT_VIEW_SQL:
            conn.execute(statement)
        _verify_views(conn, snapshot)
        if _other_table_counts(conn) != before_counts:
            raise _CliError(CODE_VERIFY_FAILED)
        if apply:
            conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        else:
            conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        return {
            "status": "APPLIED" if apply else "PREVIEW",
            "owner_profile_requests": sum(
                1 for domain, _ in snapshot if domain == OWNER_PROFILE_DOMAIN),
            "receipt_apply_requests": sum(
                1 for domain, _ in snapshot if domain == RECEIPT_APPLY_DOMAIN),
            "verified": True,
        }
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
        raise


def _run(argv) -> dict:
    parser = argparse.ArgumentParser(description="offline request journal merge")
    parser.add_argument("--db", required=True, help="대상 오프라인 사본 SQLite 파일")
    parser.add_argument("--apply", action="store_true", help="실제로 쓴다(기본은 예행)")
    parser.add_argument("--backup", help="보호 백업 경로(기본: <db>.pre-merge-backup)")
    parser.add_argument("--report", help="집계 결과 JSON을 남길 경로")
    args = parser.parse_args(argv)

    db = _check_path(args.db)
    backup = _backup_path(args.backup, db)
    conn = sqlite3.connect(str(db), isolation_level=None, timeout=5.0)
    backup_created = False
    try:
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            wal = Path(str(db) + "-wal")
            if wal.exists() and wal.stat().st_size > 0:
                raise _CliError(CODE_DB_BUSY)
            if args.apply:
                # Refuse before creating a backup when the shape is wrong or
                # there is nothing to convert, so a refusal leaves no artifacts.
                _check_legacy_shape(conn)
                if not _snapshot_journal(conn):
                    raise _CliError(CODE_NO_DATA)
                _create_backup(db, backup)
                backup_created = True
            result = convert(conn, apply=args.apply)
        except BaseException as exc:
            if backup_created:
                conn.close()
                conn = None
                restored = _restore_backup(db, backup)
                code = exc.code if isinstance(exc, _CliError) else CODE_INTERNAL_ERROR
                raise _CliError(code, backup_restored=restored) from None
            raise
    finally:
        if conn is not None:
            conn.close()

    if args.report:
        try:
            Path(args.report).write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            result["report_error"] = CODE_IO_ERROR
    return result


def main(argv=None) -> int:
    """Entry point. Returns 0 on success and 2 on any refusal."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        result = _run(argv)
    except _CliError as exc:
        payload = {"status": "ERROR", "reason": exc.code}
        payload.update(exc.extra)
        print(json.dumps(payload, ensure_ascii=False))
        return EXIT_REFUSED
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": CODE_INTERNAL_ERROR},
                         ensure_ascii=False))
        return EXIT_REFUSED
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
