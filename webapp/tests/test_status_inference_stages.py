"""State/source separation and genuine agent P2 with atomic safety boundaries."""
import copy
import json
import sqlite3

import pytest

from app import ai_classification as ai, automatic_classification as code
from app.classification_provenance import label
from tools.review_card_inference import run
from webapp.card_actions import next_action
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


def response(request):
    return dict(request_digest=request['digest'],
        execution=dict(kind='connected_agent', provider='synthetic', model='synthetic-test-model', run_id='synthetic-run-1'),
        results=[dict(transaction_id=c['transaction_id'], trip_id='B', item='교통비',
                      basis='합성 자료의 이동 일정 대조', uncertainty='분류 용도만 판단; 결제 연결은 변경하지 않음')
                 for c in request['cases']])


def prepared(setup):
    board, _, _, rows = setup
    ids = [r['transaction_id'] for r in rows[:2]]
    p = code.plan(board.conn, TRIPS, transaction_ids=ids)
    code.apply(board.conn, p, TRIPS, transaction_ids=ids)
    return board.conn, ids, ai.prepare(board.conn, TRIPS, ids)


@pytest.mark.parametrize('source,expected', [('inference','코드 추론'), ('auto_inferred','코드 추론'),
    ('code_inference','코드 추론'), ('ai_inference','AI 추론'), ('rule','자동'),
    ('owner_booking','자동'), ('manual','직접'), ('user_decision','직접')])
def test_origin_uses_actual_execution_not_decided_or_p2_text(source, expected):
    assert label(dict(classification_source=source, decided=1, classification_basis='P2_REVIEW')) == expected
    assert label(dict(classification_source=source, decided_at='synthetic-user-decision')) == '직접'


def test_financial_facts_are_visible_without_human_classification_work():
    row = dict(batch_id='b',transaction_id='t',item='숙박비',display_tab_id='A',classification_state='classified')
    assert next_action(row,{'already_booked':True})['state_label'] == '완료'
    assert next_action(dict(row,duplicate_of='original'))['state_label'] == '제외'
    assert next_action(dict(row,item=''))['state_label'] == ''
    for source,preview,status,category in [
        (dict(row,parse_error='unreadable'),{},'원본 오류','evidence'),
        (row,{'blocked':'refund_exceeds_original'},'환불 금액 불일치','finance')]:
        result=next_action(source,preview)
        assert result['state_label'] == status and result['reason_category'] == category
        assert not result['required'] and result['protection']
    protected=next_action(dict(row,review_hold={'kind':'manual_hold','reason':'private old decision'}))
    assert not protected['required'] and 'private old decision' not in protected['reason']


def test_internal_classification_state_is_not_user_action_without_open_p3():
    row = dict(batch_id='b', transaction_id='t', item='숙박비', display_tab_id='A',
               classification_state='needs_review', classification_source='inference')
    action = next_action(row, {}, user_action_required=False)
    assert action['required'] is False
    assert action['state_label'] == ''
    assert action.get('group', '') == ''


def test_historical_open_p3_never_recreates_classification_question():
    row=dict(batch_id='b',transaction_id='t',item='',display_tab_id='A',classification_state='needs_review')
    assert next_action(row,user_action_required=True) == next_action(row,user_action_required=False)
    assert not next_action(row,user_action_required=True)['required']
    assert next_action(row,user_action_required=True)['state_label'] == ''


@pytest.mark.parametrize('item,tab', [('', 'unclassified'), ('숙박비', ''), ('', 'A')])
def test_pending_automation_without_open_p3_is_not_human_work(item,tab):
    row=dict(batch_id='b',transaction_id='t',item=item,display_tab_id=tab,classification_state='needs_review')
    for legacy_flag in (False,True,None):
        assert not next_action(row,user_action_required=legacy_flag)['required']
        assert next_action(row,user_action_required=legacy_flag)['state_label'] == ''
    for preview in ({'blocked':'preview_unavailable'},{'blocked':'refund_exceeds_original'}):
        result=next_action(row,preview)
        assert not result['required'] and result['protection'] == preview['blocked']
    assert next_action(dict(row,parse_error='synthetic'))['protection'] == 'source_conflict'


