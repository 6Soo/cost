"""Synthetic concurrency regression for the P2 assembly lock boundary."""
import json
import threading

from webapp.autonomous_cleanup_worker import AutonomousCleanupWorker
from webapp.deployment_role import route_lock
from webapp.tests.test_autonomous_cleanup import setup, receive, make_weak_rows, create_trip, response_for


def test_p2_assembly_does_not_hold_route_or_runtime_lock(setup, tmp_path, monkeypatch):
    route = tmp_path / 'route.json'
    route.write_text(json.dumps({'paused': False, 'port': 12345}), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_ROUTE', str(route))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_PORT', '12345')
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    make_weak_rows(setup, batch, rows, trip)
    entered, release, acquired = threading.Event(), threading.Event(), threading.Event()

    class Repository:
        def select(self, case, row):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('synthetic timeout')
            return []

    worker = AutonomousCleanupWorker(setup, setup._lock, provider=response_for, evidence_repository=Repository())
    thread = threading.Thread(target=worker.sweep_once)
    thread.start()
    try:
        assert entered.wait(5)
        def competitor():
            with route_lock(route), setup._lock:
                acquired.set()
        competitor_thread = threading.Thread(target=competitor)
        competitor_thread.start()
        try:
            assert acquired.wait(1), 'P2 assembly held the route or runtime lock'
        finally:
            release.set()
            competitor_thread.join(5)
    finally:
        release.set()
        thread.join(5)


def test_freshness_assembly_does_not_hold_route_or_runtime_lock(setup, tmp_path, monkeypatch):
    from tests.test_p2_worker_boundaries import rich_response
    route = tmp_path / 'route.json'
    route.write_text(json.dumps({'paused': False, 'port': 12345}), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_ROUTE', str(route))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_PORT', '12345')
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    make_weak_rows(setup, batch, rows, trip)
    entered, release, acquired = threading.Event(), threading.Event(), threading.Event()

    class Repository:
        count = 0
        def select(self, case, row):
            self.count += 1
            if self.count == 2:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('synthetic timeout')
            return []

    worker = AutonomousCleanupWorker(setup, setup._lock, provider=rich_response, evidence_repository=Repository())
    thread = threading.Thread(target=worker.sweep_once)
    thread.start()
    try:
        assert entered.wait(5)
        def competitor():
            with route_lock(route), setup._lock:
                acquired.set()
        competing = threading.Thread(target=competitor)
        competing.start()
        try:
            assert acquired.wait(1), 'freshness assembly held the route or runtime lock'
        finally:
            release.set()
            competing.join(5)
    finally:
        release.set()
        thread.join(5)


def test_window_closes_during_provider_prevents_apply(setup, monkeypatch):
    from webapp import autonomous_cleanup_worker as module
    from webapp.autonomous_cleanup_worker import load_job
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    window = [True]
    monkeypatch.setattr(module, '_options', lambda path: {'autonomous_ai_review_window': {}})
    monkeypatch.setattr(module, 'p2_window_open', lambda path: window[0])
    def provider(request):
        window[0] = False
        return response_for(request)
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider)
    worker.sweep_once()
    assert load_job(setup.conn, ids[0])['status'] == 'blocked'
    assert load_job(setup.conn, ids[0])['reason'] == 'AGENT_OUTSIDE_WINDOW'
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 0


def test_concurrent_sweeps_do_not_assemble_beyond_first_fifty(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 55)
    make_weak_rows(setup, batch, rows, trip)
    entered, release = threading.Event(), threading.Event()
    selected = []
    class Repository:
        def select(self, case, row):
            selected.append(row['transaction_id'])
            entered.set()
            if not release.wait(10):
                raise RuntimeError('synthetic timeout')
            return []
    first = AutonomousCleanupWorker(setup, setup._lock, provider=response_for,
                                    evidence_repository=Repository(), chunk=50)
    second = AutonomousCleanupWorker(setup, setup._lock, provider=response_for,
                                     evidence_repository=Repository(), chunk=50)
    thread = threading.Thread(target=first.sweep_once)
    thread.start()
    try:
        assert entered.wait(10)
        other = threading.Thread(target=second.sweep_once)
        other.start()
        try:
            other.join(2)
        finally:
            release.set()
            other.join(10)
    finally:
        release.set()
        thread.join(10)
    assert len(set(selected)) <= 50


