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