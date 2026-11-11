"""Preview or append saved forest portal reservations to the unified OTA store."""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.forest_portal_capture import records
from app.ota_store import OtaStore, connect_read, direct_facts, encoded


def plan(directory, observed_at, store_path=None, account_key='forest-owner'):
    groups = collections.defaultdict(list)
    for raw, fact in records(directory, observed_at):
        groups[fact['booking_number']].append((raw, fact))
    existing = {}
    if store_path and Path(store_path).exists():
        conn = connect_read(store_path)
        try:
            for booking, fact, conflicts in direct_facts(conn):
                if booking['provider'] == 'forest' and booking['account_key'] == account_key:
                    existing[booking['booking_number']] = (fact, conflicts)
        finally:
            conn.close()
    summary = dict(records=sum(map(len, groups.values())), reservations=len(groups),
                   duplicate_input=sum(len(v)-1 for v in groups.values()),
                   additional=0, duplicate=0, conflict=0, inserted=0)
    pending = []
    for ref, observations in sorted(groups.items()):
        conflicts = any(len({encoded(f.get(field)) for _, f in observations if f.get(field) is not None}) > 1
                        for field in ('service_start_on', 'service_end_on', 'amount_krw', 'paid_on'))
        fact = dict(max((f for _, f in observations), key=lambda f: (
            f['reservation_status'] == 'cancelled', f['payment_status'] == 'paid',
            f['reservation_status'] == 'completed')))
        if conflicts:
            summary['conflict'] += 1
            continue
        if ref in existing:
            old, old_conflicts = existing[ref]
            # Reobservation time alone does not justify modifying an existing source.
            same = {k:v for k,v in old.items() if k != 'observed_at'} == {k:v for k,v in fact.items() if k != 'observed_at'}
            summary['duplicate' if same and not old_conflicts else 'conflict'] += 1
            continue
        pending.append(({'observations':[raw for raw, _ in observations]}, fact))
    summary['additional'] = len(pending)
    return summary, pending


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--observed-at', required=True, help='capture time including timezone')
    parser.add_argument('--store')
    parser.add_argument('--account-key', default='forest-owner')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and not args.store:
        parser.error('--apply requires --store')
    try:
        summary, pending = plan(args.directory, args.observed_at, args.store, args.account_key)
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({'error':'FOREST_CAPTURE_INVALID', 'inserted':0}))
        return 1
    if args.apply and pending:
        store = OtaStore(args.store)
        try:
            store.conn.execute('BEGIN IMMEDIATE')
            try:
                # Recheck under the write lock; another importer cannot turn an append into an overwrite.
                locked, pending = plan(args.directory, args.observed_at, args.store, args.account_key)
                if locked != summary:
                    raise ValueError('FOREST_IMPORT_PLAN_CHANGED')
                for snapshot, fact in pending:
                    summary['inserted'] += bool(store.import_direct(provider='forest', account_key=args.account_key,
                        source_key=fact['booking_number'], snapshot=snapshot, facts=[fact]))
                store.conn.commit()
            except BaseException:
                store.conn.rollback()
                raise
        finally:
            store.close()
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