def test_running_owned_process_is_cancelled_when_window_closes(tmp_path):
    import os
    import sys
    import time
    import pytest
    from app.connected_agent_provider import _run_bounded, AgentUnavailable
    started = time.monotonic()
    def check():
        if time.monotonic() - started > .3:
            raise AgentUnavailable('AGENT_OUTSIDE_WINDOW')
    with pytest.raises(AgentUnavailable, match='AGENT_OUTSIDE_WINDOW'):
        _run_bounded([sys.executable, '-c', 'import time; time.sleep(20)'], cwd=tmp_path,
                     env=dict(os.environ), timeout=10, check=check)
    assert time.monotonic() - started < 5


def test_window_closes_during_freshness_prevents_apply(setup, monkeypatch):
    from webapp import autonomous_cleanup_worker as module
    from webapp.autonomous_cleanup_worker import load_job
    from tests.test_p2_worker_boundaries import rich_response
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    window = [True]
    monkeypatch.setattr(module, '_options', lambda path: {'autonomous_ai_review_window': {}})
    monkeypatch.setattr(module, 'p2_window_open', lambda path: window[0])
    class Repository:
        count = 0
        def select(self, case, row):
            self.count += 1
            if self.count == 2:
                window[0] = False
            return []
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=rich_response, evidence_repository=Repository())
    worker.sweep_once()
    assert load_job(setup.conn, ids[0])['status'] == 'blocked'
    assert load_job(setup.conn, ids[0])['reason'] == 'AGENT_OUTSIDE_WINDOW'
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 0


def test_evidence_byte_budget_aborts_before_oversized_source_is_loaded(setup, tmp_path, monkeypatch):
    import pytest
    from app import ota_mail, p2_case
    from tests.test_p2_case import prepared
    request, trips = prepared(setup)
    source = tmp_path / 'gmail-large.json'
    source.write_bytes(b'0' * 4096)
    monkeypatch.setattr(p2_case, 'EVIDENCE_CASE_BYTES', 1024, raising=False)
    loaded = []
    monkeypatch.setattr(ota_mail, 'load_messages_from', lambda dirs: (loaded.append(True) or {}, []))
    monkeypatch.setattr(ota_mail, '_load_messages_uncached', lambda dirs: (loaded.append(True) or {}, []))
    repository = p2_case.Repository(setup.conn, {'mail_directories': [source]})
    repository.begin_snapshot()
    with pytest.raises(ValueError, match='P2_READ_BUDGET_EXCEEDED'):
        p2_case.assemble(setup.conn, trips, request, repository=repository)
    assert loaded == []



def test_index_candidates_match_full_scan(tmp_path, monkeypatch):
    import itertools
    from app import ota_mail, p2_case
    mail = tmp_path / 'mail'
    mail.mkdir()
    (mail / 'gmail-a.json').write_bytes(b'1')
    texts = ['AUTONOMY 10,000 on 2026-10-01', 'AUTONOMY ref XAB123456Z', 'AUTONOMY card 99382012',
             'AUTONOMY 110000 12026-10-015', 'OTHER 10000 2026-10-01', 'AUTONOMY 100001', 'autonomy ab123456',
             'AUTONOMY 2026-10-0', 'AUTONOMY 1000 0', 'AUTONOMY 3820']
    monkeypatch.setattr(ota_mail, '_load_messages_uncached', lambda dirs: ({str(i): {'payload': {}} for i in range(len(texts))}, []))
    bodies = iter(texts)
    monkeypatch.setattr(ota_mail, 'body_text', lambda payload: next(bodies))
    repo = p2_case.Repository(None, {'mail_directories': [mail]})
    rows = [dict(transaction_id='t', merchant='AUTONOMY', approval_number=a, amount_krw=m, card_tail=c, approval_date=d)
            for a, m, c, d in itertools.product(['', 'AB123456', 'AB-123456'], ['', '10000', '1,000'],
                                                ['', '3820', 'x1'], ['', '2026-10-01', '2026/10/01'])]
    indexed = [[e['ref'] for e in repo._source_evidence(row)] for row in rows]
    monkeypatch.setattr(p2_case._Index, 'candidates', lambda self, row: range(len(self.entries)))
    assert indexed == [[e['ref'] for e in repo._source_evidence(row)] for row in rows]
    assert any(indexed) and not all(indexed)

