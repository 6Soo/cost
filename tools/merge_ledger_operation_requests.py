# -*- coding: utf-8 -*-
"""owner_profile_requests + receipt_apply_requests → ledger_operation_requests 오프라인 병합.

기본은 무쓰기 예행이다. 닫힌 사본을 `mode=ro&immutable=1`로 읽기만 하며
체크포인트·SAVEPOINT·DDL을 하지 않는다. `-wal`/`-shm`/`-journal`이 있으면
바이트 보존을 위해 거부한다(닫힌 사본만 대상). `--apply`는 `mode=rw`(생성 없음)로
열고 BEGIN IMMEDIATE 뒤 스냅숏·검증·배타 백업(`open xb`, 기본
`<db>.pre-merge-backup`)·INSERT/DROP/뷰 검증을 같은 트랜잭션에서 하고 커밋한다.
실패는 롤백과 백업 보존으로 끝내며 파일 바이트를 덮어쓰지 않는다.

`--include-source-facts`를 명시한 때만 세 번째 저널 `source_fact_applies`도
합친다: 레거시 → 세 도메인, 또는 기존 통합(두 도메인) → 세 도메인. 이때 백업은
`<db>.pre-source-facts-merge-backup`을 배타 생성하며 첫 백업(`.pre-merge-backup`)은
보존한다. 기본(플래그 없음)은 기존 두 도메인 계약 그대로이고, 이미 통합된 형태는
반복 실행 시 무쓰기로 거부한다. `reserve_link_saves`는 AccessStore 계약(SPEC 16.4)
때문에 이 병합에서 제외한다.

예행과 적용은 소스 저널의 형태(테이블/뷰/혼합)·NULL·중복 키를 공통 검증하고,
저널이 모두 비었으면 NO_DATA로 거부한다. 운영 경로·별칭(심링크/정션/하드링크)은
거부한다. 출력은 집계와 고정 코드뿐이며 응답 원문·traceback은 내보내지 않는다.

    python -I tools/merge_ledger_operation_requests.py --db <사본 경로>           # 예행
    python -I tools/merge_ledger_operation_requests.py --db <사본 경로> --apply   # 적용
    python -I tools/merge_ledger_operation_requests.py --db <사본 경로> --include-source-facts --apply
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
    SOURCE_FACT_DOMAIN,
    SOURCE_FACTS_COMPAT_VIEW_SQL,
    UNIFIED_TABLE_SQL,
    UNIFIED_SOURCE_FACTS_TABLE_SQL,
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

LIVE_HOST = Path("D:/WebLedgerHost")
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
        live_root = LIVE_HOST.resolve()
    except OSError:
        raise _CliError(CODE_PATH_REFUSED) from None
    if resolved.is_relative_to(live_root) or _norm(resolved) != _norm(absolute):
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


def _check_source_shape(conn, include_source_facts: bool) -> str:
    """Common shape validation for preview and apply: fail closed on mixed.

    Returns the convertible shape ('legacy', or 'unified' for a two-to-three
    upgrade). An already-converted database is refused write-free.
    """
    try:
        shape = request_journal_shape(conn)
    except RuntimeError:
        raise _CliError(CODE_LEGACY_SHAPE) from None
    if include_source_facts:
        if shape == "unified_source_facts":
            raise _CliError(CODE_ALREADY_UNIFIED)
        if shape == "unified":
            # request_journal_shape guarantees source_fact_applies is still a
            # legacy table here; the two compatibility views already exist.
            return "unified"
        kinds = dict(conn.execute(
            "SELECT name, type FROM sqlite_master WHERE name IN"
            " ('owner_profile_requests','receipt_apply_requests','source_fact_applies')"))
        if any(kinds.get(name) != "table" for name in
               ("owner_profile_requests", "receipt_apply_requests", "source_fact_applies")):
            raise _CliError(CODE_LEGACY_SHAPE)
        return "legacy"
    if shape in ("unified", "unified_source_facts"):
        raise _CliError(CODE_ALREADY_UNIFIED)
    kinds = dict(conn.execute(
        "SELECT name, type FROM sqlite_master WHERE name IN"
        " ('owner_profile_requests','receipt_apply_requests')"))
    if (kinds.get("owner_profile_requests") != "table"
            or kinds.get("receipt_apply_requests") != "table"):
        raise _CliError(CODE_LEGACY_SHAPE)
    return "legacy"


def _snapshot_journal(conn, include_source_facts: bool) -> dict:
    """Read the source journals, refusing NULL fields and duplicate keys.

    Values are (digest, result_json, created_at, binding, choices_revision);
    the first two domains carry no provenance (None, None).
    """
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
            rows[(domain, request_id)] = (digest, result_json, created_at, None, None)
    if include_source_facts:
        for (request_id, digest, binding, choices_revision,
             result_json, created_at) in conn.execute(
                "SELECT request_id, input_digest, binding, choices_revision,"
                " result_json, created_at FROM source_fact_applies"):
            if any(value is None for value in
                   (request_id, digest, binding, choices_revision,
                    result_json, created_at)):
                raise _CliError(CODE_SOURCE_INVALID)
            if (SOURCE_FACT_DOMAIN, request_id) in rows:
                raise _CliError(CODE_SOURCE_INVALID)
            rows[(SOURCE_FACT_DOMAIN, request_id)] = (
                digest, result_json, created_at, binding, choices_revision)
    return rows


def _other_table_counts(conn, include_source_facts: bool) -> dict:
    excluded = ("'owner_profile_requests','receipt_apply_requests',"
                "'ledger_operation_requests'")
    if include_source_facts:
        excluded += ",'source_fact_applies'"
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        f" AND name NOT IN ({excluded}) ORDER BY name")]
    return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in names}


def _verify_unified(conn, snapshot: dict, include_source_facts: bool) -> None:
    if include_source_facts:
        stored = {(domain, request_id): (digest, result_json, created_at,
                                         binding, choices_revision)
                  for (domain, request_id, digest, result_json, created_at,
                       binding, choices_revision) in conn.execute(
                      "SELECT domain, request_id, input_digest, result_json,"
                      " created_at, binding, choices_revision"
                      " FROM ledger_operation_requests")}
    else:
        stored = {(domain, request_id): (digest, result_json, created_at, None, None)
                  for domain, request_id, digest, result_json, created_at in conn.execute(
                      "SELECT domain, request_id, input_digest, result_json, created_at"
                      " FROM ledger_operation_requests")}
    if stored != snapshot:
        raise _CliError(CODE_VERIFY_FAILED)


def _verify_views(conn, snapshot: dict, include_source_facts: bool) -> None:
    via_views = {}
    for request_id, digest, result_json, created_at in conn.execute(
            "SELECT client_request_id, input_digest, result_json, created_at"
            " FROM owner_profile_requests"):
        via_views[(OWNER_PROFILE_DOMAIN, request_id)] = (
            digest, result_json, created_at, None, None)
    for request_id, digest, result_json, created_at in conn.execute(
            "SELECT request_id, request_hash, result_json, created_at"
            " FROM receipt_apply_requests"):
        via_views[(RECEIPT_APPLY_DOMAIN, request_id)] = (
            digest, result_json, created_at, None, None)
    if include_source_facts:
        for (request_id, digest, binding, choices_revision,
             result_json, created_at) in conn.execute(
                "SELECT request_id, input_digest, binding, choices_revision,"
                " result_json, created_at FROM source_fact_applies"):
            via_views[(SOURCE_FACT_DOMAIN, request_id)] = (
                digest, result_json, created_at, binding, choices_revision)
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


def _counts(snapshot: dict, status: str, include_source_facts: bool) -> dict:
    counts = {
        "status": status,
        "owner_profile_requests": sum(
            1 for domain, _ in snapshot if domain == OWNER_PROFILE_DOMAIN),
        "receipt_apply_requests": sum(
            1 for domain, _ in snapshot if domain == RECEIPT_APPLY_DOMAIN),
    }
    if include_source_facts:
        counts["source_fact_applies"] = sum(
            1 for domain, _ in snapshot if domain == SOURCE_FACT_DOMAIN)
    return counts


def _preview(db: Path, include_source_facts: bool) -> dict:
    """Write-free read of a closed copy: no checkpoint, no DDL, no journal."""
    conn = sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1",
                           uri=True, isolation_level=None)
    try:
        _check_source_shape(conn, include_source_facts)
        snapshot = _snapshot_journal(conn, include_source_facts)
        if not snapshot:
            raise _CliError(CODE_NO_DATA)
        return _counts(snapshot, "PREVIEW", include_source_facts)
    finally:
        conn.close()


def _apply(db: Path, backup: Path, include_source_facts: bool) -> dict:
    conn = sqlite3.connect(db.as_uri() + "?mode=rw",
                           uri=True, isolation_level=None, timeout=5.0)
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise _CliError(CODE_DB_BUSY) from None
        try:
            shape = _check_source_shape(conn, include_source_facts)
            snapshot = _snapshot_journal(conn, include_source_facts)
            if not snapshot:
                raise _CliError(CODE_NO_DATA)
            wal = Path(str(db) + "-wal")
            if wal.exists() and wal.stat().st_size:
                raise _CliError(CODE_SIDECAR_PRESENT)
            before_counts = _other_table_counts(conn, include_source_facts)
            _create_backup(db, backup)
            if include_source_facts:
                if shape == "unified":
                    # Rebuild the two-domain table as the three-domain variant;
                    # the owner/receipt views resolve again by name afterwards.
                    conn.execute("DROP TABLE ledger_operation_requests")
                conn.execute(UNIFIED_SOURCE_FACTS_TABLE_SQL)
                for (domain, request_id), (digest, result_json, created_at,
                                           binding, choices_revision) in sorted(snapshot.items()):
                    insert_operation_request(
                        conn, unified=True, domain=domain, request_id=request_id,
                        input_digest=digest, result_json=result_json,
                        created_at=created_at, binding=binding,
                        choices_revision=choices_revision)
                _verify_unified(conn, snapshot, True)
                conn.execute("DROP TABLE source_fact_applies")
                if shape == "legacy":
                    conn.execute("DROP TABLE owner_profile_requests")
                    conn.execute("DROP TABLE receipt_apply_requests")
                for statement in SOURCE_FACTS_COMPAT_VIEW_SQL:
                    conn.execute(statement)
                _verify_views(conn, snapshot, True)
            else:
                conn.execute(UNIFIED_TABLE_SQL)
                for (domain, request_id), (digest, result_json, created_at,
                                           _binding, _choices_revision) in sorted(snapshot.items()):
                    insert_operation_request(
                        conn, unified=True, domain=domain, request_id=request_id,
                        input_digest=digest, result_json=result_json,
                        created_at=created_at)
                _verify_unified(conn, snapshot, False)
                conn.execute("DROP TABLE owner_profile_requests")
                conn.execute("DROP TABLE receipt_apply_requests")
                for statement in COMPAT_VIEW_SQL:
                    conn.execute(statement)
                _verify_views(conn, snapshot, False)
            if _other_table_counts(conn, include_source_facts) != before_counts:
                raise _CliError(CODE_VERIFY_FAILED)
            conn.execute("COMMIT")
            return _counts(snapshot, "APPLIED", include_source_facts)
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
    parser.add_argument("--include-source-facts", action="store_true",
                        help="source_fact_applies도 함께 병합(명시적일 때만, 세 도메인)")
    args = parser.parse_args(argv)

    db = _check_path(args.db)
    for suffix in _SIDECARS:
        if os.path.lexists(str(db) + suffix):
            raise _CliError(CODE_SIDECAR_PRESENT)
    include = args.include_source_facts
    if not args.apply:
        return _preview(db, include)
    backup_name = (".pre-source-facts-merge-backup" if include
                   else ".pre-merge-backup")
    return _apply(db, Path(str(db) + backup_name), include)


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
