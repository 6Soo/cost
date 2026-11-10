"""Import saved Agoda booking-detail API records into the unified OTA store.

Records are written by the signed-in browser procedure in
docs/specs/ota-portal-browser-collection-20261110.md, one JSON file per booking:
{"observed_at": ISO time with zone, "list": GetBookingsList entry, "detail": details response}.
Without --apply only the parsed summary is printed; nothing is written.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agoda_api_capture import parse_api_detail, records  # noqa: E402

ACCOUNT_KEY = 'aside-u0'  # The same signed-in Agoda account the page captures used.


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory', required=True)
    parser.add_argument('--store', help='unified OTA store; required with --apply')
    parser.add_argument('--account-key', default=ACCOUNT_KEY)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and not args.store:
        parser.error('--apply requires --store')
    parsed, errors = [], collections.Counter()
    for path, record in records(args.directory):
        try:
            parsed.append((record, parse_api_detail(record)))
        except (KeyError, TypeError, ValueError) as exc:
            errors[str(exc) or type(exc).__name__] += 1
    summary = {
        'records': len(parsed) + sum(errors.values()), 'parsed': len(parsed), 'errors': dict(errors),
        'status': dict(collections.Counter(fact['reservation_status'] for _, fact in parsed)),
        'payment': dict(collections.Counter(fact['payment_status'] for _, fact in parsed)),
        'inserted': 0,
    }
    # Any unreadable record stops the run before anything is written; the batch commits as one.
    if args.apply and parsed and not errors:
        from app.ota_store import OtaStore
        store = OtaStore(args.store)
        try:
            # One explicit transaction: each import_direct nests as a savepoint inside it.
            store.conn.execute('BEGIN IMMEDIATE')
            try:
                for record, fact in parsed:
                    snapshot = {'list': record['list'], 'detail': record['detail'], 'observed_at': record['observed_at']}
                    summary['inserted'] += bool(store.import_direct(
                        provider='agoda', account_key=args.account_key,
                        source_key='agoda-api:' + fact['booking_number'], snapshot=snapshot, facts=[fact]))
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