def test_no_bundle_assembly_runs_under_board_lock(setup, monkeypatch):
    from app import p2_case
    from tests.test_p2_worker_boundaries import rich_response
    trip = create_trip(setup)
    batch, rows = receive(setup, 2)
    make_weak_rows(setup, batch, rows, trip)
    held, original = [], p2_case.assemble
    def assemble(*args, **kwargs):
        held.append(setup._lock._is_owned())
        return original(*args, **kwargs)
    monkeypatch.setattr(p2_case, 'assemble', assemble)
    class Repository:
        def select(self, case, row):
            return []
    AutonomousCleanupWorker(setup, setup._lock, provider=rich_response, evidence_repository=Repository()).sweep_once()
    assert held and not any(held)
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 2


def test_ledger_change_after_unlocked_rebuild_refuses_apply(setup, monkeypatch):
    # Only history evidence differs between the unlocked rebuild (read snapshot)
    # and the writer connection; apply's own revision binding cannot see it.
    from app import p2_case
    from webapp.autonomous_cleanup_worker import load_job
    from tests.test_p2_worker_boundaries import rich_response
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    repository = p2_case.Repository(setup.conn, {})
    def history(row):
        if repository.conn is setup.conn:
            return [dict(ref='history:changed', kind='history', transaction_id=row['transaction_id'], content={'x': 1})]
        return []
    monkeypatch.setattr(repository, 'history', history)
    AutonomousCleanupWorker(setup, setup._lock, provider=rich_response, evidence_repository=repository).sweep_once()
    assert load_job(setup.conn, ids[0])['status'] == 'ai_retry'
    assert load_job(setup.conn, ids[0])['reason'] == 'apply_AI_EVIDENCE_STALE'
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 0


def test_source_loader_checks_between_real_read_blocks(setup, tmp_path):
    import pytest
    from app import p2_case
    source = tmp_path / 'mail'
    source.mkdir()
    # Real file I/O, not a mocked loader; cancellation must happen inside load.
    path = source / 'gmail-large.json'
    path.write_text(json.dumps({'responses': [], 'padding': 'x' * (3 << 20)}), encoding='utf-8')
    repo = p2_case.Repository(setup.conn, {'mail_directories': [source]})
    def check():
        if repo.read_bytes >= 1 << 20:
            raise RuntimeError('synthetic-window-closed')
    repo.begin_snapshot(check)
    with pytest.raises(RuntimeError, match='synthetic-window-closed'):
        repo.source_items({'transaction_id': 'one'})
    assert 1 << 20 <= repo.read_bytes < path.stat().st_size
    assert not repo._snapshot  # incomplete index is never reusable


def test_index_build_has_internal_time_checks(setup, tmp_path, monkeypatch):
    import pytest
    from app import ota_mail, p2_case
    mail = tmp_path / 'mail'
    mail.mkdir()
    (mail / 'gmail-one.json').write_text('{"responses": []}', encoding='utf-8')
    monkeypatch.setattr(ota_mail, '_load_messages_uncached', lambda dirs: ({}, []))
    original = p2_case._Index.__init__
    def slow_index(self, entries, size, check=lambda: None):
        monkeypatch.setattr(p2_case, 'EVIDENCE_CASE_SECONDS', -1)
        original(self, [('AUTONOMY 10000', {}, None)], size, check)
    monkeypatch.setattr(p2_case._Index, '__init__', slow_index)
    repo = p2_case.Repository(setup.conn, {'mail_directories': [mail]})
    repo.begin_snapshot()
    with pytest.raises(ValueError, match='P2_READ_TIME_EXCEEDED'):
        repo.source_items({'transaction_id': 'one'})
    assert not repo._snapshot


