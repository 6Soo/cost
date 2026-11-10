import json
from datetime import datetime, timezone

import pytest

from app import connected_agent_provider
from webapp import autonomous_cleanup_worker as worker_module
from webapp.autonomous_cleanup_worker import AutonomousCleanupWorker, detection_candidates, load_job
from webapp.tests.test_autonomous_cleanup import setup, receive, make_weak_rows, create_trip, response_for


def test_detection_pages_past_400_and_deduplicates_imports(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 407)
    ids = make_weak_rows(setup, batch, rows, trip)
    setup.conn.execute("INSERT INTO import_batch_rows VALUES ('synthetic-copy',?,1)", (ids[0],))
    found = detection_candidates(setup.conn)
    assert len(found) == 407
    assert {r[0] for r in found} == set(ids)
    assert len({r[0] for r in found}) == 407


def test_specific_item_without_service_period_is_detected_but_exact_p1_stays_out(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 2)
    ids = make_weak_rows(setup, batch, rows, trip, item='숙박비')
    setup.conn.execute("UPDATE transactions SET classification_source='owner_booking' WHERE transaction_id=?", (ids[1],))
    assert [r[0] for r in detection_candidates(setup.conn)] == [ids[0]]


@pytest.mark.parametrize('utc,expected', [('2026-11-11T12:59:00+00:00', False),
    ('2026-11-11T13:00:00+00:00', True), ('2026-11-11T20:59:00+00:00', True),
    ('2026-11-11T21:00:00+00:00', False)])
def test_night_window_has_local_midnight_and_exclusive_end(tmp_path, utc, expected):
    assert worker_module.p2_window_open(tmp_path / 'missing.json', now=datetime.fromisoformat(utc)) is expected


def test_first_rollout_reserves_only_fifty_distinct_cases(setup, tmp_path):
    trip = create_trip(setup)
    batch, rows = receive(setup, 57)
    make_weak_rows(setup, batch, rows, trip)
    seen = []
    def provider(request):
        seen.extend(c['transaction_id'] for c in request['cases'])
        return response_for(request)
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider, chunk=50)
    for _ in range(3):
        worker.sweep_once()
    assert len(seen) == len(set(seen)) == 50
    assert any(load_job(setup.conn, r['transaction_id']).get('reason') == 'AGENT_FIRST_BATCH_LIMIT' for r in rows[50:])


def test_rate_limit_wait_preserves_attempts(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    def provider(_):
        raise connected_agent_provider.AgentUnavailable('AGENT_RATE_LIMITED', 420)
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider)
    worker.sweep_once()
    job = load_job(setup.conn, ids[0])
    assert job['status'] == 'blocked'
    assert job['attempts'] == 0
    assert job['reason'] == 'AGENT_RATE_LIMITED'


class SyntheticRepository:
    def __init__(self):
        self.calls = []

    def select(self, case, row):
        return []

    def lookup(self, kind, query, transaction_id):
        self.calls.append((kind, query, transaction_id))
        return [dict(ref='mail:synthetic', kind='mail', content='합성 이용기간', transaction_id=transaction_id)]


def rich_response(request):
    result = response_for(request)
    result['more_evidence'] = []
    for row in result['results']:
        row.update(service_start='', service_end='', evidence_refs=[], rule_ids=['PROC-001'])
    return result


def test_worker_completes_allowed_more_evidence_then_atomic_apply(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    repository = SyntheticRepository()
    calls = []
    def provider(request):
        calls.append(request)
        result = rich_response(request)
        if len(calls) == 1:
            result['results'] = []
            result['more_evidence'] = [dict(kind='mail_search', query='합성', why='이용기간', transaction_id=ids[0])]
        else:
            result['results'][0]['evidence_refs'] = ['mail:synthetic']
        return result
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider, evidence_repository=repository)
    assert worker.sweep_once()
    assert len(calls) == 2
    assert load_job(setup.conn, ids[0])['status'] == 'p2_applied'
    outcomes = [json.loads(r[0])['outcome'] for r in setup.conn.execute(
        "SELECT response_json FROM requests WHERE scope='p2_call_reservation' ORDER BY rowid")]
    assert outcomes == ['more_evidence', 'validated']


def test_worker_refuses_third_more_evidence_and_arbitrary_commands(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    repository = SyntheticRepository()
    calls = []
    def provider(request):
        calls.append(request)
        result = rich_response(request)
        result['results'] = []
        result['more_evidence'] = [dict(kind='mail_search', query='합성', why='이용기간', transaction_id=ids[0])]
        return result
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider, evidence_repository=repository)
    worker.sweep_once()
    assert len(calls) == 3
    assert load_job(setup.conn, ids[0])['status'] == 'ai_retry'
    assert setup.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 0


def test_format_error_retries_once_with_each_call_reserved(setup):
    from app.connected_agent_provider import AgentUnavailable
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    calls = []
    def provider(request):
        calls.append(request)
        if len(calls) == 1:
            raise AgentUnavailable('AGENT_RESPONSE_INVALID')
        return response_for(request)
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=provider)
    worker.sweep_once()
    assert len(calls) == 2
    assert load_job(setup.conn, ids[0])['status'] == 'p2_applied'
    assert worker_module.reserved_calls_today(setup.conn) == 2


