"""Import saved Trip.com hotel-order details into the unified OTA store.

Records are written by the signed-in browser procedure in
docs/specs/ota-portal-browser-collection-20261110.md: one {"observed_at", "detail"} file per order
in --directory, joined with the getAllOrders list in --orders. Without --apply only the parsed
summary is printed. Any unreadable record stops the run before anything is written.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.trip_api_capture import parse_hotel_detail, records  # noqa: E402

ACCOUNT_KEY = 'trip-owner'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory', required=True)
    parser.add_argument('--orders', required=True)
    parser.add_argument('--store', help='unified OTA store; required with --apply')
    parser.add_argument('--account-key', default=ACCOUNT_KEY)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and not args.store:
        parser.error('--apply requires --store')
    parsed, errors = [], collections.Counter()
    for _path, record in records(args.directory, args.orders):
        try:
            parsed.append((record, parse_hotel_detail(record)))
        except (KeyError, TypeError, ValueError) as exc:
            errors[str(exc) or type(exc).__name__] += 1
    summary = {
        'records': len(parsed) + sum(errors.values()), 'parsed': len(parsed), 'errors': dict(errors),
        'status': dict(collections.Counter(fact['reservation_status'] for _, fact in parsed)),
        'preauthorization': dict(collections.Counter(str(fact['preauthorization_refund']) for _, fact in parsed)),
        'inserted': 0,
    }
    if args.apply and parsed and not errors:
        from app.ota_store import OtaStore
        store = OtaStore(args.store)
        try:
            store.conn.execute('BEGIN IMMEDIATE')
            try:
                for record, fact in parsed:
                    summary['inserted'] += bool(store.import_direct(
                        provider='trip', account_key=args.account_key,
                        source_key='trip-api:' + fact['booking_number'], snapshot=record, facts=[fact]))
                store.conn.commit()
            except BaseException:
                store.conn.rollback()
                summary['inserted'] = 0
                raise
        finally:
            store.close()
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
