"""Resume durable card imports without HTTP retries or raw-source/network scans."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
from app.partial_refund import read_only_scope as refund_evidence_scope

INTERVAL = 30
CHUNK = 50
JOB_SCOPE = 'card_completion_job'


def queue_batch(board, batch_id, transaction_ids=None):
    """Persist exact resumable row IDs before classification can commit."""
    from app.db import utc_now
    with board._lock:
        identities = set(transaction_ids) if transaction_ids is not None else {
            r[0] for r in board.conn.execute('SELECT transaction_id FROM import_batch_rows WHERE batch_id=?',(batch_id,))}
        key = 'card-completion:'+batch_id
        old = board.conn.execute('SELECT response_json FROM requests WHERE request_id=? AND scope=?',(key,JOB_SCOPE)).fetchone()
        if old:
            state = json.loads(old[0])
            if state.get('pending'):
                identities.update(state['ids'])
        state = json.dumps({'pending':True,'ids':sorted(identities)})
        board.conn.execute('INSERT INTO requests VALUES (?,?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET response_json=excluded.response_json WHERE requests.scope=excluded.scope',
            (key,JOB_SCOPE,_digest(batch_id),state,utc_now()))
        board.conn.commit()


def finish_jobs(board):
    with board._lock:
        pending = {row[0] for row in candidates(board.conn)}
        for key, raw in board.conn.execute('SELECT request_id,response_json FROM requests WHERE scope=?',(JOB_SCOPE,)).fetchall():
            state = json.loads(raw)
            if state.get('pending') and not pending.intersection(state['ids']):
                state['pending'] = False
                board.conn.execute('UPDATE requests SET response_json=? WHERE request_id=? AND scope=?',(json.dumps(state),key,JOB_SCOPE))
        board.conn.commit()


def enabled_for(board):
    """Activation is an explicit host option, separate from a code deployment."""
    try:
        options = json.loads((board.path.parent.parent / 'config/card-flow.json').read_text(encoding='utf-8-sig'))
        return options.get('automatic_card_completion') is True
    except FileNotFoundError:
        return os.environ.get('WEBLEDGER_CARD_COMPLETION') == '1'
    except (OSError, ValueError, AttributeError):
        return False


def candidates(conn):
    # Existing rows are the durable queue, including receive() committed before
    # an exception or process exit. A reservation/payment link is never changed.
    return conn.execute(
        "WITH imported AS MATERIALIZED (SELECT transaction_id,MIN(batch_id) batch_id"
        " FROM import_batch_rows GROUP BY transaction_id),"
        " queued AS MATERIALIZED (SELECT j.value transaction_id FROM requests q, json_each(q.response_json,'$.ids') j"
        " WHERE q.scope='card_completion_job' AND json_extract(q.response_json,'$.pending')=1),"
        " refund_originals AS MATERIALIZED (SELECT DISTINCT issuer,card_tail,original_approval_number"
        " FROM transactions WHERE COALESCE(original_approval_number,'')!=''"
        " AND (transaction_direction IN ('cancellation','refund') OR amount_krw<0))"
        " SELECT t.transaction_id,b.batch_id,t.revision,t.classification_state,"
        "t.classification_source,t.item,t.display_tab_id,t.trip_id,t.source_hash"
        " FROM imported b JOIN transactions t USING(transaction_id)"
        " LEFT JOIN refund_originals f ON f.issuer=t.issuer AND f.card_tail=t.card_tail"
        " AND f.original_approval_number=t.approval_number"
        " WHERE t.transaction_direction='purchase' AND t.amount_krw>0"
        " AND (t.classification_state NOT IN ('classified','booked') OR COALESCE(t.item,'')=''"
        " OR t.transaction_id IN (SELECT transaction_id FROM queued))"
        " AND COALESCE(t.parse_error,'')='' AND COALESCE(t.conflict_reason,'')=''"
        " AND COALESCE(t.duplicate_of,'')='' AND t.decided_at IS NULL"
        " AND COALESCE(t.classification_source,'') NOT IN"
        " ('user_decision','user_exception','owner_booking','manual','manual_hold')"
        " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM board_rows r WHERE r.row_id='card-'||t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM review_decisions d WHERE d.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM board_manual_overrides o WHERE o.row_id='card-'||t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM transaction_company_exclusions e WHERE e.transaction_id=t.transaction_id AND e.excluded=1)"
        " AND f.original_approval_number IS NULL"
        " ORDER BY b.batch_id,t.row_index,t.transaction_id").fetchall()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class CardCompletionWorker:
    def __init__(self, board, runtime_lock, *, interval=INTERVAL, chunk=CHUNK, clock=time.monotonic,
                 flow_factory=None):
        self.board, self.runtime_lock = board, runtime_lock
        self.interval, self.chunk, self.clock = interval, chunk, clock
        self.flow_factory = flow_factory
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread = None
        self._attempts = {}
        self.status = {'state': 'idle', 'passes': 0, 'recorded': 0, 'failures': 0}

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self):
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='card-completion', daemon=True)
            self._thread.start()
        return self._thread

    def wake(self):
        self._wake.set()

    def stop(self, timeout=5):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def _publish(self):
        # Aggregate operational evidence only; the queue survives in SQLite.
        path = self.board.path.parent / 'card-completion-status.json'
        temporary = path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(dict(self.status, updated_at=time.time())), encoding='utf-8')
            temporary.replace(path)
        except OSError:
            pass  # A status-file failure cannot cancel committed work.

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
            # Drain further bounded chunks, then wait or wake on a new upload.
            delay = self.interval
            if self._attempts:
                delay = min(delay, max(.1, min(entry[1] for entry in self._attempts.values()) - self.clock()))
            self._wake.wait(.1 if worked else delay)
        self.status['state'] = 'stopped'
        self._publish()

    @refund_evidence_scope()
    def sweep_once(self):
        from .card_flow import CardFlow
        from .card_classification_completion import context
        from . import ota_payment_review

        # Same order as HTTP handlers: one writer for this connection. The
        # freshness-held snapshot prevents raw parsing or network inside locks.
        with self.runtime_lock, self.board._lock:
            if self._stop.is_set():
                return False
            rows = candidates(self.board.conn)
            self.status['pending'] = len(rows)
            self._attempts = {r[0]: self._attempts[r[0]] for r in rows if r[0] in self._attempts}
            if not rows:
                self.status['state'] = 'idle'
                finish_jobs(self.board)
                return False
            flow = (self.flow_factory or CardFlow)(self.board)
            held = (flow._held_ota_snapshot() if ota_payment_review.enabled() else (None, False))
            flow._held_ota_snapshot = lambda: held
            published_report = flow._canonical_snapshot_report(held[0]) if held[0] and held[1] else None
            # Recording metadata/holds use the same publication as classification;
            # they must not fall back to a raw-source scan either.
            flow._ota_report = lambda: published_report
            trips, nets = context(flow)
            rules = self.board.conn.execute('SELECT rule_id,version,status,rule_hash FROM cost_classification_rules ORDER BY rule_id').fetchall()
            inputs = _digest((trips, nets, rules, (held[0] or {}).get('generation'), held[1]))
            now, selected, batch = self.clock(), [], None
            for row in rows:
                token = _digest((row, inputs))
                previous = self._attempts.get(row[0])
                if previous and previous[0] == token and previous[1] > now:
                    continue
                if batch is None:
                    batch = row[1]
                if row[1] == batch:
                    selected.append(row)
                if len(selected) == self.chunk:
                    break
            if not selected:
                self.status['state'] = 'waiting'
                return False
            ids = {r[0] for r in selected}
            self.status['passes'] += 1
            self.status['state'] = 'running'
            try:
                queue_batch(self.board,batch,ids)
                unfinished = {row[0] for row in selected if row[4]!='guide_airfare_evidence'
                              and (row[3]!='classified' or not row[5])}
                if unfinished:
                    flow._classify(batch, transaction_ids=unfinished, snapshot_only=True)
                missing_assignment = {row[0] for row in selected if row[0] not in unfinished
                    and row[4]!='guide_airfare_evidence' and row[5]!='분기 기타비용'
                    and row[6] in (None,'','unclassified') and row[7] in (None,'','unclassified')}
                if missing_assignment:
                    from .card_classification_completion import complete
                    # A crash after successful classification must resume its
                    # recording, not replace stronger saved booking evidence.
                    complete(flow,batch,missing_assignment)
                result = flow._auto_record_locked(batch, include_state=False, transaction_ids=ids)
            except Exception as exc:
                self.status.update(state='retry', error=type(exc).__name__)
                self.status['failures'] += 1
                for row in selected:
                    count = self._attempts.get(row[0], (None, 0, 0))[2] + 1
                    current = self.board.conn.execute('SELECT revision,classification_state,classification_source,item,display_tab_id,trip_id,source_hash FROM transactions WHERE transaction_id=?', (row[0],)).fetchone()
                    token = _digest(((row[0], row[1], *current), inputs))
                    self._attempts[row[0]] = (token, now + min(300, 5 * 2 ** min(count - 1, 6)), count)
            else:
                self.status['recorded'] += result['auto_recorded']
                self.status.pop('error', None)
                # A genuine policy/authority hold is retried when its evidence
                # changes, or after five minutes, without monopolizing a batch.
                for row in candidates(self.board.conn):
                    if row[0] in ids:
                        self._attempts[row[0]] = (_digest((row, inputs)), now + 300, 0)
                finish_jobs(self.board)
            return True