def test_native_sqlite_scan_preserves_gate_cancellation(tmp_path):
    import pytest
    from app import ota_store
    from app.p2_source_io import guarded
    import sqlite3
    path = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE numbers(n)')
        conn.executemany('INSERT INTO numbers VALUES(?)', [(i,) for i in range(100)])
    checked = [0]
    def check():
        checked[0] += 1
        if checked[0] > 5:
            raise RuntimeError('synthetic-window-closed')
    with pytest.raises(RuntimeError, match='synthetic-window-closed'):
        with guarded(check, lambda *a, **kw: None):
            conn = ota_store.connect_read(path)
            try:
                conn.execute('SELECT sum(a.n*b.n*c.n) FROM numbers a,numbers b,numbers c').fetchone()
            finally:
                conn.close()
    assert checked[0] == 6


def test_source_change_after_rebuild_before_writer_refuses_apply(setup, tmp_path, monkeypatch):
    from app import p2_case
    from tests.test_p2_worker_boundaries import rich_response
    from webapp.autonomous_cleanup_worker import load_job
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    mail = tmp_path / 'mail'
    mail.mkdir()
    source = mail / 'gmail-a.json'
    source.write_text('{"responses": []}', encoding='utf-8')
    repo = p2_case.Repository(setup.conn, {'mail_directories': [mail]})
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=rich_response, evidence_repository=repo)
    original = worker._verify_fresh_unlocked
    def rebuild(*a, **kw):
        result = original(*a, **kw)
        (mail / 'gmail-added.json').write_text('{"responses": []}', encoding='utf-8')
        return result
    monkeypatch.setattr(worker, '_verify_fresh_unlocked', rebuild)
    worker.sweep_once()
    assert load_job(setup.conn, ids[0])['reason'] == 'apply_AI_EVIDENCE_STALE'
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 0


def test_p2_refresh_does_not_rebuild_p1_evidence_context(setup, monkeypatch):
    from tests.test_p2_worker_boundaries import rich_response
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    make_weak_rows(setup, batch, rows, trip)
    class Repository:
        def select(self, case, row):
            return []
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=rich_response, evidence_repository=Repository())
    calls, held = [], worker._held_context
    def context():
        calls.append('p1')
        return held()
    monkeypatch.setattr(worker, '_held_context', context)
    worker.sweep_once()
    assert calls == ['p1']
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 1


def test_split_prompts_count_all_assembled_cases_toward_first_fifty(setup, monkeypatch):
    from app import p2_case
    from tests.test_p2_worker_boundaries import rich_response
    trip = create_trip(setup)
    batch, rows = receive(setup, 65)
    make_weak_rows(setup, batch, rows, trip)
    seen = set()
    class Repository:
        def select(self, case, row):
            seen.add(row['transaction_id'])
            return []
    original = p2_case.assemble
    def split(*a, **kw):
        bundle = original(*a, **kw)
        if len(a[2]['cases']) > 10:
            raise ValueError('P2_PROMPT_BASE_TOO_LARGE')
        return bundle
    monkeypatch.setattr(p2_case, 'assemble', split)
    calls = []
    def provider(request):
        calls.append(request['digest'])
        response = rich_response(request)
        response['execution']['run_id'] = 'synthetic-split-' + str(len(calls))
        return response
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider,
                                     evidence_repository=Repository(), chunk=20)
    for _ in range(4):
        worker.sweep_once()
    assert len(seen) == 50
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 30


def test_growing_source_is_stopped_by_actual_case_and_round_bytes(setup, tmp_path, monkeypatch):
    import pytest
    from app import p2_case, p2_source_io
    for budget in ('EVIDENCE_CASE_BYTES', 'EVIDENCE_ROUND_BYTES'):
        mail = tmp_path / budget
        mail.mkdir()
        source = mail / 'gmail-one.json'
        source.write_text('{"responses": []}', encoding='utf-8')
        read_text = p2_source_io.read_text
        def grow(path):
            if path == source:
                source.write_text(json.dumps({'responses': [], 'padding': 'x' * (3 << 20)}), encoding='utf-8')
            return read_text(path)
        with monkeypatch.context() as patch:
            patch.setattr(p2_source_io, 'read_text', grow)
            patch.setattr(p2_case, budget, (2 << 20) + 1024)
            repo = p2_case.Repository(setup.conn, {'mail_directories': [mail]})
            repo.begin_snapshot()
            with pytest.raises(ValueError, match='P2_READ_BUDGET_EXCEEDED'):
                repo.source_items({'transaction_id': 'one'})
            assert 1 << 20 <= repo.read_bytes <= (2 << 20) + 1024
            assert not repo._snapshot
