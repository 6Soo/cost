"""Count-only preview or offline apply/restore of the authorized dist141 repair."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import decision_provenance as repair
from app.db import StoreError
from app.ota_sources import OtaSourcesError as ManifestSourceError
from tools.complete_card_classification import load_context, load_review_evidence, require_offline_backup, read_flow


def canonical_report(conn, host):
    """Rebuild the current core projection locally, without publishing a snapshot.

    The legacy recovery report cannot carry LINK-108 shared periods. Use the
    same canonical matcher/projection as the board, including existing pins,
    rather than silently rejudging against the old report.
    """
    from app.automatic_classification import _read
    from app.ota_payments import build_ota_payment_events, match_ota_payment_events
    from app.ota_core_projection import card_matches
    from app.ota_review import OtaReviewStore
    sources = read_flow(conn,host)._ota_sources()
    events = build_ota_payment_events(sources)
    cards = _read(conn)
    review = OtaReviewStore(host/'data/ota-review/ota-review.sqlite')
    try:
        links = review.links()
        results = match_ota_payment_events(events,cards,existing_links=links,
            rules=review.active_rules(),frozen_groups=review.group_pins())
        return dict(matches=card_matches([],dict(events=events,transactions=cards,results=results,links=links)))
    finally:
        review.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root',type=Path,required=True)
    parser.add_argument('--request-id',required=True)
    parser.add_argument('--restore',action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-digest')
    parser.add_argument('--backup-evidence',type=Path)
    parser.add_argument('--report',type=Path)
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    db = host/'data/board.sqlite'
    try:
        if args.apply:
            if not args.expected_digest or not args.backup_evidence:
                raise ValueError('PREVIEW_AND_BACKUP_REQUIRED')
            require_offline_backup(host,args.backup_evidence,db)
        with sqlite3.connect(db.as_uri()+'?mode='+('rw' if args.apply else 'ro'),uri=True,isolation_level=None) as conn:
            if args.restore:
                plan = repair.restore_preview(conn,args.request_id)
                options = {}
            else:
                trips,nets = load_context(conn,host)
                evidence,_ = load_review_evidence(conn,host,trips,report=canonical_report(conn,host))
                options = dict(nets=nets,evidence=evidence)
                plan = repair.preview(conn,trips,**options)
            if args.apply and plan['digest'] != args.expected_digest:
                raise ValueError('PROVENANCE_PREVIEW_STALE')
            target = conn if args.apply else sqlite3.connect(':memory:',isolation_level=None)
            try:
                if not args.apply:
                    conn.backup(target)
                result = (repair.restore(target,plan,args.request_id) if args.restore else
                          repair.apply(target,plan,trips,request_id=args.request_id,**options))
            finally:
                if target is not conn:
                    target.close()
            report = dict(status='APPLIED' if args.apply else 'PREVIEW',digest=plan['digest'],**result)
        if args.report:
            args.report.write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report))
        return 0
    except (OSError,ValueError,KeyError,sqlite3.Error,StoreError,ManifestSourceError) as exc:
        code = (exc.code if isinstance(exc,(StoreError,ManifestSourceError)) else
                str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else type(exc).__name__)
        print(json.dumps(dict(status='FAILED',code=code)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
