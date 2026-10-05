"""Create source-backed review tabs on a copy or in guarded maintenance."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ledger.domain.direct_trip_schedule_authority import validate_document
from webapp.ledger_store import LedgerStore


def table_digest(conn, table):
    rows = sorted(conn.execute('SELECT * FROM ' + table).fetchall(), key=repr)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str, separators=(',', ':')).encode('utf-8')).hexdigest()


def backup(source, target):
    read = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    write = sqlite3.connect(target)
    try:
        read.backup(write)
    finally:
        write.close()
        read.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    evidence = ROOT / 'docs/handoff/2026-10-01'
    if args.apply:
        if os.environ.get('WEBLEDGER_MAINTENANCE') != 'SELECTED_TRIP_DIRECTORY':
            raise RuntimeError('MAINTENANCE_GUARD_REQUIRED')
        backup_evidence = json.loads((evidence / 'operational-backup-restore-evidence.json').read_text(encoding='utf-8'))
        backup_time = datetime.datetime.fromisoformat(backup_evidence['recorded_at'])
        age = (datetime.datetime.now(datetime.timezone.utc) - backup_time).total_seconds()
        if not 0 <= age <= 300 or not backup_evidence['live_state_unchanged']:
            raise RuntimeError('FRESH_VERIFIED_BACKUP_REQUIRED')
    validation = json.loads((evidence / 'selected-review-schedule-validation.json').read_text(encoding='utf-8'))
    artifact = Path(validation['validated_artifact'])
    data = artifact.read_bytes()
    if hashlib.sha256(data).hexdigest() != validation['validated_artifact_sha256']:
        raise RuntimeError('VALIDATED_ARTIFACT_CHANGED')
    records = validate_document(json.loads(data))
    config = json.loads(Path('D:/WebLedgerHost/config/real-review.json').read_text(encoding='utf-8-sig'))
    source_sha = hashlib.sha256(Path(config['snapshot_path']).read_bytes()).hexdigest()
    if source_sha != validation['source_sha256'] or any(r.source_sha256 != source_sha for r in records):
        raise RuntimeError('SELECTED_SOURCE_CHANGED')
    identities = [(r.starts_on.isoformat(), r.region) for r in records]
    if len(identities) != len(set(identities)):
        raise RuntimeError('EXISTING_TRIP_CREATION_WOULD_MERGE_SOURCE_IDENTITIES')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = Path('D:/WebLedgerHost/data/restore-verification') / ('trip-directory-' + stamp)
    directory.mkdir(parents=True, exist_ok=False)
    source_db = Path('D:/WebLedgerHost/data/board.sqlite')
    clone = directory / 'board.sqlite'
    if args.apply:
        clone = source_db
    else:
        backup(source_db, clone)
        backup(source_db.with_suffix('.operator.sqlite'), clone.with_suffix('.operator.sqlite'))
    production = sqlite3.connect(source_db.as_uri() + '?mode=ro', uri=True)
    before = table_digest(production, 'trip_tabs')
    store = LedgerStore(clone, seed_demo=False)
    try:
        initial = store.conn.execute('SELECT COUNT(*) FROM trip_tabs').fetchone()[0]
        for r in records:
            existing = store.conn.execute(
                'SELECT display_key,source_sha256,ends_on FROM trip_tabs WHERE starts_on=? AND destination=? AND deleted=0 AND archived=0',
                (r.starts_on.isoformat(), r.region)).fetchall()
            if any(row != (r.trip_code, r.source_sha256, r.ends_on.isoformat()) for row in existing):
                raise RuntimeError('EXISTING_TRIP_SOURCE_CONFLICT')
        for r in records:
            store.create_trip(starts_on=r.starts_on.isoformat(), ends_on=r.ends_on.isoformat(),
                              destination=r.region, display_key=r.trip_code, source_sha256=r.source_sha256,
                              client_request_id='schedule-target-' + hashlib.sha256(r.trip_code.encode('utf-8')).hexdigest(),
                              actor='owner')
        first = table_digest(store.conn, 'trip_tabs')
        first_count = store.conn.execute('SELECT COUNT(*) FROM trip_tabs').fetchone()[0]
        first_requests = store.conn.execute('SELECT COUNT(*) FROM trip_tab_requests').fetchone()[0]
        for r in records:
            store.create_trip(starts_on=r.starts_on.isoformat(), ends_on=r.ends_on.isoformat(),
                              destination=r.region, display_key=r.trip_code, source_sha256=r.source_sha256,
                              client_request_id='schedule-target-' + hashlib.sha256(r.trip_code.encode('utf-8')).hexdigest(),
                              actor='owner')
        second = table_digest(store.conn, 'trip_tabs')
        second_count = store.conn.execute('SELECT COUNT(*) FROM trip_tabs').fetchone()[0]
        second_requests = store.conn.execute('SELECT COUNT(*) FROM trip_tab_requests').fetchone()[0]
        if first != second or first_requests != second_requests:
            raise RuntimeError('TRIP_DIRECTORY_REPEAT_CHANGED_STATE')
        statuses = dict(store.conn.execute('SELECT authority_status,COUNT(*) FROM trip_tabs GROUP BY authority_status'))
        board_rows = store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0]
    finally:
        store.close()
    after = table_digest(production, 'trip_tabs')
    production.close()
    result = {
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'mode': 'OPERATIONAL_REVIEW_TARGETS' if args.apply else 'PROTECTED_COPY_ONLY', 'copy_directory': str(directory) if not args.apply else None,
        'selected_source_sha256': source_sha, 'schedule_records': len(records),
        'initial_trip_count': initial, 'first_trip_count': first_count,
        'second_trip_count': second_count, 'first_request_count': first_requests,
        'second_request_count': second_requests, 'trip_state_equal_after_repeat': first == second,
        'authority_states': statuses, 'board_rows': board_rows,
        'production_trip_state_unchanged': before == after,
        'operational_trip_targets_created': args.apply, 'operational_authority_activated': False,
        'actual_import_performed': False,
    }
    output = 'selected-trip-directory-operational.json' if args.apply else 'selected-trip-directory-copy-verification.json'
    (evidence / output).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
