"""Autonomous P1->P2 loop: detection, durable jobs, provider gate, recovery."""
import json

import pytest

from app import ai_classification
from tests.card_pipeline.fixtures import make_csv, domestic_row
from webapp import card_cleanup_queries
from webapp.card_flow import CardFlow
from webapp.card_completion_worker import candidates
from webapp.autonomous_cleanup_worker import (
    AutonomousCleanupWorker, JOB_SCOPE, BUNDLE_SCOPE, detect_bundles,
    fingerprint, load_job, pending_job_ids, detection_candidates, p2_calls_today,
    save_job, _digest,
)
from webapp.ledger_store import LedgerStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', 'legacy')
    monkeypatch.delenv('WEBLEDGER_AUTONOMOUS_AI_REVIEW', raising=False)
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: True)
    board = LedgerStore(tmp_path / 'autonomous.sqlite', seed_demo=False)
    yield board
    board.close()


def receive(board, count=3, suffix=''):
    flow = CardFlow(board)
    batch = flow.pipeline.receive(make_csv([
        domestic_row(merchant='SYNTHETIC AUTONOMY ' + suffix + str(i), amount=10000 + i,
                     approval='AUT' + suffix + str(i), date='2026-10-03',
                     issuer='국민', card='****-3820') for i in range(count)]), 'autonomous.csv')['batch_id']
    return batch, flow.pipeline.get_batch(batch)['rows']


def make_weak_rows(board, batch, rows, trip_id='A', item='현지경비'):
    board.conn.execute(
        "UPDATE transactions SET classification_state='classified', classification_source='code_inference',"
        " item=?, trip_id=?, display_tab_id=? WHERE batch_id=?", (item, trip_id, trip_id, batch))
    board.conn.commit()
    return [r['transaction_id'] for r in rows]


def create_trip(board):
    return board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                             destination='합성 여행', client_request_id='autonomy-trip-a')['tab_id']


def response_for(request):
    return dict(request_digest=request['digest'],
                execution=dict(kind='connected_agent', provider='synthetic', model='synthetic-model',
                               run_id='synthetic-autonomy-run'),
                results=[dict(transaction_id=c['transaction_id'], trip_id=c['trips'][0]['trip_id'],
                              item='교통비', basis='합성 일정 대조', uncertainty='분류 용도만 판단')
                         for c in request['cases']])


def financial_snapshot(board):
    names = ('review_decisions', 'ledger_entries', 'transaction_review_holds',
             'transaction_company_exclusions', 'board_manual_overrides')
    return {name: board.conn.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in names}, \
        board.conn.execute('SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM transactions').fetchone()


def test_disabled_agent_marks_jobs_blocked_without_writing(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 2)
    ids = make_weak_rows(board, batch, rows, trip)
    before_rest, before_totals = financial_snapshot(board)

    worker = AutonomousCleanupWorker(board, board._lock, provider=None)
    assert worker.sweep_once() is True
    assert worker.sweep_once() is False

    jobs = {tid: load_job(board.conn, tid) for tid in ids}
    assert {job['status'] for job in jobs.values()} == {'blocked'}
    assert {job['reason'] for job in jobs.values()} == {'AGENT_NOT_ENABLED'}
    assert financial_snapshot(board) == (before_rest, before_totals)
    assert p2_calls_today(board) == 0
    assert not (board.path.parent / 'autonomous-cleanup-metrics.jsonl').read_text(encoding='utf-8').count('"p2_call"')


def test_enabled_agent_applies_p2_and_records_provenance(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 2)
    ids = make_weak_rows(board, batch, rows, trip)
    before_rest, before_totals = financial_snapshot(board)

    calls = []

    def provider(request):
        calls.append(request)
        return response_for(request)

    worker = AutonomousCleanupWorker(board, board._lock, provider=provider)
    assert worker.sweep_once() is True

    assert len(calls) == 1
    jobs = {tid: load_job(board.conn, tid) for tid in ids}
    assert {job['status'] for job in jobs.values()} == {'p2_applied'}
    applied = board.conn.execute(
        "SELECT classification_source FROM transactions WHERE transaction_id IN (?,?)", ids).fetchall()
    assert {row[0] for row in applied} == {'ai_inference'}
    audit = json.loads(board.conn.execute(
        "SELECT detail_json FROM change_log WHERE kind='card.classification_corrected' LIMIT 1").fetchone()[0])
    assert audit['execution']['model'] == 'synthetic-model'
    assert audit['source'] == 'agent_evidence_review'
    after_rest, after_totals = financial_snapshot(board)
    assert after_rest == before_rest and after_totals == before_totals
    metrics = (board.path.parent / 'autonomous-cleanup-metrics.jsonl').read_text(encoding='utf-8')
    assert '"kind": "p2_call"' in metrics and '"outcome": "applied"' in metrics


