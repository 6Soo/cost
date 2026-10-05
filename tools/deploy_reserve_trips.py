"""기존 유지보수 실행에서 원본 보존과 재실행 검증 후 여행 동기화를 켠다."""
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.reserve_trips import sync_records, registrations
from tools.verify_operational_backup_restore import backup_database,database_state
from tools.verify_lightweight_runtime import configured_readonly_flow
from webapp.ledger_store import LedgerStore

OUT=ROOT/'.local-archive/lightweight-20261003/reserve-trip-system'


def verify_delta(original_path, current_path):
    import sqlite3
    before,after=database_state(original_path),database_state(current_path)
    allowed={'trip_tabs','trip_tab_requests','decision_events','trip_tab_history','ledger_outbox',
             'rule_process_leases','sqlite_sequence'}
    if (set(after)-set(before)-{'reserve_trip_registrations'}
            or any(after.get(t)!=v for t,v in before.items() if t not in allowed)):
        raise RuntimeError('EXISTING_DATA_CHANGED')
    with sqlite3.connect(original_path) as original, sqlite3.connect(current_path) as current:
        additions={}
        for table in allowed-{'sqlite_sequence'}:
            names=[r[1] for r in current.execute('PRAGMA table_info('+table+')')]
            old={tuple(r) for r in original.execute('SELECT * FROM '+table)}
            new={tuple(r) for r in current.execute('SELECT * FROM '+table)}
            if table=='rule_process_leases':
                old_by_id={r[0]:r for r in old}
                new_by_id={r[0]:r for r in new}
                for key,row in old_by_id.items():
                    updated=new_by_id.get(key)
                    if (not updated or row[:3]!=updated[:3] or updated[3]<row[3]
                            or (row!=updated and row[1]!=os.getpid())):
                        raise RuntimeError('EXISTING_PROCESS_LEASE_CHANGED')
                added=[r for r in new if r[0] not in old_by_id]
            else:
                if not old<=new:
                    raise RuntimeError('EXISTING_TRIP_OR_AUDIT_CHANGED')
                added=new-old
            additions[table]=[dict(zip(names,r)) for r in added]
        trip_ids={r['tab_id'] for r in additions['trip_tabs']}
        streams={'trip-'+t for t in trip_ids}
        for table in ('decision_events','ledger_outbox'):
            rows=additions[table]
            if len(rows)!=len(trip_ids) or any(r['stream_id'] not in streams or r['action']!='propose'
                    or r['actor_local_id']!='owner' for r in rows):
                raise RuntimeError('UNEXPECTED_TRIP_AUDIT_ADDED')
        for table in ('trip_tab_history','trip_tab_requests'):
            rows=additions[table]
            if len(rows)!=len(trip_ids) or any(r['tab_id'] not in trip_ids
                    or not r['client_request_id'].startswith('reserve-trip-') for r in rows):
                raise RuntimeError('UNEXPECTED_TRIP_HISTORY_ADDED')
        leases=additions['rule_process_leases']
        if len(leases)>1 or any(r['pid']!=os.getpid() for r in leases):
            raise RuntimeError('UNEXPECTED_PROCESS_LEASE_ADDED')
        old_sequence=dict(original.execute('SELECT * FROM sqlite_sequence'))
        new_sequence=dict(current.execute('SELECT * FROM sqlite_sequence'))
        expected=dict(old_sequence)
        if trip_ids:expected['trip_tab_history']=expected.get('trip_tab_history',0)+len(trip_ids)
        if expected!=new_sequence:
            raise RuntimeError('UNEXPECTED_SEQUENCE_CHANGED')


def main():
    host=Path('D:/WebLedgerHost')
    db=host/'data/board.sqlite'
    evidence=json.loads((ROOT/'docs/handoff/2026-10-01/operational-backup-restore-evidence.json').read_text(encoding='utf-8'))
    age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(evidence['recorded_at'])).total_seconds()
    if not 0<=age<=300 or not evidence['live_state_unchanged']:
        raise RuntimeError('FRESH_VERIFIED_BACKUP_REQUIRED')
    source=json.loads((OUT/'source.json').read_text(encoding='utf-8'))
    if source['source_url']!='https://reserve.foresttour.kr/api/public/ledger-trips':
        raise RuntimeError('RESERVE_SOURCE_URL_INVALID')
    records=source['records']
    before=database_state(db)
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=host/'data/backups'/('reserve-trips-'+stamp)
    backup.mkdir(parents=True,exist_ok=False)
    backup_database(db,backup/'board.sqlite')
    if database_state(backup/'board.sqlite')!=before:
        raise RuntimeError('RESTORE_VERIFICATION_FAILED')
    options_path=host/'config/card-flow.json'
    options=json.loads(options_path.read_text(encoding='utf-8'))
    authority=Path(options['trip_authority_path'])
    launcher=host/'bin/launch_web_ledger.py'
    originals={p:p.read_bytes() for p in (options_path,authority,launcher)}
    for path,body in originals.items():
        (backup/path.name).write_bytes(body)
    try:
        clone=backup/'rehearsal.sqlite'
        clone_authority=backup/'trip-authority-rehearsal.json'
        clone_authority.write_bytes(originals[authority])
        backup_database(db,clone)
        os.environ['WEBLEDGER_UNIFIED_DB']='1'
        board=LedgerStore(clone,seed_demo=False)
        try:
            rehearsal=sync_records(board,records,clone_authority,backup/'evidence')
            first=database_state(clone)
            sync_records(board,records,clone_authority,backup/'evidence')
            if first!=database_state(clone):
                raise RuntimeError('REPEATED_RESERVE_SYNC_CHANGED_DATA')
        finally:board.close()
        verify_delta(backup/'board.sqlite',clone)
        if database_state(db)!=before:
            raise RuntimeError('LIVE_DATABASE_CHANGED_DURING_REHEARSAL')
        board=LedgerStore(db,seed_demo=False)
        try:
            result=sync_records(board,records,authority,host/'data/evidence')
            if any(result[k]!=rehearsal[k] for k in ('created','linked','held')):
                raise RuntimeError('OPERATIONAL_TRIP_SYNC_DIFFERS')
            verify_delta(backup/'board.sqlite',db)
            result.update(registered_trips=len(registrations(board)),total_trips=len(board.list_trips()),
                          new_cost_entries=0,backup=str(backup),repeat_verified=True,existing_data_preserved=True)
        finally:board.close()
        flow=configured_readonly_flow(db)
        try:
            if not all(flow.trip_valid(t['tab_id']) for t in flow.board.list_trips()):
                raise RuntimeError('REGISTERED_TRIP_AUTHORITY_INVALID')
        finally:flow.board.conn.close()
        options['reserve_trip_sync']=True
        options_path.write_text(json.dumps(options,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copy2(ROOT/'tools/launch_web_ledger.py',launcher)
        result.update(status='deployed',schedule='daily_midnight',timezone='Asia/Seoul')
        (OUT/'applied.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('RESERVE_TRIP_SYNC_DEPLOYED')
    except Exception:
        backup_database(backup/'board.sqlite',db)
        for path,body in originals.items():path.write_bytes(body)
        if database_state(db)!=before:raise RuntimeError('RESERVE_TRIP_ROLLBACK_FAILED')
        raise


if __name__=='__main__':
    try:main()
    except Exception as exc:
        (OUT/'failure.json').write_text(json.dumps({'type':type(exc).__name__,'code':str(exc)},ensure_ascii=False),encoding='utf-8')
        print('RESERVE_TRIP_SYNC_DEPLOYMENT_FAILED:'+type(exc).__name__)
        raise SystemExit(2) from None
