"""Unattended P1->P2 loop for the expense cleanup queue.

Durable per-transaction jobs live in `requests` (scope `autonomous_cleanup_job`)
so restart recovery needs no migration and no schema change. Calls the local
connected agent only through `app.connected_agent_provider`, applies through
`app.ai_classification`'s existing preview/apply contract, and never touches
Google, the ledger, amounts, source rows or manual decisions.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import threading

from app.partial_refund import read_only_scope as refund_evidence_scope
from .deployment_role import active_writer

INTERVAL = 1800
STATUS_HEARTBEAT_SECONDS = 300
CHUNK = 20
MAX_ATTEMPTS = 3
STALE_PROCESSING_SECONDS = 600
BLOCKED_RETRY_SECONDS = 300
P1_RETRY_SECONDS = 120
JOB_SCOPE = 'autonomous_cleanup_job'
BUNDLE_SCOPE = 'autonomous_cause_bundle'
METRICS_FILE = 'autonomous-cleanup-metrics.jsonl'
TERMINAL = ('no_ai_needed', 'p2_applied', 'ai_dead')
CODE_DEFECT_REASONS = ('AGENT_EXECUTION_FAILED', 'AGENT_COMMAND_LINE_TOO_LONG',
                       'AGENT_RESPONSE_INVALID', 'AGENT_EXECUTION_MISMATCH')
CODE_FINGERPRINT_FILES = (
    'app/connected_agent_provider.py', 'app/ai_classification.py',
    'app/automatic_classification.py', 'app/rules.py',
    'webapp/autonomous_cleanup_worker.py', 'webapp/card_classification_completion.py',
)


def configured_interval(config_path):
    """Read the bounded recovery-sweep interval; uploads still wake the worker immediately."""
    try:
        options = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        interval = options.get('autonomous_cleanup_interval_seconds')
        if type(interval) is int and 60 <= interval <= 86400:
            return interval
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return INTERVAL


def code_fingerprint(root=None):
    """Fingerprint only the P1/P2 decision code so a verified fix requeues failed jobs."""
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    digest = hashlib.sha256()
    for relative in CODE_FINGERPRINT_FILES:
        digest.update(relative.encode('utf-8'))
        digest.update(b'\0')
        digest.update((base / relative).read_bytes())
    return digest.hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def detection_sql():
    from .card_classification_completion import missing_assignment_sql
    return (
        "SELECT t.transaction_id, b.batch_id, t.revision, t.classification_state,"
        " t.classification_source, t.item, t.display_tab_id, t.trip_id, t.source_hash, t.approval_date"
        " FROM import_batch_rows b JOIN transactions t USING(transaction_id)"
        " LEFT JOIN (SELECT DISTINCT issuer, card_tail, original_approval_number"
        "   FROM transactions"
        "   WHERE COALESCE(original_approval_number,'')!=''"
        "     AND (transaction_direction IN ('cancellation','refund') OR amount_krw < 0)) f"
        "   ON f.issuer = t.issuer AND f.card_tail = t.card_tail AND f.original_approval_number = t.approval_number"
        " WHERE t.transaction_direction = 'purchase' AND t.amount_krw > 0"
        " AND (COALESCE(t.item,'') IN ('기타경비','현지경비','여행경비')"
        "      OR COALESCE(t.display_tab_id,'') = '' OR COALESCE(t.display_tab_id,'') = 'unclassified'"
        "      OR " + missing_assignment_sql() + ")"
        " AND COALESCE(t.parse_error,'') = '' AND COALESCE(t.conflict_reason,'') = ''"
        " AND COALESCE(t.duplicate_of,'') = '' AND t.decided_at IS NULL"
        " AND COALESCE(t.classification_source,'') NOT IN"
        " ('user_decision','user_exception','owner_booking','manual','manual_hold','ai_inference')"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM ledger_entries)"
        " AND t.transaction_id NOT IN (SELECT substr(row_id, 6) FROM board_rows WHERE row_id LIKE 'card-%')"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM review_decisions)"
        " AND t.transaction_id NOT IN (SELECT substr(row_id, 6) FROM board_manual_overrides WHERE row_id LIKE 'card-%')"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM transaction_review_holds)"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM transaction_company_exclusions WHERE excluded = 1)"
        " AND f.original_approval_number IS NULL"
        " ORDER BY t.approval_date DESC, t.transaction_id LIMIT 400")


def detection_candidates(conn):
    return conn.execute(detection_sql()).fetchall()


def fingerprint(row, inputs_digest):
    return _digest([inputs_digest, row[0], row[2], row[3], row[4], row[5], row[6], row[7], row[8]])


def job_key(transaction_id):
    return 'autonomous-cleanup:' + transaction_id


def load_job(conn, transaction_id):
    row = conn.execute('SELECT response_json FROM requests WHERE request_id = ? AND scope = ?',
                       (job_key(transaction_id), JOB_SCOPE)).fetchone()
    if not row:
        return None
    try:
        state = json.loads(row[0])
    except ValueError:
        return None
    if not isinstance(state, dict):
        return None
    return state


def save_job(conn, transaction_id, fingerprint_value, state):
    from app.db import utc_now
    payload = dict(state)
    payload['fingerprint'] = fingerprint_value
    payload['updated_at'] = utc_now()
    conn.execute(
        'INSERT INTO requests VALUES (?,?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET'
        ' payload_sha256 = excluded.payload_sha256, response_json = excluded.response_json,'
        ' created_at = excluded.created_at WHERE requests.scope = excluded.scope',
        (job_key(transaction_id), JOB_SCOPE, fingerprint_value,
         json.dumps(payload, ensure_ascii=False), utc_now()))


def _updated_at_epoch(state):
    try:
        raw = str(state.get('updated_at') or '')
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0.0


def pending_job_ids(conn, fingerprints, now=None):
    now = time.time() if now is None else now
    due = {}
    for transaction_id, fingerprint_value in fingerprints.items():
        job = load_job(conn, transaction_id)
        if job is None:
            due[transaction_id] = fingerprint_value
            continue
        status = job.get('status')
        if job.get('fingerprint') == fingerprint_value:
            if status in TERMINAL:
                continue
            if status == 'awaiting_agent':
                if now - _updated_at_epoch(job) <= STALE_PROCESSING_SECONDS:
                    continue
            elif (job.get('not_before') or 0) > now:
                continue
        due[transaction_id] = fingerprint_value
    return due


def detect_bundles(conn):
    rows = [('transaction', signature, count) for signature, count in conn.execute(
        "SELECT COALESCE(NULLIF(conflict_reason,''), NULLIF(parse_error,'')) signature, COUNT(*) count"
        " FROM transactions"
        " WHERE COALESCE(conflict_reason,'') != '' OR COALESCE(parse_error,'') != ''"
        " GROUP BY signature HAVING COUNT(*) >= 8").fetchall()]
    placeholders = ','.join('?' for _ in CODE_DEFECT_REASONS)
    rows.extend(('worker', reason, count) for reason, count in conn.execute(
        "SELECT json_extract(response_json,'$.reason'), COUNT(*) FROM requests"
        " WHERE scope = ? AND json_extract(response_json,'$.status') IN ('ai_retry','ai_dead')"
        f" AND json_extract(response_json,'$.reason') IN ({placeholders})"
        " GROUP BY 1 HAVING COUNT(*) >= 8", (JOB_SCOPE, *CODE_DEFECT_REASONS)).fetchall())
    from app.db import utc_now
    for source, signature, count in rows:
        bundle_digest = signature if source == 'transaction' else source + ':' + signature
        key = 'autonomous-bundle:' + hashlib.sha256(bundle_digest.encode('utf-8')).hexdigest()[:16]
        state = {'signature': signature, 'count': count, 'state': 'suspected_code_defect',
                 'source': source, 'first_seen': utc_now(), 'resolution': 'pending_code_fix'}
        old = conn.execute('SELECT response_json FROM requests WHERE request_id = ? AND scope = ?',
                           (key, BUNDLE_SCOPE)).fetchone()
        if old:
            try:
                previous = json.loads(old[0])
            except ValueError:
                previous = {}
            if isinstance(previous, dict):
                state['first_seen'] = previous.get('first_seen', state['first_seen'])
                state['count'] = max(count, int(previous.get('count') or 0))
        conn.execute(
            'INSERT INTO requests VALUES (?,?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET'
            ' payload_sha256 = excluded.payload_sha256, response_json = excluded.response_json,'
            ' created_at = excluded.created_at WHERE requests.scope = excluded.scope',
            (key, BUNDLE_SCOPE, _digest(signature), json.dumps(state, ensure_ascii=False), utc_now()))
    return len(rows)


def metrics_path(board):
    return board.path.parent / METRICS_FILE


def append_metric(board, event):
    line = dict(event)
    line.setdefault('ts', datetime.now(timezone.utc).isoformat(timespec='seconds'))
    try:
        with metrics_path(board).open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + '\n')
    except OSError:
        pass


def p2_calls_today(board):
    path = metrics_path(board)
    if not path.is_file():
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    count = 0
    try:
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                if '"p2_call"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('kind') == 'p2_call' and str(event.get('ts', ''))[:10] == today:
                    count += 1
    except OSError:
        return 0
    return count


def job_counts(conn):
    counts = {}
    for status, count in conn.execute(
            "SELECT COALESCE(json_extract(response_json,'$.status'),'unknown'), COUNT(*)"
            " FROM requests WHERE scope = ? GROUP BY 1", (JOB_SCOPE,)).fetchall():
        counts[status] = count
    return counts


class AutonomousCleanupWorker:
    def __init__(self, board, runtime_lock, *, interval=INTERVAL, chunk=CHUNK, clock=time.monotonic,
                 flow_factory=None, provider=None, agent_config=None, agent_model=None):
        self.board, self.runtime_lock = board, runtime_lock
        self.interval, self.chunk, self.clock = interval, chunk, clock
        self.flow_factory = flow_factory
        self.provider = provider
        self.agent_config = agent_config
        self.agent_model = agent_model
        self.decision_code_fingerprint = code_fingerprint()
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread = None
        self._last_status_snapshot = None
        self._last_status_published = 0.0
        self.status = {'state': 'idle', 'passes': 0, 'p2_applied': 0, 'no_ai_needed': 0,
                       'ai_retry': 0, 'ai_dead': 0, 'blocked': 0, 'failures': 0,
                       'candidates': 0, 'due': 0, 'suspected_defects': 0}

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self):
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='autonomous-cleanup', daemon=True)
            self._thread.start()
        return self._thread

    def wake(self):
        self._wake.set()

    def stop(self, timeout=5):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    @active_writer()
    def _publish(self):
        snapshot = json.dumps(self.status, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        now = self.clock()
        if (snapshot == self._last_status_snapshot
                and now - self._last_status_published < STATUS_HEARTBEAT_SECONDS):
            return
        path = self.board.path.parent / 'autonomous-cleanup-status.json'
        temporary = path.with_suffix('.tmp')
        try:
            payload = dict(self.status, updated_at=time.time())
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
            self._last_status_snapshot = snapshot
            self._last_status_published = now
        except OSError:
            pass

    def _run(self):
        while not self._stop.is_set():
            self._wake.clear()
            try:
                worked = self.sweep_once()
            except Exception as exc:
                self.status.update(state='retry', error=type(exc).__name__)
                self.status['failures'] += 1
                worked = False
            self._publish()
            self._wake.wait(.1 if worked else self.interval)
        self.status['state'] = 'stopped'
        self._publish()

    def _config_path(self):
        return self.agent_config or (self.board.path.parent.parent / 'config/card-flow.json')

    def agent_enabled(self):
        from app import connected_agent_provider as provider
        if self.provider is not None:
            return True
        return provider.enabled(self._config_path())

    def _held_context(self):
        flow = (self.flow_factory or self._default_flow())(self.board)
        from . import ota_payment_review
        held = flow._held_ota_snapshot() if ota_payment_review.enabled() else (None, False)
        flow._held_ota_snapshot = lambda: held
        published = flow._canonical_snapshot_report(held[0]) if held[0] and held[1] else None
        flow._ota_report = lambda: published
        from .card_classification_completion import context
        trips, nets = context(flow)
        rules = self.board.conn.execute(
            'SELECT rule_id, version, status, rule_hash FROM cost_classification_rules ORDER BY rule_id').fetchall()
        inputs = (trips, nets, rules, (held[0] or {}).get('generation'), held[1],
                  self.decision_code_fingerprint)
        return flow, trips, nets, inputs

    def _default_flow(self):
        from .card_flow import CardFlow
        return CardFlow

    @active_writer(default=False)
    @refund_evidence_scope()
    def sweep_once(self):
        from app import automatic_classification, ai_classification

        with self.runtime_lock, self.board._lock:
            if self._stop.is_set():
                return False
            rows = detection_candidates(self.board.conn)
            self.status['candidates'] = len(rows)
            now = time.time()
            try:
                flow, trips, nets, inputs = self._held_context()
            except Exception as exc:
                self.status.update(state='retry', error='context_' + type(exc).__name__)
                self.status['failures'] += 1
                return False
            inputs_digest = _digest(inputs)
            fingerprints = {row[0]: fingerprint(row, inputs_digest) for row in rows}
            due_ids = pending_job_ids(self.board.conn, fingerprints, now)
            self.status['due'] = len(due_ids)
            if not due_ids:
                self._finish(rows)
                self.status['state'] = 'idle'
                return False
            due_rows = [row for row in rows if row[0] in due_ids][: self.chunk]
            ids = [row[0] for row in due_rows]
            self.status['passes'] += 1
            self.status['state'] = 'running'
            for row in due_rows:
                attempts = (load_job(self.board.conn, row[0]) or {}).get('attempts', 0)
                save_job(self.board.conn, row[0], fingerprints[row[0]],
                         {'status': 'awaiting_agent', 'attempts': attempts})
            try:
                plan = automatic_classification.plan(self.board.conn, trips, nets=nets, transaction_ids=ids)
                automatic_classification.apply(self.board.conn, plan, trips, nets=nets, transaction_ids=ids)
            except Exception as exc:
                for row in due_rows:
                    self._retry_or_dead(row, fingerprints[row[0]], now, 'p1_' + type(exc).__name__,
                                        not_before=now + P1_RETRY_SECONDS)
                self.board.conn.commit()
                self._finish(rows)
                return True
            try:
                request = ai_classification.prepare(self.board.conn, trips, ids, nets=nets)
            except ValueError as exc:
                code = str(exc)
                if code == 'CODE_STAGE_REQUIRED':
                    for row in due_rows:
                        save_job(self.board.conn, row[0], fingerprints[row[0]],
                                 {'status': 'p1_pending', 'attempts': 0,
                                  'not_before': now + P1_RETRY_SECONDS})
                else:
                    for row in due_rows:
                        save_job(self.board.conn, row[0], fingerprints[row[0]], {'status': 'no_ai_needed'})
                self.board.conn.commit()
                self._finish(rows)
                return True
            if not request['cases']:
                for row in due_rows:
                    save_job(self.board.conn, row[0], fingerprints[row[0]], {'status': 'no_ai_needed'})
                self.board.conn.commit()
                self._finish(rows)
                return True
            # Claim under the lock; the provider call runs unlocked so the HTTP path
            # stays responsive. apply() re-validates freshness in a fresh transaction.
            claim = (request, due_rows, fingerprints, now, rows)
        return self._call_agent(*claim)

    def _call_agent(self, request, due_rows, fingerprints, now, all_rows):
        from app import ai_classification, connected_agent_provider

        batch_ids = [row[0] for row in due_rows]
        if not self.agent_enabled():
            with self.runtime_lock, self.board._lock:
                for row in due_rows:
                    save_job(self.board.conn, row[0], fingerprints[row[0]],
                             {'status': 'blocked', 'reason': 'AGENT_NOT_ENABLED', 'attempts': 0,
                              'not_before': now + BLOCKED_RETRY_SECONDS})
                self.status['blocked'] += len(batch_ids)
                self.board.conn.commit()
                append_metric(self.board, {'kind': 'p2_blocked', 'cases': len(request['cases']),
                                           'reason': 'AGENT_NOT_ENABLED'})
                self._finish(all_rows)
            return True
        cap = connected_agent_provider.daily_cap(self._config_path())
        if p2_calls_today(self.board) >= cap:
            with self.runtime_lock, self.board._lock:
                for row in due_rows:
                    save_job(self.board.conn, row[0], fingerprints[row[0]],
                             {'status': 'blocked', 'reason': 'AGENT_DAILY_CAP', 'attempts': 0,
                              'not_before': now + BLOCKED_RETRY_SECONDS})
                self.status['blocked'] += len(batch_ids)
                self.board.conn.commit()
                append_metric(self.board, {'kind': 'p2_blocked', 'cases': len(request['cases']),
                                           'reason': 'AGENT_DAILY_CAP'})
                self._finish(all_rows)
            return True
        started = time.monotonic()
        try:
            if self.provider is not None:
                response = self.provider(request)
            else:
                model = self.agent_model or connected_agent_provider.configured_model(self._config_path())
                response = connected_agent_provider.run_agent(request, model=model)
        except Exception as exc:
            code = getattr(exc, 'code', type(exc).__name__)
            with self.runtime_lock, self.board._lock:
                for row in due_rows:
                    self._retry_or_dead(row, fingerprints[row[0]], now, str(code))
                self.board.conn.commit()
                append_metric(self.board, {'kind': 'p2_call', 'cases': len(request['cases']),
                                           'outcome': 'unavailable:' + str(code),
                                           'duration_ms': int((time.monotonic() - started) * 1000)})
                self._finish(all_rows)
            return True
        response = {key: value for key, value in response.items() if not key.startswith('_')}
        with self.runtime_lock, self.board._lock:
            try:
                trips, nets = self._fresh_context()
                result = ai_classification.apply(
                    self.board.conn, trips, request, response,
                    request_id='connected-agent:' + response['execution']['run_id'], nets=nets)
            except Exception as exc:
                self.board.conn.rollback()
                for row in due_rows:
                    self._retry_or_dead(row, fingerprints[row[0]], now, 'apply_' + type(exc).__name__)
                self.board.conn.commit()
                append_metric(self.board, {'kind': 'p2_call', 'cases': len(request['cases']),
                                           'outcome': 'apply_failed:' + type(exc).__name__,
                                           'duration_ms': int((time.monotonic() - started) * 1000)})
                self._finish(all_rows)
                return True
            applied = int((result or {}).get('applied') or 0) if isinstance(result, dict) else 0
            for row in due_rows:
                save_job(self.board.conn, row[0], fingerprints[row[0]], {'status': 'p2_applied', 'attempts': 0})
            self.board.conn.commit()
            self.status['p2_applied'] += len(batch_ids)
            append_metric(self.board, {'kind': 'p2_call', 'cases': len(request['cases']), 'applied': applied,
                                       'outcome': 'applied',
                                       'run_id': response.get('execution', {}).get('run_id'),
                                       'model': response.get('execution', {}).get('model'),
                                       'duration_ms': int((time.monotonic() - started) * 1000)})
            self._finish(all_rows)
            return True

    def _fresh_context(self):
        flow, trips, nets, inputs = self._held_context()
        return trips, nets

    def _retry_or_dead(self, row, fingerprint_value, now, reason, *, not_before=None):
        job = load_job(self.board.conn, row[0]) or {}
        attempts = int(job.get('attempts') or 0) + 1
        if attempts >= MAX_ATTEMPTS:
            save_job(self.board.conn, row[0], fingerprint_value,
                     {'status': 'ai_dead', 'attempts': attempts, 'reason': reason})
            self.status['ai_dead'] += 1
            return
        delay = not_before - now if not_before is not None else min(900, 60 * 2 ** (attempts - 1))
        save_job(self.board.conn, row[0], fingerprint_value,
                 {'status': 'ai_retry', 'attempts': attempts, 'reason': reason,
                  'not_before': now + delay})
        self.status['ai_retry'] += 1

    def _finish(self, all_rows):
        bundles = detect_bundles(self.board.conn)
        self.board.conn.commit()
        self.status['suspected_defects'] = bundles
        counts = job_counts(self.board.conn)
        for key in ('p2_applied', 'no_ai_needed', 'ai_retry', 'ai_dead', 'blocked'):
            self.status[key] = counts.get(key, self.status[key])
        self.status['jobs'] = counts


def enabled_for(board):
    from app import connected_agent_provider
    return connected_agent_provider.enabled(board.path.parent.parent / 'config/card-flow.json')
