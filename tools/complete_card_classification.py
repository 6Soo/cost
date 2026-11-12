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


def read_flow(conn, host):
    from app import Pipeline
    from app.db import Store
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    options = json.loads((host / 'config/card-flow.json').read_text(encoding='utf-8-sig'))
    os.environ['WEBLEDGER_UNIFIED_DB'] = '1'
    os.environ['WEBLEDGER_TRIP_AUTHORITY'] = options['trip_authority_path']
    os.environ['WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT'] = str(host / 'data/google-authority/snapshot.json')
    os.environ['WEBLEDGER_GOOGLE_LEDGER_ROWS'] = str(host / 'data/google-authority/rows.json')
    os.environ['WEBLEDGER_OTA_REVIEW_DB'] = str(host / 'data/ota-review/ota-review.sqlite')
    # A read facade avoids constructor schema, process-lease and seed writes.
    board = LedgerStore.__new__(LedgerStore)
    board.conn, board.path, board._lock = conn, host / 'data/board.sqlite', threading.RLock()
    board._card_pipeline = Pipeline(Store(conn, schema_policy='require'))
    return CardFlow(board)


def load_context(conn, host):
    from webapp.card_classification_completion import context
    return context(read_flow(conn, host))


def load_review_evidence(conn, host, trips, cache_path=None, *, report=None):
    """Read registered booking/mail sources locally; publish aggregate counts only.

    These facts guide expense attribution. They never create financial links,
    confirm a refund, publish customer text, or modify a snapshot/review store.
    """
    from collections import defaultdict
    from app.provisional_assignment import ota_service_period_candidate
    if report is not None and cache_path is not None:
        raise ValueError('SUPPLIED_REPORT_CACHE_NOT_SUPPORTED')
    flow = read_flow(conn, host) if report is None else None
    stamp = None
    if cache_path is not None:
        cache_path = cache_path.resolve()
        if not cache_path.is_relative_to((host/'data/backups').resolve()):
            raise ValueError('EVIDENCE_CACHE_LOCATION_INVALID')
        from app.ota_sources import content_stamp
        sources = flow._ota_sources()
        watched = [sources.get('manifest_path'), *sources['reference_documents']]
        for directory in sources['mail_directories']:
            watched += list(Path(directory).glob('gmail*.json')) + [Path(directory)/'collection.json']
        for database in sources['portal_databases']:
            watched += [database, Path(str(database)+'-wal')]
        stamps = [content_stamp(Path(path)) for path in watched if path and Path(path).is_file()]
        from tools.verify_operational_backup_restore import database_state
        review_db = host/'data/ota-review/ota-review.sqlite'
        inputs = [protected_state(conn), trips, sources.get('missing'), stamps,
                  database_state(review_db) if review_db.is_file() else None]
        stamp = hashlib.sha256(json.dumps(inputs,sort_keys=True,default=str).encode()).hexdigest()
        if cache_path.is_file():
            saved = json.loads(cache_path.read_text(encoding='utf-8'))
            if saved.get('stamp') != stamp:
                raise ValueError('EVIDENCE_CACHE_STALE')
            return saved['evidence'], saved['summary']
    report = (flow._compute_ota_report() or {}) if report is None else report
    from app.closed_period import formal_facts
    completed_evidence = formal_facts(report.get('matches', []), trips)
    rows = {row['transaction_id']: row for row in policy._read(conn)}
    candidates = defaultdict(list)
    for fact in report.get('matches', []):
        row = rows.get(fact.get('transaction_id'))
        if (not row or row['source_hash'] != fact.get('source_hash')
                or row['transaction_direction'] != 'purchase'
                or fact.get('reservation_status') == 'cancelled'
                or fact.get('period_conflict') or fact.get('service_period_conflict')):
            continue
        period = fact.get('period') or fact.get('service_period')
        if not isinstance(period, dict):
            continue
        options = ota_service_period_candidate({'service_period': period}, trips)
        if len(options) == 1:
            candidates[row['transaction_id']].append(dict(
                source_hash=row['source_hash'], trip_id=options[0]['trip_id'],
                item=fact.get('item') or '',
                basis='보관 예약 이용기간 ' + period['starts_on'] + '~' + period['ends_on'] + ' · 비용 귀속 추론이며 결제 연결 미확정',
                evidence_digest=hashlib.sha256(json.dumps(fact, sort_keys=True, default=str).encode()).hexdigest()))
            candidates[row['transaction_id']][-1].update(
                service_period=dict(period),
                formal_link=row['transaction_id'] in completed_evidence)
    evidence = {}
    conflicts = 0
    for tid, options in candidates.items():
        if len({option['trip_id'] for option in options}) != 1:
            conflicts += 1
            continue
        evidence[tid] = sorted(options, key=lambda option: option['evidence_digest'])[0]
    summary = {'matched_facts': len(report.get('matches', [])),
                      'service_period_evidence': len(evidence), 'conflicting_periods': conflicts,
                      'source_errors': len(report.get('ota_source_errors', [])),
                      'missing_sources': len((report.get('ota_source_inventory') or {}).get('missing', []))}
    if cache_path is not None:
        saved = dict(stamp=stamp,evidence=evidence,summary=summary)
        temporary = cache_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(saved,sort_keys=True),encoding='utf-8')
        temporary.replace(cache_path)
    return evidence, summary


