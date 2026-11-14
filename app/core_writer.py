"""Single switch for who writes P1 automatic-classification columns: Python `apply` (default) or the Rust core.

One writer at a time (AGENTS.md). `WEBLEDGER_CLASSIFICATION_WRITER=rust` sends `automatic_classification.apply`
to `costcore apply`; anything else, including unset or a typo, keeps Python. Unsetting the variable is the rollback.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing, contextmanager, nullcontext
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITER_ENV = 'WEBLEDGER_CLASSIFICATION_WRITER'
BIN_ENV = 'WEBLEDGER_COSTCORE_BIN'
CORE_DB_ENV = 'WEBLEDGER_CORE_DB'


def selected() -> str:
    return 'rust' if os.environ.get(WRITER_ENV, '').strip().lower() == 'rust' else 'python'


def _main_database(conn) -> str:
    for _, name, path in conn.execute('PRAGMA database_list'):
        if name == 'main' and path:
            return path
    raise RuntimeError('CORE_WRITER_NEEDS_FILE_DATABASE')


PERIODS_CACHE = 'period-facts.json'
PERIODS_CACHE_SCHEMA = 2


@contextmanager
def _board(board_path):
    """The board opened as a LedgerStore (its constructor opens the file writable; the OTA code only reads)."""
    from webapp.ledger_store import LedgerStore
    store = LedgerStore(Path(board_path), seed_demo=False)
    try:
        yield store
    finally:
        store.close()


def _written_columns() -> tuple:
    """Card columns this writer changes; they are not evidence, so a write of ours must not invalidate the cache."""
    from . import automatic_classification as policy
    return (*policy.FIELDS, 'revision')


def _period_input_key(board_path) -> str:
    """The OTA worker's input fingerprint minus the columns `apply` writes (seconds, not the reconciliation)."""
    from webapp import ota_payment_review
    with _board(board_path) as store:
        return ota_payment_review.current_input_key(store, _written_columns())


def _period_snapshot(board_path) -> dict:
    """One full OTA reconciliation in a child process (about ten minutes on live data)."""
    from webapp import ota_payment_review
    with _board(board_path) as store:
        return ota_payment_review.reconcile_in_child(store)['data']


def _manual_overrides(conn, lock):
    with lock or nullcontext():
        if conn.in_transaction:
            raise RuntimeError('CORE_WRITER_IN_TRANSACTION')
        return _main_database(conn), sorted(row[0] for row in conn.execute(
            "SELECT row_id FROM board_manual_overrides WHERE field='service_period'"))


def _board_reader(board_path):
    return closing(sqlite3.connect(Path(board_path).resolve().as_uri() + '?mode=ro', uri=True))


def _p2_ids(conn) -> list:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='transactions'").fetchone():
        return []
    return [r[0] for r in conn.execute(
        "SELECT transaction_id FROM transactions WHERE classification_source='ai_inference' "
        "AND item IN ('숙박비','항공료','렌터카') ORDER BY transaction_id")]


def _p2_inputs(board_path) -> str:
    """Fingerprint of what the P2 period index reads. `apply` excludes the classification columns from the OTA key,
    so a P2 write (basis, source, revision) or its audit entry would otherwise leave the saved evidence stale."""
    try:
        with _board_reader(board_path) as conn:
            ids = _p2_ids(conn)
            rows = [conn.execute('SELECT revision,source_hash,item,classification_basis FROM transactions '
                                 'WHERE transaction_id=?', (tid,)).fetchone() for tid in ids]
            audit = conn.execute("SELECT count(*),max(entry_id) FROM change_log "
                                 "WHERE kind='card.classification_corrected'").fetchone()
            reviews = conn.execute('SELECT count(*) FROM review_decisions').fetchone()
    except sqlite3.Error:
        return ''
    return hashlib.sha256(json.dumps([ids, rows, audit, reviews], ensure_ascii=False).encode('utf-8')).hexdigest()


def _evidence_key(board_path, manual) -> str:
    from tools.core_bridge import periods as bridge
    return hashlib.sha256(json.dumps(
        [PERIODS_CACHE_SCHEMA, _period_input_key(board_path), manual, bridge.FACT_KEYS, bridge.EVENT_KEYS,
         bridge.CARD_KEYS, _p2_inputs(board_path)], ensure_ascii=False).encode('utf-8')).hexdigest()


def _p2_periods(board_path) -> dict:
    """Audited P2 periods bound to the current source and decision (`webapp.ledger_stay_evidence._p2_index`)."""
    from .ai_classification import service_metadata
    try:
        with _board_reader(board_path) as conn:
            return {tid: metadata for tid in _p2_ids(conn) if (metadata := service_metadata(conn, tid))}
    except sqlite3.Error:
        return {}


def _configured() -> str:
    core = os.environ.get(CORE_DB_ENV, '')
    if not os.environ.get(BIN_ENV, '') or not core:
        raise RuntimeError('CORE_WRITER_NOT_CONFIGURED')
    return core


def period_facts(board_path, manual, core) -> tuple:
    """(facts, key): booking-period evidence per transaction for `context.periods`, from the `periods` bridge.

    The reconciliation runs only when its input key (without the columns apply writes), the service-period
    overrides or the bridge columns changed; otherwise the derived facts saved beside core.sqlite are reused, so
    an apply does not invalidate the evidence for the next one. Rust then re-judges only transactions whose
    evidence digest changed, so nothing is computed when a screen renders.
    """
    from tools.core_bridge import periods as bridge
    key = _evidence_key(board_path, manual)
    cache = Path(core).with_name(PERIODS_CACHE)
    try:
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved.get('key') == key and isinstance(saved.get('facts'), dict):
            return saved['facts'], key
    except (OSError, ValueError):
        pass
    facts = bridge.evidence_from_snapshot(_period_snapshot(board_path), set(manual), _p2_periods(board_path))
    scratch = cache.with_name(cache.name + '.tmp')
    scratch.write_text(json.dumps({'key': key, 'facts': facts}, ensure_ascii=False), encoding='utf-8')
    os.replace(scratch, cache)
    return facts, key


