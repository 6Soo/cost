import json
import sqlite3
import subprocess

import pytest

from app import automatic_classification as policy
from app import core_writer


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in (core_writer.WRITER_ENV, core_writer.BIN_ENV, core_writer.CORE_DB_ENV):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch, tmp_path


@pytest.mark.parametrize('value', [None, '', 'python', 'PYTHON', 'rusty', 'true'])
def test_python_is_the_default_writer_and_every_other_value_keeps_it(env, value):
    monkeypatch, _ = env
    if value is not None:
        monkeypatch.setenv(core_writer.WRITER_ENV, value)
    assert core_writer.selected() == 'python'


def test_only_rust_selects_the_core_and_unsetting_returns_to_python(env):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.WRITER_ENV, ' Rust ')
    assert core_writer.selected() == 'rust'
    monkeypatch.delenv(core_writer.WRITER_ENV)
    assert core_writer.selected() == 'python'


def test_python_apply_does_not_touch_the_core_writer_by_default(env, monkeypatch):
    monkeypatch.setattr(core_writer, 'apply', lambda *a, **k: pytest.fail('core writer used'))
    conn = sqlite3.connect(':memory:')
    with pytest.raises(sqlite3.OperationalError):  # reaches the Python path (no schema), not the core writer
        policy.apply(conn, {'digest': 'x'}, [])


def test_rust_writer_refuses_without_configuration_or_inside_a_transaction(env, tmp_path):
    monkeypatch, _ = env
    db = tmp_path / 'board.sqlite'
    conn = sqlite3.connect(db)
    with pytest.raises(RuntimeError, match='CORE_WRITER_NOT_CONFIGURED'):
        core_writer.apply(conn, {'digest': 'd'}, [])
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn.execute('CREATE TABLE t(a)')
    conn.execute('INSERT INTO t VALUES (1)')
    with pytest.raises(RuntimeError, match='CORE_WRITER_IN_TRANSACTION'):
        core_writer.apply(conn, {'digest': 'd'}, [])


def _fake_run(monkeypatch, stdout):
    seen = {}

    def run(command, **kwargs):
        seen['command'], seen['input'] = command, json.loads(kwargs['input'])
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr='')
    monkeypatch.setattr(core_writer.subprocess, 'run', run)
    return seen


def test_rust_writer_passes_digest_and_context_and_returns_the_summary(env, tmp_path):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn = sqlite3.connect(tmp_path / 'board.sqlite')
    seen = _fake_run(monkeypatch, json.dumps({'ok': True, 'result': {'to_classify': 2}}) + '\n')
    result = core_writer.apply(conn, {'digest': 'abc'}, [{'trip_id': 'A'}], transaction_ids={'t2', 't1'},
                               reconsider=True, evidence={'t1': {}})
    assert result == {'to_classify': 2}
    assert seen['command'][1] == 'apply' and seen['command'][seen['command'].index('--digest') + 1] == 'abc'
    assert seen['input'] == {'trips': [{'trip_id': 'A'}], 'nets': {}, 'evidence': {'t1': {}},
                             'reconsider': True, 'transaction_ids': ['t1', 't2']}


def _counts_response(written):
    return json.dumps({'ok': True, 'result': {'to_classify': 1}, 'written': written, 'skipped_unjudged': 2,
                       'skipped_mismatch': 0, 'backfilled': 3, 'transaction_id': 'SECRET-TID'}) + '\n'


def test_apply_counts_are_kept_in_last_run_and_an_atomic_json_without_ids(env, tmp_path):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn = sqlite3.connect(tmp_path / 'board.sqlite')
    _fake_run(monkeypatch, _counts_response(5))
    assert core_writer.apply(conn, {'digest': 'abc'}, []) == {'to_classify': 1}
    run = core_writer.LAST_RUN.get()
    assert (run['written'], run['skipped_mismatch'], run['skipped_unjudged'], run['backfilled']) == (5, 0, 2, 3)
    folder = tmp_path / core_writer.RUNS_DIR
    saved = json.loads((folder / 'latest.json').read_text(encoding='utf-8'))
    assert saved['latest'] == run and saved['recent'] == [run] and run['digest'] == 'abc'
    assert 'SECRET-TID' not in (folder / 'latest.json').read_text(encoding='utf-8')
    assert [p.name for p in folder.iterdir()] == ['latest.json']
    _fake_run(monkeypatch, _counts_response(7))
    core_writer.apply(conn, {'digest': 'def'}, [])
    saved = json.loads((folder / 'latest.json').read_text(encoding='utf-8'))
    assert [r['written'] for r in saved['recent']] == [5, 7] and saved['latest']['digest'] == 'def'