def test_first_batch_p2_gate_never_prevents_p1_publication(setup):
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    setup.conn.execute("UPDATE transactions SET classification_state='needs_review',item='',trip_id='',display_tab_id='',classification_source=''")
    worker_module.reserve_call(setup.conn, ['synthetic-used-' + str(i) for i in range(50)], 'synthetic')
    setup.conn.commit()
    worker = AutonomousCleanupWorker(setup, setup._lock, provider=response_for)
    worker.sweep_once()
    state, item, tab = setup.conn.execute('SELECT classification_state,item,display_tab_id FROM transactions').fetchone()
    assert state == 'classified' and item and tab


@pytest.mark.parametrize('source', ['pattern','card_category','provider_default'])
def test_weak_category_p1_with_unknown_period_is_eligible_unless_exact_or_manual(setup, source):
    from app import ai_classification
    from webapp.card_classification_completion import context
    from webapp.card_flow import CardFlow
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip, item='숙박비')
    setup.conn.execute('UPDATE transactions SET classification_source=?', (source,))
    trips, nets = context(CardFlow(setup))
    assert [r[0] for r in detection_candidates(setup.conn)] == ids
    assert len(ai_classification.prepare(setup.conn, trips, ids, nets=nets)['cases']) == 1
    row = rows[0]
    # Existing source-bound exact OTA rule, not a source-label exemption.
    setup.conn.execute("INSERT INTO cost_classification_rules VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
        'synthetic-exact', 1, 'active', '{}', '{}', json.dumps({'source_hash':row['source_hash']}),
        '', 'owner-ota-booking', 'synthetic-exact-hash', 'synthetic', 'synthetic'))
    assert ai_classification.prepare(setup.conn, trips, ids, nets=nets)['cases'] == []
    setup.conn.execute("DELETE FROM cost_classification_rules WHERE rule_id='synthetic-exact'")
    setup.conn.execute("INSERT INTO board_manual_overrides VALUES (?,'service_period','synthetic-manual')", ('card-'+ids[0],))
    assert ai_classification.prepare(setup.conn, trips, ids, nets=nets)['cases'] == []


def test_default_worker_full_ota_refund_context_fits_cli_stdin_and_applies(setup, tmp_path, monkeypatch):
    import subprocess
    from datetime import timedelta
    from app import frontier_agent_provider as frontier, p2_case
    trip = create_trip(setup)
    batch, rows = receive(setup, 1)
    ids = make_weak_rows(setup, batch, rows, trip)
    class Repository(SyntheticRepository):
        def select(self, case, row):
            return [dict(ref='portal:synthetic',kind='portal',transaction_id=case['transaction_id'],
                         content=dict(reservation_status='cancelled',text='합성 취소 예약 원문'))]
    now = datetime.now(timezone(timedelta(hours=9)))
    config = tmp_path / 'default-worker-config.json'
    config.write_text(json.dumps(dict(autonomous_ai_review=True, autonomous_ai_review_daily_cap=1,
        autonomous_ai_review_window=dict(start=(now-timedelta(hours=1)).strftime('%H:%M'),end=(now+timedelta(hours=1)).strftime('%H:%M')))))
    monkeypatch.setattr(frontier, '_executable', lambda: 'synthetic-codex.exe')
    sizes=[]
    def runner(command, *, cwd, env, timeout, input_bytes):
        sizes.append(len(input_bytes))
        assert len(input_bytes) <= 262144
        decoded = input_bytes.decode()
        bundle = json.loads(decoded.split('\n',1)[1].split('\nEXECUTION:',1)[0])
        assert {'CORE','process','trip','item','date','link','refund'} == set(bundle['policy'])
        execution = json.loads(decoded.split('\nEXECUTION:',1)[1].split('\n',1)[0])
        answer = rich_response(dict(digest=bundle['request_digest'],cases=bundle['cases']))
        answer['execution']=execution
        answer['results'][0]['evidence_refs']=['portal:synthetic']
        from jsonschema import Draft202012Validator
        Draft202012Validator(json.loads(frontier.schema_path().read_text())).validate(answer)
        raw = '\n'.join(json.dumps(e) for e in [dict(type='thread.started',thread_id='synthetic'),
            dict(type='turn.started'),dict(type='item.completed',item=dict(type='agent_message',text=json.dumps(answer))),
            dict(type='turn.completed',usage={})]).encode()
        return subprocess.CompletedProcess(command,0,raw,b'')
    monkeypatch.setattr(frontier, '_run_bounded', runner)
    worker = AutonomousCleanupWorker(setup,setup._lock,agent_config=config,evidence_repository=Repository(),chunk=1)
    assert worker.provider is None
    worker.sweep_once()
    assert len(sizes) == 1 and sizes[0] > 200000
    assert load_job(setup.conn, ids[0])['status']=='p2_applied'