def test_restart_recovers_stale_processing_job_without_duplicates(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 2)
    ids = make_weak_rows(board, batch, rows, trip)

    worker = AutonomousCleanupWorker(board, board._lock, provider=None)
    worker.sweep_once()
    board.conn.execute(
        "UPDATE requests SET response_json = json_set(response_json, '$.status','awaiting_agent',"
        " '$.updated_at','2000-01-01T00:00:00+00:00') WHERE scope = ?", (JOB_SCOPE,))
    board.conn.commit()

    calls = []

    def provider(request):
        calls.append(request)
        return response_for(request)

    fresh = AutonomousCleanupWorker(board, board._lock, provider=provider)
    fresh.sweep_once()
    assert len(calls) == 1
    jobs = [load_job(board.conn, tid) for tid in ids]
    assert {job['status'] for job in jobs} == {'p2_applied'}
    ledger_count = board.conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE kind='card.classification_corrected'").fetchone()[0]
    assert ledger_count >= 1


def test_non_stale_pending_job_blocks_reprocessing(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)

    worker = AutonomousCleanupWorker(board, board._lock, provider=None)
    worker.sweep_once()
    board.conn.execute(
        "UPDATE requests SET response_json = json_set(response_json, '$.status','awaiting_agent') WHERE scope = ?",
        (JOB_SCOPE,))
    board.conn.commit()

    calls = []

    def provider(request):
        calls.append(request)
        return response_for(request)

    fresh = AutonomousCleanupWorker(board, board._lock, provider=provider)
    fresh.sweep_once()
    assert calls == []


def test_ai_failure_retries_with_backoff_then_dead_letters(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)

    def provider(request):
        raise RuntimeError('synthetic agent outage')

    worker = AutonomousCleanupWorker(board, board._lock, provider=provider)
    worker.sweep_once()
    job = load_job(board.conn, ids[0])
    assert job['status'] == 'ai_retry' and job['attempts'] == 1
    assert financial_snapshot(board)[1][0] == 1

    board.conn.execute(
        "UPDATE requests SET response_json = json_set(response_json, '$.not_before', 0) WHERE scope = ?",
        (JOB_SCOPE,))
    board.conn.commit()
    worker.sweep_once()
    job = load_job(board.conn, ids[0])
    assert job['status'] == 'ai_retry' and job['attempts'] == 2

    board.conn.execute(
        "UPDATE requests SET response_json = json_set(response_json, '$.not_before', 0) WHERE scope = ?",
        (JOB_SCOPE,))
    board.conn.commit()
    worker.sweep_once()
    job = load_job(board.conn, ids[0])
    assert job['status'] == 'ai_dead' and job['attempts'] == 3

    calls = []

    def counting_provider(request):
        calls.append(request)
        return response_for(request)

    restarted = AutonomousCleanupWorker(board, board._lock, provider=counting_provider)
    restarted.sweep_once()
    assert calls == []


def test_evidence_change_requeues_dead_job(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)

    def provider(request):
        raise RuntimeError('synthetic outage')

    worker = AutonomousCleanupWorker(board, board._lock, provider=provider)
    for _ in range(3):
        board.conn.execute(
            "UPDATE requests SET response_json = json_set(response_json, '$.not_before', 0) WHERE scope = ?",
            (JOB_SCOPE,))
        board.conn.commit()
        worker.sweep_once()
    assert load_job(board.conn, ids[0])['status'] == 'ai_dead'

    board.conn.execute("UPDATE transactions SET revision = revision + 1 WHERE transaction_id = ?", (ids[0],))
    board.conn.commit()
    calls = []

    def counting_provider(request):
        calls.append(request)
        return response_for(request)

    fresh = AutonomousCleanupWorker(board, board._lock, provider=counting_provider)
    fresh.sweep_once()
    assert len(calls) == 1
    assert load_job(board.conn, ids[0])['status'] == 'p2_applied'


