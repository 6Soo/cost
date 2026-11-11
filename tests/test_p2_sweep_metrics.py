"""Durable stage counters and bounded pilot controls, using synthetic inputs only."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import p2_case
from app.connected_agent_provider import AgentUnavailable
from tests.test_p2_worker_boundaries import SyntheticRepository, rich_response
from webapp import autonomous_cleanup_worker as module
from webapp.tests.test_autonomous_cleanup import setup, receive, make_weak_rows, create_trip


def events(board):
    return [json.loads(line) for line in module.metrics_path(board).read_text(encoding='utf-8').splitlines()]


def prepare(board, count=2):
    trip = create_trip(board)
    batch, rows = receive(board, count)
    return make_weak_rows(board, batch, rows, trip)


def config(tmp_path, **options):
    path = tmp_path / 'pilot-config.json'
    path.write_text(json.dumps(options), encoding='utf-8')
    return path


def summary(board):
    result = events(board)
    end = result[-1]
    assert end['kind'] == 'p2_sweep_end'
    same = [e for e in result if e['sweep_id'] == end['sweep_id']]
    assert same[0]['stage'] == 'started'
    assert end['duration_ms'] >= 0
    return end


def test_off_records_zero_evidence_assembly_and_model_activity(setup, monkeypatch):
    prepare(setup)
    calls = []
    monkeypatch.setattr(p2_case, 'assemble', lambda *a, **kw: calls.append('assemble'))
    class Repository:
        def select(self, *args):
            calls.append('select')
            return []
    worker = module.AutonomousCleanupWorker(setup, setup._lock, evidence_repository=Repository())
    assert worker.sweep_once()
    end = summary(setup)
    assert end['candidates'] == end['selected'] == 2
    assert end['reason'] == 'AGENT_NOT_ENABLED'
    assert end['assembly_started'] == end['assembly_completed'] == end['model_attempts'] == 0
    assert end['source_read_attempts'] == end['lookup_attempts'] == 0
    assert calls == []
    assert end['preview_passed'] == end['applied'] == 0
    first_id = end['sweep_id']
    assert worker.sweep_once() is False
    assert summary(setup)['reason'] == 'NO_WORK'
    assert summary(setup)['sweep_id'] != first_id


def test_assembly_start_is_durable_before_source_read_failure(setup):
    prepare(setup)
    class Repository:
        def select(self, *args):
            latest = events(setup)[-1]
            assert latest['stage'] == 'assembly_started'
            assert latest['assembly_started'] == 2
            assert latest['assembly_completed'] == latest['model_attempts'] == 0
            raise ValueError('private customer content must never enter metrics')
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=rich_response,
                                             evidence_repository=Repository())
    assert worker.sweep_once()
    end = summary(setup)
    assert end['reason'] == 'ValueError'
    assert end['assembly_started'] == 2 and end['assembly_completed'] == 0
    assert end['source_read_attempts'] == 1 and end['lookup_attempts'] == 0
    assert end['model_attempts'] == 0
    assert 'private customer' not in module.metrics_path(setup).read_text(encoding='utf-8')


def test_snapshot_start_is_durable_before_any_assembly(setup, monkeypatch):
    prepare(setup, 1)
    repository = p2_case.Repository(setup.conn, {})
    def snapshot(*args, **kwargs):
        latest = events(setup)[-1]
        assert latest['stage'] == 'repository_snapshot_started'
        assert latest['source_read_attempts'] == 1
        assert latest['assembly_started'] == latest['model_attempts'] == 0
        raise ValueError('P2_READ_BUDGET_EXCEEDED')
    monkeypatch.setattr(repository, 'begin_snapshot', snapshot)
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=rich_response,
                                             evidence_repository=repository)
    assert worker.sweep_once()
    end = summary(setup)
    assert end['reason'] == 'P2_READ_BUDGET_EXCEEDED'
    assert end['source_read_attempts'] == 1
    assert end['assembly_started'] == end['model_attempts'] == 0


def test_model_failure_has_normalized_reason_and_no_preview_or_apply(setup):
    prepare(setup)
    def provider(request):
        assert events(setup)[-1]['stage'] == 'model_started'
        raise AgentUnavailable('AGENT_RATE_LIMITED', 420)
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=provider,
                                             evidence_repository=SyntheticRepository())
    assert worker.sweep_once()
    end = summary(setup)
    assert end['model_attempts'] == end['model_failures'] == 1
    assert end['model_successes'] == 0
    assert end['model_failure_reasons'] == {'AGENT_RATE_LIMITED': 1}
    assert end['reason'] == 'AGENT_RATE_LIMITED'
    assert end['preview_passed'] == end['applied'] == 0


def test_success_counts_preview_apply_and_freshness_assembly(setup):
    ids = prepare(setup)
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=rich_response,
                                             evidence_repository=SyntheticRepository())
    assert worker.sweep_once()
    end = summary(setup)
    assert end['candidates'] == end['selected'] == end['preview_passed'] == end['applied'] == 2
    assert end['assembly_started'] == end['assembly_completed'] == 4  # Initial + freshness, per case.
    assert end['model_attempts'] == end['model_successes'] == 1
    assert end['model_failures'] == 0 and end['model_failure_reasons'] == {}
    assert end['source_read_attempts'] == 3 and end['lookup_attempts'] == 0
    assert end['reason'] == 'APPLIED'
    text = module.metrics_path(setup).read_text(encoding='utf-8')
    assert all(tid not in text for tid in ids)


def test_exception_and_stopped_early_returns_always_end_the_round(setup, monkeypatch):
    worker = module.AutonomousCleanupWorker(setup, setup._lock)
    worker._stop.set()
    assert worker.sweep_once() is False
    assert summary(setup)['reason'] == 'AGENT_STOPPED'
    def fail():
        raise RuntimeError('sensitive exception details')
    monkeypatch.setattr(worker, '_prepare_sweep', fail)
    with pytest.raises(RuntimeError):
        worker.sweep_once()
    assert summary(setup)['reason'] == 'RuntimeError'
    assert 'sensitive exception' not in module.metrics_path(setup).read_text(encoding='utf-8')


def test_metric_io_failure_does_not_change_application(setup, monkeypatch):
    ids = prepare(setup)
    monkeypatch.setattr(module, 'metrics_path', lambda board: board.path.parent / 'missing' / 'metrics.jsonl')
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=rich_response)
    assert worker.sweep_once()
    assert all(module.load_job(setup.conn, tid)['status'] == 'p2_applied' for tid in ids)


def test_more_evidence_counts_each_lookup_and_model_call(setup):
    ids = prepare(setup, 1)
    calls = []
    def provider(request):
        calls.append(request)
        result = rich_response(request)
        if len(calls) == 1:
            result['results'] = []
            result['more_evidence'] = [dict(kind='mail_search', query='synthetic', why='synthetic', transaction_id=ids[0])]
        return result
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=provider,
                                             evidence_repository=SyntheticRepository())
    assert worker.sweep_once()
    end = summary(setup)
    assert end['lookup_attempts'] == 2  # Initial lookup and freshness revalidation.
    assert end['assembly_started'] == end['assembly_completed'] == 3
    assert end['model_attempts'] == end['model_successes'] == 2
    assert end['preview_passed'] == end['applied'] == 1


@pytest.mark.parametrize('deadline', ['2000-01-01T00:00:00Z', 'invalid', '', None,
    '2099-01-01T00:00:00', '2099-01-01T00:00:00+09:00'])
def test_expired_or_invalid_deadline_blocks_before_evidence(setup, tmp_path, deadline):
    prepare(setup)
    def forbidden(*args):
        raise AssertionError('provider must not run')
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=forbidden,
        evidence_repository=SyntheticRepository(),
        agent_config=config(tmp_path, autonomous_p2_pilot_deadline=deadline))
    assert worker.sweep_once()
    end = summary(setup)
    assert end['reason'] == 'AGENT_NOT_ENABLED'
    assert end['assembly_started'] == end['model_attempts'] == 0


def test_deadline_expiring_during_model_call_prevents_apply(setup, tmp_path):
    ids = prepare(setup)
    path = config(tmp_path, autonomous_p2_pilot_deadline=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
    def provider(request):
        config(tmp_path, autonomous_p2_pilot_deadline='2000-01-01T00:00:00Z')
        return rich_response(request)
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=provider, agent_config=path)
    assert worker.sweep_once()
    end = summary(setup)
    assert end['model_successes'] == 1 and end['applied'] == 0
    assert end['reason'] == 'AGENT_NOT_ENABLED'
    assert all(module.load_job(setup.conn, tid)['status'] == 'blocked' for tid in ids)


def test_deadline_expiring_during_assembly_prevents_model_call(setup, tmp_path):
    prepare(setup, 1)
    path = config(tmp_path, autonomous_p2_pilot_deadline=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
    class Repository:
        def select(self, *args):
            config(tmp_path, autonomous_p2_pilot_deadline='2000-01-01T00:00:00Z')
            return []
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=rich_response,
        evidence_repository=Repository(), agent_config=path)
    assert worker.sweep_once()
    end = summary(setup)
    assert end['reason'] == 'AGENT_NOT_ENABLED'
    assert end['assembly_started'] == end['assembly_completed'] == 1
    assert end['model_attempts'] == end['applied'] == 0


def test_pilot_five_then_fifty_counts_existing_reservations(setup, tmp_path):
    prepare(setup, 57)
    path = config(tmp_path, autonomous_p2_pilot_case_limit=5)
    seen = []
    def provider(request):
        seen.extend(c['transaction_id'] for c in request['cases'])
        result = rich_response(request)
        result['execution']['run_id'] += str(len(seen))
        return result
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=provider, chunk=50, agent_config=path)
    assert worker.sweep_once()
    assert len(seen) == len(module.reserved_cases(setup.conn)) == 5
    assert worker.sweep_once()
    assert len(seen) == 5
    config(tmp_path, autonomous_p2_pilot_case_limit=50)
    for _ in range(3):
        worker.sweep_once()
    assert len(seen) == len(set(seen)) == len(module.reserved_cases(setup.conn)) == 50


@pytest.mark.parametrize('limit', [0, 51, True, '5'])
def test_invalid_pilot_limit_selects_no_new_cases(setup, tmp_path, limit):
    prepare(setup)
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=rich_response,
        agent_config=config(tmp_path, autonomous_p2_pilot_case_limit=limit))
    worker.sweep_once()
    assert summary(setup)['reason'] == 'AGENT_FIRST_BATCH_LIMIT'
    assert summary(setup)['model_attempts'] == 0


def test_full_rollout_ignores_pilot_case_limit(setup, tmp_path):
    prepare(setup, 6)
    worker = module.AutonomousCleanupWorker(setup, setup._lock, provider=rich_response, chunk=50,
        agent_config=config(tmp_path, autonomous_p2_pilot_case_limit=5, autonomous_p2_full_rollout=True))
    assert worker.sweep_once()
    assert summary(setup)['applied'] == 6