def counts(conn, trips=(), evidence=None):
    from app.closed_period import excluded, manual_ids, open_scope
    manual = manual_ids(conn)
    completed = [r['transaction_id'] for r in policy._read(conn)
                 if not open_scope(r,trips) or excluded(r, trips, evidence=(evidence or {}).get(r['transaction_id']),
                             manual=r['transaction_id'] in manual)]
    eligible = (" FROM transactions t WHERE 1=1 "
        "AND t.transaction_id NOT IN (SELECT value FROM json_each(?)) "
        "AND COALESCE(t.duplicate_of,'')='' AND COALESCE(t.conflict_reason,'')='' "
        "AND COALESCE(t.parse_error,'')='' "
        "AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
        "AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e WHERE e.transaction_id=t.transaction_id AND e.excluded=1)")
    result = {name: conn.execute('SELECT COUNT(*)'+eligible+predicate, (json.dumps(completed),)).fetchone()[0] for name,predicate in (
        ('unclassified_purchases', " AND t.transaction_direction='purchase' AND (t.classification_state!='classified' OR COALESCE(t.item,'')='')"),
        ('unclassified_all_directions', " AND (t.classification_state!='classified' OR COALESCE(t.item,'')='')"),
        ('purchase_without_trip', " AND t.transaction_direction='purchase' AND COALESCE(t.trip_id,'')='' AND COALESCE(t.display_tab_id,'') IN ('','unclassified') AND t.item!='분기 기타비용'"),
        ('automatic_purchase_without_trip', " AND t.transaction_direction='purchase' AND COALESCE(t.trip_id,'')='' AND COALESCE(t.display_tab_id,'') IN ('','unclassified') AND t.item!='분기 기타비용' AND t.decided_at IS NULL AND COALESCE(t.classification_source,'') NOT IN ('user_decision','user_exception','owner_booking') AND NOT EXISTS(SELECT 1 FROM review_decisions d WHERE d.transaction_id=t.transaction_id) AND NOT EXISTS(SELECT 1 FROM board_manual_overrides b WHERE b.row_id='card-'||t.transaction_id)"))}
    return result


