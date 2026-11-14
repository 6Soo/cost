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
PERIODS_CACHE_SCHEMA = 1


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


def period_facts(board_path, manual, core) -> dict:
    """Booking-period evidence per transaction for `context.periods`, from the `periods` bridge.

    The reconciliation runs only when its input key (without the columns apply writes), the service-period
    overrides or the bridge columns changed; otherwise the derived facts saved beside core.sqlite are reused, so
    an apply does not invalidate the evidence for the next one. Rust then re-judges only transactions whose
    evidence digest changed, so nothing is computed when a screen renders.
    """
    from tools.core_bridge import periods as bridge
    key = hashlib.sha256(json.dumps(
        [PERIODS_CACHE_SCHEMA, _period_input_key(board_path), manual, bridge.FACT_KEYS, bridge.EVENT_KEYS,
         bridge.CARD_KEYS], ensure_ascii=False).encode('utf-8')).hexdigest()
    cache = Path(core).with_name(PERIODS_CACHE)
    try:
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved.get('key') == key and isinstance(saved.get('facts'), dict):
            return saved['facts']
    except (OSError, ValueError):
        pass
    facts = bridge.facts_from_snapshot(_period_snapshot(board_path), set(manual))
    scratch = cache.with_name(cache.name + '.tmp')
    scratch.write_text(json.dumps({'key': key, 'facts': facts}, ensure_ascii=False), encoding='utf-8')
    os.replace(scratch, cache)
    return facts


def periods_for(conn, lock=None) -> dict:
    """`period_facts` with the writer's configuration checks (the caller passes the result to `apply`).

    Pass the board lock as `lock` to call this outside it: only the short reads of `conn` take the lock, and the
    slow evidence build runs without it.
    """
    core = os.environ.get(CORE_DB_ENV, '')
    if not os.environ.get(BIN_ENV, '') or not core:
        raise RuntimeError('CORE_WRITER_NOT_CONFIGURED')
    with lock or nullcontext():
        if conn.in_transaction:
            raise RuntimeError('CORE_WRITER_IN_TRANSACTION')
        board_path = _main_database(conn)
        manual = sorted(row[0] for row in conn.execute(
            "SELECT row_id FROM board_manual_overrides WHERE field='service_period'"))
    return period_facts(board_path, manual, core)

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
    """Stored use period of a decision (core.sqlite), or None. Screens and exports read this; they never recompute it."""
    core = os.environ.get(CORE_DB_ENV, '')
    if not core:
        raise RuntimeError('CORE_WRITER_NOT_CONFIGURED')
    with closing(sqlite3.connect(Path(core).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT service_period_json FROM decisions WHERE transaction_id=?',
                           (transaction_id,)).fetchone()
    return json.loads(row[0]) if row else None
