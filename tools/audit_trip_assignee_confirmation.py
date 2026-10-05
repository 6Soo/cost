"""Read-only verification of the explicitly authorized trip metadata edits."""
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3


def main():
    reports = Path(__file__).resolve().parents[1] / 'docs/handoff/2026-10-01'
    baseline = json.loads((reports / 'owner-trip-confirmation-before.json').read_text(encoding='utf-8'))
    columns = ('tab_id', 'display_key', 'destination', 'starts_on', 'ends_on',
               'event_year', 'tab_kind', 'authority_status', 'source_sha256',
               'sort_order', 'prepared_on', 'prepared_by_name', 'archived',
               'deleted', 'revision')
    conn = sqlite3.connect('file:D:/WebLedgerHost/data/board.sqlite?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        profile = conn.execute('SELECT assignee_name FROM owner_profile').fetchone()
        rows = conn.execute('SELECT * FROM trip_tabs ORDER BY tab_id').fetchall()
        restored = []
        changes_allowed = True
        matched = 0
        sources = {}
        for row in rows:
            matched += int(row['prepared_by_name'] == profile['assignee_name'])
            sources[row['assignee_source']] = sources.get(row['assignee_source'], 0) + 1
            history = conn.execute('SELECT prev_json,new_json FROM trip_tab_history WHERE tab_id=? AND revision=?',
                                   (row['tab_id'], row['revision'])).fetchone()
            previous = json.loads(history['prev_json'])
            current = json.loads(history['new_json'])
            changed = {key for key in set(previous) | set(current) if previous.get(key) != current.get(key)}
            changes_allowed &= changed <= {'prepared_by_name', 'assignee_source', 'revision'}
            restored.append([previous.get(key) if key in {'prepared_by_name', 'revision'} else row[key]
                             for key in columns])
        old_digest = hashlib.sha256(json.dumps(restored, ensure_ascii=False, separators=(',', ':'),
                                                sort_keys=True).encode('utf-8')).hexdigest()
        result = dict(recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      read_only=True, identities_exported=False, trip_count=len(rows),
                      assignees_match_profile=matched, assignee_source_counts=sources,
                      latest_changes_only_authorized_metadata=bool(changes_allowed),
                      reconstructed_previous_rows_match_baseline=old_digest == baseline['original_trip_fields_sha256'],
                      database_integrity=conn.execute('PRAGMA integrity_check').fetchone()[0],
                      cost_counts={table: conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                                   for table in ('board_rows', 'board_requests', 'source_fact_rows', 'source_fact_applies')})
    finally:
        conn.close()
    (reports / 'owner-trip-confirmation-after.json').write_bytes((json.dumps(result, indent=2) + '\n').encode('utf-8'))


if __name__ == '__main__':
    main()