def test_p1_then_real_p2_updates_source_and_audit_without_human_or_financial_writes(setup):
    board, flow, batch, rows = setup
    c, ids, request = prepared(setup)
    before = {name:c.execute('SELECT * FROM '+name).fetchall() for name in
              ('review_decisions','ledger_entries','transaction_review_holds','transaction_company_exclusions')}
    expected = ai.preview(c, TRIPS, request, response(request))
    result = ai.apply(c, TRIPS, request, response(request), request_id='agent-review')
    assert result['applied'] == 2
    assert all(row == ('ai_inference','classified','교통비','B',None) for row in c.execute(
        'SELECT classification_source,classification_state,item,trip_id,decided_at FROM transactions WHERE transaction_id IN (?,?)',ids))
    audit = json.loads(c.execute("SELECT detail_json FROM change_log WHERE kind='card.classification_corrected' LIMIT 1").fetchone()[0])
    assert audit['execution']['model'] == 'synthetic-test-model'
    assert audit['source'] == 'agent_evidence_review' and not audit['user_booking_or_refund_confirmation']
    for name, content in before.items():
        assert c.execute('SELECT * FROM '+name).fetchall() == content
    count = c.total_changes
    assert ai.apply(c, TRIPS, request, response(request), request_id='agent-review')['replay']
    assert c.total_changes == count
    assert not code.plan(c, TRIPS, transaction_ids=ids, reconsider=True)['targets']
    # Ordinary rule reclassification also preserves P2 without calling it manual.
    flow.pipeline.classify_batch(batch, transaction_ids=ids)
    assert {r[0] for r in c.execute('SELECT classification_source FROM transactions WHERE transaction_id IN (?,?)',ids)} == {'ai_inference'}


@pytest.mark.parametrize('change', ['revision','source','trip','manual','hold','refund','duplicate'])
def test_p2_stale_or_protected_results_cannot_apply(setup, change):
    c, ids, request = prepared(setup)
    tid = ids[0]
    trips = copy.deepcopy(TRIPS)
    if change == 'trip':
        trips[0]['ends_on'] = '2026-10-06'
    elif change == 'manual':
        c.execute("UPDATE transactions SET classification_source='user_decision',decided_at='synthetic' WHERE transaction_id=?",(tid,))
    elif change == 'hold':
        c.execute("UPDATE transactions SET parse_error='synthetic unreadable' WHERE transaction_id=?",(tid,))
    elif change == 'refund':
        c.execute("UPDATE transactions SET transaction_direction='refund' WHERE transaction_id=?",(tid,))
    elif change == 'duplicate':
        c.execute('UPDATE transactions SET duplicate_of=? WHERE transaction_id=?',(ids[1],tid))
    else:
        field = 'revision=revision+1' if change == 'revision' else "source_hash='changed'"
        c.execute('UPDATE transactions SET '+field+' WHERE transaction_id=?',(tid,))
    c.commit()
    before = '\n'.join(c.iterdump())
    with pytest.raises(ValueError):
        ai.apply(c, trips, request, response(request), request_id='stale-agent')
    assert '\n'.join(c.iterdump()) == before


@pytest.mark.parametrize('bad', ['missing_execution','wrong_digest','invented_trip','incomplete','duplicate','no_basis'])
def test_p2_rejects_fake_incomplete_or_unbounded_output(setup, bad):
    c, ids, request = prepared(setup)
    answer = response(request)
    if bad == 'missing_execution': answer.pop('execution')
    elif bad == 'wrong_digest': answer['request_digest'] = 'wrong'
    elif bad == 'invented_trip': answer['results'][0]['trip_id'] = 'made-up'
    elif bad == 'incomplete': answer['results'].pop()
    elif bad == 'duplicate': answer['results'][1] = answer['results'][0]
    else: answer['results'][0]['basis'] = ''
    before = '\n'.join(c.iterdump())
    with pytest.raises(ValueError):
        ai.apply(c, TRIPS, request, answer, request_id='bad-agent')
    assert '\n'.join(c.iterdump()) == before


