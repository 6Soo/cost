"""Inspect the integrated host without changing choices or ledger facts."""
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3


def main():
    root = Path(__file__).resolve().parents[1]
    evidence = root / 'docs/handoff/2026-10-01'
    config = json.loads(Path('D:/WebLedgerHost/config/real-review.json').read_text(encoding='utf-8-sig'))
    binding = '|'.join(config[k + '_sha256'] for k in ('snapshot', 'review', 'master'))
    counts = {}
    with sqlite3.connect('file:D:/WebLedgerHost/data/board.sqlite?mode=ro', uri=True) as conn:
        for table in ('board_rows', 'board_requests', 'source_fact_rows', 'source_fact_applies'):
            counts[table] = conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    db = Path(config['decisions_db_path'])
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
        row = conn.execute('SELECT revision, choices_json FROM review_choice_sets WHERE binding=?', (binding,)).fetchone()
    choices = json.loads(row[1]) if row else {}
    hashes = json.loads((evidence / 'apply-integration-hashes.json').read_text(encoding='utf-8'))['files']
    expected = {name: data['after'] for name, data in hashes.items()}
    initial_match = all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
                        for name, digest in expected.items())
    accepted_updates = []
    for prefix in ('reserve-navigation', 'google-cookie-jar', 'reserve-mobile',
                   'owner-metadata', 'export-assignee-guidance'):
        path = evidence / (prefix + '-operational-integration.json')
        if not path.exists():
            continue
        update = json.loads(path.read_text(encoding='utf-8-sig'))
        if update.get('success') is True:
            accepted_updates.append((datetime.datetime.fromisoformat(update['recorded_at']), prefix, update))
    overrides = {}
    for _, prefix, update in sorted(accepted_updates):
        accepted = json.loads((evidence / (prefix + '-candidate-hashes.json')).read_text(encoding='utf-8-sig'))
        if accepted.get('parent_tests_passed') is not True or accepted['files'] != update['files']:
            raise RuntimeError('ACCEPTED_INTEGRATION_MANIFEST_MISMATCH')
        for name, digest in update['files'].items():
            if name in expected:
                expected[name] = digest
                overrides[name] = prefix
    result = {
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'read_only': True,
        'binding': binding,
        'choices_revision': row[0] if row else 0,
        'selected': sum(isinstance(v, str) and v.startswith('APPROVE:') for v in choices.values()),
        'rejected': sum(v == 'REJECT' for v in choices.values()),
        'counts': counts,
        'database_integrity': integrity,
        'initial_apply_files_match': initial_match,
        'integration_scope': 'initial_apply_with_later_accepted_overrides',
        'accepted_overrides': overrides,
        'integrated_files_match': all(hashlib.sha256((root / n).read_bytes()).hexdigest() == h for n, h in expected.items()),
        'source_integrity': {k: hashlib.sha256(Path(config[k + '_path']).read_bytes()).hexdigest() == config[k + '_sha256'] for k in ('snapshot', 'review', 'master')},
        'actual_import_performed': bool(counts['source_fact_rows']),
    }
    (evidence / 'apply-protected-runtime-audit.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
