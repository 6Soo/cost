# -*- coding: utf-8 -*-
"""owner_profile_requests + receipt_apply_requests → ledger_operation_requests 오프라인 병합.

기본은 무쓰기 예행이다. 닫힌 사본을 `mode=ro&immutable=1`로 읽기만 하며
체크포인트·SAVEPOINT·DDL을 하지 않는다. `-wal`/`-shm`/`-journal`이 있으면
바이트 보존을 위해 거부한다(닫힌 사본만 대상). `--apply`는 `mode=rw`(생성 없음)로
열고 BEGIN IMMEDIATE 뒤 스냅숏·검증·배타 백업(`open xb`, 기본
`<db>.pre-merge-backup`)·INSERT/DROP/뷰 검증을 같은 트랜잭션에서 하고 커밋한다.
실패는 롤백과 백업 보존으로 끝내며 파일 바이트를 덮어쓰지 않는다.

예행과 적용은 소스 저널의 형태(테이블/뷰/혼합)·NULL·중복 키를 공통 검증하고,
두 저널이 모두 비었으면 NO_DATA로 거부한다. 운영 경로·별칭(심링크/정션/하드링크)은
거부한다. 출력은 집계와 고정 코드뿐이며 응답 원문·traceback은 내보내지 않는다.

    python -I tools/merge_ledger_operation_requests.py --db <사본 경로>           # 예행
    python -I tools/merge_ledger_operation_requests.py --db <사본 경로> --apply   # 적용
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
    request_journal_shape,
)

EXIT_OK = 0
EXIT_REFUSED = 2

CODE_INVALID_ARGUMENT = "INVALID_ARGUMENT"
CODE_DB_NOT_FOUND = "DB_NOT_FOUND"
CODE_PATH_REFUSED = "PATH_REFUSED"
CODE_SIDECAR_PRESENT = "SIDECAR_PRESENT"
CODE_DB_BUSY = "DB_BUSY"
CODE_BACKUP_EXISTS = "BACKUP_EXISTS"
CODE_ALREADY_UNIFIED = "ALREADY_UNIFIED"
CODE_LEGACY_SHAPE = "LEGACY_SHAPE"
CODE_NO_DATA = "NO_DATA"
CODE_SOURCE_INVALID = "SOURCE_INVALID"
CODE_VERIFY_FAILED = "VERIFY_FAILED"
CODE_IO_ERROR = "IO_ERROR"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"

_SIDECARS = ("-wal", "-shm", "-journal")


class _CliError(Exception):
    """A refusal reduced to a stable, printable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _norm(path: Path) -> str:
    return os.path.normcase(str(path))


def _check_path(raw: str) -> Path:
    """Refuse production paths and aliases before anything is opened."""
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


def _check_source_shape(conn) -> None:
    """Common shape validation for preview and apply: fail closed on mixed."""
    try:
        shape = request_journal_shape(conn)
    except RuntimeError:
        raise _CliError(CODE_LEGACY_SHAPE) from None
    if shape == "unified":
        raise _CliError(CODE_ALREADY_UNIFIED)
    kinds = dict(conn.execute(
        "SELECT name, type FROM sqlite_master WHERE name IN"
        " ('owner_profile_requests','receipt_apply_requests')"))
    if (kinds.get("owner_profile_requests") != "table"
            or kinds.get("receipt_apply_requests") != "table"):
        raise _CliError(CODE_LEGACY_SHAPE)


def _snapshot_journal(conn) -> dict:
    """Read both source journals, refusing NULL fields and duplicate keys."""
    rows = {}
    for domain, sql in (
            (OWNER_PROFILE_DOMAIN,
             "SELECT client_request_id, input_digest, result_json, created_at"
             " FROM owner_profile_requests"),
            (RECEIPT_APPLY_DOMAIN,
             "SELECT request_id, request_hash, result_json, created_at"
             " FROM receipt_apply_requests")):
        for request_id, digest, result_json, created_at in conn.execute(sql):
            if (request_id is None or digest is None
                    or result_json is None or created_at is None):
                raise _CliError(CODE_SOURCE_INVALID)
            if (domain, request_id) in rows:
                raise _CliError(CODE_SOURCE_INVALID)
            rows[(domain, request_id)] = (digest, result_json, created_at)
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


def _create_backup(db: Path, backup: Path) -> None:
    """Exclusive creation only: an existing backup is never overwritten."""
    try:
        with open(backup, "xb") as out:
            with open(db, "rb") as src:
                shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
    except FileExistsError:
        raise _CliError(CODE_BACKUP_EXISTS) from None
    except OSError:
        raise _CliError(CODE_IO_ERROR) from None


def _counts(snapshot: dict, status: str) -> dict:
    return {
        "status": status,
        "owner_profile_requests": sum(
            1 for domain, _ in snapshot if domain == OWNER_PROFILE_DOMAIN),
        "receipt_apply_requests": sum(
            1 for domain, _ in snapshot if domain == RECEIPT_APPLY_DOMAIN),
    }


def _preview(db: Path) -> dict:
    """Write-free read of a closed copy: no checkpoint, no DDL, no journal."""
    conn = sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1",
                           uri=True, isolation_level=None)
    try:
        _check_source_shape(conn)
        snapshot = _snapshot_journal(conn)
        if not snapshot:
            raise _CliError(CODE_NO_DATA)
        return _counts(snapshot, "PREVIEW")
    finally:
        conn.close()


def _apply(db: Path, backup: Path) -> dict:
    conn = sqlite3.connect(db.as_uri() + "?mode=rw",
                           uri=True, isolation_level=None, timeout=5.0)
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise _CliError(CODE_DB_BUSY) from None
        try:
            _check_source_shape(conn)
            snapshot = _snapshot_journal(conn)
            if not snapshot:
                raise _CliError(CODE_NO_DATA)
            before_counts = _other_table_counts(conn)
            _create_backup(db, backup)
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
            conn.execute("COMMIT")
            return _counts(snapshot, "APPLIED")
        except BaseException:
            # Rollback undoes the conversion; the backup is preserved as
            # evidence. Never copy old bytes over a live database file.
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _run(argv) -> dict:
    parser = argparse.ArgumentParser(description="offline request journal merge")
    parser.add_argument("--db", required=True, help="대상 오프라인 사본 SQLite 파일")
    parser.add_argument("--apply", action="store_true", help="실제로 쓴다(기본은 무쓰기 예행)")
    args = parser.parse_args(argv)

    db = _check_path(args.db)
    for suffix in _SIDECARS:
        if os.path.lexists(str(db) + suffix):
            raise _CliError(CODE_SIDECAR_PRESENT)
    if not args.apply:
        return _preview(db)
    return _apply(db, Path(str(db) + ".pre-merge-backup"))


def main(argv=None) -> int:
    """Entry point. Returns 0 on success and 2 on any refusal."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        result = _run(argv)
    except _CliError as exc:
        print(json.dumps({"status": "ERROR", "reason": exc.code}, ensure_ascii=False))
        return EXIT_REFUSED
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": CODE_INTERNAL_ERROR},
                         ensure_ascii=False))
        return EXIT_REFUSED
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
