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
    return ''  # no file (:memory: clone): the connection's own rows go to costcore on stdin


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
    if not path:
        return True
    if not (conn.in_transaction and _committed_digest(path) != digest):
        return False
    if not (_UNCOMMITTED_OK.get() or _query_only(conn)):
        raise RuntimeError('CORE_LINKS_UNCOMMITTED_ROWS')
    return True


def _query_only(conn) -> bool:
    """A query_only connection holds no writes of its own: its differing rows are a read snapshot, not a rollback risk."""
    return bool(conn.execute('PRAGMA query_only').fetchone()[0])


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


_ENTRY_TEXT = ('item', 'display_tab_id', 'trip_id', 'description')
_ENTRY_KEYS = frozenset(('id', *_ENTRY_TEXT, 'blocked', 'already_booked', 'external', 'ready'))


def _ledger_entry(entry, ready_ids):
    return dict(id=entry['transaction_id'],
                **{key: str(entry.get(key) or '') for key in _ENTRY_TEXT},
                blocked=(dict(code=entry['blocked'], reason=str(entry.get('reason') or ''))
                         if entry.get('blocked') else None),
                already_booked=bool(entry.get('already_booked')),
                external=bool(entry.get('source_batch_id')), ready=entry['transaction_id'] in ready_ids)


def _ledger_run(conn, command, entries, *, booked=(), authority=None):
    """Use this connection's exact source snapshot, including its pending rows. Never fall back."""
    binary = os.environ.get(BIN_ENV, '')
    if not binary:
        raise RuntimeError('CORE_LINKS_NOT_CONFIGURED')
    digest = source_digest(conn)
    config = CONFIG.read_bytes()
    request = dict(rows=row_dicts(fetch_rows(conn)), entries=entries, booked=list(booked),
                   authority=authority or dict(trips=None, tabs=None))
    done = subprocess.run([binary, 'links', command, '--repo-root', str(ROOT)],
                          input=json.dumps(request, ensure_ascii=False), capture_output=True,
                          text=True, encoding='utf-8', timeout=300)
    if source_digest(conn) != digest or CONFIG.read_bytes() != config:
        raise RuntimeError('CORE_LINKS_DB_CHANGING')
    try:
        response = json.loads(done.stdout.splitlines()[0])
        if not isinstance(response, dict):
            raise ValueError
    except (ValueError, IndexError):
        raise RuntimeError('CORE_LINKS_NO_RESPONSE') from None
    if done.returncode or response.get('ok') is not True:
        from .db import StoreError
        error = response.get('error')
        code = error.get('code') if isinstance(error, dict) else None
        if code in ('REFUND_GROUP_INCOMPLETE', 'REFUND_GROUP_EXCLUDED', 'INVALID_INPUT'):
            raise StoreError(code, '환불 묶음 검증을 통과하지 못했습니다.')
        raise RuntimeError('CORE_LINKS_FAILED')
    if not isinstance(response.get('result'), dict):
        raise RuntimeError('CORE_LINKS_INVALID_RESPONSE')
    return response['result']


def _validate_entries(result, sent, source_ids):
    out = result.get('entries')
    invalid = lambda: RuntimeError('CORE_LINKS_INVALID_RESPONSE')
    if not isinstance(out, list) or len(out) != len(sent):
        raise invalid()
    for before, after in zip(sent, out):
        if not isinstance(after, dict) or not _ENTRY_KEYS <= after.keys() or after.keys() - (_ENTRY_KEYS | {'refund_link'}):
            raise invalid()
        if (after['id'] != before['id'] or after['id'] not in source_ids
                or any(type(after[key]) is not bool for key in ('already_booked', 'external', 'ready'))
                or any(after[key] != before[key] for key in ('already_booked', 'external'))
                or any(not isinstance(after[key], str) for key in _ENTRY_TEXT)):
            raise invalid()
        block = after['blocked']
        if block is not None and (not isinstance(block, dict) or set(block) != {'code', 'reason'}
                                  or any(not isinstance(block[k], str) for k in block) or not block['code']):
            raise invalid()
        if block is not None and after['ready']:
            raise invalid()
        note = after.get('refund_link')
        if note is not None:
            required = {'gross_krw', 'refund_krw', 'net_krw', 'status', 'role', 'counterpart_id'}
            if (not isinstance(note, dict) or not required <= note.keys()
                    or note.keys() - (required | {'basis', 'inferred'})
                    or any(type(note[k]) is not int for k in ('gross_krw', 'refund_krw', 'net_krw'))
                    or note['status'] not in ('full', 'partial', 'excess')
                    or note['role'] not in ('original', 'refund')
                    or note['counterpart_id'] not in source_ids
                    or type(note.get('inferred', False)) is not bool
                    or note.get('basis') is not None and not isinstance(note['basis'], str)):
                raise invalid()
    return out


