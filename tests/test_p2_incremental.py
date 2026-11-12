import argparse
import copy
import json
from pathlib import Path

import pytest

from app.connected_agent_provider import AgentUnavailable
from tests.test_p2_batch import row, data
from tools.p2_batch import layer1, run_incremental as inc


def rule(merchant='ruled', item='식비', **changes):
    result = dict(conditions=dict(merchant_normalized=merchant, transaction_direction='purchase'),
                  optional={}, effects={'item': item}, origin='existing')
    result.update(changes)
    return result


def mid(name):
    return layer1.merchants([row(merchant_normalized=name)])[0][0]['merchant_id']


def test_selects_new_merchants_excludes_proposals_rules_completed_manual_and_refunds():
    source = data([row(transaction_id=k, merchant_normalized=k, **change) for k, change in [
        ('new', {}), ('old', {}), ('ruled', {}), ('manual', {'classification_source': 'manual'}),
        ('completed', {'approval_date': '2026-01-01'}), ('refund-protected', {}),
    ]]+[row(transaction_id='refund', amount_krw=-100, transaction_direction='refund', original_approval_number='approval')])
    # Give unrelated purchases distinct approval numbers.
    for r in source['transactions']:
        if r['transaction_id'] not in {'refund', 'refund-protected'}:
            r['approval_number'] = r['transaction_id']
    report, inputs, _ = inc.select_increment(source, [rule()], {mid('old')})
    assert [m['normalized'] for m in inputs] == ['new']
    assert report['new_rows'] == 1
    assert report['broad_partition'] == dict(new_merchant=1, previous_layer1=1, existing_p1_rule=1,
                                           manual=1, COMPLETED_PERIOD=1, ORIGINAL_WITH_REFUND=1)


@pytest.mark.parametrize(('change', 'reason'), [
    ({'approval_date': '2025-06-15'}, 'COMPLETED_PERIOD'),
    ({'approval_date': '2026-03-31'}, 'COMPLETED_PERIOD'),
    ({'approval_date': '', 'posting_date': '2025-12-31'}, 'COMPLETED_PERIOD'),
    ({'approval_date': '2026-04-01'}, 'new_merchant'),
])
def test_completed_2025_and_q1_boundary_uses_posting_fallback(change, reason):
    source = data([row(transaction_id='target', **change)])
    report, selected, _ = inc.select_increment(source, [], set())
    assert report['broad_partition'] == {reason: 1}
    assert bool(selected) == (reason == 'new_merchant')


def test_manual_decision_history_excludes_incremental_targets():
    source = data([row(transaction_id='decided'),
                   row(transaction_id='overridden', merchant_normalized='other shop'),
                   row(transaction_id='new', merchant_normalized='new shop')])
    source['review_decisions'] = [dict(transaction_id='decided', item='식비', display_tab_id='open')]
    source['board_manual_overrides'] = [dict(row_id='card-overridden', field='item')]
    report, selected, _ = inc.select_increment(source, [], set())
    assert [m['normalized'] for m in selected] == ['new shop']
    assert report['broad_partition'] == {'manual': 2, 'new_merchant': 1}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(inc, 'PRIVATE', tmp_path)
    monkeypatch.setattr(inc, 'operational_items', lambda db: ['식비', '현지경비'])
    path = tmp_path/'state.json'
    inc.save(path, dict(version=1, history_merchants=[], history_evidence={'synthetic': True}, jobs=[], runs=[]))
    args = argparse.Namespace(state=str(path), db=str(tmp_path/'db.sqlite'), dry_run=False, propose_only=False,
                              api_config=None, max_merchants=30, max_calls=1, batch_size=30)
    rows = []
    existing = []
    calls = []
    requests = {}
    def model(batch, allowed):
        calls.append(copy.deepcopy(batch))
        return dict(request_digest=inc.digest(dict(merchants=batch, allowed_items=allowed, policy=layer1.policy_text())),
            execution=dict(kind='connected_agent', provider='codex', model=layer1.provider.MODEL, run_id='synthetic-run'),
            results=[dict(merchant_id=r['merchant_id'], item='식비', confidence='높음', basis='합성 식당') for r in batch])
    writes = []
    def api(endpoint, payload):
        if payload is None:
            return {'rules': copy.deepcopy(existing)}
        writes.append((endpoint, copy.deepcopy(payload)))
        if endpoint.endswith('/preview'):
            assert 0 < len(payload['corrections']) <= 50
            return {'digest': 'synthetic-preview'}
        rid = payload['request_id']
        if rid in requests:
            return dict(requests[rid], applied=0, replay=True)
        if endpoint.endswith('/apply'):
            for fix in payload['corrections']:
                target = next(r for r in rows if r['transaction_id'] == fix['transaction_id'])
                assert target['revision'] == fix['revision']
                target.update(item=fix['item'], revision=target['revision']+1, classification_source='ai_inference')
            result = {'applied': len(payload['corrections'])}
        else:
            draft = copy.deepcopy(payload['draft'])
            existing.append(draft)
            result = {'result': {'version': 1}}
        requests[rid] = result
        return result
    def run(**kw):
        return inc.run(args, model=kw.get('model', model), api=kw.get('api', api),
                       reader=lambda db: data(copy.deepcopy(rows)), rule_reader=lambda db: copy.deepcopy(existing))
    return args, rows, existing, calls, writes, path, run, api


