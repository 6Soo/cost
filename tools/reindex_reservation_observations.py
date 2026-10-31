"""Preview/add derived forest reservation observations; preserve every original table.

Apply requires a fresh full SQLite backup and a separate verified restore matching
the locked source. Only the additive observation schema and its rows may change.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.ota_store import DDL, OtaStore

TABLE = 'ota_reservation_observations'


def states(conn):
    result = {}
    for table, schema in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        quoted='"'+table.replace('"','""')+'"'
        digest=hashlib.sha256(str(schema).encode())
        count=0
        for row in conn.execute('SELECT * FROM '+quoted+' ORDER BY rowid'):
            digest.update(repr(tuple(row)).encode()); count+=1
        result[table] = dict(rows=count,sha256=digest.hexdigest())
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def connect(path,write=False):
    conn=sqlite3.connect(Path(path).resolve().as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,isolation_level=None,timeout=30)
    conn.row_factory=sqlite3.Row
    return conn


def apply(conn,expected_digest,backup,restored):
    live=Path(conn.execute('PRAGMA database_list').fetchone()[2]).resolve()
    if not backup or not restored or len({live,Path(backup).resolve(),Path(restored).resolve()})!=3:
        raise ValueError('RESERVATION_INDEX_DISTINCT_BACKUP_RESTORE_REQUIRED')
    conn.execute('BEGIN IMMEDIATE')
    try:
        before=states(conn)
        if fingerprint(before)!=expected_digest:
            raise ValueError('RESERVATION_INDEX_SOURCE_CHANGED')
        for path in (backup,restored):
            if not path or not Path(path).is_file() or not 0 <= datetime.now(timezone.utc).timestamp()-Path(path).stat().st_mtime < 3600:
                raise ValueError('RESERVATION_INDEX_FRESH_RESTORE_REQUIRED')
            with closing(connect(path)) as copy:
                if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or states(copy)!=before:
                    raise ValueError('RESERVATION_INDEX_RESTORE_MISMATCH')
        observation_schema=re.search(r'CREATE TABLE IF NOT EXISTS '+TABLE+r'\(.*?;',DDL,re.S).group(0)
        conn.execute(observation_schema)
        previous=[tuple(r) for r in conn.execute('SELECT * FROM '+TABLE)]
        store=OtaStore.__new__(OtaStore); store.conn=conn
        inserted=store.rebuild_reservation_observations()
        after=states(conn)
        if {k:v for k,v in before.items() if k!=TABLE}!={k:v for k,v in after.items() if k!=TABLE}:
            raise ValueError('RESERVATION_INDEX_ORIGINAL_CHANGED')
        current={tuple(r) for r in conn.execute('SELECT * FROM '+TABLE)}
        if not set(previous)<=current or len(current)-len(previous)!=inserted:
            raise ValueError('RESERVATION_INDEX_APPEND_MISMATCH')
        total_changes=conn.total_changes
        if store.rebuild_reservation_observations()!=0 or conn.total_changes!=total_changes:
            raise ValueError('RESERVATION_INDEX_REPLAY_WRITES')
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('RESERVATION_INDEX_INTEGRITY')
        distinct=conn.execute('SELECT count(DISTINCT observation_id) FROM '+TABLE).fetchone()[0]
        conn.commit()
        return dict(status='APPLIED',inserted_evidence_rows=inserted,distinct_observations=distinct,
            original_tables_unchanged=True,existing_observations_retained=True,replay_writes=0,
            backup_and_separate_restore_verified=True,new_financial_links=0,source_digest=expected_digest,
            after_digest=fingerprint(after))
    except BaseException:
        conn.rollback();raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--apply',action='store_true')
    p.add_argument('--expected-digest');p.add_argument('--backup-file',type=Path);p.add_argument('--restored-file',type=Path)
    p.add_argument('--report',type=Path)
    args=p.parse_args()
    if args.apply and (not args.expected_digest or not args.backup_file or not args.restored_file
            or len({args.db.resolve(),args.backup_file.resolve(),args.restored_file.resolve()})!=3):
        p.error('RESERVATION_INDEX_DISTINCT_BACKUP_RESTORE_REQUIRED')
    conn=connect(args.db,args.apply)
    try:
        if args.apply:
            result=apply(conn,args.expected_digest,args.backup_file,args.restored_file)
        else:
            conn.execute('BEGIN')
            before=states(conn)
            result=dict(status='PREVIEW',source_digest=fingerprint(before),
                        existing_evidence_rows=before.get(TABLE,{}).get('rows',0),writes=conn.total_changes)
            conn.rollback()
    finally:conn.close()
    result['recorded_at']=datetime.now(timezone.utc).isoformat()
    if args.report:args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
