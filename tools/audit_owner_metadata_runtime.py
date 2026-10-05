"""Read-only hashes of existing trip fields before and after metadata integration."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':'),
                                     sort_keys=True).encode('utf-8')).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('before', 'after'))
    args = parser.parse_args()
    conn = sqlite3.connect('file:D:/WebLedgerHost/data/board.sqlite?mode=ro', uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        columns = ('tab_id', 'display_key', 'destination', 'starts_on', 'ends_on',
                   'event_year', 'tab_kind', 'authority_status', 'source_sha256',
                   'sort_order', 'prepared_on', 'prepared_by_name', 'archived',
                   'deleted', 'revision')
        rows = conn.execute('SELECT ' + ','.join(columns) +
                            ' FROM trip_tabs ORDER BY tab_id').fetchall()
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        present_columns = {row[1] for row in conn.execute('PRAGMA table_info(trip_tabs)')}
        history = conn.execute('SELECT * FROM trip_tab_history ORDER BY tab_id,revision').fetchall()
        requests = conn.execute('SELECT * FROM trip_tab_requests ORDER BY client_request_id').fetchall()
        result = dict(recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      read_only=True, identities_exported=False, stage=args.stage,
                      trip_count=len(rows), original_trip_fields_sha256=digest(rows),
                      trip_history_sha256=digest(history), trip_requests_sha256=digest(requests),
                      database_integrity=conn.execute('PRAGMA integrity_check').fetchone()[0])
        result['profile_counts'] = {
            table: conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
            if table in tables else None
            for table in ('owner_profile', 'owner_profile_requests', 'owner_profile_history')}
        result['assignee_source_counts'] = dict(conn.execute(
            'SELECT assignee_source,COUNT(*) FROM trip_tabs GROUP BY assignee_source')) \
            if 'assignee_source' in present_columns else None
    finally:
        conn.close()
    reports = Path(__file__).resolve().parents[1] / 'docs/handoff/2026-10-01'
    if args.stage == 'after':
        before = json.loads((reports / 'owner-metadata-runtime-before.json').read_text(encoding='utf-8'))
        result['original_trip_data_unchanged'] = all(result[key] == before[key] for key in
            ('trip_count', 'original_trip_fields_sha256', 'trip_history_sha256', 'trip_requests_sha256'))
    (reports / ('owner-metadata-runtime-' + args.stage + '.json')).write_bytes(
        (json.dumps(result, indent=2) + '\n').encode('utf-8'))


if __name__ == '__main__':
    main()
