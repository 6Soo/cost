"""Single switch for who derives refund pairs: Python `partial_refund` (default) or `costcore links refund`.

`WEBLEDGER_LINKS_PRODUCER=rust` makes `partial_refund._analyse` take its result from the Rust core; anything else,
including unset or a typo, keeps Python. Independent of WEBLEDGER_CLASSIFICATION_WRITER. Unsetting it is the rollback.
Pairs are never stored: every analysis is derived from the `transactions` source rows, so there is nothing to restore.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCER_ENV = 'WEBLEDGER_LINKS_PRODUCER'
BIN_ENV = 'WEBLEDGER_COSTCORE_BIN'
CONFIG = ROOT / 'config' / 'refund-pairing.json'
# Exactly the columns `Refunds::derive` reads (core `shadow::links::refund_rows`); rowid fixes the row order.
COLUMNS = ('transaction_id', 'issuer', 'card_tail', 'transaction_direction', 'approval_number',
           'original_approval_number', 'amount_krw', 'approval_date', 'posting_date', 'merchant',
           'merchant_normalized', 'foreign_amount', 'foreign_currency', 'duplicate_of', 'conflict_reason',
           'parse_error')
_QUERY = f"SELECT rowid,{','.join(COLUMNS)} FROM transactions ORDER BY rowid"
_CACHE_SIZE = 4
_cache: dict = {}
_versions: dict = {}
_lock = threading.Lock()
_UNCOMMITTED_OK: ContextVar = ContextVar('links_uncommitted_rows_ok', default=False)


def selected() -> str:
    return 'rust' if os.environ.get(PRODUCER_ENV, '').strip().lower() == 'rust' else 'python'


def _database(conn) -> str:
    for _, name, path in conn.execute('PRAGMA database_list'):
        if name == 'main' and path:
            return str(Path(path).resolve())
    raise RuntimeError('CORE_LINKS_NEEDS_FILE_DATABASE')


def fetch_rows(conn) -> list:
    return conn.execute(_QUERY).fetchall()


def row_dicts(rows) -> list:
    """Rows as the JSON `costcore links refund --rows-stdin` reads (rowid dropped, order kept)."""
    return [dict(zip(COLUMNS, row[1:])) for row in rows]


@contextmanager
def uncommitted_rows():
    """Let `analyse` inside this block serve a write transaction's own uncommitted rows.

    Outside it an uncommitted pairing input is refused (CORE_LINKS_UNCOMMITTED_ROWS). Inside it the rows are sent to
    costcore on stdin instead of being read from the file, so the answer is the Python derivation's on the same rows.
    Only for callers that read the pairs to decide inside their own transaction and still roll back as a unit.
    """
    token = _UNCOMMITTED_OK.set(True)
    try:
        yield
    finally:
        _UNCOMMITTED_OK.reset(token)


def source_digest(conn) -> str:
    """Content digest of every source column the derivation reads, plus row count and max rowid.

    `revision` is not enough: it counts decisions, while duplicate_of, conflict_reason, parse_error and the source
    fields can change without moving it. Any change to a pairing input changes this digest; a change to a column the
    derivation ignores (classification, item, trip) does not, so a classification apply never invalidates the cache.
    """
    digest = hashlib.blake2b(digest_size=20)
    count, last = 0, 0
    cursor = conn.execute(_QUERY)
    while chunk := cursor.fetchmany(4096):
        digest.update(repr([tuple(row) for row in chunk]).encode('utf-8'))
        count += len(chunk)
        last = chunk[-1][0]
    return f'{count}:{last}:{digest.hexdigest()}'


def _committed_digest(path: str) -> str:
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
        return source_digest(conn)


def _binary(binary: str) -> tuple:
    """(stat key, `--version` text) of the binary; the version is asked once per file state."""
    info = os.stat(binary)
    stamp = (binary, info.st_size, info.st_mtime_ns)
    with _lock:
        if stamp in _versions:
            return stamp, _versions[stamp]
    done = subprocess.run([binary, '--version'], capture_output=True, text=True, encoding='utf-8', timeout=60)
    if done.returncode != 0:
        raise RuntimeError('CORE_LINKS_BINARY_FAILED')
    with _lock:
        _versions[stamp] = done.stdout.strip()
        return stamp, _versions[stamp]


def _run(binary: str, path: str, rows=None) -> str:
    """`rows` (a list from `fetch_rows`) replaces the file with the connection's own rows, sent on stdin."""
    if rows is None:
        done = subprocess.run([binary, 'links', 'refund', '--db', path, '--repo-root', str(ROOT)],
                              capture_output=True, text=True, encoding='utf-8', timeout=300)
    else:
        done = subprocess.run([binary, 'links', 'refund', '--rows-stdin', '--repo-root', str(ROOT)],
                              input=json.dumps(row_dicts(rows), ensure_ascii=False),
                              capture_output=True, text=True, encoding='utf-8', timeout=300)
    try:
        response = json.loads(done.stdout.splitlines()[0])
    except (IndexError, ValueError):
        raise RuntimeError('CORE_LINKS_NO_RESPONSE') from None
    if not response.get('ok') or done.returncode != 0:
        raise RuntimeError((response.get('error') or {}).get('code', 'CORE_LINKS_FAILED'))
    return json.dumps(response['result'], ensure_ascii=False)


def _uncommitted(conn, path: str, digest: str) -> bool:
    """True when this connection's pairing inputs differ from the file's, which Rust reads.

    Refused unless the caller opted in with `uncommitted_rows()`: then the rows are sent on stdin, never mixed.
    """
    if not (conn.in_transaction and _committed_digest(path) != digest):
        return False
    if not _UNCOMMITTED_OK.get():
        raise RuntimeError('CORE_LINKS_UNCOMMITTED_ROWS')
    return True


def analyse(conn) -> tuple:
    """(links, held, extra) as `partial_refund._analyse` returns them, produced by `costcore links refund`.

    `extra` carries the Rust `group_exclusions` and `review_originals` for the functions built on the same analysis.
    The result is cached in process memory under (file, binary version, config, source digest); a changed source
    row gives a different digest and recomputes. A costcore failure raises: there is no quiet fallback to Python,
    because two producers disagreeing silently is the failure this switch exists to prevent.
    """
    binary = os.environ.get(BIN_ENV, '')
    if not binary:
        raise RuntimeError('CORE_LINKS_NOT_CONFIGURED')
    path = _database(conn)
    stamp, version = _binary(binary)
    config = hashlib.blake2b(CONFIG.read_bytes(), digest_size=20).hexdigest()
    for _ in (0, 1):
        digest = source_digest(conn)
        pending = _uncommitted(conn, path, digest)
        key = (path, stamp, version, config, digest)
        with _lock:
            text = _cache.get(key)
        if text is None:
            text = _run(binary, path, fetch_rows(conn) if pending else None)
            # A commit during the run makes the result belong to another state: do not cache it, run again.
            if source_digest(conn) != digest:
                continue
            if not pending:
                _uncommitted(conn, path, digest)
            with _lock:
                while len(_cache) >= _CACHE_SIZE:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = text
        result = json.loads(text)
        return (result['links'], result['held'],
                {'group_exclusions': result['group_exclusions'], 'review_originals': result['review_originals']})
    raise RuntimeError('CORE_LINKS_DB_CHANGING')


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _versions.clear()