def ledger_pairs(conn, rows, ready, unresolved, *, trip_validator=None, tab_validator=None):
    """Consume Rust's decision fields only, validating the entire response before changing any row."""
    ready_ids = {entry['transaction_id'] for entry in ready}
    sent = [_ledger_entry(entry, ready_ids) for entry in rows]
    ids = [entry['id'] for entry in sent]
    if len(set(ids)) != len(ids):
        raise RuntimeError('CORE_LINKS_DUPLICATE_ENTRY')
    def authorities(key, validator, extra=()):
        return ({value: bool(validator(value)) for value in {entry[key] for entry in sent} | set(extra) if value}
                if callable(validator) else None)
    result = _ledger_run(conn, 'refund-entries', sent,
                         authority=dict(trips=authorities('trip_id', trip_validator),
                                        tabs=authorities('display_tab_id', tab_validator, ('refunds',))))
    source_ids = {row[0] for row in conn.execute('SELECT transaction_id FROM transactions')}
    updates = _validate_entries(result, sent, source_ids)
    for entry, update in zip(rows, updates):
        entry.update({key: update[key] for key in _ENTRY_TEXT})
        for key in ('blocked', 'reason', 'refund_link'):
            entry.pop(key, None)
        if update['blocked'] is not None:
            entry.update(blocked=update['blocked']['code'], reason=update['blocked']['reason'])
        if update.get('refund_link') is not None:
            entry['refund_link'] = update['refund_link']
        for bucket in (ready, unresolved):
            if entry in bucket:
                bucket.remove(entry)
        (ready if update['ready'] else unresolved).append(entry)


def check_ledger_groups(conn, rows):
    """Return the sealed member IDs whose last authority check must remain atomic with publication."""
    ready_ids = {row['transaction_id'] for row in rows if not row.get('blocked') and not row.get('already_booked')}
    sent = [_ledger_entry(row, ready_ids) for row in rows]
    booked = [row[0] for row in conn.execute('SELECT transaction_id FROM ledger_entries ORDER BY transaction_id')]
    result = _ledger_run(conn, 'refund-check', sent, booked=booked)
    groups = result.get('groups')
    if not isinstance(groups, list):
        raise RuntimeError('CORE_LINKS_INVALID_RESPONSE')
    source_ids = {row[0] for row in conn.execute('SELECT transaction_id FROM transactions')}
    members, group_ids = set(), set()
    for group in groups:
        if (not isinstance(group, dict) or set(group) != {'id', 'members'}
                or not isinstance(group['id'], str) or not group['id'] or group['id'] in group_ids
                or not isinstance(group['members'], list)
                or any(not isinstance(member, str) for member in group['members'])):
            raise RuntimeError('CORE_LINKS_INVALID_RESPONSE')
        current = set(group['members'])
        if (len(current) != len(group['members']) or len(current) < 2 or current & members
                or not current <= source_ids or not current & ready_ids
                or not current <= ready_ids | set(booked)):
            raise RuntimeError('CORE_LINKS_INVALID_RESPONSE')
        members.update(current)
        group_ids.add(group['id'])
    required = {row['transaction_id'] for row in rows if row['transaction_id'] in ready_ids
                and row.get('refund_link') and not row['refund_link'].get('inferred')}
    if not required <= members:
        raise RuntimeError('CORE_LINKS_INVALID_RESPONSE')
    return frozenset(members)
