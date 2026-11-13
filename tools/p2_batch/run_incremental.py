"""Bounded layer-1 increments; private journal, authenticated server writes only."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import sqlite3

from app import rules
from app.normalize import normalize_merchant
from . import layer1, scope
from .normalize import operational_items

PRIVATE = Path('D:/WebLedgerHost/data')
DEFAULT_STATE = PRIVATE / 'p2-incremental.json'
PUBLIC_SUMMARY = PRIVATE / 'p2-runs' / 'latest.json'
LOCK_MAX_SECONDS = 2 * 3600


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save_public_summary(metrics, data_root):
    """Publish aggregate run status only; never copy merchant or transaction data."""
    failure = safe_public_failure(metrics.get('failure_code'))
    summary = dict(schema=1, started_at=metrics.get('started_at'), finished_at=metrics.get('finished_at'),
        target_groups=(metrics.get('scope') or {}).get('new_merchants', 0),
        target_rows=(metrics.get('scope') or {}).get('new_rows', 0),
        model_calls=metrics.get('calls', 0), successful_calls=metrics.get('successful_calls', 0),
        failed_calls=metrics.get('failed_calls', 0), applied_rows=metrics.get('applied_rows', 0),
        limit_failure=any(word in failure for word in ('LIMIT', 'QUOTA', 'USAGE')),
        run_success_rate=metrics.get('run_success_rate'),
        run_success_denominator=metrics.get('run_success_denominator', 0),
        status=metrics.get('status'), failure_reason_code=failure or None)
    path = Path(data_root) / 'p2-runs' / 'latest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, summary)


def safe_public_failure(value):
    """Return a bounded public reason code, never arbitrary exception text."""
    allowed = {'VERIFIED_LAYER1_HISTORY_REQUIRED', 'AUTHENTICATED_API_CONFIG_REQUIRED',
               'PRIVATE_STATE_REQUIRED', 'INVALID_RUN_LIMIT', 'P2_INCREMENTAL_LOCK_HELD',
               'ValueError', 'TypeError', 'OSError', 'PermissionError', 'FileNotFoundError',
               'JSONDecodeError', 'RuntimeError', 'AgentUnavailable',
               'AGENT_CAPACITY', 'AGENT_RATE_LIMITED', 'AGENT_USAGE_LIMIT', 'AGENT_TIMEOUT',
               'AGENT_AUTH_REQUIRED', 'AGENT_TOOL_EXECUTION_DETECTED', 'AGENT_PROMPT_TOO_LARGE',
               'AGENT_EXECUTION_FAILED', 'AGENT_EXECUTION_MISMATCH', 'AGENT_PROVIDER_ERROR',
               'AGENT_RESPONSE_INVALID', 'AGENT_RESPONSE_TOO_LARGE', 'AGENT_PROCESS_BOUNDARY_UNAVAILABLE',
               'AGENT_COMMAND_LINE_TOO_LONG', 'AGENT_MODEL_NOT_ALLOWED', 'AGENT_CODEX_NOT_FOUND'}
    return value if isinstance(value, str) and value in allowed else ''


def pid_alive(pid):
    """Probe without signalling: os.kill would terminate the process on Windows."""
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def lock_state(lock):
    """(held, info): only a live writer inside the time limit holds the lock."""
    try:
        info = json.loads(lock.read_text(encoding='utf-8'))
        pid = int(info['pid'])
        started = datetime.fromisoformat(info['started_at'])
    except (OSError, ValueError, KeyError, TypeError):
        # Unverifiable content: a recent file may be a writer mid-creation.
        held = time.time() - lock.stat().st_mtime < LOCK_MAX_SECONDS
        return held, {'stale_reason': 'unverifiable_content'}
    age = (datetime.now(timezone.utc) - started).total_seconds()
    if age >= LOCK_MAX_SECONDS:
        return False, dict(info, stale_reason='age_limit')
    if not pid_alive(pid):
        return False, dict(info, stale_reason='pid_not_running')
    return True, info


def read_rules(db):
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as conn:
        return rules.list_rules(type('Reader', (), {'conn': conn})())


def merchant_key(row):
    return normalize_merchant(row.get('merchant_normalized') or row.get('merchant') or '')


def has_rule(row, existing):
    # A merchant counts as already ruled only when an unconditional rule names
    # it explicitly and assigns a specific item. Wildcard/pattern rules and
    # country/period/source-bound conditions cover only part of the merchant,
    # and a rule that keeps a broad item is exactly what AI must re-review.
    name = merchant_key(row)
    if not name or name == '*':
        return False
    for rule in existing:
        conditions = rule.get('conditions') or {}
        if conditions.get('merchant_normalized') != name:
            continue
        if set(conditions) - {'merchant_normalized', 'transaction_direction'}:
            continue
        direction = conditions.get('transaction_direction')
        if direction and direction != row.get('transaction_direction'):
            continue
        if rule.get('optional'):
            continue
        item = (rule.get('effects') or {}).get('item')
        if item and item not in scope.GENERAL:
            return True
    return False


def select_increment(data, existing, seen):
    excluded = {}
    report, scoped, eligible, general = scope.select(data, exclusion_reasons=excluded)
    inputs, targets = layer1.merchants(general)
    reasons = Counter()
    selected = []
    for value in inputs:
        rows = targets[value['merchant_id']]
        if any(has_rule(r, existing) for r in rows):
            reason = 'existing_p1_rule'
        elif value['merchant_id'] in seen:
            reason = 'previous_layer1'
        else:
            reason = 'new_merchant'
            selected.append(value)
        reasons[reason] += len(rows)
    # Separate the two broad labels requested by operations from 여행경비.
    opened = {r['tab_id'] for r in data['trip_tabs'] if not r['deleted'] and r['starts_on'] >= '2026-06-30'}
    def open_row(row):
        quarter = scope.destination(row)
        return scope.tab(row) in opened or (quarter and (quarter['year'], quarter['quarter']) >= (2026, 3))
    broad = [r for r in data['transactions'] if r['item'] in {'기타경비', '현지경비'}
             and r['transaction_direction'] == 'purchase' and (r['amount_krw'] or 0) > 0 and open_row(r)]
    eligible_ids = {r['transaction_id'] for r in eligible}
    new_ids = {r['transaction_id'] for m in selected for r in targets[m['merchant_id']]}
    broad_reasons = Counter()
    for row in broad:
        mid = hashlib.sha256((row['merchant_normalized'] or row['merchant']).encode()).hexdigest()[:24]
        reason = (excluded.get(row['transaction_id'], 'scope_protection') if row['transaction_id'] not in eligible_ids else
                  'existing_p1_rule' if has_rule(row, existing) else
                  'previous_layer1' if mid in seen else 'new_merchant')
        broad_reasons[reason] += 1
    report.update(new_merchants=len(selected), new_rows=sum(len(targets[m['merchant_id']]) for m in selected),
                  general_partition=dict(reasons), broad_rows=len(broad),
                  broad_incremental_rows=sum(r['transaction_id'] in new_ids for r in broad),
                  broad_partition=dict(broad_reasons))
    report.pop('quarterly_review', None)  # public output contains aggregate counts only
    return report, selected, targets


class BrowserAPI:
    """One documented ego Page fetch per request; no credential extraction."""
    def __init__(self, config, directory):
        self.config = json.loads(Path(config).read_text(encoding='utf-8'))
        self.directory = directory

    def __call__(self, endpoint, payload):
        if endpoint not in {'/api/p2-batch/corrections/preview', '/api/p2-batch/corrections/apply', '/api/imports/rules'}:
            raise ValueError('API_ENDPOINT_REFUSED')
        # Files stay in the private directory and are removed after this request.
        with tempfile.TemporaryDirectory(prefix='p2-api-', dir=self.directory) as folder:
            root = Path(folder)
            request = root/'request.json'
            response = root/'response.json'
            request.write_text(json.dumps(dict(self.config, endpoint=endpoint, payload=payload), ensure_ascii=False), encoding='utf-8')
            bridge = Path(__file__).with_name('authenticated_api.mjs').as_uri()
            script = root/'round.mjs'
            script.write_text('const {request} = await import('+json.dumps(bridge)+');\nawait request('+json.dumps(request.as_posix())+','+json.dumps(response.as_posix())+');', encoding='utf-8')
            try:
                result = subprocess.run(['ego-browser', 'nodejs', '-e', "await import('"+script.as_uri()+"')"],
                                        capture_output=True, timeout=60)
            except subprocess.TimeoutExpired:
                raise ValueError('API_TRANSPORT_TIMEOUT') from None
            if result.returncode or not response.exists():
                raise ValueError('API_BROWSER_AUTH_OR_TRANSPORT_FAILED')
            result = json.loads(response.read_text(encoding='utf-8'))
            if not result['ok']:
                code = result.get('body', {}).get('code', '')
                raise ValueError('API_REJECTED_'+str(result['status'])+'_'+str(code)[:100])
            return result['body']


def apply_job(job, api, checkpoint, current_data, existing, metrics, fresh_rules=None, fresh_data=None,
              register_rules=False):
    """Persist each exact request before sending it, including its preview digest."""
    proposal = job['proposal']
    if proposal['item'] == layer1.KEEP:
        job['done'] = True
        checkpoint()
        return
    if 'requests' not in job:
        # Fresh selection rechecks manual, financial, completed/open scope and
        # projection guards. A changed rule set stops unprepared old proposals.
        if any(has_rule(r, existing) for r in job['targets']):
            raise ValueError('MERCHANT_RULE_CHANGED')
        _, _, eligible, _ = scope.select(current_data)
        fresh = {r['transaction_id']: r for r in eligible}
        corrections = []
        for old in job['targets']:
            row = fresh.get(old['transaction_id'])
            if row is None or any(row[k] != old[k] for k in scope.FIELDS):
                raise ValueError('INCREMENTAL_TARGET_STALE')
            if row['item'] == proposal['item']:
                continue
            corrections.append(dict(transaction_id=old['transaction_id'], source_hash=old['source_hash'],
                revision=old['revision'], trip_id=scope.tab(old), item=proposal['item'], basis=proposal['basis'],
                classification_source='ai_inference', execution=proposal['execution']))
        job['requests'] = [dict(request_id='p2-incremental-'+uuid.uuid4().hex, corrections=corrections[i:i+50])
                           for i in range(0, len(corrections), 50)]
        checkpoint()
    for request in job['requests']:
        if request.get('done'):
            continue
        if 'preview_digest' not in request:
            preview = api('/api/p2-batch/corrections/preview', {'corrections': request['corrections']})
            request['preview_digest'] = preview['digest']
            checkpoint()
        # The exact saved request is replayed after a lost response; server
        # request replay runs before revision/digest checks and returns applied=0.
        result = api('/api/p2-batch/corrections/apply', {k:v for k,v in request.items() if k != 'done'})
        metrics['applied_rows'] += result.get('applied', 0)
        metrics['confirmed_rows'] += len(request['corrections'])
        if result.get('replay'):
            metrics['recovered_rows'] += len(request['corrections'])
        request['done'] = True
        checkpoint()
    if register_rules:
        if 'rule' not in job:
            existing = fresh_rules() if fresh_rules else existing
            rows = job['targets']
            latest = fresh_data() if fresh_data else current_data
            _, _, eligible, _ = scope.select(latest)
            eligible_by_id = {r['transaction_id']: r for r in eligible}
            still_ai = all((r := eligible_by_id.get(old['transaction_id'])) is not None
                           and r['source_hash'] == old['source_hash'] and r['item'] == proposal['item']
                           and r['classification_source'] == 'ai_inference' for old in rows)
            key = merchant_key(rows[0])
            can_promote = (proposal['confidence'] == '높음' and proposal['item'] not in scope.GENERAL
                           and still_ai and len(rows) >= 2 and key and key != '*'
                           and all(merchant_key(r) == key for r in rows)
                           and not any(has_rule(r, existing) for r in rows))
            job['rule'] = None
            if can_promote:
                draft = rules.normalize_rule(dict(conditions=dict(merchant_normalized=key, transaction_direction='purchase'),
                    optional={}, effects=dict(item=proposal['item']), origin='p2-layer1:'+proposal['execution']['run_id'],
                    note=proposal['basis']))
                job['rule'] = dict(draft=draft, expected_revision=0, request_id='p2-rule-'+uuid.uuid4().hex)
            checkpoint()
        if job['rule'] and not job.get('rule_done'):
            # An unrelated fresh rule is never overwritten. A saved identical
            # request can be replayed safely if the previous response was lost.
            current_rules = fresh_rules() if fresh_rules else existing
            matches = [r for r in current_rules if has_rule(job['targets'][0], [r])]
            if any(r['conditions'] != job['rule']['draft']['conditions'] or r['optional']
                   or r['effects'] != job['rule']['draft']['effects']
                   or r['origin'] != job['rule']['draft']['origin'] for r in matches):
                raise ValueError('MERCHANT_RULE_CHANGED')
            api('/api/imports/rules', job['rule'])
            metrics['registered_rules'] += 1
            job['rule_done'] = True
            checkpoint()
        job['done'] = True
    else:
        # Correction-only approval. A job with an already drafted rule stays
        # pending so a later --register-rules run can finish registration.
        job['done'] = 'rule' not in job
    checkpoint()


def _run(args, *, model=layer1.call, api=None, reader=scope.read_projection, rule_reader=read_rules):
    if not 1 <= args.max_merchants <= 500 or not 1 <= args.max_calls <= 20 or not 30 <= args.batch_size <= 50:
        raise ValueError('INVALID_RUN_LIMIT')
    path = Path(args.state).resolve()
    if not path.is_relative_to(PRIVATE.resolve()) or path == Path(args.db).resolve():
        raise ValueError('PRIVATE_STATE_REQUIRED')
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    stale_lock = None
    if lock.exists():
        held, info = lock_state(lock)
        if held:
            raise FileExistsError('P2_INCREMENTAL_LOCK_HELD')
        stale_lock = info
    temporary = lock.with_name(lock.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(dict(pid=os.getpid(), started_at=datetime.now(timezone.utc).isoformat()), stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if stale_lock is None:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
        os.replace(temporary, lock)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    try:
        if not path.is_file():
            raise ValueError('VERIFIED_LAYER1_HISTORY_REQUIRED')
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('version') != 1 or not state.get('history_evidence'):
            raise ValueError('VERIFIED_LAYER1_HISTORY_REQUIRED')
        for previous in state.get('runs', []):
            if previous['status'] == 'running':
                previous.update(status='failed', failure_code='INTERRUPTED_PREVIOUS_RUN')
        if stale_lock is not None:
            now = datetime.now(timezone.utc).isoformat()
            state.setdefault('runs', []).append(dict(run_id=uuid.uuid4().hex, started_at=now, finished_at=now,
                mode='lock-recovery', status='failed', failure_code='STALE_LOCK_RECOVERED', stale_lock=stale_lock,
                calls=0, successful_calls=0, failed_calls=0, applied_rows=0, confirmed_rows=0, recovered_rows=0,
                registered_rules=0, usage={}))
        metrics = dict(run_id=uuid.uuid4().hex, started_at=datetime.now(timezone.utc).isoformat(),
            mode='dry-run' if args.dry_run else 'propose-only' if args.propose_only else 'apply',
            calls=0, successful_calls=0, failed_calls=0, applied_rows=0, confirmed_rows=0, recovered_rows=0,
            registered_rules=0, usage={}, status='running')
        state.setdefault('runs', []).append(metrics)
        state.setdefault('jobs', [])
        checkpoint = lambda: save(path, state)
        checkpoint()
        try:
            data = reader(args.db)
            # Reuse source-bound selection evidence during this one run. The
            # server independently resolves live formal facts at preview/apply.
            refresh = (lambda: scope.read_projection(args.db, completed_evidence=data['completed_period_evidence'])
                       if reader is scope.read_projection else reader(args.db))
            existing = rule_reader(args.db)
            seen = set(state['history_merchants']) | {j['merchant_id'] for j in state['jobs']}
            report, inputs, targets = select_increment(data, existing, seen)
            metrics['scope'] = report
            checkpoint()
            if not args.dry_run:
                pending = [j for j in state['jobs'] if not j.get('done')]
                metrics['pending_merchants'] = len(pending)
                # Resume bounded merchants first, without another model call.
                budget = args.max_merchants
                if not args.propose_only:
                    if (pending or inputs) and api is None:
                        if not args.api_config:
                            raise ValueError('AUTHENTICATED_API_CONFIG_REQUIRED')
                        api = BrowserAPI(args.api_config, path.parent)
                    if pending or inputs:
                        api('/api/imports/rules', None)  # read-only authentication preflight before spending model usage
                    for job in pending[:budget]:
                        apply_job(job, api, checkpoint, refresh(), rule_reader(args.db), metrics,
                                  lambda: rule_reader(args.db), refresh, register_rules=args.register_rules)
                        budget -= 1
                else:
                    budget -= min(len(pending), budget)
                inputs = inputs[:budget]
                allowed = operational_items(args.db) if inputs else []
                for offset in range(0, len(inputs), args.batch_size):
                    if metrics['calls'] >= args.max_calls:
                        break
                    batch = inputs[offset:offset+args.batch_size]
                    metrics['calls'] += 1
                    checkpoint()
                    try:
                        response = model(batch, allowed)
                        expected_digest = digest(dict(merchants=batch, allowed_items=allowed, policy=layer1.policy_text()))
                        layer1.validate(dict(request_digest=response['request_digest'], run_id=response['execution']['run_id'],
                            results=response['results']), batch, allowed, expected_digest, response['execution']['run_id'])
                        if response['execution'].get('model') != layer1.provider.MODEL or response['execution'].get('provider') != 'codex':
                            raise ValueError('CODEX_EXECUTION_REQUIRED')
                    except Exception:
                        metrics['failed_calls'] += 1
                        raise
                    metrics['successful_calls'] += 1
                    metrics['usage'] = dict(Counter(metrics['usage']) + Counter(response.get('usage', {})))
                    normalized = layer1.normalize_results(batch, response['results'], allowed)
                    jobs = []
                    for proposal in normalized:
                        mid = proposal['merchant_id']
                        job = dict(merchant_id=mid, proposal=dict(proposal, execution=response['execution']),
                            request_digest=response['request_digest'], usage=response.get('usage', {}),
                            targets=targets[mid], rules_digest=digest(existing), done=False)
                        state['jobs'].append(job)
                        jobs.append(job)
                    checkpoint()
                    if not args.propose_only:
                        # All jobs in this batch saw the same original rule set;
                        # own rule additions do not invalidate sibling proposals.
                        for job in jobs:
                            apply_job(job, api, checkpoint, refresh(), rule_reader(args.db), metrics,
                                      lambda: rule_reader(args.db), refresh, register_rules=args.register_rules)
                        existing = rule_reader(args.db)
            metrics['status'] = 'success'
        except Exception as exc:
            metrics['status'] = 'failed'
            # Keep arbitrary transport/model output out of public logs.
            code = getattr(exc, 'code', None) or str(exc)
            metrics['failure_code'] = code if code.replace('_','').replace('-','').isalnum() and len(code) < 160 else type(exc).__name__
        finally:
            metrics['finished_at'] = datetime.now(timezone.utc).isoformat()
            metrics['model_success_rate'] = metrics['successful_calls']/metrics['calls'] if metrics['calls'] else None
            finished = [r for r in state['runs']
                        if r.get('mode') in {'apply', 'propose-only'}
                        and r.get('status') in {'success', 'failed'}
                        and r.get('failure_code') != 'INTERRUPTED_PREVIOUS_RUN']
            metrics['run_success_denominator'] = len(finished)
            metrics['run_success_rate'] = (sum(r['status'] == 'success' for r in finished)/len(finished)
                                           if finished else None)
            checkpoint()
            save_public_summary(metrics, Path(args.db).resolve().parent)
        return metrics
    finally:
        lock.unlink()


def run(args, *, model=layer1.call, api=None, reader=scope.read_projection, rule_reader=read_rules):
    """Run once; also publish failures that occur before run metrics exist."""
    try:
        return _run(args, model=model, api=api, reader=reader, rule_reader=rule_reader)
    except Exception as exc:
        if isinstance(exc, FileExistsError):
            # Another writer owns the in-progress latest.json result. Do not
            # publish this rejected concurrent attempt over that run's status.
            raise
        else:
            reason = safe_public_failure(str(exc)) or type(exc).__name__
        now = datetime.now(timezone.utc).isoformat()
        save_public_summary(dict(started_at=now, finished_at=now, scope={}, calls=0,
            successful_calls=0, failed_calls=1, applied_rows=0, status='failed', failure_code=reason),
            Path(args.db).resolve().parent)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(PRIVATE/'board.sqlite'))
    parser.add_argument('--state', default=str(DEFAULT_STATE))
    parser.add_argument('--api-config', help='Private JSON: task_space, page, origin (existing owner login)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--propose-only', action='store_true')
    parser.add_argument('--max-merchants', type=int, default=30)
    parser.add_argument('--max-calls', type=int, default=1)
    parser.add_argument('--batch-size', type=int, default=30)
    parser.add_argument('--register-rules', action='store_true',
                        help='Also register promoted P1 rules; separate approval, default off')
    result = run(parser.parse_args())
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(0 if result['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