def test_recent_runs_are_capped_and_an_unwritable_folder_does_not_fail_the_apply(env, tmp_path):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn = sqlite3.connect(tmp_path / 'board.sqlite')
    _fake_run(monkeypatch, _counts_response(1))
    for _ in range(core_writer.RUNS_KEPT + 3):
        core_writer.apply(conn, {'digest': 'd'}, [])
    saved = json.loads((tmp_path / core_writer.RUNS_DIR / 'latest.json').read_text(encoding='utf-8'))
    assert len(saved['recent']) == core_writer.RUNS_KEPT
    (tmp_path / 'sub').write_text('file, not a folder', encoding='utf-8')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'sub' / 'core.sqlite'))
    assert core_writer.apply(conn, {'digest': 'd'}, []) == {'to_classify': 1}


def test_stale_preview_keeps_the_python_error_and_other_codes_are_runtime_errors(env, tmp_path):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    conn = sqlite3.connect(tmp_path / 'board.sqlite')
    _fake_run(monkeypatch, json.dumps({'ok': False, 'error': {'code': 'CLASSIFICATION_PREVIEW_STALE'}}) + '\n')
    with pytest.raises(ValueError, match='CLASSIFICATION_PREVIEW_STALE'):
        core_writer.apply(conn, {'digest': 'x'}, [])
    _fake_run(monkeypatch, json.dumps({'ok': False, 'error': {'code': 'STORE_ERROR'}}) + '\n')
    with pytest.raises(RuntimeError, match='STORE_ERROR'):
        core_writer.apply(conn, {'digest': 'x'}, [])


def test_stored_service_period_reads_core_sqlite_read_only(env, tmp_path):
    monkeypatch, _ = env
    core = tmp_path / 'core.sqlite'
    with sqlite3.connect(core) as c:
        c.execute('CREATE TABLE decisions(transaction_id TEXT, service_period_json TEXT)')
        c.execute("INSERT INTO decisions VALUES ('t1', '{\"kind\": \"known\", \"starts_on\": \"2026-10-01\", \"ends_on\": \"2026-10-02\"}')")
    c.close()
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(core))
    assert core_writer.stored_service_period('t1')['starts_on'] == '2026-10-01'
    assert core_writer.stored_service_period('missing') is None


def test_stored_service_period_names_verified_inferred_and_unknown(env, tmp_path):
    monkeypatch, _ = env
    core = tmp_path / 'core.sqlite'
    stored = {
        'old': {'kind': 'known', 'starts_on': '2026-10-01', 'ends_on': '2026-10-02'},
        'new': {'kind': 'inferred', 'starts_on': '2026-10-01', 'ends_on': '2026-10-02', 'basis': 'p2_run'},
        'none': {'kind': 'unknown', 'reason': 'no_evidence'},
        'odd': {'kind': 'surprise'},
    }
    with sqlite3.connect(core) as c:
        c.execute('CREATE TABLE decisions(transaction_id TEXT, service_period_json TEXT)')
        c.executemany('INSERT INTO decisions VALUES (?, ?)', [(k, json.dumps(v)) for k, v in stored.items()])
    c.close()
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(core))
    read = core_writer.stored_service_period
    assert read('old')['kind'] == 'verified' and read('old')['starts_on'] == '2026-10-01'
    assert read('new')['kind'] == 'inferred' and read('new')['basis'] == 'p2_run'
    assert read('none') == {'kind': 'unknown', 'reason': 'no_evidence'}
    assert read('odd')['kind'] == 'unknown'