def test_p2_failure_rolls_back_first_row_projections_and_audit(setup):
    c, ids, request = prepared(setup)
    c.commit()
    c.execute("CREATE TEMP TRIGGER ai_failure BEFORE UPDATE ON transactions WHEN OLD.transaction_id='"+ids[1]+"' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    before = '\n'.join(c.iterdump())
    with pytest.raises(sqlite3.IntegrityError):
        ai.apply(c, TRIPS, request, response(request), request_id='failed-agent')
    assert '\n'.join(c.iterdump()) == before


def test_local_agent_request_is_readonly_and_contains_no_original_text(setup):
    c, ids, request = prepared(setup)
    before = c.total_changes
    assert ai.prepare(c, TRIPS, ids) == request and c.total_changes == before
    data = json.dumps(request)
    assert all(key not in data for key in ('raw_row','merchant','card_tail','approval_number','description','amount_krw'))
    answer = response(request)
    result = run(c, TRIPS, ids, request=request, response=answer)
    assert result['ai_result']['applied'] == 2
    assert run(c, TRIPS, ids, request=request, response=answer)['ai_result']['replay']


def test_p2_requires_code_first_and_never_reopens_verified_booking(setup):
    board, _, _, rows = setup
    ids = [r['transaction_id'] for r in rows[:2]]
    with pytest.raises(ValueError, match='CODE_STAGE_REQUIRED'):
        ai.prepare(board.conn, TRIPS, ids)
    c, ids, request = prepared(setup)
    c.execute("UPDATE transactions SET classification_source='owner_booking' WHERE transaction_id=?",(ids[0],))
    assert len(ai.prepare(c, TRIPS, ids, reconsider=True)['cases']) == 1


def test_cli_private_request_and_agent_response_preview_never_write_live_db(setup, tmp_path, monkeypatch):
    from tools import review_card_inference as cli
    board, _, _, rows = setup
    host = tmp_path/'host'
    (host/'data').mkdir(parents=True)
    target = sqlite3.connect(host/'data/board.sqlite')
    board.conn.backup(target)
    target.close()
    monkeypatch.setattr(cli, 'load_context', lambda *_: (TRIPS, {}))
    ids = [r['transaction_id'] for r in rows[:2]]
    args = ['--host-root',str(host),'--output',str(tmp_path/'prepared.json')]
    for tid in ids:
        args += ['--transaction',tid]
    before = (host/'data/board.sqlite').read_bytes()
    assert cli.main(args) == 0
    request = json.loads((tmp_path/'prepared.json').read_text(encoding='utf-8'))['request']
    (tmp_path/'answer.json').write_text(json.dumps(response(request)),encoding='utf-8')
    preview_args = list(args)
    preview_args[preview_args.index('--output')+1] = str(tmp_path/'preview.json')
    preview_args += ['--request',str(tmp_path/'prepared.json'), '--response',str(tmp_path/'answer.json')]
    assert cli.main(preview_args) == 0
    report = json.loads((tmp_path/'preview.json').read_text(encoding='utf-8'))
    assert report['ai_result']['applied'] == 2
    assert (host/'data/board.sqlite').read_bytes() == before
    # The real apply path includes the existing backup/writer gate and queues
    # internal recording in the SAME transaction. Output failure rolls it back.
    from types import SimpleNamespace
    import threading
    gates = []
    monkeypatch.setattr(cli, 'require_offline_backup', lambda *a:gates.append(a))
    monkeypatch.setattr(cli, 'read_flow', lambda conn, host:SimpleNamespace(board=SimpleNamespace(conn=conn,_lock=threading.RLock())))
    apply_args = preview_args + ['--apply','--expected-digest',report['digest'], '--backup-evidence',str(tmp_path/'backup.json')]
    apply_args[apply_args.index('--output')+1] = str(tmp_path/'missing-dir'/'result.json')
    assert cli.main(apply_args) == 1
    assert (host/'data/board.sqlite').read_bytes() == before
    apply_args[apply_args.index('--output')+1] = str(tmp_path/'applied.json')
    assert cli.main(apply_args) == 0 and len(gates) == 2
    with sqlite3.connect(host/'data/board.sqlite') as live:
        assert live.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0] == 2
        job = json.loads(live.execute("SELECT response_json FROM requests WHERE scope='card_completion_job'").fetchone()[0])
        assert set(job['ids']) == set(ids) and job['pending']


def test_ai_recording_queue_is_part_of_the_outer_atomic_write(setup):
    from webapp.card_completion_worker import queue_batch
    board, _, batch, rows = setup
    c = board.conn
    c.commit()
    before = c.execute('SELECT * FROM requests').fetchall()
    c.execute('BEGIN IMMEDIATE')
    queue_batch(board, batch, [rows[0]['transaction_id']], commit=False)
    assert c.in_transaction
    c.rollback()
    assert c.execute('SELECT * FROM requests').fetchall() == before


def test_ai_request_rejects_changed_rules_and_protects_source_bound_ota_authority(setup):
    c, ids, request = prepared(setup)
    source = c.execute('SELECT source_hash FROM transactions WHERE transaction_id=?',(ids[0],)).fetchone()[0]
    c.execute("INSERT INTO cost_classification_rules(rule_id,version,conditions_json,effects_json,optional_json,origin,rule_hash,created_at,updated_at) VALUES ('synthetic-ota',1,'{}','{}',?,'auto-ota-period','synthetic','now','now')",
              (json.dumps(dict(source_hash=source)),))
    c.commit()
    with pytest.raises(ValueError,match='AI_REQUEST_STALE'):
        ai.apply(c,TRIPS,request,response(request),request_id='rules-changed')
    current = ai.prepare(c,TRIPS,ids,reconsider=True)
    assert current['protected'] == 1 and len(current['cases']) == 1


def test_retired_queue_failure_cannot_reintroduce_question_or_recovery_link():
    row=dict(batch_id='b',transaction_id='t',item='',display_tab_id='',classification_state='needs_review',
             user_action_lookup_unavailable=True)
    result=next_action(row)
    assert not result['required'] and result['state_label'] == ''
    assert result['href'].startswith('/import?') and '/my-actions' not in result['href']


def test_rendered_card_badge_never_recreates_retired_workflow():
    from webapp.cards_all import _status_badges
    row=dict(batch_id='b',transaction_id='t',item='숙박비',display_tab_id='A',classification_state='needs_review',
             user_action_lookup_unavailable=True)
    row['next_action']=next_action(row)
    assert _status_badges(row) == ''