def test_daily_cap_blocks_unbounded_ai_calls(setup, tmp_path):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    (config_dir / 'card-flow.json').write_text(json.dumps(
        {'automatic_card_completion': True, 'autonomous_ai_review': True,
         'autonomous_ai_review_daily_cap': 0}), encoding='utf-8')

    calls = []

    def provider(request):
        calls.append(request)
        return response_for(request)

    worker = AutonomousCleanupWorker(board, board._lock, provider=provider,
                                     agent_config=config_dir / 'card-flow.json')
    worker.sweep_once()
    assert calls == []
    assert load_job(board.conn, ids[0])['reason'] == 'AGENT_DAILY_CAP'


def test_cause_bundles_group_repeated_signatures(setup):
    board = setup
    batch, rows = receive(board, 9)
    signature = 'cleanup:date-mismatch-alternative-posting'
    for index, row in enumerate(rows):
        board.conn.execute("UPDATE transactions SET conflict_reason = ? WHERE transaction_id = ?",
                           (signature, row['transaction_id']))
    board.conn.commit()
    assert detect_bundles(board.conn) >= 1
    bundle = board.conn.execute(
        "SELECT json_extract(response_json,'$.signature'), json_extract(response_json,'$.count')"
        " FROM requests WHERE scope = ? AND json_extract(response_json,'$.signature') = ?",
        (BUNDLE_SCOPE, signature)).fetchone()
    assert bundle is not None and bundle[0] == signature and bundle[1] >= 9


def test_resolved_transaction_conflict_fingerprint_is_not_reopened_as_code_defect(setup, monkeypatch):
    import hashlib
    from webapp import autonomous_cleanup_worker as worker_module

    board = setup
    signature = 'synthetic-resolved-date-alias-conflict'
    batch, rows = receive(board, 9)
    for row in rows:
        board.conn.execute("UPDATE transactions SET conflict_reason = ? WHERE transaction_id = ?",
                           (signature, row['transaction_id']))
    board.conn.commit()
    monkeypatch.setattr(worker_module, 'RESOLVED_TRANSACTION_CONFLICT_FINGERPRINTS',
                        frozenset({hashlib.sha256(signature.encode('utf-8')).hexdigest()}))

    assert detect_bundles(board.conn) == 0
    assert board.conn.execute("SELECT COUNT(*) FROM requests WHERE scope = ?", (BUNDLE_SCOPE,)).fetchone()[0] == 0


def test_gateway_and_cleanup_worker_recover_together_without_financial_side_effects(setup, tmp_path):
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from tools.ledger_gateway import Gateway, atomic_json

    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 1, suffix='GATEWAY-RECOVERY-')
    ids = make_weak_rows(board, batch, rows, trip)
    before = financial_snapshot(board)

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'synthetic healthy')

        def log_message(self, *_args):
            pass

    backend = ThreadingHTTPServer(('127.0.0.1', 0), HealthHandler)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    route, status = tmp_path / 'gateway-route.json', tmp_path / 'gateway-status.json'
    atomic_json(route, {'port': backend.server_address[1], 'paused': False, 'generation': 'synthetic'})
    gateway = Gateway(0, route, status)
    gateway_thread = threading.Thread(target=lambda: gateway.serve_forever(poll_interval=.01), daemon=True)
    gateway_thread.start()
    calls = []

    class SyntheticExecutionFailure(Exception):
        code = 'AGENT_EXECUTION_FAILED'

    def fail_once_then_recover(request):
        calls.append(request)
        if len(calls) == 1:
            raise SyntheticExecutionFailure()
        return response_for(request)

    worker = AutonomousCleanupWorker(board, board._lock, provider=fail_once_then_recover)
    gateway_url = f'http://127.0.0.1:{gateway.server_address[1]}/healthz'
    try:
        assert worker.sweep_once() is True
        assert load_job(board.conn, ids[0])['status'] == 'ai_retry'
        with urllib.request.urlopen(gateway_url, timeout=3) as response:
            assert response.read() == b'synthetic healthy'

        retry = load_job(board.conn, ids[0])
        retry['not_before'] = 0
        save_job(board.conn, ids[0], retry['fingerprint'], retry)
        board.conn.commit()
        assert worker.sweep_once() is True
        assert load_job(board.conn, ids[0])['status'] == 'p2_applied'
        with urllib.request.urlopen(gateway_url, timeout=3) as response:
            assert response.read() == b'synthetic healthy'
        assert len(calls) == 2
        assert financial_snapshot(board) == before
    finally:
        gateway.shutdown()
        gateway.server_close()
        gateway_thread.join(timeout=3)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=3)