def _periods_env(env, tmp_path, monkeypatch_calls):
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    board = tmp_path / 'board.sqlite'
    conn = sqlite3.connect(board)
    conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT, field TEXT, event_id TEXT)')
    conn.commit()
    key = {'value': 'k1'}
    monkeypatch.setattr(core_writer, '_period_input_key', lambda path: key['value'])

    def snapshot(path):
        monkeypatch_calls.append(path)
        from tools.core_bridge.golden import _card, _event
        return {'events': [_event('syn-e1', item='숙박비', reservation_status='confirmed')],
                'transactions': [_card('syn-t1', source_hash='syn-hash-syn-t1')],
                'results': [{'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}],
                'links': {}}
    monkeypatch.setattr(core_writer, '_period_snapshot', snapshot)
    return conn, key


def test_period_facts_reuse_the_cache_until_the_evidence_input_changes(env, tmp_path):
    calls = []
    conn, key = _periods_env(env, tmp_path, calls)
    first = core_writer.periods_for(conn)
    assert 'syn-t1' in first and len(calls) == 1
    assert core_writer.periods_for(conn) == first and len(calls) == 1
    key['value'] = 'k2'
    core_writer.periods_for(conn)
    assert len(calls) == 2
    conn.execute("INSERT INTO board_manual_overrides VALUES ('card-syn-t1','service_period','e')")
    conn.commit()
    assert core_writer.periods_for(conn)['syn-t1'][0]['manual'] is True
    assert len(calls) == 3


def test_rust_writer_sends_the_period_facts_and_apply_without_them_sends_none(env, tmp_path):
    calls = []
    conn, _ = _periods_env(env, tmp_path, calls)
    seen = _fake_run(env[0], json.dumps({'ok': True, 'result': {}}) + '\n')
    core_writer.apply(conn, {'digest': 'd'}, [], periods=core_writer.periods_for(conn))
    assert 'syn-t1' in seen['input']['periods']
    core_writer.apply(conn, {'digest': 'd'}, [])
    assert 'periods' not in seen['input']


def test_policy_apply_with_the_rust_writer_passes_period_facts(env, tmp_path):
    calls = []
    conn, _ = _periods_env(env, tmp_path, calls)
    env[0].setenv(core_writer.WRITER_ENV, 'rust')
    seen = _fake_run(env[0], json.dumps({'ok': True, 'result': {'to_classify': 0}}) + '\n')
    assert policy.apply(conn, {'digest': 'd'}, []) == {'to_classify': 0}
    assert 'syn-t1' in seen['input']['periods']


def test_second_apply_after_an_apply_does_not_rebuild_the_period_evidence(env, tmp_path):
    from contextlib import contextmanager
    from webapp import ota_payment_review
    calls = []
    conn, _ = _periods_env(env, tmp_path, calls)
    monkeypatch = env[0]
    monkeypatch.undo()  # drop the stubbed key; use the real key function over a fake board below
    monkeypatch.setenv(core_writer.BIN_ENV, 'costcore')
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    monkeypatch.setattr(core_writer, '_period_snapshot', lambda path: calls.append(path) or {
        'events': [], 'transactions': [], 'results': [], 'links': {}})
    conn.execute('CREATE TABLE transactions(transaction_id, amount, item, classification_state, revision)')
    conn.execute("INSERT INTO transactions VALUES ('t1', 100, 'a', 'unclassified', 1)")
    conn.commit()

    @contextmanager
    def board(path):
        yield None
    monkeypatch.setattr(core_writer, '_board', board)

    def key(_, ignore):
        rows = conn.execute('SELECT * FROM transactions').fetchall()
        names = [c[1] for c in conn.execute('PRAGMA table_info(transactions)')]
        return json.dumps([{n: v for n, v in zip(names, r) if n not in ignore} for r in rows])
    monkeypatch.setattr(ota_payment_review, 'current_input_key', key)

    def run(command, **kwargs):  # the Rust writer changes the judged columns of the card row
        conn.execute("UPDATE transactions SET classification_state='classified', item='b', revision=revision+1")
        conn.commit()
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({'ok': True, 'result': {}}) + '\n', stderr='')
    monkeypatch.setattr(core_writer.subprocess, 'run', run)
    core_writer.apply(conn, {'digest': 'd'}, [], periods=core_writer.periods_for(conn))
    assert len(calls) == 1
    core_writer.apply(conn, {'digest': 'd'}, [], periods=core_writer.periods_for(conn))
    assert len(calls) == 1
    conn.execute('UPDATE transactions SET amount=200')  # a real evidence input still rebuilds it
    conn.commit()
    core_writer.periods_for(conn)
    assert len(calls) == 2


def _scope_flow(monkeypatch, conn, applied):
    import threading
    from types import SimpleNamespace
    from webapp import card_classification_completion as completion
    monkeypatch.setenv(core_writer.WRITER_ENV, 'rust')
    monkeypatch.setattr(completion, 'context', lambda flow: ([], {}))
    monkeypatch.setattr(completion, 'classification_evidence', lambda *a, **k: {})
    monkeypatch.setattr(completion.policy, 'plan', lambda *a, **k: {'digest': 'd'})
    monkeypatch.setattr(completion.policy, 'apply', lambda c, preview, trips, **k: applied.append(k['periods']) or {})
    return completion, SimpleNamespace(board=SimpleNamespace(conn=conn, _lock=threading.RLock()))


def test_complete_scope_never_saves_with_evidence_built_before_a_new_transaction(env, tmp_path):
    calls = []
    conn, key = _periods_env(env, tmp_path, calls)
    applied = []
    completion, flow = _scope_flow(env[0], conn, applied)
    build = core_writer._period_snapshot

    def snapshot(path):  # a card arrives while the evidence is being built (first build only)
        data = build(path)
        if len(calls) == 1:
            key['value'] = 'k-new-card'
        return data
    env[0].setattr(core_writer, '_period_snapshot', snapshot)
    completion.complete_scope(flow)
    assert len(calls) == 2 and len(applied) == 1  # rebuilt once under the new key, then applied

    key['value'] = 'k2'
    applied.clear()
    env[0].setattr(core_writer, '_period_snapshot',
                   lambda path: key.update(value=key['value'] + 'x') or build(path))  # never settles
    with pytest.raises(ValueError, match='CLASSIFICATION_PREVIEW_STALE'):
        completion.complete_scope(flow)
    assert applied == []


class _TrackedLock:
    def __init__(self):
        import threading
        self._lock, self.depth = threading.RLock(), 0

    def __enter__(self):
        self._lock.acquire()
        self.depth += 1

    def __exit__(self, *exc):
        self.depth -= 1
        self._lock.release()


def _lifted(env, tmp_path, applied, built_under_lock):
    """A flow whose board lock is tracked; the evidence build records whether the lock was held."""
    from types import SimpleNamespace
    from webapp import card_classification_completion as completion
    from webapp.card_flow import CardFlow
    calls = []
    conn, key = _periods_env(env, tmp_path, calls)
    monkeypatch = env[0]
    monkeypatch.setenv(core_writer.WRITER_ENV, 'rust')
    board = SimpleNamespace(conn=conn, _lock=_TrackedLock())
    build = core_writer._period_snapshot

    def snapshot(path):
        built_under_lock.append(board._lock.depth)
        return build(path)
    monkeypatch.setattr(core_writer, '_period_snapshot', snapshot)
    monkeypatch.setattr(completion, 'context', lambda flow: ([], {}))
    monkeypatch.setattr(completion, 'classification_evidence', lambda *a, **k: {})
    monkeypatch.setattr(completion.policy, 'plan', lambda *a, **k: {'digest': 'd'})
    monkeypatch.setattr(completion.policy, 'apply', lambda c, preview, trips, **k: applied.append(
        (k['periods'], c.in_transaction, board._lock.depth)) or {})
    flow = CardFlow.__new__(CardFlow)
    flow.board, flow._ota_request_depth = board, 0
    monkeypatch.setattr(CardFlow, '_classify', lambda self, batch, **k: completion.complete_scope(self, set()))
    monkeypatch.setattr(CardFlow, '_auto_record_locked', lambda self, batch, **k: {'auto_recorded': 0})
    monkeypatch.setattr(CardFlow, 'sync_ledger_rows', lambda self: 0)
    return flow, board, key, calls


def test_classify_builds_the_evidence_before_taking_the_board_lock(env, tmp_path):
    applied, held = [], []
    flow, board, _, calls = _lifted(env, tmp_path, applied, held)
    flow.classify('b')
    assert held == [0] and len(applied) == 1 and 'syn-t1' in applied[0][0]
    flow.classify('b')  # warm cache: no rebuild
    assert len(calls) == 1 and len(applied) == 2


def test_auto_record_with_the_rust_writer_applies_outside_the_transaction(env, tmp_path):
    from webapp.card_flow import CardFlow
    applied, held = [], []
    flow, board, _, calls = _lifted(env, tmp_path, applied, held)
    seen = []
    env[0].setattr(CardFlow, '_pending_reclassification', lambda self, batch: {'t1'})
    env[0].setattr(CardFlow, '_auto_record_locked',
                   lambda self, batch, **k: seen.append(board.conn.in_transaction) or {'auto_recorded': 1})
    assert flow.auto_record('b') == {'auto_recorded': 1}
    assert held == [0] and applied[0][1] is False  # built and applied with no open transaction
    assert seen == [True]  # recording and projection still share one transaction


def _rule_review_flow(env, tmp_path, applied, held, locked):
    from types import SimpleNamespace
    from webapp import rule_review
    from webapp.card_flow import CardFlow
    flow, board, key, calls = _lifted(env, tmp_path, applied, held)
    flow.pipeline = SimpleNamespace(store=SimpleNamespace(lock=board._lock))
    env[0].setattr(CardFlow, '_pending_reclassification', lambda self, batch: set())
    env[0].setattr(CardFlow, '_auto_record_locked', lambda self, batch, **k: {'auto_recorded': 0})
    env[0].setattr(rule_review, '_approve_locked',
                   lambda f, batch, body: locked.append(board._lock.depth) or {'applied': ['t1']})
    return rule_review, flow, board, key, calls


def test_rule_review_approve_refreshes_without_holding_the_board_lock_during_the_evidence_build(env, tmp_path):
    applied, held, locked = [], [], []
    rule_review, flow, board, _, calls = _rule_review_flow(env, tmp_path, applied, held, locked)
    result = rule_review.approve(flow, 'b', {})
    assert locked == [1] and held == [0] and len(calls) == 1  # decisions saved under the lock, evidence built outside
    assert result['applied'] == ['t1'] and len(applied) == 1 and applied[0][1] is False  # no open transaction at apply


def test_rule_review_approve_rebuilds_once_on_a_key_change_then_fails_after_the_commit(env, tmp_path):
    applied, held, locked = [], [], []
    rule_review, flow, board, key, calls = _rule_review_flow(env, tmp_path, applied, held, locked)
    build = core_writer._period_snapshot

    def moving(path):
        data = build(path)
        key['value'] += 'x'
        return data
    env[0].setattr(core_writer, '_period_snapshot', moving)
    result = rule_review.approve(flow, 'b', {})
    assert locked == [1] and applied == [] and len(calls) == 2
    assert result == {'applied': ['t1'], 'state': None, 'refresh_required': True}  # the write stays reported as saved


def test_auto_record_with_the_python_writer_keeps_classification_in_the_transaction(env, tmp_path):
    from webapp.card_flow import CardFlow
    applied, held = [], []
    flow, board, _, _ = _lifted(env, tmp_path, applied, held)
    env[0].delenv(core_writer.WRITER_ENV)
    inside = []
    env[0].setattr(CardFlow, '_pending_reclassification', lambda self, batch: {'t1'})
    env[0].setattr(CardFlow, '_classify', lambda self, batch, **k: inside.append(board.conn.in_transaction))
    flow.auto_record('b')
    assert inside == [True] and held == []


def test_sweep_once_builds_the_evidence_before_the_locks_and_only_with_work(env, tmp_path):
    from types import SimpleNamespace
    from webapp import card_completion_worker as worker_module
    applied, held = [], []
    flow, board, _, _ = _lifted(env, tmp_path, applied, held)
    worker = worker_module.CardCompletionWorker.__new__(worker_module.CardCompletionWorker)
    worker.board = board
    env[0].setattr(worker_module, 'candidates', lambda conn: [])
    env[0].setattr(worker_module.CardCompletionWorker, '_sweep_once', lambda self: worker_module.completion_probe(self))
    ran = []
    env[0].setattr(worker_module, 'completion_probe', lambda self: ran.append(1) or False, raising=False)
    worker.sweep_once()
    assert held == [] and ran == [1]  # idle: nothing was built
    env[0].setattr(worker_module, 'candidates', lambda conn: [('t',)])
    env[0].setattr(worker_module, 'completion_probe',
                   lambda self: __import__('webapp.card_classification_completion', fromlist=['x']).complete_scope(flow, set()),
                   raising=False)
    worker.sweep_once()
    assert held == [0] and len(applied) == 1


def test_a_key_change_after_the_lifted_build_rebuilds_once_then_fails(env, tmp_path):
    applied, held = [], []
    flow, board, key, calls = _lifted(env, tmp_path, applied, held)
    build = core_writer._period_snapshot

    def moving(path):
        data = build(path)
        key['value'] += 'x'  # a card arrives during every build
        return data
    env[0].setattr(core_writer, '_period_snapshot', moving)
    with pytest.raises(ValueError, match='CLASSIFICATION_PREVIEW_STALE'):
        flow.classify('b')
    assert applied == [] and len(calls) == 2  # one rebuild, no write with stale evidence
    env[0].setattr(core_writer, '_period_snapshot', build)
    flow.classify('b')
    assert len(applied) == 1


def test_run_with_periods_inside_prepared_checks_the_key_under_the_lock(env, tmp_path):
    applied, held = [], []
    flow, board, key, _ = _lifted(env, tmp_path, applied, held)
    seen = []

    def work(periods):
        seen.append(board._lock.depth)
        return periods
    assert 'syn-t1' in core_writer.prepared(board, lambda: core_writer.run_with_periods(board, work))
    assert seen == [1] and held == [0]


def test_python_writer_runs_the_work_under_the_board_lock(env, tmp_path):
    applied, held = [], []
    flow, board, _, _ = _lifted(env, tmp_path, applied, held)
    env[0].delenv(core_writer.WRITER_ENV)
    depth = []
    assert core_writer.run_with_periods(board, lambda periods: depth.append((board._lock.depth, periods)) or 'ok') == 'ok'
    assert depth == [(1, None)] and held == []


def test_cleanup_group_loop_lets_a_stale_key_rebuild_the_evidence(env, tmp_path):
    from webapp import card_flow
    applied, held = [], []
    flow, board, key, calls = _lifted(env, tmp_path, applied, held)
    stale = {'left': 1}

    def classify(self, batch, **k):
        from webapp import card_classification_completion as completion
        if stale['left']:
            stale['left'] -= 1
            key['value'] += 'x'  # an earlier group's write moved the evidence inputs
        return completion.complete_scope(self, set())
    env[0].setattr(card_flow.CardFlow, '_classify', classify)
    env[0].setattr(card_flow, '_cleanup_card_where', lambda board: ' FROM transactions t JOIN import_batch_rows r USING(transaction_id) WHERE 1=1')
    env[0].setattr(card_flow, '_is_ota_row', lambda row: False)
    env[0].setattr(card_flow, 'assign_existing_local_expenses', lambda *a, **k: 0)
    env[0].setattr(card_flow, '_sync_booked_authority_inferences', lambda flow: (0, 0))
    env[0].setattr(card_flow, '_cleanup_card_breakdown', lambda board: {})
    board.conn.execute('CREATE TABLE transactions(transaction_id, merchant, amount_krw, transaction_direction, display_tab_id, trip_id,'
                       ' conflict_reason, parse_error, classification_source)')
    board.conn.execute('CREATE TABLE import_batch_rows(batch_id, transaction_id)')
    board.conn.execute('CREATE TABLE transaction_review_holds(transaction_id)')
    board.conn.execute("INSERT INTO transactions VALUES ('t1','m',10,'purchase','','','','','')")
    board.conn.execute("INSERT INTO import_batch_rows VALUES ('b','t1')")
    board.conn.commit()
    env[0].setattr(card_flow, 'decided_sql', lambda alias: '0')
    result = card_flow.reclassify_cleanup(board, flow=flow, request_snapshot=False)
    assert result['failures'] == [] and result['processed'] == 1 and len(applied) == 1
    assert len(calls) == 2  # rebuilt once after the key moved


def test_audit_entries_and_reviews_do_not_invalidate_the_period_evidence(env, tmp_path):
    calls = []
    conn, _ = _periods_env(env, tmp_path, calls)
    conn.execute('CREATE TABLE change_log(entry_id INTEGER PRIMARY KEY, kind TEXT, subject TEXT)')
    conn.execute('CREATE TABLE review_decisions(transaction_id TEXT)')
    conn.commit()
    core_writer.periods_for(conn)
    conn.execute("INSERT INTO change_log(kind, subject) VALUES ('card.classification_corrected', 't1')")
    conn.execute("INSERT INTO review_decisions VALUES ('t1')")
    conn.commit()
    core_writer.periods_for(conn)
    assert len(calls) == 1


def test_period_evidence_takes_no_p2_periods_so_it_matches_the_cache_key(env, tmp_path, monkeypatch):
    from tools.core_bridge import periods as bridge
    seen = []
    real = bridge.evidence_from_snapshot
    monkeypatch.setattr(bridge, 'evidence_from_snapshot', lambda *args, **kw: seen.append((args, kw)) or real(*args, **kw))
    conn, _ = _periods_env(env, tmp_path, [])
    facts = core_writer.periods_for(conn)
    (args, kw), = seen
    assert len(args) == 2 and not kw and 'syn-t1' in facts
    assert not hasattr(core_writer, '_p2_periods')


def test_status_writes_are_serialised_so_a_stale_state_cannot_overwrite_a_newer_one(env, tmp_path):
    import threading
    monkeypatch, _ = env
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'core.sqlite'))
    monkeypatch.setitem(core_writer._PUBLISHED, 'key', None)
    done = threading.Event()
    with core_writer._PUBLISH_LOCK:
        worker = threading.Thread(target=lambda: (core_writer._publish_status(), done.set()))
        worker.start()
        assert not done.wait(0.3)
    worker.join(5)
    assert done.is_set() and (tmp_path / core_writer.STATUS_FILE).is_file()


def test_sweep_with_a_moved_key_leaves_the_chunk_for_the_next_pass(env, tmp_path):
    from webapp import card_classification_completion as completion
    from webapp import card_completion_worker as worker_module
    applied, held = [], []
    flow, board, key, calls = _lifted(env, tmp_path, applied, held)
    worker = worker_module.CardCompletionWorker.__new__(worker_module.CardCompletionWorker)
    worker.board = board
    env[0].setattr(worker_module, 'candidates', lambda conn: [('t',)])
    env[0].setattr(worker_module.CardCompletionWorker, '_sweep_once',
                   lambda self: completion.complete_scope(flow, {'t'}))
    build = core_writer._period_snapshot

    def moving(path):
        data = build(path)
        key['value'] += 'x'  # a card arrives during every build
        return data
    env[0].setattr(core_writer, '_period_snapshot', moving)
    with pytest.raises(core_writer.PeriodsStale):
        worker.sweep_once()
    assert applied == [] and all(depth == 0 for depth in held)  # nothing written, nothing built under the lock
    env[0].setattr(core_writer, '_period_snapshot', build)
    worker.sweep_once()
    assert len(applied) == 1 and applied[0][2] == 1  # applied once, inside the lock, with matching evidence