def test_zero_and_dry_run_never_call_model_or_api(harness):
    args, rows, _, calls, writes, _, run, _ = harness
    assert run()['status'] == 'success'
    rows.append(row())
    args.dry_run = True
    assert run()['scope']['new_merchants'] == 1
    assert not calls and not writes


def test_zero_targets_apply_mode_exits_without_api_config(harness):
    args, _, _, calls, writes, _, run, _ = harness
    result = run(api=None)
    assert result['status'] == 'success' and result['calls'] == 0
    assert not calls and not writes


def test_bounded_calls_and_merchants_and_propose_only(harness):
    args, rows, _, calls, writes, path, run, _ = harness
    rows.extend(row(transaction_id=str(i), merchant_normalized=f'cafe {i}') for i in range(90))
    args.max_merchants = 67
    args.max_calls = 2
    args.propose_only = True
    result = run()
    assert result['status'] == 'success' and len(calls) == 2
    assert sum(len(c) for c in calls) == 60 and not writes
    assert len(json.loads(path.read_text(encoding='utf-8'))['jobs']) == 60
    # Another proposal-only run does not repeat any stored proposal.
    before = {r['merchant_id'] for c in calls for r in c}
    run()
    assert not before & {r['merchant_id'] for r in calls[-1]}


def test_apply_mode_merchant_budget_spans_runs_without_duplicates(harness):
    args, rows, existing, calls, _, path, run, _ = harness
    rows.extend(row(transaction_id=str(i), merchant_normalized=f'shop {i}') for i in range(5))
    args.max_merchants = 2
    # scope counts all candidates; the budget caps merchants processed per run.
    for candidates, processed in ((5, 2), (3, 2), (1, 1), (0, 0)):
        before = len(calls)
        result = run()
        assert result['status'] == 'success'
        assert result['scope']['new_merchants'] == candidates
        assert result['calls'] <= 1
        assert sum(len(c) for c in calls[before:]) == processed
    assert all(r['revision'] == 2 for r in rows)
    assert len(calls) == 3 and sum(len(c) for c in calls) == 5
    assert not existing  # single transactions are never promoted
    assert all(j['done'] for j in json.loads(path.read_text(encoding='utf-8'))['jobs'])


