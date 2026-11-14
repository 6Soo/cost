"""Local connected-agent AI review: private request, safe preview, gated apply.

Prepare/preview simulate P1 on an in-memory copy. An actual connected agent reads
the derived request and supplies a response, including provider/model/run_id.
Apply replays P1 and validates that exact AI result atomically, then queues the
existing internal recording worker. No remote model, new credentials or schema.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ai_classification as ai, automatic_classification as code, core_switch_config
from tools.complete_card_classification import load_context, read_flow, require_offline_backup


def run(conn, trips, ids, *, nets=None, reconsider=False, request=None, response=None, apply=False, completed_evidence=None):
    """Caller owns one transaction; no hidden commits or external effects."""
    if request is not None and response is not None:
        request_id = 'connected-agent:' + (response.get('execution') or {}).get('run_id', '')
        if conn.execute("SELECT 1 FROM requests WHERE request_id=? AND scope='ai_classification'", (request_id,)).fetchone():
            result = ai.apply(conn, trips, request, response, request_id=request_id, nets=nets,completed_evidence=completed_evidence)
            return dict(request=request, ai_result=result, digest=result['digest'], code_changes=0)
    plan = code.plan(conn, trips, transaction_ids=ids, nets=nets,evidence=completed_evidence)
    code.apply(conn, plan, trips, transaction_ids=ids, nets=nets,evidence=completed_evidence)
    fresh = ai.prepare(conn, trips, ids, reconsider=reconsider, nets=nets,completed_evidence=completed_evidence)
    if request is not None and fresh != request:
        raise ValueError('AI_REQUEST_STALE')
    if response is None:
        return dict(request=fresh, code_changes=plan['summary']['to_classify'])
    expected = ai.preview(conn, trips, fresh, response, nets=nets,completed_evidence=completed_evidence)
    result = ai.apply(conn, trips, fresh, response,
                      request_id='connected-agent:' + response['execution']['run_id'], nets=nets,completed_evidence=completed_evidence)
    return dict(request=fresh, ai_result=result, digest=expected['digest'],
                code_changes=plan['summary']['to_classify'])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-root', type=Path, default=Path('D:/WebLedgerHost'))
    p.add_argument('--transaction', action='append', required=True)
    p.add_argument('--reconsider', action='store_true')
    p.add_argument('--request', type=Path)
    p.add_argument('--response', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--expected-digest')
    p.add_argument('--backup-evidence', type=Path)
    args = p.parse_args(argv)
    host = args.host_root.resolve()
    try:
        inputs = [host/'data/board.sqlite', args.request, args.response, args.backup_evidence]
        if args.output.resolve() in {value.resolve() for value in inputs if value is not None}:
            raise ValueError('AI_OUTPUT_MUST_NOT_OVERWRITE_INPUT')
        if args.apply:
            core_switch_config.refuse_manual_apply(host)
            if not all((args.request, args.response, args.expected_digest, args.backup_evidence)):
                raise ValueError('PREVIEW_AND_BACKUP_REQUIRED')
            require_offline_backup(host, args.backup_evidence, host/'data/board.sqlite')
        live = sqlite3.connect((host/'data/board.sqlite').as_uri() + '?mode=' + ('rw' if args.apply else 'ro'), uri=True, isolation_level=None)
        work = live if args.apply else sqlite3.connect(':memory:', isolation_level=None)
        try:
            if work is not live:
                live.backup(work)
            work.execute('BEGIN IMMEDIATE' if args.apply else 'BEGIN')
            trips, nets = load_context(work, host)
            from tools.complete_card_classification import load_completed_period_evidence
            completed_evidence = load_completed_period_evidence(work,host,trips)
            request = json.loads(args.request.read_text(encoding='utf-8')) if args.request else None
            if request is not None:
                request = request.get('request', request)
            response = json.loads(args.response.read_text(encoding='utf-8')) if args.response else None
            result = run(work, trips, args.transaction, nets=nets,
                         reconsider=args.reconsider or bool(request and request.get('reconsider')),
                         request=request, response=response, apply=args.apply,completed_evidence=completed_evidence)
            if args.apply:
                if result.get('digest') != args.expected_digest:
                    raise ValueError('AI_PREVIEW_STALE')
                from webapp.card_completion_worker import queue_batch
                board = read_flow(work, host).board
                by_batch = {}
                for case in result['request']['cases'] if result['ai_result']['applied'] else []:
                    batch = work.execute('SELECT batch_id FROM transactions WHERE transaction_id=?', (case['transaction_id'],)).fetchone()[0]
                    by_batch.setdefault(batch, set()).add(case['transaction_id'])
                for batch, ids in by_batch.items():
                    queue_batch(board, batch, ids, commit=False)
                # Write the reviewable result before commit, so output errors cannot
                # leave a successful mutation reported as a failed execution.
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                work.commit()
            else:
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                work.rollback()
        finally:
            if work is not live:
                work.close()
            live.close()
        print(json.dumps(dict(status='APPLIED' if args.apply else 'PREVIEW', cases=len(result['request']['cases']),
                              code_changes=result['code_changes'], ai_applied=(result.get('ai_result') or {}).get('applied', 0),
                              database_writes=bool(args.apply), google_writes=0)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        # Never print customer input, exception details or original text.
        message = str(exc)
        error = message if message.isascii() and message.replace('_', '').isalnum() and message.isupper() else type(exc).__name__
        print(json.dumps(dict(status='FAILED', code=error)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
