"""Correct bulk record-batch owner confirmation stamps: count-only preview, digest/backup-gated apply, audited restore."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from app import bulk_confirmation_repair as repair
from app.db import StoreError
from app.ota_sources import OtaSourcesError
from tools.complete_card_classification import load_context, require_offline_backup
from tools.repair_dist141_provenance import emit_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, required=True)
    parser.add_argument('--year', type=int)
    parser.add_argument('--quarter', type=int, choices=range(1, 5))
    parser.add_argument('--min-batch', type=int, default=5)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    parser.add_argument('--backup-evidence', type=Path)
    parser.add_argument('--isolated-copy', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    db = host / 'data/board.sqlite'
    try:
        if not args.restore:
            if args.year is None or args.quarter is None:
                raise ValueError('SCOPE_REQUIRED')
            if (args.year, args.quarter) < repair.MIN_SCOPE:
                raise ValueError('INVALID_SCOPE')
            if args.min_batch < 1:
                raise ValueError('INVALID_MIN_BATCH')
        with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as reader:
            prior = repair.replay(reader, args.request_id) if not args.restore else None
        if prior:
            if args.expected_digest and args.expected_digest != prior['digest']:
                raise ValueError('BULK_CONFIRMATION_REQUEST_CONFLICT')
            return emit_report(dict(prior, status='REPLAYED', replay=True, applied_this_run=0, to_correct=0), args.report)
        if args.apply:
            if not args.expected_digest or not args.backup_evidence:
                raise ValueError('PREVIEW_AND_BACKUP_REQUIRED')
            require_offline_backup(host, args.backup_evidence, db, isolated_copy=args.isolated_copy)
        with closing(sqlite3.connect(db.as_uri() + '?mode=' + ('rw' if args.apply else 'ro'), uri=True, isolation_level=None)) as conn:
            if args.restore:
                plan = repair.restore_preview(conn, args.request_id)
            else:
                trips, _ = load_context(conn, host)
                plan = repair.preview(conn, trips, year=args.year, quarter=args.quarter, min_batch=args.min_batch)
            if args.apply and plan['digest'] != args.expected_digest:
                raise ValueError('BULK_CONFIRMATION_PREVIEW_STALE')
            # Preview never runs a repair, even on an in-memory database.
            result = (repair.restore(conn, plan, args.request_id) if args.restore else
                      repair.apply(conn, plan, trips, request_id=args.request_id,
                                   year=args.year, quarter=args.quarter, min_batch=args.min_batch)) if args.apply else plan['summary']
            report = dict(status='APPLIED' if args.apply else 'PREVIEW', digest=plan['digest'], **result)
        return emit_report(report, args.report)
    except (OSError, ValueError, KeyError, sqlite3.Error, StoreError, OtaSourcesError) as exc:
        code = (exc.code if isinstance(exc, (StoreError, OtaSourcesError)) else str(exc)
                if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__)
        print(json.dumps(dict(status='FAILED', code=code)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