def test_partial_apply_lost_response_replays_without_model_or_double_writes(harness):
    args, rows, existing, calls, writes, path, run, api = harness
    rows.extend(row(transaction_id=str(i)) for i in range(55))
    lost = False
    def flaky(endpoint, payload):
        nonlocal lost
        result = api(endpoint, payload)
        if endpoint.endswith('/apply') and not lost:
            lost = True
            raise ValueError('API_TRANSPORT_TIMEOUT')
        return result
    assert run(api=flaky)['status'] == 'failed'
    assert sum(r['revision'] == 2 for r in rows) == 50
    result = run()
    assert result['status'] == 'success' and result['applied_rows'] == 5
    assert result['confirmed_rows'] == 55 and result['recovered_rows'] == 50
    assert len(calls) == 1 and all(r['revision'] == 2 for r in rows)
    assert len(existing) == 1 and set(existing[0]['effects']) == {'item'}
    assert run()['scope']['new_merchants'] == 0
    applies = [p for ep, p in writes if ep.endswith('/apply')]
    assert applies[0] == applies[1]
    assert len(applies[0]['corrections']) == 50 and len(applies[2]['corrections']) == 5


def test_model_capacity_failure_remains_eligible_next_run(harness):
    args, rows, _, calls, writes, _, run, _ = harness
    rows.append(row())
    def failure(*a):
        raise AgentUnavailable('AGENT_CAPACITY')
    result = run(model=failure)
    assert result['status'] == 'failed' and result['failed_calls'] == 1
    assert not writes
    assert run()['status'] == 'success' and len(calls) == 1


def test_codex_rate_limit_recorded_and_resumed_next_run(harness):
    args, rows, _, calls, writes, path, run, _ = harness
    rows.append(row())
    def limited(*a):
        raise AgentUnavailable('AGENT_RATE_LIMITED', 300)
    result = run(model=limited)
    assert result['status'] == 'failed' and result['failure_code'] == 'AGENT_RATE_LIMITED'
    assert result['failed_calls'] == 1 and not writes
    state = json.loads(path.read_text(encoding='utf-8'))
    assert state['runs'][-1]['failure_code'] == 'AGENT_RATE_LIMITED' and not state['jobs']
    assert run()['status'] == 'success' and len(calls) == 1


def test_lost_rule_response_replays_registration_without_duplicate(harness):
    _, rows, existing, calls, _, _, run, api = harness
    rows.extend([row(), row(transaction_id='second')])
    lost = False
    def flaky(endpoint, payload):
        nonlocal lost
        result = api(endpoint, payload)
        if endpoint == '/api/imports/rules' and payload is not None and not lost:
            lost = True
            raise ValueError('API_TRANSPORT_TIMEOUT')
        return result
    assert run(api=flaky)['status'] == 'failed'
    assert len(existing) == 1
    assert run()['status'] == 'success'
    assert len(existing) == 1 and len(calls) == 1


def test_initial_history_preserves_keep_proposals_and_refuses_overwrite(tmp_path, monkeypatch):
    from tools.p2_batch import initialize_history as history
    monkeypatch.setattr(history, 'PRIVATE', tmp_path)
    proposals = tmp_path/'proposals.jsonl'
    proposals.write_text(json.dumps({'merchant_id': 'keep-merchant', 'item': layer1.KEEP}), encoding='utf-8')
    state = tmp_path/'state.json'
    assert history.initialize(state, proposals=proposals) == 1
    assert json.loads(state.read_text())['history_merchants'] == ['keep-merchant']
    with pytest.raises(ValueError, match='NEW_PRIVATE_STATE_REQUIRED'):
        history.initialize(state, proposals=proposals)


