"""Preview/apply the owner-authorized inference policy with offline backup/restore gates.

No source text or row identifiers are printed. No new ledger entry, financial link,
Google write, source import, schema change, or authentication change is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import automatic_classification as policy
from app.db import StoreError


def load_context(conn, host):
    from app import Pipeline
    from app.db import Store
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    from webapp.card_classification_completion import context
    options = json.loads((host / 'config/card-flow.json').read_text(encoding='utf-8-sig'))
    os.environ['WEBLEDGER_UNIFIED_DB'] = '1'
    os.environ['WEBLEDGER_TRIP_AUTHORITY'] = options['trip_authority_path']
    os.environ['WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT'] = str(host / 'data/google-authority/snapshot.json')
    os.environ['WEBLEDGER_GOOGLE_LEDGER_ROWS'] = str(host / 'data/google-authority/rows.json')
    # A read facade avoids constructor schema, process-lease and seed writes.
    board = LedgerStore.__new__(LedgerStore)
    board.conn, board.path, board._lock = conn, host / 'data/board.sqlite', threading.RLock()
    board._card_pipeline = Pipeline(Store(conn, schema_policy='require'))
    return context(CardFlow(board))


def counts(conn):
    eligible = (" FROM transactions t WHERE t.classification_state!='preserved' "
        "AND COALESCE(t.duplicate_of,'')='' AND COALESCE(t.conflict_reason,'')='' "
        "AND COALESCE(t.parse_error,'')='' "
        "AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
        "AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e WHERE e.transaction_id=t.transaction_id AND e.excluded=1)")
    result = {name: conn.execute('SELECT COUNT(*)'+eligible+predicate).fetchone()[0] for name,predicate in (
        ('unclassified_purchases', " AND t.transaction_direction='purchase' AND (t.classification_state!='classified' OR COALESCE(t.item,'')='')"),
        ('unclassified_all_directions', " AND (t.classification_state!='classified' OR COALESCE(t.item,'')='')"),
        ('purchase_without_trip', " AND t.transaction_direction='purchase' AND COALESCE(t.trip_id,'')='' AND COALESCE(t.display_tab_id,'') IN ('','unclassified') AND t.item!='분기 기타비용'"),
        ('automatic_purchase_without_trip', " AND t.transaction_direction='purchase' AND COALESCE(t.trip_id,'')='' AND COALESCE(t.display_tab_id,'') IN ('','unclassified') AND t.item!='분기 기타비용' AND t.decided_at IS NULL AND COALESCE(t.classification_source,'') NOT IN ('user_decision','user_exception','owner_booking') AND NOT EXISTS(SELECT 1 FROM review_decisions d WHERE d.transaction_id=t.transaction_id) AND NOT EXISTS(SELECT 1 FROM board_manual_overrides b WHERE b.row_id='card-'||t.transaction_id)"))}
    result['historical_purchase_without_trip'] = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE classification_state='classified' "
        "AND transaction_direction='purchase' AND COALESCE(trip_id,'')='' "
        "AND COALESCE(display_tab_id,'') IN ('','unclassified') "
        "AND COALESCE(classification_basis,'') LIKE '%등록된 유효 여행 없음%'").fetchone()[0]
    return result


def protected_state(conn):
    """Compare everything except the explicitly authorized classification columns."""
    result = {}
    allowed = {'transactions': set(policy.FIELDS) | {'revision'},
               'ledger_entries': {'item','display_tab_id','trip_id'},
               'board_rows': {'display_tab_id','revision','payload_json'}}
    tables = {'transactions','ledger_entries','board_rows','review_decisions',
              'transaction_review_holds','transaction_company_exclusions','board_manual_overrides'}
    tables.update(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if 'link' in r[0] or 'group_pin' in r[0])
    for table in sorted(tables):
        quoted = '"'+table.replace('"','""')+'"'
        columns = [r[1] for r in conn.execute('PRAGMA table_info('+quoted+')')]
        values = []
        for raw in conn.execute('SELECT * FROM '+quoted):
            row = dict(zip(columns,raw))
            if table == 'board_rows':
                payload = json.loads(row.get('payload_json') or '{}')
                for field in ('item','display_tab_id','classification_state'):
                    payload.pop(field,None)
                row['protected_payload'] = payload
            values.append({k:v for k,v in row.items() if k not in allowed.get(table,set())})
        result[table] = hashlib.sha256(repr(sorted(values,key=repr)).encode()).hexdigest()
    return result


def require_offline_backup(host, evidence, db):
    from tools.verify_operational_backup_restore import database_state
    saved = json.loads(evidence.read_text(encoding='utf-8-sig'))
    for key in ('live_state_unchanged','all_database_tables_and_columns_compared','restored_review_binding_equal'):
        if saved.get(key) is not True:
            raise ValueError('BACKUP_RESTORE_NOT_VERIFIED')
    if not 0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(saved['recorded_at'])).total_seconds() < 3600:
        raise ValueError('BACKUP_NOT_FRESH')
    backup = Path(saved['backup_directory']).resolve()
    if not backup.is_relative_to((host/'data/backups').resolve()):
        raise ValueError('BACKUP_LOCATION_INVALID')
    manifest = json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
    if manifest['databases']['board.sqlite'] != database_state(db):
        raise ValueError('BACKUP_SOURCE_CHANGED')
    script = "$t=@(Get-ScheduledTask -TaskName WebLedger-Board,WebLedger-SourceRefresh);if($t.Count -ne 2 -or @($t|Where-Object State -eq Running).Count -ne 0){exit 1};if(@(Get-NetTCPConnection -LocalPort 8751 -State Listen -ErrorAction SilentlyContinue).Count -ne 0){exit 2};exit 0"
    check = subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True)
    if check.returncode:
        raise ValueError('WRITERS_NOT_OFFLINE')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root',type=Path,default=Path('D:/WebLedgerHost'))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-digest')
    parser.add_argument('--backup-evidence',type=Path)
    parser.add_argument('--report',type=Path)
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    db = host/'data/board.sqlite'
    try:
        if args.apply:
            if not args.expected_digest or not args.backup_evidence:
                raise ValueError('PREVIEW_AND_BACKUP_REQUIRED')
            require_offline_backup(host,args.backup_evidence,db)
        connection = sqlite3.connect(db.as_uri()+'?mode='+('rw' if args.apply else 'ro'),uri=True,isolation_level=None)
        try:
            trips, nets = load_context(connection,host)
            before = counts(connection)
            connection.execute('BEGIN IMMEDIATE' if args.apply else 'BEGIN')
            preview = policy.plan(connection,trips,nets=nets)
            if args.apply and args.expected_digest != preview['digest']:
                raise ValueError('CLASSIFICATION_PREVIEW_STALE')
            if args.apply:
                target = connection
            else:
                target = sqlite3.connect(':memory:',isolation_level=None)
                connection.backup(target)
            try:
                protected = protected_state(target)
                result = policy.apply(target,preview,trips,nets=nets)
                after = counts(target)
                if protected_state(target) != protected:
                    raise ValueError('SOURCE_OR_USER_DATA_CHANGED')
                if after['unclassified_purchases'] or after['unclassified_all_directions']:
                    raise ValueError('UNCLASSIFIED_CARDS_REMAIN')
                if trips and after['purchase_without_trip'] > after['historical_purchase_without_trip']:
                    raise ValueError('UNASSIGNED_CARDS_REMAIN')
                if policy.plan(target,trips,nets=nets)['summary']['to_classify']:
                    raise ValueError('CLASSIFICATION_REPEAT_NOT_NOOP')
                if args.apply:
                    connection.commit()
            finally:
                if target is not connection:
                    target.close()
            report = {'status':'APPLIED' if args.apply else 'PREVIEW','digest':preview['digest'],
                'before':before,'after':after,**result,'protected_source_and_user_data_unchanged':True,
                'new_ledger_entries':0,'new_financial_links':0,'google_writes':0}
        finally:
            connection.close()
        if args.report:
            try:
                args.report.write_text(json.dumps(report,indent=2),encoding='utf-8')
            except OSError:
                report['report_file_written'] = False
        print(json.dumps(report))
        return 0
    except (OSError,ValueError,KeyError,sqlite3.Error,StoreError) as exc:
        code = exc.code if isinstance(exc,StoreError) else str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else type(exc).__name__
        print(json.dumps({'status':'FAILED','code':code}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
