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
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from pathlib import Path
import threading
import uuid
import re

from app.partial_refund import read_only_scope as refund_evidence_scope
from .deployment_role import active_writer, writer

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
# PR #631 verified and resolved this historical date-alias conflict pattern.
# Preserve its transaction conflict records, but do not reopen them as a code
# defect whenever the autonomous worker groups repeated causes.
RESOLVED_TRANSACTION_CONFLICT_FINGERPRINTS = frozenset({
    '349b777b720eec2918cce955a216ef52ae021a6ad0b8d94b0c33232793a4f9cc',
})
CODE_FINGERPRINT_FILES = (
    'app/connected_agent_provider.py', 'app/ai_classification.py',
    'app/automatic_classification.py', 'app/rules.py',
    'webapp/autonomous_cleanup_worker.py', 'webapp/card_classification_completion.py',
    'app/p2_case.py', 'app/frontier_agent_provider.py',
    'app/p2_source_io.py', 'app/ota_mail.py', 'app/ota_portal.py', 'app/ota_store.py',
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


class WriterInactive(RuntimeError):
    """This process lost the writer role mid-round; leave state to the active writer."""


def failure_code(exc):
    candidate = getattr(exc, 'code', None) or str(exc)
    return candidate if isinstance(candidate, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{2,80}', candidate) else type(exc).__name__


def detection_sql(*, after=False):
    from .card_classification_completion import missing_assignment_sql
    return (
        "SELECT t.transaction_id, b.batch_id, t.revision, t.classification_state,"
        " t.classification_source, t.item, t.display_tab_id, t.trip_id, t.source_hash, t.approval_date"
        " FROM (SELECT transaction_id,MIN(batch_id) batch_id FROM import_batch_rows GROUP BY transaction_id) b"
        " JOIN transactions t USING(transaction_id)"
        " LEFT JOIN (SELECT DISTINCT issuer, card_tail, original_approval_number"
        "   FROM transactions"
        "   WHERE COALESCE(original_approval_number,'')!=''"
        "     AND (transaction_direction IN ('cancellation','refund') OR amount_krw < 0)) f"
        "   ON f.issuer = t.issuer AND f.card_tail = t.card_tail AND f.original_approval_number = t.approval_number"
        " WHERE t.transaction_direction = 'purchase' AND t.amount_krw > 0"
        " AND (COALESCE(t.item,'') IN ('기타경비','현지경비','여행경비')"
        "      OR COALESCE(t.display_tab_id,'') = '' OR COALESCE(t.display_tab_id,'') = 'unclassified'"
        "      OR (t.classification_source IN ('inference','auto_inferred','code_inference','pattern','card_category','provider_default')"
        "          AND t.classification_basis NOT LIKE '%P2_METADATA%')"
        "      OR " + missing_assignment_sql() + ")"
        " AND COALESCE(t.parse_error,'') = '' AND COALESCE(t.conflict_reason,'') = ''"
        " AND COALESCE(t.duplicate_of,'') = '' AND t.decided_at IS NULL"
        " AND COALESCE(t.classification_source,'') NOT IN"
        " ('user_decision','user_exception','owner_booking','manual','manual_hold','ai_inference',"
        "  'guide_airfare_evidence','refund_original','rule','auto')"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM ledger_entries)"
        " AND t.transaction_id NOT IN (SELECT substr(row_id, 6) FROM board_rows WHERE row_id LIKE 'card-%')"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM review_decisions)"
        " AND t.transaction_id NOT IN (SELECT substr(row_id, 6) FROM board_manual_overrides WHERE row_id LIKE 'card-%')"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM transaction_review_holds)"
        " AND t.transaction_id NOT IN (SELECT transaction_id FROM transaction_company_exclusions WHERE excluded = 1)"
        " AND f.original_approval_number IS NULL"
        + (" AND (t.approval_date < ? OR (t.approval_date = ? AND t.transaction_id > ?))" if after else "")
        + " ORDER BY t.approval_date DESC, t.transaction_id LIMIT 400")


def detection_candidates(conn):
    rows, after = [], None
    while True:
        page = conn.execute(detection_sql(after=after is not None), after or ()).fetchall()
        rows.extend(page)
        if len(page) < 400:
            return rows
        last = page[-1]
        after = (last[9], last[9], last[0])


