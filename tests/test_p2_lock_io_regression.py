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