def periods_with_key(conn, lock=None) -> tuple:
    """`period_facts` with the writer's configuration checks, as (facts, key).

    Pass the board lock as `lock` to call this outside it: only the short reads of `conn` take the lock, and the
    slow evidence build runs without it. Compare `key` with `periods_key` under the lock before applying.
    """
    core = _configured()
    board_path, manual = _manual_overrides(conn, lock)
    return period_facts(board_path, manual, core)


def periods_key(conn, lock=None) -> str:
    """The evidence key as of now (seconds, no reconciliation); a different value means the facts are stale."""
    _configured()
    board_path, manual = _manual_overrides(conn, lock)
    return _evidence_key(board_path, manual)


def periods_for(conn, lock=None) -> dict:
    """The facts of `periods_with_key` (the caller passes them to `apply`)."""
    return periods_with_key(conn, lock)[0]

class PeriodsStale(ValueError):
    """The evidence inputs changed after the evidence was built (same code as a stale preview)."""

    def __init__(self):
        super().__init__('CLASSIFICATION_PREVIEW_STALE')


_PREPARED: ContextVar = ContextVar('core_writer_prepared_periods', default=None)


def prepared(board, work):
    """Run `work()` with the period evidence built first, before any board lock or write transaction.

    Entry points that hold the board lock or open a transaction call this around themselves; the evidence build
    (minutes when the cache is cold) then never runs inside a lock. `run_with_periods` below, called inside
    `work`, only compares the key under the lock. A changed key rebuilds once, then raises `PeriodsStale`.
    Python writer: `work()` runs unchanged and nothing is computed.
    """
    if selected() != 'rust' or _PREPARED.get() is not None:
        return work()
    for _ in (0, 1):
        built = periods_with_key(board.conn, board._lock)
        token = _PREPARED.set(built)
        try:
            return work()
        except PeriodsStale:
            continue
        finally:
            _PREPARED.reset(token)
    raise PeriodsStale()


def run_with_periods(board, work):
    """`work(periods)` with the board lock held and `periods` still matching the inputs (None for the Python writer).

    Inside `prepared` the evidence already exists. Without it (a caller not yet lifted) the evidence is built here
    first, outside the lock if the caller holds none, and rebuilt once if the key moved.
    """
    if selected() != 'rust':
        with board._lock:
            return work(None)
    built = _PREPARED.get()
    if built is not None:
        with board._lock:
            if periods_key(board.conn) != built[1]:
                raise PeriodsStale()
            return work(built[0])
    for _ in (0, 1):
        facts, key = periods_with_key(board.conn, board._lock)
        with board._lock:
            if periods_key(board.conn) == key:
                return work(facts)
    raise PeriodsStale()

def apply(conn, expected, trips, *, nets=None, transaction_ids=None, reconsider=False, evidence=None, periods=None):
    """Rust apply with the same contract as `automatic_classification.apply` (returns the plan summary).

    `periods` is `periods_for(conn)`; without it the Rust period evidence is empty and stored periods are unknown.
    """
    binary, core = os.environ.get(BIN_ENV, ''), os.environ.get(CORE_DB_ENV, '')
    if not binary or not core:
        raise RuntimeError('CORE_WRITER_NOT_CONFIGURED')
    if conn.in_transaction:
        raise RuntimeError('CORE_WRITER_IN_TRANSACTION')
    request = {'trips': trips, 'nets': nets or {}, 'evidence': evidence or {}, 'reconsider': bool(reconsider)}
    if periods is not None:
        request['periods'] = periods
    if transaction_ids is not None:
        request['transaction_ids'] = sorted(transaction_ids)
    done = subprocess.run(
        [binary, 'apply', '--db', _main_database(conn), '--core', core, '--digest', expected['digest'],
         '--allow-live', '--python', sys.executable, '--repo-root', str(ROOT)],
        input=json.dumps(request, ensure_ascii=False), capture_output=True, text=True, encoding='utf-8', timeout=600)
    try:
        response = json.loads(done.stdout.splitlines()[0])
    except (IndexError, ValueError):
        raise RuntimeError('CORE_WRITER_NO_RESPONSE') from None
    if response.get('ok'):
        return response['result']
    code = (response.get('error') or {}).get('code', 'CORE_WRITER_FAILED')
    if code == 'CLASSIFICATION_PREVIEW_STALE':
        raise ValueError(code)
    raise RuntimeError(code)


def stored_service_period(transaction_id: str):
    """Stored use period of a decision (core.sqlite), or None. Screens and exports read this; they never recompute it.

    `kind` is verified (a stored value, a verified link or a flight booking), inferred (with `basis`) or unknown
    (with `reason`). Decisions written before inferred periods existed keep their old `known` spelling in the
    database; it reads as verified.
    """
    core = os.environ.get(CORE_DB_ENV, '')
    if not core:
        raise RuntimeError('CORE_WRITER_NOT_CONFIGURED')
    with closing(sqlite3.connect(Path(core).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT service_period_json FROM decisions WHERE transaction_id=?',
                           (transaction_id,)).fetchone()
    if not row:
        return None
    stored = json.loads(row[0])
    kind = {'known': 'verified'}.get(stored.get('kind'), stored.get('kind'))
    return {**stored, 'kind': kind if kind in ('verified', 'inferred', 'unknown') else 'unknown'}