def test_ego_bridge_uses_owner_page_fetch_and_refuses_other_origin(tmp_path):
    import subprocess
    request = tmp_path/'request.json'
    output = tmp_path/'response.json'
    request.write_text(json.dumps(dict(task_space=17, page='p1', origin='https://synthetic.invalid',
        endpoint='/api/imports/rules', payload=None)), encoding='utf-8')
    script = tmp_path/'test.mjs'
    bridge = Path(inc.__file__).with_name('authenticated_api.mjs').as_uri()
    script.write_text('import assert from "node:assert/strict";\n'
        'const {request} = await import('+json.dumps(bridge)+');\n'
        'globalThis.taskSpace=async id=>{assert.equal(id,17);return {page(label){assert.equal(label,"p1");return {'
        'url:async()=>"https://synthetic.invalid/ledger",evaluate:async()=>"synthetic-csrf",'
        'fetch:async(endpoint,options)=>{assert.equal(endpoint,"/api/imports/rules");assert.equal(options.method,"GET");'
        'assert.equal(options.headers["X-CSRF-Token"],"synthetic-csrf");return {ok:true,status:200,body:"{\\"rules\\":[]}"}}}}}};\n'
        'await request('+json.dumps(request.as_posix())+','+json.dumps(output.as_posix())+');\n', encoding='utf-8')
    result = subprocess.run(['node', str(script)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(output.read_text()) == {'ok': True, 'status': 200, 'body': {'rules': []}}
    request.write_text(request.read_text().replace('https://synthetic.invalid', 'https://other.invalid'), encoding='utf-8')
    result = subprocess.run(['node', str(script)], capture_output=True)
    assert result.returncode != 0 and b'API_ORIGIN_MISMATCH' in result.stderr


def test_propose_then_manual_change_stops_without_api_writes(harness):
    args, rows, _, calls, writes, _, run, _ = harness
    rows.append(row())
    args.propose_only = True
    assert run()['status'] == 'success'
    args.propose_only = False
    rows[0]['classification_source'] = 'manual'
    assert run()['failure_code'] == 'INCREMENTAL_TARGET_STALE'
    assert len(calls) == 1 and not writes


def test_single_transaction_never_promoted_and_existing_narrow_rule_excluded(harness):
    _, rows, existing, calls, writes, _, run, _ = harness
    rows.append(row())
    assert run()['registered_rules'] == 0
    assert not existing
    source = data([row(merchant_normalized='ruled')])
    assert not inc.select_increment(source, [rule(optional={'travel_country': 'JP'})], set())[1]


@pytest.mark.parametrize('merchant', ['AGODA * HOTEL', '아고다 HOTEL', 'Agoda.hotel'])
def test_existing_merchant_family_rule_excludes_variants(merchant):
    from app.normalize import normalize_merchant
    source = data([row(merchant=merchant, merchant_normalized=normalize_merchant(merchant))])
    family = rule('agoda', optional={'merchant_family': 'agoda', 'travel_country': 'JP'})
    report, selected, _ = inc.select_increment(source, [family], set())
    assert not selected and report['general_partition'] == {'existing_p1_rule': 1}
    assert not inc.has_rule(row(merchant='AGODAX HOTEL', merchant_normalized='agodax hotel'), [family])


def test_concurrent_writer_and_missing_history_fail_closed(harness):
    args, _, _, _, _, path, run, _ = harness
    lock = path.with_suffix('.lock')
    lock.write_text('owned', encoding='utf-8')
    with pytest.raises(FileExistsError):
        run()
    assert lock.read_text() == 'owned'
    lock.unlink()
    path.unlink()
    with pytest.raises(ValueError, match='VERIFIED_LAYER1_HISTORY_REQUIRED'):
        run()
    assert not lock.exists()


@pytest.mark.parametrize(('field', 'value'), [
    ('max_calls', 0), ('max_calls', 21), ('max_merchants', 0), ('max_merchants', 501),
    ('batch_size', 29), ('batch_size', 51),
])
def test_private_state_limit_and_invalid_bound_refused(harness, field, value):
    args, _, _, _, _, _, run, _ = harness
    setattr(args, field, value)
    with pytest.raises(ValueError, match='INVALID_RUN_LIMIT'):
        run()


def test_registration_script_parses_and_uses_whatif():
    import subprocess
    script = Path(inc.__file__).with_name('register_incremental_task.ps1')
    result = subprocess.run(['powershell', '-NoProfile', '-Command',
        '$tokens=$null; $parseErrors=$null; [System.Management.Automation.Language.Parser]::ParseFile(\''
        +str(script)+"', [ref]$tokens, [ref]$parseErrors) | Out-Null; if ($parseErrors.Count) { exit 1 }"], capture_output=True)
    assert result.returncode == 0
    text = script.read_text(encoding='utf-8')
    assert 'SupportsShouldProcess=$true' in text and 'TASK_ALREADY_EXISTS' in text
