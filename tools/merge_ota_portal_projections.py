"""Dry-run/apply CLI for the in-flight `app.ota_store.merge_portal_projections`.

`merge_portal_projections(conn, *, apply=False)` owns the schema and the reported
counts; this tool only opens an explicit target and drives it: no-op by default
(`apply=False`), `--apply` opts in, and its returned mapping is reported as-is.

Safety: `--db` is required and resolved first; the live host `D:/WebLedgerHost`,
`WEBLEDGER_DATA_ROOT`, and an exact resolved `WEBLEDGER_DB` are refused before the
existence/type checks; multi-link targets and non-SQLite targets are refused; the
connect is SQLite `mode=rw` so a missing target is never created.

Failures print one fixed-code JSON object on stdout ({"ok": false, "code": ...}),
never a message or traceback. Exit codes: 0 ok; 1 INTERNAL; 2 usage (argparse); 3
DB_MISSING; 4 DB_UNUSABLE/DB_LINK_REFUSED; 5 LIVE_ROOT_REFUSED/
OPERATIONAL_ROOT_REFUSED/OPERATIONAL_ROOT_INVALID/OPERATIONAL_DB_REFUSED; 6
MERGE_VALIDATION_FAILED; 7 DB_BUSY/DB_IO_ERROR/DB_ERROR.

The `app.ota_store` import is lazy so `--help` works before the function lands; a
normal run without it closes as INTERNAL.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIVE_HOST = Path('D:/WebLedgerHost')
DATA_ROOT_ENV = 'WEBLEDGER_DATA_ROOT'
DATABASE_ENV = 'WEBLEDGER_DB'
SQLITE_MAGIC = b'SQLite format 3\x00'


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n')


def _fail(code: str, exit_code: int) -> int:
    _emit({'ok': False, 'code': code})
    return exit_code


def _refusal(resolved: Path) -> str | None:
    """Live-host / operational-root / configured-database refusal, else None."""
    try:
        host = LIVE_HOST.resolve()
    except OSError:
        return 'LIVE_ROOT_REFUSED'  # cannot prove the path is outside the host root
    if resolved == host or resolved.is_relative_to(host):
        return 'LIVE_ROOT_REFUSED'
    raw_root = os.environ.get(DATA_ROOT_ENV, '').strip()
    if raw_root:
        try:
            root = Path(raw_root).resolve()
        except (OSError, ValueError):
            return 'OPERATIONAL_ROOT_INVALID'
        if resolved == root or resolved.is_relative_to(root):
            return 'OPERATIONAL_ROOT_REFUSED'
    raw_db = os.environ.get(DATABASE_ENV, '').strip()
    if raw_db:
        try:
            configured = Path(raw_db).resolve()
        except (OSError, ValueError):
            return 'OPERATIONAL_ROOT_INVALID'
        if resolved == configured:
            return 'OPERATIONAL_DB_REFUSED'
    return None


def _link_refusal(path: Path) -> str | None:
    """Refuse nlink>1 (alias) and a vanished target; None when it is an ordinary file."""
    try:
        links = getattr(os.stat(path), 'st_nlink', 0)
    except OSError:
        return 'DB_IO_ERROR'
    return 'DB_LINK_REFUSED' if links > 1 else None


def _sqlite_header_ok(path: Path) -> bool:
    try:
        with path.open('rb') as handle:
            return handle.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def _open_rw(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)


def _busy_code(error: sqlite3.OperationalError) -> str:
    text = str(error).lower()
    return 'DB_BUSY' if 'locked' in text or 'busy' in text else 'DB_IO_ERROR'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Dry-run/apply CLI for app.ota_store.merge_portal_projections.')
    parser.add_argument('--db', type=Path, required=True,
                        help='existing unified OTA database to merge into (never created here)')
    parser.add_argument('--apply', action='store_true',
                        help='write; default is dry-run via the merge function no-op transaction')
    args = parser.parse_args(argv)

    try:
        try:
            target = Path(args.db).resolve()
        except OSError:
            return _fail('DB_MISSING', 3)
        refusal = _refusal(target)
        if refusal is not None:
            return _fail(refusal, 5)
        if not target.is_file():
            return _fail('DB_MISSING', 3)
        link_refusal = _link_refusal(target)
        if link_refusal == 'DB_IO_ERROR':
            return _fail(link_refusal, 7)
        if link_refusal is not None:
            return _fail(link_refusal, 4)
        if not _sqlite_header_ok(target):
            return _fail('DB_UNUSABLE', 4)
        conn: sqlite3.Connection | None = None
        try:
            # Imported on demand so --help never depends on the in-flight function.
            from app import ota_store  # noqa: PLC0415
            if not hasattr(ota_store, 'merge_portal_projections'):
                raise RuntimeError('ota_store.merge_portal_projections is unavailable in this tree')
            conn = _open_rw(target)
            mode = 'apply' if args.apply else 'dry-run'
            result = ota_store.merge_portal_projections(conn, apply=bool(args.apply))
            _emit({'ok': True, 'mode': mode, 'result': result})
            return 0
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
    except ValueError:
        return _fail('MERGE_VALIDATION_FAILED', 6)
    except sqlite3.OperationalError as error:
        return _fail(_busy_code(error), 7)
    except sqlite3.Error:
        return _fail('DB_ERROR', 7)
    except Exception:
        return _fail('INTERNAL', 1)


if __name__ == '__main__':
    raise SystemExit(main())