def _options(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def p2_window_open(config_path, *, now=None):
    """Local KST 22:00 inclusive to 06:00 exclusive; a configured window overrides."""
    try:
        window = _options(config_path).get('autonomous_ai_review_window', {'start': '22:00', 'end': '06:00'})
        start = datetime.strptime(window['start'], '%H:%M').time()
        end = datetime.strptime(window['end'], '%H:%M').time()
        local = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=9))).time()
        if start < end:
            return start <= local < end
        return local >= start or local < end if start > end else False
    except (OSError, ValueError, TypeError, KeyError):
        return False


CALL_SCOPE = 'p2_call_reservation'
ASSEMBLY_SCOPE = 'p2_assembly_reservation'


def reserved_cases(conn):
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT value FROM requests,json_each(requests.response_json,'$.transaction_ids') WHERE scope IN (?,?)",
        (CALL_SCOPE, ASSEMBLY_SCOPE))}


def reserved_calls_today(conn):
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    return conn.execute("SELECT COUNT(*) FROM requests WHERE scope=? AND json_extract(response_json,'$.local_date')=?",
                        (CALL_SCOPE, today)).fetchone()[0]


def reserve_call(conn, ids, model):
    from app.db import utc_now
    key = 'p2-call:' + uuid.uuid4().hex
    payload = dict(transaction_ids=ids, model=model, outcome='started',
                   local_date=datetime.now(timezone(timedelta(hours=9))).date().isoformat())
    conn.execute('INSERT INTO requests VALUES (?,?,?,?,?)',
                 (key, CALL_SCOPE, _digest(payload), json.dumps(payload), utc_now()))
    return key


