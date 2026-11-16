"""Apply a private AI quarter-review manifest: count-only preview, digest/backup-gated apply, audited restore. 쓰는 DB는 board.sqlite 하나라 백업 확인은 `verify_operational_backup_restore.py --scope board`로 충분하다."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from app import ai_review_repair as repair
from app.db import StoreError
from app.ota_sources import OtaSourcesError
from tools.complete_card_classification import load_context, require_offline_backup
from tools.repair_dist141_provenance import emit_report


def load_manifest(path):
    manifest = Path(path).resolve()
    # Customer identifiers never live inside the repository working folder.
    if manifest.is_relative_to(REPO_ROOT):
        raise ValueError('MANIFEST_IN_REPOSITORY')
    return json.loads(manifest.read_text(encoding='utf-8-sig'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--source-review', type=Path,
                        help='Protected original-bound source recheck directory (PROC-073)')
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
        manifest = None
        if not args.restore:
            if not args.manifest:
                raise ValueError('MANIFEST_REQUIRED')
            manifest = load_manifest(args.manifest)
        with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as reader:
            prior = repair.replay(reader, args.request_id) if not args.restore else None
        if prior:
            if args.expected_digest and args.expected_digest != prior['digest']:
                raise ValueError('AI_REVIEW_REQUEST_CONFLICT')
            return emit_report(dict(prior, status='REPLAYED', replay=True, applied_this_run=0, to_apply=0), args.report)
        if args.apply:
            if not args.expected_digest or not args.backup_evidence:
                raise ValueError('PREVIEW_AND_BACKUP_REQUIRED')
            # A drained gateway may remain paused throughout offline maintenance.
            # Its explicit backend is still the port the writer-offline gate must
            # check; never fall back to a hard-coded port when a route exists.
            route_path = host / 'config/ledger-route.json'
            board_port = None
            if not args.isolated_copy and route_path.exists():
                from tools.ledger_gateway import read_route
                board_port = read_route(route_path)['port']
                if type(board_port) is not int or board_port not in (8751, 8752):
                    raise ValueError('ROUTE_PORT_INVALID')
            require_offline_backup(host, args.backup_evidence, db,
                                   isolated_copy=args.isolated_copy, board_port=board_port)
        trips = None
        with closing(sqlite3.connect(db.as_uri() + '?mode=' + ('rw' if args.apply else 'ro'), uri=True, isolation_level=None)) as conn:
            if args.restore:
                plan = repair.restore_preview(conn, args.request_id)
            else:
                trips, _ = load_context(conn, host)
                evidence = None
                if args.source_review:
                    from app.source_recheck import load
                    if args.source_review.resolve().is_relative_to(REPO_ROOT):
                        raise ValueError('MANIFEST_IN_REPOSITORY')
                    evidence = load(conn, trips, args.source_review)
                plan = repair.preview(conn, trips, manifest, evidence=evidence)
            if args.apply and plan['digest'] != args.expected_digest:
                raise ValueError('AI_REVIEW_PREVIEW_STALE')
            # Preview never runs a repair, even on an in-memory database.
            result = (repair.restore(conn, plan, args.request_id) if args.restore else
                      repair.apply(conn, plan, trips, manifest, request_id=args.request_id,
                                   evidence=evidence)) if args.apply else plan['summary']
            report = dict(status='APPLIED' if args.apply else 'PREVIEW', digest=plan['digest'], **result)
        return emit_report(report, args.report)
    except (OSError, ValueError, KeyError, sqlite3.Error, StoreError, OtaSourcesError) as exc:
        code = (exc.code if isinstance(exc, (StoreError, OtaSourcesError)) else str(exc)
                if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__)
        print(json.dumps(dict(status='FAILED', code=code)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