def test_cause_bundles_group_repeated_provider_code_failures_but_not_rate_limits(setup):
    from webapp.autonomous_cleanup_worker import code_fingerprint

    board = setup
    from app.db import Store as CardStore
    CardStore(board.conn)
    for index in range(9):
        save_job(board.conn, f'synthetic-provider-{index}', code_fingerprint(),
                 {'status': 'ai_retry', 'attempts': 1, 'reason': 'AGENT_EXECUTION_FAILED'})
    for index in range(9):
        save_job(board.conn, f'synthetic-rate-limit-{index}', code_fingerprint(),
                 {'status': 'ai_retry', 'attempts': 1, 'reason': 'AGENT_RATE_LIMITED'})
    board.conn.commit()

    assert detect_bundles(board.conn) == 1
    bundle = board.conn.execute(
        "SELECT json_extract(response_json,'$.signature'), json_extract(response_json,'$.count'),"
        " json_extract(response_json,'$.source') FROM requests WHERE scope = ?"
        " AND json_extract(response_json,'$.source') = 'worker'", (BUNDLE_SCOPE,)).fetchone()
    assert bundle == ('AGENT_EXECUTION_FAILED', 9, 'worker')


def test_decision_code_fingerprint_changes_when_relevant_code_changes(tmp_path):
    from webapp.autonomous_cleanup_worker import CODE_FINGERPRINT_FILES, code_fingerprint

    for index, relative in enumerate(CODE_FINGERPRINT_FILES):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'synthetic code {index}', encoding='utf-8')
    first = code_fingerprint(tmp_path)
    (tmp_path / CODE_FINGERPRINT_FILES[0]).write_text('synthetic verified fix', encoding='utf-8')
    assert code_fingerprint(tmp_path) != first


def test_verified_code_change_requeues_previously_dead_job(setup, monkeypatch):
    from webapp import autonomous_cleanup_worker as worker_module

    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)
    row = detection_candidates(board.conn)[0]

    monkeypatch.setattr(worker_module, 'code_fingerprint', lambda: 'verified-code-v1')
    worker_v1 = AutonomousCleanupWorker(board, board._lock, provider=lambda request: response_for(request))
    _, trips, nets, inputs_v1 = worker_v1._held_context()
    first = fingerprint(row, _digest(inputs_v1))
    save_job(board.conn, ids[0], first,
             {'status': 'ai_dead', 'attempts': 3, 'reason': 'AGENT_EXECUTION_FAILED'})
    board.conn.commit()
    assert ids[0] not in pending_job_ids(board.conn, {ids[0]: first})

    monkeypatch.setattr(worker_module, 'code_fingerprint', lambda: 'verified-code-v2')
    worker_v2 = AutonomousCleanupWorker(board, board._lock, provider=lambda request: response_for(request))
    _, trips, nets, inputs_v2 = worker_v2._held_context()
    second = fingerprint(row, _digest(inputs_v2))
    assert ids[0] in pending_job_ids(board.conn, {ids[0]: second})