def finish_call(conn, key, outcome, duration_ms):
    conn.execute("UPDATE requests SET response_json=json_set(response_json,'$.outcome',?,'$.duration_ms',?) "
                 "WHERE request_id=? AND scope=?", (outcome, duration_ms, key, CALL_SCOPE))


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
    rows = []
    transaction_groups = conn.execute(
        "SELECT COALESCE(NULLIF(conflict_reason,''), NULLIF(parse_error,'')) signature, COUNT(*) count"
        ", SUM(CASE WHEN COALESCE(conflict_reason,'') != '' THEN 1 ELSE 0 END) conflict_count"
        ", SUM(CASE WHEN COALESCE(parse_error,'') != '' THEN 1 ELSE 0 END) parse_error_count"
        " FROM transactions"
        " WHERE COALESCE(conflict_reason,'') != '' OR COALESCE(parse_error,'') != ''"
        " GROUP BY signature HAVING COUNT(*) >= 8").fetchall()
    for signature, count, conflict_count, parse_error_count in transaction_groups:
        fingerprint_value = hashlib.sha256(str(signature).encode('utf-8')).hexdigest()
        if (fingerprint_value in RESOLVED_TRANSACTION_CONFLICT_FINGERPRINTS
                and conflict_count == count and parse_error_count == 0):
            continue
        rows.append(('transaction', signature, count))
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
    zone = timezone(timedelta(hours=9))
    today = datetime.now(zone).date()
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
                try:
                    at = datetime.fromisoformat(str(event.get('ts', '')).replace('Z', '+00:00')).astimezone(zone).date()
                except ValueError:
                    continue
                if event.get('kind') == 'p2_call' and at == today:
                    count += int(event.get('calls', 1))
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
                 flow_factory=None, provider=None, agent_config=None, agent_model=None, evidence_repository=None):
        self.board, self.runtime_lock = board, runtime_lock
        self.interval, self.chunk, self.clock = interval, chunk, clock
        self.flow_factory = flow_factory
        self.provider = provider
        self.agent_config = agent_config
        self.agent_model = agent_model
        self.evidence_repository = evidence_repository
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

    @refund_evidence_scope()
    def sweep_once(self):
        claim = self._prepare_sweep()
        if not isinstance(claim, tuple):
            return claim
        return self._call_agent(*claim)

    @active_writer(default=False)
    def _prepare_sweep(self):
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
            due_rows = [row for row in rows if row[0] in due_ids]
            due_rows = due_rows[:max(1, min(50, self.chunk))]
            if not due_rows:
                self.board.conn.commit()
                self._finish(rows)
                return False
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
                self.board.conn.commit()
            except Exception as exc:
                for row in due_rows:
                    self._retry_or_dead(row, fingerprints[row[0]], now, 'p1_' + type(exc).__name__,
                                        not_before=now + P1_RETRY_SECONDS)
                self.board.conn.commit()
                self._finish(rows)
                return True
            # Rollout controls P2 only. P1 above must publish for every due chunk.
            if _options(self._config_path()).get('autonomous_p2_full_rollout') is not True:
                reserved = reserved_cases(self.board.conn)
                # Other live claims also consume first-batch capacity before they
                # reserve a model call. Otherwise concurrent sweeps can each
                # assemble 50 distinct cases while no call has yet been reserved.
                own_ids = {row[0] for row in due_rows}
                for key, raw in self.board.conn.execute(
                        "SELECT request_id,response_json FROM requests WHERE scope=?", (JOB_SCOPE,)):
                    try:
                        job = json.loads(raw)
                        tid = key.removeprefix('autonomous-cleanup:')
                        if (tid not in own_ids and job.get('status') == 'awaiting_agent'
                                and now - _updated_at_epoch(job) <= STALE_PROCESSING_SECONDS):
                            reserved.add(tid)
                    except (ValueError, TypeError, AttributeError):
                        continue
                remaining = max(0, 50 - len(reserved))
                eligible = []
                for row in due_rows:
                    if row[0] in reserved:
                        eligible.append(row)
                    elif remaining:
                        eligible.append(row)
                        remaining -= 1
                    else:
                        save_job(self.board.conn, row[0], fingerprints[row[0]],
                                 {'status': 'blocked', 'reason': 'AGENT_FIRST_BATCH_LIMIT', 'attempts': 0,
                                  'not_before': now + BLOCKED_RETRY_SECONDS})
                due_rows = eligible
            if not due_rows:
                self.board.conn.commit()
                self._finish(rows)
                return True
            ids = [row[0] for row in due_rows]
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
            self.board.conn.commit()  # P1 is published before any P2 gate/call.
            return (request, due_rows, fingerprints, now, rows)

    def _call_agent(self, request, due_rows, fingerprints, now, all_rows):
        from app import p2_case
        try:
            return self._call_agent_impl(request, due_rows, fingerprints, now, all_rows)
        except WriterInactive:
            return False
        finally:
            if isinstance(self.evidence_repository, p2_case.Repository):
                self.evidence_repository.end_snapshot()

    @contextmanager
    def _writer_locks(self):
        """Short writer section: route lock, then runtime and board locks."""
        with writer() as active:
            if not active:
                raise WriterInactive('WRITER_INACTIVE')
            with self.runtime_lock, self.board._lock:
                yield

    @contextmanager
    def _read_view(self, repository):
        """Read-only ledger connection for P2 evidence; never takes writer locks."""
        import sqlite3
        from app import p2_case
        reader = sqlite3.connect(self.board.path.resolve().as_uri() + '?mode=ro', uri=True)
        owned = isinstance(repository, p2_case.Repository)
        try:
            reader.execute('BEGIN')
            if owned:
                repository.conn = reader
            yield reader
        finally:
            if owned:
                repository.conn = self.board.conn
            reader.close()

    def _verify_fresh_unlocked(self, request, bundle, repository, lookups, check_budget, bundle_limit, trips):
        """Rebuild the bundle from a read snapshot outside the writer locks.

        Returns the ledger inputs that rebuild used. The caller re-reads only those
        under the writer lock and must find them unchanged before apply."""
        from app import p2_case
        owned = isinstance(repository, p2_case.Repository)
        if owned:
            repository.begin_snapshot(check_budget, new_round=False)
        source_stamp = repository.source_stamp() if owned else None
        policy_stamp = p2_case.policy_stamp()
        gathered = []
        with self._read_view(repository) as reader:
            ledger = self._ledger_inputs(reader, request, repository, lookups)
            rows = {r['transaction_id']: r for r in ledger[0]}
            for case in sorted(request['cases'], key=lambda c: c['transaction_id']):
                row = rows.get(case['transaction_id'])
                if row is None:
                    raise ValueError('AI_EVIDENCE_STALE')
                gathered.extend(repository.source_items(row) if owned else repository.select(case, row))
            for query in lookups:
                if not owned or query['kind'] != 'card_search':
                    gathered.extend(repository.lookup(query['kind'], query['query'], query['transaction_id']))
            current = p2_case.assemble(reader, trips, request, repository=None, max_bytes=bundle_limit,
                                       extra=gathered + ledger[1])
        if current != bundle:
            raise ValueError('AI_EVIDENCE_STALE')
        if (policy_stamp != p2_case.policy_stamp() or
                owned and (not repository.snapshot_is_current() or repository.source_stamp() != source_stamp)):
            raise ValueError('AI_EVIDENCE_STALE')
        return ledger, source_stamp, policy_stamp

    def _ledger_inputs(self, conn, request, repository, lookups):
        """Case rows plus ledger-backed evidence (history, card lookups) read on `conn`."""
        from app import p2_case
        rows = p2_case._read(conn, [c['transaction_id'] for c in request['cases']])
        evidence = []
        if isinstance(repository, p2_case.Repository):
            for row in rows:
                evidence.extend(repository.history(row))
            for query in lookups:
                if query['kind'] == 'card_search':
                    evidence.extend(repository.lookup(query['kind'], query['query'], query['transaction_id']))
        return rows, evidence

    def _call_agent_impl(self, request, due_rows, fingerprints, now, all_rows):
        from app import ai_classification, connected_agent_provider, frontier_agent_provider, p2_case

        batch_ids = [row[0] for row in due_rows]
        gate = None
        if not self.agent_enabled():
            gate = 'AGENT_NOT_ENABLED'
        elif (self.provider is None or 'autonomous_ai_review_window' in _options(self._config_path())) and not p2_window_open(self._config_path()):
            gate = 'AGENT_OUTSIDE_WINDOW'
        if gate:
            with self._writer_locks():
                for row in due_rows:
                    save_job(self.board.conn, row[0], fingerprints[row[0]],
                             {'status': 'blocked', 'reason': gate, 'attempts': 0,
                              'not_before': now + BLOCKED_RETRY_SECONDS})
                self.status['blocked'] += len(batch_ids)
                self.board.conn.commit()
                append_metric(self.board, {'kind': 'p2_blocked', 'cases': len(request['cases']),
                                           'reason': gate})
                self._finish(all_rows)
            return True
        cap = connected_agent_provider.daily_cap(self._config_path())
        if max(p2_calls_today(self.board), reserved_calls_today(self.board.conn)) >= cap:
            with self._writer_locks():
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
        bundle = None
        repository = self.evidence_repository
        model = self.agent_model or frontier_agent_provider.configured_model(self._config_path())
        extra, lookups = [], []
        call_count = 0
        bundle_limit = p2_case.MAX_BYTES - 2048
        try:
            last_gate_check = [0.0]
            def check_budget(force=False):
                current = time.monotonic()
                if self._stop.is_set():
                    raise connected_agent_provider.AgentUnavailable('AGENT_STOPPED')
                if current - started >= frontier_agent_provider.TIMEOUT_SECONDS:
                    raise connected_agent_provider.AgentUnavailable('AGENT_TIMEOUT')
                if force or current - last_gate_check[0] >= .25:
                    last_gate_check[0] = current
                    if not self.agent_enabled():
                        raise connected_agent_provider.AgentUnavailable('AGENT_NOT_ENABLED', BLOCKED_RETRY_SECONDS)
                    if (self.provider is None or 'autonomous_ai_review_window' in _options(self._config_path())) and not p2_window_open(self._config_path()):
                        raise connected_agent_provider.AgentUnavailable('AGENT_OUTSIDE_WINDOW', BLOCKED_RETRY_SECONDS)
            if self.provider is None:
                bundle_limit = frontier_agent_provider.bundle_budget()
            if self.provider is None and repository is None:
                from app import ota_sources, ota_portal
                from .ota_payment_review import SOURCES_ENV
                import os
                raw = os.environ.get(SOURCES_ENV, '').strip()
                sources = json.loads(raw) if raw else ota_sources.resolve_sources(
                    self.board.path.parent, mail_default=os.environ.get('WEBLEDGER_OTA_MAIL_DIR') or self.board.path.parent / 'ota-mail',
                    portal_default=ota_portal.evidence_path(self.board.path.parent))
                repository = p2_case.Repository(self.board.conn, sources)
            if repository is not None:
                # Assembly consumes first-batch capacity even when an oversized
                # prompt is split before any model call. Persist before reads.
                with self._writer_locks():
                    check_budget(force=True)
                    if reserved_calls_today(self.board.conn) >= cap:
                        raise connected_agent_provider.AgentUnavailable('AGENT_DAILY_CAP', BLOCKED_RETRY_SECONDS)
                    from app.db import utc_now
                    payload = dict(transaction_ids=[c['transaction_id'] for c in request['cases']])
                    self.board.conn.execute('INSERT INTO requests VALUES (?,?,?,?,?)',
                        ('p2-assembly:' + uuid.uuid4().hex, ASSEMBLY_SCOPE, _digest(payload), json.dumps(payload), utc_now()))
                    self.board.conn.commit()
                if isinstance(repository, p2_case.Repository):
                    repository.begin_snapshot(check_budget)
                with self._writer_locks():
                    trips, _ = self._fresh_context()
                with self._read_view(repository) as reader:
                    while True:
                        try:
                            bundle = p2_case.assemble(reader, trips, request, repository=repository, max_bytes=bundle_limit)
                            break
                        except ValueError as exc:
                            if str(exc) != 'P2_PROMPT_BASE_TOO_LARGE' or len(request['cases']) < 2:
                                raise
                            keep = {c['transaction_id'] for c in request['cases'][:max(1, len(request['cases'])//2)]}
                            with self._writer_locks():
                                for row in due_rows:
                                    if row[0] not in keep:
                                        attempts = (load_job(self.board.conn, row[0]) or {}).get('attempts', 0)
                                        save_job(self.board.conn, row[0], fingerprints[row[0]], dict(status='ai_retry',
                                            reason='P2_BATCH_SPLIT', attempts=attempts, not_before=now+1))
                                due_rows = [row for row in due_rows if row[0] in keep]
                                batch_ids = [row[0] for row in due_rows]
                                trips, nets = self._fresh_context()
                                request = ai_classification.prepare(self.board.conn, trips, batch_ids, nets=nets)
                                self.board.conn.commit()
            retried_format, rounds = False, 0
            while True:
                with self._writer_locks():
                    check_budget(force=True)
                    if reserved_calls_today(self.board.conn) >= cap:
                        raise connected_agent_provider.AgentUnavailable('AGENT_DAILY_CAP', BLOCKED_RETRY_SECONDS)
                    reservation = reserve_call(self.board.conn, [c['transaction_id'] for c in request['cases']], model)
                    self.board.conn.commit()
                call_count += 1
                call_started, outcome = time.monotonic(), 'failed'
                try:
                    check_budget(force=True)
                    elapsed = time.monotonic() - started
                    response = (self.provider(request) if self.provider is not None else frontier_agent_provider.run_agent(
                        request, bundle=bundle, model=model, timeout=frontier_agent_provider.TIMEOUT_SECONDS - elapsed,
                        evidence_rounds_remaining=2-rounds, check=check_budget))
                    check_budget(force=True)
                    if bundle is not None:
                        queries = response.get('more_evidence')
                        if not isinstance(queries, list) or len(queries) > 8:
                            raise ValueError('AI_RESPONSE_SCHEMA_INVALID')
                        if queries:
                            if rounds >= 2:
                                raise ValueError('AI_MORE_EVIDENCE_LIMIT')
                            ids = {c['transaction_id'] for c in request['cases']}
                            # Lookups and re-assembly read a WAL snapshot outside the
                            # writer locks; apply re-validates under the lock.
                            with self._read_view(repository) as reader:
                                for query in queries:
                                    if set(query) != {'kind', 'query', 'transaction_id', 'why'} or not isinstance(query['why'], str) or len(query['why']) > 1000:
                                        raise ValueError('P2_LOOKUP_INVALID')
                                    p2_case.validate_lookup(query['kind'], query['query'], query['transaction_id'], ids)
                                    extra.extend(repository.lookup(query['kind'], query['query'], query['transaction_id']))
                                    lookups.append(query)
                                bundle = p2_case.assemble(reader, trips, request, repository=repository,
                                    max_bytes=bundle_limit, extra=extra)
                            rounds += 1
                            outcome = 'more_evidence'
                            continue
                        with self._writer_locks():
                            trips, nets = self._fresh_context()
                            ai_classification.preview(self.board.conn, trips, request, response, nets=nets, bundle=bundle)
                    outcome = 'validated'
                    break
                except Exception as exc:
                    code = getattr(exc, 'code', str(exc))
                    format_errors = {'AGENT_RESPONSE_INVALID', 'AI_RESPONSE_SCHEMA_INVALID', 'AI_RESULTS_INCOMPLETE',
                        'AI_REASON_REQUIRED', 'AI_SERVICE_PERIOD_INVALID', 'AI_SERVICE_UNCERTAINTY_REQUIRED'}
                    if not retried_format and code in format_errors:
                        retried_format = True
                        outcome = 'format_retry'
                        continue
                    raise
                finally:
                    with self._writer_locks():
                        finish_call(self.board.conn, reservation, outcome, int((time.monotonic()-call_started)*1000))
                        self.board.conn.commit()
        except Exception as exc:
            code = failure_code(exc)
            with self._writer_locks():
                for row in due_rows:
                    if code in ('AGENT_RATE_LIMITED', 'AGENT_DAILY_CAP', 'AGENT_OUTSIDE_WINDOW', 'AGENT_AUTH_REQUIRED', 'AGENT_NOT_ENABLED', 'AGENT_STOPPED'):
                        attempts = (load_job(self.board.conn, row[0]) or {}).get('attempts', 0)
                        save_job(self.board.conn, row[0], fingerprints[row[0]], dict(status='blocked', reason=code,
                            attempts=attempts, not_before=now + max(60, getattr(exc, 'retry_after', None) or BLOCKED_RETRY_SECONDS)))
                    else:
                        self._retry_or_dead(row, fingerprints[row[0]], now, str(code))
                self.board.conn.commit()
                append_metric(self.board, {'kind': 'p2_call', 'cases': len(request['cases']),
                                           'outcome': 'unavailable:' + str(code),
                                           'model': model, 'calls': call_count,
                                           'duration_ms': int((time.monotonic() - started) * 1000)})
                self._finish(all_rows)
            return True
        response = {key: value for key, value in response.items() if not key.startswith('_')}
        ledger = stale = None
        try:
            if bundle is not None:
                # Re-read sources and rebuild the bundle outside the writer locks;
                # under the lock only the ledger inputs are re-read and compared.
                ledger = self._verify_fresh_unlocked(request, bundle, repository, lookups, check_budget,
                                                     bundle_limit, trips)
        except Exception as exc:
            stale = exc
        with self._writer_locks():
            try:
                if stale is not None:
                    raise stale
                trips, nets = self._fresh_context()
                if bundle is not None:
                    ledger_inputs, source_stamp, policy_stamp = ledger
                    if (self._ledger_inputs(self.board.conn, request, repository, lookups) != ledger_inputs or
                            p2_case.policy_stamp() != policy_stamp or
                            isinstance(repository, p2_case.Repository) and repository.source_stamp() != source_stamp):
                        raise ValueError('AI_EVIDENCE_STALE')
                check_budget(force=True)
                result = ai_classification.apply(
                    self.board.conn, trips, request, response,
                    request_id='connected-agent:' + response['execution']['run_id'], nets=nets, bundle=bundle)
            except Exception as exc:
                self.board.conn.rollback()
                code = failure_code(exc)
                for row in due_rows:
                    if code in ('AGENT_OUTSIDE_WINDOW', 'AGENT_NOT_ENABLED', 'AGENT_STOPPED'):
                        attempts = (load_job(self.board.conn, row[0]) or {}).get('attempts', 0)
                        save_job(self.board.conn, row[0], fingerprints[row[0]], dict(
                            status='blocked', reason=code, attempts=attempts,
                            not_before=now + BLOCKED_RETRY_SECONDS))
                    else:
                        self._retry_or_dead(row, fingerprints[row[0]], now, 'apply_' + code)
                self.board.conn.commit()
                append_metric(self.board, {'kind': 'p2_call', 'cases': len(request['cases']),
                                           'outcome': 'apply_failed:' + code,
                                           'duration_ms': int((time.monotonic() - started) * 1000)})
                self._finish(all_rows)
                return True
            applied = int((result or {}).get('applied') or 0) if isinstance(result, dict) else 0
            for row in due_rows:
                save_job(self.board.conn, row[0], fingerprints[row[0]], {'status': 'p2_applied', 'attempts': 0})
            self.board.conn.commit()
            self.status['p2_applied'] += len(batch_ids)
            append_metric(self.board, {'kind': 'p2_call', 'cases': len(request['cases']), 'applied': applied,
                                       'calls': call_count,
                                       'outcome': 'applied',
                                       'run_id': response.get('execution', {}).get('run_id'),
                                       'model': response.get('execution', {}).get('model'),
                                       'duration_ms': int((time.monotonic() - started) * 1000)})
            self._finish(all_rows)
            return True

    def _fresh_context(self):
        # P2 needs only current trip candidates/net values. Rebuilding the P1
        # OTA matcher snapshot here would re-read all registered evidence while
        # holding writer locks, even though none of that report is used below.
        from .card_classification_completion import context
        return context((self.flow_factory or self._default_flow())(self.board))

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
