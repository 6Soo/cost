"""Single switch for who writes P1 automatic-classification columns: Python `apply` (default) or the Rust core.

One writer at a time (AGENTS.md). `WEBLEDGER_CLASSIFICATION_WRITER=rust` sends `automatic_classification.apply`
to `costcore apply`; anything else, including unset or a typo, keeps Python. Unsetting the variable is the rollback.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
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


def apply(conn, expected, trips, *, nets=None, transaction_ids=None, reconsider=False, evidence=None):
    """Rust apply with the same contract as `automatic_classification.apply` (returns the plan summary)."""
    binary, core = os.environ.get(BIN_ENV, ''), os.environ.get(CORE_DB_ENV, '')
    if not binary or not core:
        raise RuntimeError('CORE_WRITER_NOT_CONFIGURED')
    if conn.in_transaction:
        raise RuntimeError('CORE_WRITER_IN_TRANSACTION')
    request = {'trips': trips, 'nets': nets or {}, 'evidence': evidence or {}, 'reconsider': bool(reconsider)}
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