def test_detection_excludes_protected_and_ai_reviewed_rows(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 4)
    ids = make_weak_rows(board, batch, rows, trip)
    board.conn.execute("UPDATE transactions SET conflict_reason='synthetic conflict' WHERE transaction_id=?", (ids[0],))
    board.conn.execute("UPDATE transactions SET duplicate_of=? WHERE transaction_id=?", (ids[1], ids[2]))
    board.conn.execute("UPDATE transactions SET classification_source='ai_inference' WHERE transaction_id=?", (ids[3],))
    board.conn.commit()
    detected = {row[0] for row in detection_candidates(board.conn)}
    assert ids[0] not in detected and ids[2] not in detected and ids[3] not in detected


def test_pending_job_ids_requires_fingerprint_match_or_expiry(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)
    row = detection_candidates(board.conn)[0]
    fp = fingerprint(row, 'inputs')
    fingerprints = {row[0]: fp}
    assert ids[0] in pending_job_ids(board.conn, fingerprints, now=1000)


def test_cleanup_no_longer_exposes_a_second_owner_action_queue(tmp_path, monkeypatch):
    import webapp.card_flow as card_flow
    from webapp import ledger_board

    board = LedgerStore(tmp_path / 'owner.sqlite', seed_demo=False)
    try:
        ledger_board.bind_store(board)
        monkeypatch.setattr(card_flow, '_ota_entries_by_card', lambda _b, **kw: {})
        header = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
                  'Date,Post Date,Authorization Code,Cancel,Status\n')
        lines = ('국민,1234,domestic,purchase,SYNTHETIC USER CASE,5000,,,5000,2026-10-03,2026-10-04,AU001,,매입\n'
                 '국민,1234,domestic,purchase,SYNTHETIC AUTO CASE,6000,,,6000,2026-10-03,2026-10-04,AU002,,매입\n')
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((header + lines).encode(), 'owner-synthetic.csv')['batch_id']
        transactions = board.conn.execute(
            "SELECT transaction_id, merchant FROM transactions WHERE batch_id = ?", (batch,)).fetchall()
        for tid, merchant in transactions:
            if 'USER' in merchant:
                board.conn.execute("UPDATE transactions SET parse_error='synthetic unreadable' WHERE transaction_id=?", (tid,))
            else:
                board.conn.execute(
                    "UPDATE transactions SET classification_state='classified', classification_source='code_inference',"
                    " item='현지경비', trip_id='', display_tab_id='' WHERE transaction_id=?", (tid,))
        board.conn.commit()

        html = card_flow.render_expense_cleanup(board, 'token')
        assert '/my-actions' not in html and '내 확인 필요' not in html
        assert '자동 진행·대기' not in html
        assert 'cleanup_owner=' not in html

        user_html = card_flow.render_expense_cleanup(board, 'token', owner='user')
        assert 'SYNTHETIC USER CASE' in user_html
        assert 'SYNTHETIC AUTO CASE' in user_html
        assert "cleanup_owner=" not in user_html

        auto_html = card_flow.render_expense_cleanup(board, 'token', owner='auto')
        assert 'SYNTHETIC AUTO CASE' in auto_html
        assert 'SYNTHETIC USER CASE' in auto_html
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_provider_resolves_real_exe_behind_cmd_shim(tmp_path, monkeypatch):
    from app import connected_agent_provider as provider
    bin_dir = tmp_path / 'npm' / 'node_modules' / 'opencode-ai' / 'bin'
    bin_dir.mkdir(parents=True)
    shim = tmp_path / 'npm' / 'opencode.cmd'
    shim.write_text('@echo off\n', encoding='utf-8')
    real = bin_dir / 'opencode.exe'
    real.write_bytes(b'')
    monkeypatch.delenv('WEBLEDGER_OPENCODE_EXE', raising=False)
    monkeypatch.setattr(provider.shutil, 'which', lambda name: str(shim))
    assert provider._executable() == str(real)


def test_provider_keeps_explicit_executable(tmp_path, monkeypatch):
    from app import connected_agent_provider as provider
    custom = tmp_path / 'opencode.exe'
    custom.write_bytes(b'')
    monkeypatch.setenv('WEBLEDGER_OPENCODE_EXE', str(custom))
    monkeypatch.setattr(provider.shutil, 'which', lambda name: None)
    assert provider._executable() == str(custom)


