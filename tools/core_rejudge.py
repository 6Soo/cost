"""Operational full re-judgement through the same writer path as the live Board (rust writer only).

Use after a deploy that changes a judgement function version (e.g. PERIOD_FN_VERSION). The write goes
`core_writer.prepared` (evidence and key built outside any lock) -> `run_with_periods` (key compared under the
lock) -> `automatic_classification.apply` (Rust), so period evidence always travels with the judgement.
The Board may keep running (Rust apply is BEGIN IMMEDIATE plus a plan-digest check); run in a quiet hour.
No transaction ids or customer text are printed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import automatic_classification as policy, core_switch_config, core_writer  # noqa: E402

STALE = 'CLASSIFICATION_PREVIEW_STALE'
ATTEMPTS = 2


class Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def require_backup(host: Path, evidence) -> str:
    """A fresh scoped/full backup that covers board.sqlite and core.sqlite. The Board stays up, so the live
    state is not compared with the backup manifest (it moves); freshness and coverage are required."""
    from tools.verify_operational_backup_restore import backup_covers
    if not evidence:
        raise Refused('BACKUP_EVIDENCE_REQUIRED')
    try:
        saved = json.loads(Path(evidence).read_text(encoding='utf-8-sig'))
        recorded = datetime.fromisoformat(saved['recorded_at'])
        directory = Path(saved['backup_directory']).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        raise Refused('BACKUP_RESTORE_NOT_VERIFIED') from None
    if any(saved.get(key) is not True for key in ('live_state_unchanged', 'restored_review_binding_equal')) \
            or not backup_covers(saved, host, ['board.sqlite']):
        raise Refused('BACKUP_RESTORE_NOT_VERIFIED')
    if recorded.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - recorded).total_seconds() < 3600:
        raise Refused('BACKUP_NOT_FRESH')
    if not directory.is_relative_to((host / 'data/backups').resolve()):
        raise Refused('BACKUP_LOCATION_INVALID')
    return saved['recorded_at']


def _open(host: Path, write: bool):
    db = host / 'data/board.sqlite'
    return sqlite3.connect(db.resolve().as_uri() + '?mode=' + ('rw' if write else 'ro'), uri=True,
                           isolation_level=None, timeout=30)


def _scope(flow, backfill: bool):
    from webapp.card_classification_completion import complete_scope
    return complete_scope(flow, None, backfill=backfill)


def run_apply(flow, backfill: bool) -> dict:
    """One full pass; a concurrent Board write surfaces as CLASSIFICATION_PREVIEW_STALE and is retried once."""
    for attempt in range(ATTEMPTS):
        try:
            return core_writer.prepared(flow.board, lambda: _scope(flow, backfill))
        except ValueError as exc:
            if str(exc) != STALE:
                raise
            if attempt == ATTEMPTS - 1:
                raise Refused('CORE_REJUDGE_PREVIEW_STALE') from None
    raise AssertionError('unreachable')


def run_dry(flow) -> dict:
    """Evidence build time and the plan's counts; nothing is written to the classification columns or core.sqlite."""
    from webapp.card_classification_completion import classification_evidence, context
    started = time.monotonic()
    facts, _ = core_writer.periods_with_key(flow.board.conn, flow.board._lock)
    evidence_seconds = round(time.monotonic() - started, 2)
    trips, nets = context(flow)
    evidence = classification_evidence(flow.board, trips, flow)
    preview = policy.plan(flow.board.conn, trips, nets=nets, evidence=evidence)
    return {'status': 'DRY_RUN', 'writes': 0, 'period_fact_transactions': len(facts),
            'evidence_seconds': evidence_seconds, **{k: preview['summary'][k] for k in ('scanned', 'to_classify', 'protected')}}


def latest_run(host: Path):
    path = host / 'data' / core_writer.RUNS_DIR / 'latest.json'
    try:
        return json.loads(path.read_text(encoding='utf-8')).get('latest')
    except (OSError, ValueError, AttributeError):
        return core_writer.LAST_RUN.get()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, default=Path('D:/WebLedgerHost'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--backup-evidence', type=Path)
    parser.add_argument('--backfill-decisions', action='store_true',
                        help='also store decisions for rows whose screen columns already equal the plan')
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    try:
        options = core_switch_config.read_options(host / 'config')
        if options.get('classification_writer') != 'rust':
            raise Refused('CORE_REJUDGE_WRITER_NOT_RUST')  # python writer: use tools/complete_card_classification.py
        core_switch_config.apply(options, host / 'data')
        if not args.dry_run:
            backup_recorded_at = require_backup(host, args.backup_evidence)
        from tools.complete_card_classification import read_flow
        with closing(_open(host, write=not args.dry_run)) as conn:
            flow = read_flow(conn, host)
            if args.dry_run:
                report = run_dry(flow)
            else:
                started = time.monotonic()
                run_apply(flow, args.backfill_decisions)
                run = latest_run(host) or {}
                report = {'status': 'APPLIED', 'seconds_total': round(time.monotonic() - started, 2),
                          'backup_recorded_at': backup_recorded_at,
                          **{k: run.get(k) for k in (*core_writer.RUN_COUNTS, 'seconds')}}
        print(json.dumps(report))
        return 0
    except Refused as exc:
        code = exc.code
    except core_switch_config.CoreSwitchRefused as exc:
        code = exc.code
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, (ValueError, RuntimeError)) and str(exc).replace('_', '').isalnum() \
            else type(exc).__name__
    print(json.dumps({'status': 'FAILED', 'code': code}))
    return 2 if code.startswith(('CORE_REJUDGE', 'BACKUP')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
