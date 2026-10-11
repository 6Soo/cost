"""Rehearse COST's additive SQLite schema on an expendable copy only.

This is NOT a deployment or production migration tool. Pass a quiescent,
verified backup/restore copy; do not pass an operational database. No customer
rows, original file paths, or monetary values are printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RehearsalError(RuntimeError):
    pass


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _baseline(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """Fingerprint existing schema and rows without returning their contents."""
    if conn.execute('PRAGMA integrity_check').fetchone() != ('ok',):
        raise RehearsalError('INPUT_INTEGRITY_FAILED')
    objects = {
        (kind, name): (table_name, sql)
        for kind, name, table_name, sql in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    }
    rows = {}
    for (kind, name), _ in objects.items():
        if kind != 'table':
            continue
        hashes = sorted(
            hashlib.sha256(repr(tuple(row)).encode('utf-8')).digest()
            for row in conn.execute('SELECT * FROM ' + _quote(name))
        )
        digest = hashlib.sha256()
        for entry in hashes:
            digest.update(entry)
        rows[name] = (len(hashes), digest.hexdigest())
    return objects, rows


def rehearse(source_copy: Path, expected_sha256: str | None = None) -> dict:
    """Read one offline SQLite copy; modify only an auto-deleted temporary clone."""
    source_copy = Path(source_copy)
    if source_copy.is_symlink() or not source_copy.is_file():
        raise RehearsalError('ISOLATED_SOURCE_REQUIRED')
    # Refuse known live path even when explicitly passed; the tool never needs it.
    normalized = str(source_copy.resolve()).replace('\\', '/').lower()
    if normalized.endswith('d:/webledgerhost/data/board.sqlite'):
        raise RehearsalError('LIVE_DATABASE_REFUSED')
    for suffix in ('-wal', '-shm', '-journal'):
        if Path(str(source_copy) + suffix).exists():
            raise RehearsalError('UNQUIESCENT_SOURCE_REFUSED')
    original_hash = _sha_file(source_copy)
    if expected_sha256 is not None and original_hash != expected_sha256.lower():
        raise RehearsalError('BACKUP_CHECKSUM_MISMATCH')

    with TemporaryDirectory(prefix='cost-schema-rehearsal-') as temp:
        cloned = Path(temp) / 'rehearsal.sqlite'
        shutil.copyfile(source_copy, cloned)
        if _sha_file(cloned) != original_hash:
            raise RehearsalError('CLONE_CHECKSUM_MISMATCH')
        conn = sqlite3.connect(cloned, isolation_level=None)
        try:
            before_objects, before_rows = _baseline(conn)
            from app.db import Store
            Store(conn)  # DDL is intentionally permitted only on the scratch clone.
            after_objects, after_rows = _baseline(conn)
            if any(after_objects.get(key) != value for key, value in before_objects.items()):
                raise RehearsalError('EXISTING_SCHEMA_CHANGED')
            if any(after_rows.get(table) != value for table, value in before_rows.items()):
                raise RehearsalError('EXISTING_ROWS_CHANGED')
            exclusions = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='transaction_company_exclusions'"
            ).fetchone()
            if exclusions is None:
                raise RehearsalError('EXCLUSION_TABLE_MISSING')
            added_tables = sorted(
                name for (kind, name) in after_objects
                if kind == 'table' and (kind, name) not in before_objects
            )
        finally:
            conn.close()
    if _sha_file(source_copy) != original_hash:
        raise RehearsalError('SOURCE_CHANGED_DURING_REHEARSAL')
    return {
        'status': 'PASS',
        'scope': 'isolated_backup_copy_only',
        'original_tables_preserved': len(before_rows),
        'added_tables': added_tables,
        'source_sha256_unchanged': True,
        'production_migrated': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-copy', type=Path, required=True,
                        help='Quiescent restored/backup SQLite COPY, never live DB')
    parser.add_argument('--expected-sha256', help='Optional known SHA-256 of backup copy')
    parser.add_argument('--confirm-isolated-copy', action='store_true',
                        help='Confirm the input is a disposable offline copy')
    args = parser.parse_args(argv)
    if not args.confirm_isolated_copy:
        parser.error('--confirm-isolated-copy is required')
    try:
        print(json.dumps(rehearse(args.source_copy, args.expected_sha256),
                         sort_keys=True))
    except (RehearsalError, sqlite3.Error, OSError) as exc:
        # Error codes only: sqlite3 errors may contain sensitive file paths.
        code = str(exc) if isinstance(exc, RehearsalError) else type(exc).__name__
        print(json.dumps({'status': 'FAIL', 'error': code}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
