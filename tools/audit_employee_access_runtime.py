"""Read only aggregate access state; never export employee identity fields."""
import datetime
import json
from pathlib import Path
import sqlite3


def main():
    result = {'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'read_only': True, 'identities_exported': False}
    conn = sqlite3.connect('file:D:/WebLedgerHost/data/board.sqlite?mode=ro', uri=True)
    try:
        result['counts'] = {table: conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                            for table in ('access_accounts', 'access_applications', 'access_connections',
                                          'access_reservation_persons', 'access_trip_assignments',
                                          'access_reservation_directory_head')}
        result['account_roles'] = dict(conn.execute('SELECT role, COUNT(*) FROM access_accounts GROUP BY role'))
        result['application_states'] = dict(conn.execute('SELECT status, COUNT(*) FROM access_applications GROUP BY status'))
        result['connection_states'] = dict(conn.execute('SELECT status, COUNT(*) FROM access_connections GROUP BY status'))
        result['database_integrity'] = conn.execute('PRAGMA integrity_check').fetchone()[0]
        result['trip_targets'] = {
            'total': conn.execute('SELECT COUNT(*) FROM trip_tabs').fetchone()[0],
            'available': conn.execute('SELECT COUNT(*) FROM trip_tabs WHERE deleted=0 AND archived=0').fetchone()[0],
        }
    finally:
        conn.close()
    path = Path(__file__).resolve().parents[1] / 'docs/handoff/2026-10-01/employee-access-runtime-audit.json'
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
