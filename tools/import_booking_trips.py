"""Preview or append saved Booking.com trip reservations to the unified OTA store.

Reads the preserved trip screens (booking/details/trip-*.json) and the PAST/CANCELLED trip
lists, normalizes each booking as a direct-observation fact and appends it through
OtaStore.import_direct. Without --apply only the parsed summary is printed; nothing is written.
Re-importing the same observations is a no-op (duplicate), and a differing prior observation is
held as a conflict, never overwritten. Screen fares stay display amounts, not payment evidence.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.booking_trips_capture import parse_trip, records
from app.ota_store import OtaStore, connect_read, direct_facts, encoded

ACCOUNT_KEY = 'booking-owner'  # Direct portal observations, separate from booking mail evidence.
CONFLICT_FIELDS = ('service_start_on', 'service_end_on', 'display_amount_krw',
                   'reservation_status', 'product_type')
VOLATILE_FIELDS = ('observed_at', 'snapshot_sha256')


def _comparable(fact):
    return {k: v for k, v in fact.items() if k not in VOLATILE_FIELDS}


def plan(directory, store_path=None, account_key=ACCOUNT_KEY):
    groups = collections.defaultdict(list)
    for _path, record in records(directory):
        for fact in parse_trip(record):
            groups[fact['booking_number']].append((record, fact))
    existing = {}
    if store_path and Path(store_path).exists():
        conn = connect_read(store_path)
        try:
            for booking, fact, conflicts in direct_facts(conn):
                if booking['provider'] == 'booking' and booking['account_key'] == account_key:
                    existing[booking['booking_number']] = (fact, conflicts)
        finally:
            conn.close()
    summary = dict(records=sum(map(len, groups.values())), reservations=len(groups),
                   duplicate_input=sum(len(v) - 1 for v in groups.values()),
                   additional=0, duplicate=0, conflict=0, inserted=0)
    pending = []
    for ref, observations in sorted(groups.items()):
        conflicts = any(len({encoded(f.get(field)) for _, f in observations if f.get(field) is not None}) > 1
                        for field in CONFLICT_FIELDS)
        record, fact = max(observations, key=lambda item: item[1]['observed_at'])
        if conflicts:
            summary['conflict'] += 1
            continue
        if ref in existing:
            old, old_conflicts = existing[ref]
            # Reobservation time alone does not justify modifying an existing source.
            same = _comparable(old) == _comparable(fact)
            summary['duplicate' if same and not old_conflicts else 'conflict'] += 1
            continue
        pending.append((record, fact))
    summary['additional'] = len(pending)
    return summary, pending


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory', required=True)
    parser.add_argument('--store')
    parser.add_argument('--account-key', default=ACCOUNT_KEY)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and not args.store:
        parser.error('--apply requires --store')
    try:
        summary, pending = plan(args.directory, args.store, args.account_key)
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({'error': 'BOOKING_CAPTURE_INVALID', 'inserted': 0}))
        return 1
    if args.apply and pending:
        store = OtaStore(args.store)
        try:
            store.conn.execute('BEGIN IMMEDIATE')
            try:
                # Recheck under the write lock; another importer cannot turn an append into an overwrite.
                locked, pending = plan(args.directory, args.store, args.account_key)
                if locked != summary:
                    raise ValueError('BOOKING_IMPORT_PLAN_CHANGED')
                for record, fact in pending:
                    summary['inserted'] += bool(store.import_direct(
                        provider='booking', account_key=args.account_key,
                        source_key=fact['booking_number'], snapshot=record, facts=[fact]))
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
