"""Read protected operating tables and write only aggregate release evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

DATABASES = {'board': Path('D:/WebLedgerHost/data/board.sqlite'),
             'review': Path('D:/WebLedgerHost/data/ota-review/ota-review.sqlite')}
REQUIRED_TABLES = frozenset({
    'board:board_rows', 'board:income_source_links', 'board:reserve_event_links',
    'board:reserve_link_state', 'board:reserve_link_saves',
    'board:reserve_link_apply_requests', 'board:reserve_link_applies',
    'board:transactions', 'board:review_decisions', 'board:ledger_entries',
    'board:transaction_review_holds', 'review:ota_review_links',
    'review:ota_review_group_pins',
})
APPROVABLE_EMPTY_TABLES = frozenset({'board:receipt_evidence_links'})


def snapshot(databases):
    result = {}
    for name, path in databases.items():
        connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            connection.execute('BEGIN')
            for table, schema in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall():
                if table in ('transactions', 'ledger_entries', 'review_decisions', 'transaction_review_holds', 'board_rows') or 'link' in table or 'group_pin' in table:
                    quoted = '"' + table.replace('"', '""') + '"'
                    rows = sorted(connection.execute('SELECT * FROM ' + quoted).fetchall(), key=repr)
                    result[name + ':' + table] = {'count': len(rows),
                        'sha256': hashlib.sha256(repr((schema, rows)).encode()).hexdigest()}
        finally:
            connection.close()
    return result


def validate_inventory(state):
    if not REQUIRED_TABLES.issubset(state):
        raise ValueError('PROTECTED_TABLE_MISSING')


def verify(current, previous, *, allowed_empty_tables=()):
    additions = current.keys() - previous.keys()
    allowed = set(allowed_empty_tables) & APPROVABLE_EMPTY_TABLES
    if (any(current.get(key) != value for key, value in previous.items())
            or not additions.issubset(allowed)
            or any(current[key]['count'] != 0 for key in additions)):
        raise ValueError('PROTECTED_STATE_CHANGED')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--phase', choices=('before', 'after', 'validate-baseline'), required=True)
    parser.add_argument('--allow-empty-table', action='append', default=[],
                        choices=sorted(APPROVABLE_EMPTY_TABLES))
    args = parser.parse_args(argv)
    try:
        baseline_path = args.evidence_dir / 'protection-before.json'
        if args.phase == 'validate-baseline':
            previous = json.loads(baseline_path.read_text(encoding='utf-8-sig'))
            validate_inventory(previous)
            print(json.dumps({'status': 'PASS', 'tables': len(previous), 'phase': args.phase}))
            return 0
        current = snapshot(DATABASES)
        validate_inventory(current)
        if args.phase == 'after':
            previous = json.loads(baseline_path.read_text(encoding='utf-8-sig'))
            validate_inventory(previous)
            verify(current, previous, allowed_empty_tables=args.allow_empty_table)
        destination = args.evidence_dir / ('protection-' + args.phase + '.json')
        destination.write_text(json.dumps(current, indent=2), encoding='utf-8')
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({'status': 'FAILED', 'code': 'PROTECTED_STATE_UNVERIFIED'}))
        return 2
    print(json.dumps({'status': 'PASS', 'tables': len(current), 'phase': args.phase,
                      'unchanged': args.phase == 'after'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
