import pytest

from app import ota_mail, ota_portal, p2_case
from tests.test_p2_case import prepared
from webapp.tests.test_autonomous_cleanup import setup, receive, make_weak_rows, create_trip
from webapp.autonomous_cleanup_worker import AutonomousCleanupWorker, load_job


def test_request_snapshot_reuses_sources_but_refreshes(setup, tmp_path, monkeypatch):
    # Contract (2026-11-11 P2 I/O budget): unchanged sources are answered from the
    # index without reading them again; a changed source is read again.
    request, trips = prepared(setup)
    path = tmp_path / 'portal.db'
    path.write_bytes(b'1')
    mail = tmp_path / 'mail'
    mail.mkdir()
    (mail / 'gmail-a.json').write_bytes(b'1')
    calls = []
    monkeypatch.setattr(ota_mail, '_load_messages_uncached', lambda dirs: (calls.append('mail') or {}, []))
    monkeypatch.setattr(ota_portal, '_read_records', lambda path, index: calls.append('portal') or [])
    repo = p2_case.Repository(setup.conn, {'portal_databases': [path], 'mail_directories': [mail]})
    repo.begin_snapshot()
    first = p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert p2_case.assemble(setup.conn, trips, request, repository=repo) == first
    assert calls == ['mail', 'portal']
    repo.begin_snapshot()
    p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert calls == ['mail', 'portal'] and repo.read_bytes == 0
    path.write_bytes(b'22')
    (mail / 'gmail-a.json').write_bytes(b'22')
    repo.begin_snapshot()
    p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert calls == ['mail', 'portal', 'mail', 'portal'] and repo.read_bytes == 4


def test_source_scan_is_cancellable(setup, tmp_path, monkeypatch):
    request, trips = prepared(setup)
    mail = tmp_path / 'mail'
    mail.mkdir()
    (mail / 'gmail-a.json').write_bytes(b'1')
    monkeypatch.setattr(ota_mail, '_load_messages_uncached', lambda dirs: ({str(i): {'payload': {}} for i in range(100)}, []))
    monkeypatch.setattr(ota_mail, 'body_text', lambda payload: 'AUTONOMY 10000 2026-10-01')
    count = [0]
    def check():
        count[0] += 1
        if count[0] == 10:
            raise RuntimeError('cancelled')
    repo = p2_case.Repository(setup.conn, {'mail_directories': [mail]})
    repo.begin_snapshot(check)
    with pytest.raises(RuntimeError, match='cancelled'):
        p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert count[0] == 10


def test_stop_during_assembly_prevents_reservation(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    calls = []
    class Repository:
        def select(self, case, row):
            worker.stop()
            return []
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=lambda req: calls.append(req), evidence_repository=Repository())
    worker.sweep_once()
    assert calls == []
    assert setup.conn.execute("SELECT COUNT(*) FROM requests WHERE scope='p2_call_reservation'").fetchone()[0] == 0

@pytest.mark.parametrize('gate', ['disabled', 'window', 'timeout'])
def test_changed_gate_during_assembly_prevents_call(setup, monkeypatch, gate):
    from app import frontier_agent_provider
    from webapp import autonomous_cleanup_worker as module
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    make_weak_rows(setup, batch, rows, trip)
    calls = []
    class Repository:
        def select(self, case, row):
            if gate == 'disabled':
                monkeypatch.setattr(worker, 'agent_enabled', lambda: False)
            elif gate == 'window':
                monkeypatch.setattr(module, '_options', lambda path: {'autonomous_ai_review_window': {}})
                monkeypatch.setattr(module, 'p2_window_open', lambda path: False)
            else:
                monkeypatch.setattr(frontier_agent_provider, 'TIMEOUT_SECONDS', 0)
            return []
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=lambda req: calls.append(req), evidence_repository=Repository())
    worker.sweep_once()
    assert calls == []
    assert setup.conn.execute("SELECT COUNT(*) FROM requests WHERE scope='p2_call_reservation'").fetchone()[0] == 0


def test_changed_source_after_call_refuses_apply(setup, tmp_path, monkeypatch):
    from tests.test_p2_worker_boundaries import rich_response
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    mail = tmp_path / 'mail'
    mail.mkdir()
    source = mail / 'gmail-a.json'
    source.write_bytes(b'first')
    monkeypatch.setattr(ota_mail, '_load_messages_uncached', lambda dirs: ({'one': {'payload': {'headers': []}}}, []))
    monkeypatch.setattr(ota_mail, 'body_text', lambda payload: 'AUTONOMY 10000 2026-10-01 ' + source.read_text())
    repo = p2_case.Repository(setup.conn, {'mail_directories': [mail]})
    def provider(request):
        source.write_bytes(b'changed')
        return rich_response(request)
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider, evidence_repository=repo)
    worker.sweep_once()
    assert load_job(setup.conn, ids[0])['status'] == 'ai_retry'
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 0
    assert repo._snapshot is None


def test_snapshot_keeps_loaded_portal_when_file_disappears_then_refreshes(setup, tmp_path, monkeypatch):
    request, trips = prepared(setup)
    path = tmp_path / 'portal.db'
    path.touch()
    monkeypatch.setattr(ota_mail, 'load_messages_from', lambda dirs: ({}, []))
    monkeypatch.setattr(ota_portal, '_read_records', lambda path, index: [
        {'text': 'AUTONOMY 10000 2026-10-01', 'database': index}])
    repo = p2_case.Repository(setup.conn, {'portal_databases': [path]})
    repo.begin_snapshot()
    first = p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert any(item['kind'] == 'portal' for item in first['evidence'])
    path.unlink()
    assert p2_case.assemble(setup.conn, trips, request, repository=repo) == first
    repo.begin_snapshot()
    assert not any(item['kind'] == 'portal' for item in p2_case.assemble(setup.conn, trips, request, repository=repo)['evidence'])
