"""Local read-only audit using the deployed Google M:N expense reconciler."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp.expense_amount_group_service import audit_all_trips
from webapp.ledger_store import LedgerStore


def audit(*, board_db, snapshot, rows):
    """No schema initialization, source acquisition, canonical writes or exports."""
    names = ('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', 'WEBLEDGER_GOOGLE_LEDGER_ROWS')
    previous = {name:os.environ.get(name) for name in names}
    store = LedgerStore.__new__(LedgerStore)
    store.path = Path(board_db).resolve()
    store._lock = threading.RLock()
    store.current_role = lambda: 'owner'
    store.conn = sqlite3.connect(store.path.as_uri() + '?mode=ro', uri=True)
    try:
        store.conn.execute('PRAGMA query_only=ON')
        store.conn.execute('BEGIN')
        os.environ[names[0]], os.environ[names[1]] = str(snapshot), str(rows)
        result = audit_all_trips(store)
        result['database_changes'] = store.conn.total_changes
        return result
    finally:
        store.conn.close()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-db', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--rows', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit(board_db=args.board_db, snapshot=args.snapshot, rows=args.rows)
    except (OSError, sqlite3.Error, ValueError):
        report = {'available': False, 'reason': 'AUDIT_SOURCE_UNAVAILABLE'}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get('available') else 2


if __name__ == '__main__':
    raise SystemExit(main())