def load_completed_period_evidence(conn, host, trips):
    """Offline tools revalidate formal links from registered current sources."""
    from app.closed_period import completed_period
    dates = conn.execute('SELECT transaction_id,approval_date,posting_date FROM transactions').fetchall()
    completed = {r[0] for r in dates if completed_period(dict(zip(('approval_date','posting_date'),r[1:])))}
    if not completed:
        return {}
    from tools.repair_dist141_provenance import canonical_report
    evidence,_ = load_review_evidence(conn,host,trips,report=canonical_report(conn,host))
    return {k:v for k,v in evidence.items() if k in completed and v.get('formal_link')}


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
                for field in ('item','display_tab_id','classification_state',
                              'classification_source','classification_basis','revision'):
                    payload.pop(field,None)
                row['protected_payload'] = payload
            values.append({k:v for k,v in row.items() if k not in allowed.get(table,set())})
        result[table] = hashlib.sha256(repr(sorted(values,key=repr)).encode()).hexdigest()
    return result


def require_writers_offline(port=8751):
    """Refuse writes while a managed writer task runs or the Board port listens.

    Shared single-writer gate for offline tools. A non-zero PowerShell exit (a
    task is Running, the task pair is missing, or the port has a listener)
    raises ValueError('WRITERS_NOT_OFFLINE').
    """
    script = ("$t=@(Get-ScheduledTask -TaskName WebLedger-Board,WebLedger-SourceRefresh);"
              "if($t.Count -ne 2 -or @($t|Where-Object State -eq Running).Count -ne 0){exit 1};"
              "if(@(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue).Count -ne 0){exit 2};exit 0") % port
    check = subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True)
    if check.returncode:
        raise ValueError('WRITERS_NOT_OFFLINE')


def require_offline_backup(host, evidence, db, *, isolated_copy=False):
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
    if isolated_copy:
        live = Path('D:/WebLedgerHost/data/board.sqlite')
        if (host.resolve() == Path('D:/WebLedgerHost').resolve()
                or db.resolve().parent != (host/'data').resolve()
                or (live.exists() and os.path.samefile(db,live))):
            raise ValueError('ISOLATED_COPY_REQUIRED')
        return
    require_writers_offline()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root',type=Path,default=Path('D:/WebLedgerHost'))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-digest')
    parser.add_argument('--backup-evidence',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--reconsider', action='store_true',
                        help='Revisit automatic classifications using existing booking evidence; preserve manual decisions')
    parser.add_argument('--evidence-cache',type=Path,
                        help='Optional source-bound derived evidence cache under protected host backups')
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
            evidence, evidence_summary = load_review_evidence(connection,host,trips,args.evidence_cache) if args.reconsider else ({}, {})
            before = counts(connection, trips, evidence)
            connection.execute('BEGIN IMMEDIATE' if args.apply else 'BEGIN')
            options = dict(nets=nets, reconsider=args.reconsider, evidence=evidence)
            preview = policy.plan(connection,trips,**options)
            if args.apply and args.expected_digest != preview['digest']:
                raise ValueError('CLASSIFICATION_PREVIEW_STALE')
            if args.apply:
                target = connection
            else:
                target = sqlite3.connect(':memory:',isolation_level=None)
                connection.backup(target)
            try:
                protected = protected_state(target)
                result = policy.apply(target,preview,trips,**options)
                after = counts(target, trips, evidence)
                if protected_state(target) != protected:
                    raise ValueError('SOURCE_OR_USER_DATA_CHANGED')
                if after['unclassified_purchases'] or after['unclassified_all_directions']:
                    raise ValueError('UNCLASSIFIED_CARDS_REMAIN')
                if trips and after['purchase_without_trip']:
                    raise ValueError('UNASSIGNED_CARDS_REMAIN')
                if policy.plan(target,trips,**options)['summary']['to_classify']:
                    raise ValueError('CLASSIFICATION_REPEAT_NOT_NOOP')
                if args.apply:
                    connection.commit()
            finally:
                if target is not connection:
                    target.close()
            report = {'status':'APPLIED' if args.apply else 'PREVIEW','digest':preview['digest'],
                'before':before,'after':after,**result,'protected_source_and_user_data_unchanged':True,
                'new_ledger_entries':0,'new_financial_links':0,'google_writes':0,
                'evidence_review': evidence_summary}
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