def test_provider_catalog_stays_on_free_tier():
    from app import connected_agent_provider as provider
    assert provider.DEFAULT_MODEL in provider.MODELS
    assert all(name.startswith('opencode/') and name.endswith('-free') for name in provider.MODELS)


def test_provider_attaches_large_review_request_from_private_temp_file(tmp_path, monkeypatch):
    import re
    import subprocess
    from pathlib import Path
    from app import connected_agent_provider as provider
    monkeypatch.setattr(provider, '_executable', lambda: 'synthetic-opencode')

    request = {'digest': 'synthetic-digest', 'cases': [
        {'transaction_id': f'synthetic-{index}', 'context': 'x' * 2400} for index in range(20)]}
    observed = {}

    def runner(command, *, cwd, env, timeout):
        command_line = subprocess.list2cmdline(command)
        assert len(command_line) < 10000
        assert 'x' * 100 not in command_line
        request_file = Path(command[command.index('--file') + 1])
        prompt = request_file.read_text(encoding='utf-8')
        assert len(prompt) > 32767
        assert json.dumps(request, ensure_ascii=False) in prompt
        observed['path'] = request_file
        run_id = re.search(r'run_id: ([a-f0-9]+)', prompt).group(1)
        answer = json.dumps({'request_digest': request['digest'],
                             'execution': {'kind': 'connected_agent', 'provider': 'opencode',
                                           'model': provider.DEFAULT_MODEL, 'run_id': run_id},
                             'results': []})
        event = json.dumps({'type': 'text', 'part': {'type': 'text', 'text': answer}}).encode('utf-8')
        return subprocess.CompletedProcess(command, 0, event, b'')

    result = provider.run_agent(request, runner=runner)
    assert result['execution']['kind'] == 'connected_agent'
    assert not observed['path'].exists()


def test_provider_classifies_windows_command_line_limit_without_exposing_error_text(monkeypatch):
    from app import connected_agent_provider as provider
    monkeypatch.setattr(provider, '_executable', lambda: 'synthetic-opencode')

    def runner(command, *, cwd, env, timeout):
        error = OSError('synthetic Windows command size failure')
        error.winerror = 206
        raise error

    with pytest.raises(provider.AgentUnavailable) as caught:
        provider.run_agent({'digest': 'synthetic', 'cases': []}, runner=runner)
    assert caught.value.code == 'AGENT_COMMAND_LINE_TOO_LONG'


def test_autonomous_interval_config_is_bounded_and_defaults_to_thirty_minutes(tmp_path):
    import json
    from webapp.autonomous_cleanup_worker import INTERVAL, configured_interval

    config = tmp_path / 'card-flow.json'
    assert INTERVAL == 1800
    assert configured_interval(config) == 1800
    config.write_text(json.dumps({'autonomous_cleanup_interval_seconds': 600}), encoding='utf-8')
    assert configured_interval(config) == 600
    config.write_text(json.dumps({'autonomous_cleanup_interval_seconds': 5}), encoding='utf-8')
    assert configured_interval(config) == 1800


def test_autonomous_status_skips_identical_writes_until_heartbeat(setup, monkeypatch):
    from webapp import autonomous_cleanup_worker as worker_module

    board = setup
    monotonic = [100.0]
    wall = [1000.0]
    monkeypatch.setattr(worker_module.time, 'time', lambda: wall[0])
    worker = AutonomousCleanupWorker(board, board._lock, clock=lambda: monotonic[0])
    worker._publish()
    path = board.path.parent / 'autonomous-cleanup-status.json'
    first = json.loads(path.read_text(encoding='utf-8'))

    worker._publish()
    assert json.loads(path.read_text(encoding='utf-8')) == first
    monotonic[0] += worker_module.STATUS_HEARTBEAT_SECONDS - 1
    worker._publish()
    assert json.loads(path.read_text(encoding='utf-8')) == first

    monotonic[0] += 1
    wall[0] += 300
    worker._publish()
    assert json.loads(path.read_text(encoding='utf-8'))['updated_at'] == 1300.0

    worker.status['state'] = 'running'
    worker._publish()
    assert json.loads(path.read_text(encoding='utf-8'))['state'] == 'running'
