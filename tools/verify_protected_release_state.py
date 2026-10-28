"""Read protected operating tables and write only aggregate release evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

DATABASES = {'board': Path('D:/WebLedgerHost/data/board.sqlite'),
             'review': Path('D:/WebLedgerHost/data/ota-review/ota-review.sqlite')}


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


def verify(current, previous):
    if current != previous:
        raise ValueError('PROTECTED_STATE_CHANGED')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    args = parser.parse_args(argv)
    try:
        current = snapshot(DATABASES)
        if len(current) != 13:
            raise ValueError('PROTECTED_TABLE_COUNT_CHANGED')
        if args.phase == 'after':
            verify(current, json.loads((args.evidence_dir / 'protection-before.json').read_text(encoding='utf-8-sig')))
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
