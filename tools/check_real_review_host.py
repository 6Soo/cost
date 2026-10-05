"""Read-only operational inspection. Output contains counts and integrity only."""
import hashlib
import json
from pathlib import Path
import sqlite3


def main():
    config = json.loads(Path('D:/WebLedgerHost/config/real-review.json').read_text(encoding='utf-8-sig'))
    checks = {kind: hashlib.sha256(Path(config[kind + '_path']).read_bytes()).hexdigest() == config[kind + '_sha256']
              for kind in ('snapshot', 'review', 'master')}
    connection = sqlite3.connect('file:D:/WebLedgerHost/data/board.sqlite?mode=ro', uri=True)
    try:
        operational_rows = connection.execute('select count(*) from board_rows').fetchone()[0]
    finally:
        connection.close()
    choices_path = Path(config['decisions_db_path'])
    revision = 0
    selected = rejected = 0
    if choices_path.exists():
        connection = sqlite3.connect(choices_path.as_uri() + '?mode=ro', uri=True)
        try:
            binding = '|'.join(config[k + '_sha256'] for k in ('snapshot', 'review', 'master'))
            row = connection.execute('select revision, choices_json from review_choice_sets where binding=?', (binding,)).fetchone()
            if row:
                revision = row[0]
                choices = json.loads(row[1])
                selected = sum(isinstance(v, str) and v.startswith('APPROVE:') for v in choices.values())
                rejected = sum(v == 'REJECT' for v in choices.values())
        finally:
            connection.close()
    output = {'source_integrity': checks, 'operational_rows': operational_rows,
              'saved_revision': revision, 'selected': selected, 'rejected': rejected,
              'read_only': True}
    Path('C:/AX/cost/docs/handoff/2026-10-01/current-protected-source-audit.json').write_text(json.dumps(output, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
