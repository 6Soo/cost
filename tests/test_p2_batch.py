import copy
import json
from pathlib import Path
import subprocess
import sqlite3

import pytest

from app.connected_agent_provider import AgentUnavailable
from tools.p2_batch import layer1, scope


def row(**changes):
    result = dict(transaction_id='synthetic',source_hash='hash',issuer='issuer',card_tail='1234',
        card_kind='해외',transaction_direction='purchase',transaction_kind='purchase',
        approval_number='approval',original_approval_number='',approval_date='2026-05-01',posting_date='',
        merchant='SYNTHETIC CAFE',merchant_normalized='synthetic cafe',amount_krw=1000,
        foreign_amount=1,foreign_currency='JPY',description_raw='',raw_row_json='{}',duplicate_of='',
        conflict_reason='',parse_error='',classification_state='classified',classification_source='inference',
        classification_basis='old basis',item='현지경비',display_tab_id='open',trip_id='open',revision=1,decided_at=None)
    result.update(changes)
    return result


def data(rows):
    return dict(transactions=rows,trip_tabs=[dict(tab_id='open',display_key='0630',starts_on='2026-06-30',ends_on='2026-07-04',deleted=0),
        dict(tab_id='closed',display_key='0601',starts_on='2026-06-01',ends_on='2026-06-29',deleted=0)],
        review_decisions=[],board_manual_overrides=[],transaction_review_holds=[],transaction_company_exclusions=[],
        board_rows=[],read_seconds=0)


def test_scope_uses_trip_including_prepay_and_quarter_not_card_cutoff():
    d=data([row(),row(transaction_id='late',display_tab_id='closed',trip_id='closed',approval_date='2026-08-01'),
            row(transaction_id='quarter',display_tab_id='',trip_id='',item='분기 기타비용',approval_date='2026-10-01')])
    report,all_rows,eligible,general=scope.select(d)
    assert report['scope_purchases']==2
    assert report['early_card_open_trip']==1
    assert report['quarterly_review']==[{'trip':'0601','count':1}]
    assert [r['transaction_id'] for r in general]==['synthetic']


@pytest.mark.parametrize('change',[
    {'classification_source':'user_decision'}, {'classification_source':'owner_booking'},
    {'classification_source':'manual_hold'}, {'decided_at':'2026-01-01'},
    {'duplicate_of':'other'}, {'parse_error':'invalid'}, {'conflict_reason':'conflict'},
    {'transaction_kind':'취소'},
])
def test_scope_never_admits_protected_rows(change):
    report,_,eligible,_=scope.select(data([row(**change)]))
    assert not eligible
    assert sum(report['protected'].values())==1


def test_refund_manual_override_and_empty_review_decision():
    d=data([row(),row(transaction_id='refund',transaction_direction='refund',amount_krw=-100,
                      original_approval_number='approval')])
    assert not scope.select(d)[2]
    d=data([row()]);d['review_decisions']=[dict(transaction_id='synthetic',item='',display_tab_id='unclassified')]
    assert len(scope.select(d)[2])==1
    d['board_manual_overrides']=[dict(row_id='card-synthetic',field='item')]
    assert not scope.select(d)[2]


def test_prompt_projection_excludes_personal_source_columns():
    source=row(raw_row_json=json.dumps(dict(name='PRIVATE PERSON',card_number='1234567890123456',mcc='5812',country='JP')),
               merchant='SYNTHETIC CAFE 12345678')
    inputs,targets=layer1.merchants([source])
    serialized=json.dumps(inputs)
    assert all(secret not in serialized for secret in ('PRIVATE PERSON','1234567890123456','12345678','source_hash','approval_number'))
    assert inputs[0]['industry_codes']==['5812']
    assert inputs[0]['countries']==['JP']
    assert len(targets)==1


def test_stage2_normalization_uses_ledger_names_and_majority():
    inputs = [
        {'merchant_id': 'a', 'normalized': 'ALPICO KOTSU  NAGANO JP', 'names': ['ALPICO KOTSU  NAGANO JP'], 'count': 3},
        {'merchant_id': 'b', 'normalized': 'ALPICO KOTSU NAGANO JP', 'names': ['ALPICO KOTSU NAGANO JP'], 'count': 1},
    ]
    results = [
        {'merchant_id': 'a', 'item': '대중교통', 'confidence': '높음', 'basis': '합성'},
        {'merchant_id': 'b', 'item': '교통비', 'confidence': '낮음', 'basis': '합성'},
    ]
    normalized = layer1.normalize_results(inputs, results, ['교통비', '수수료', '입장료'])
    assert [r['item'] for r in normalized] == ['교통비', '교통비']


@pytest.mark.parametrize(('item','names','expected'), [
    ('편의점', ['CONVENIENCE STORE'], layer1.KEEP),
    ('이용료', ['HOT SPRING ONSEN'], '입장료'),
    ('이용료', ['ANNUAL CLUB FEE'], layer1.KEEP),
    ('세금과공과', ['UTILITY'], layer1.KEEP),
])
def test_stage2_item_mapping_is_conservative(item, names, expected):
    assert layer1.normalize_item(item, names, ['교통비', '수수료', '입장료']) == expected


def test_batch_runs_with_empty_cwd_and_rejects_tool_events(monkeypatch):
    monkeypatch.setattr(layer1.provider,'_executable',lambda:'synthetic.exe')
    batch=[{'merchant_id':'one'}]
    def runner(command,*,cwd,env,timeout,input_bytes):
        assert not list(Path(cwd).iterdir())
        assert '--ignore-user-config' in command and '--ephemeral' in command
        assert command[command.index('--sandbox')+1]=='read-only'
        assert 'approval_policy="never"' in command and 'mcp_servers={}' in command
        prompt=input_bytes.decode()
        digest=prompt.split('\nrequest_digest=')[1].splitlines()[0]
        run_id=prompt.split('\nrun_id=')[1]
        answer=dict(request_digest=digest,run_id=run_id,results=[dict(merchant_id='one',item='식비',confidence='높음',basis='합성 카페')])
        events=[dict(type='turn.started'),dict(type='item.completed',item=dict(type='agent_message',text=json.dumps(answer))),
                dict(type='turn.completed',usage=dict(input_tokens=100,output_tokens=20))]
        return subprocess.CompletedProcess(command,0,'\n'.join(json.dumps(e) for e in events).encode(),b'')
    assert layer1.call(batch,['식비'],runner=runner)['usage']['output_tokens']==20
    def tool_runner(*args,**kwargs):
        return subprocess.CompletedProcess([],0,b'{"type":"item.completed","item":{"type":"command_execution"}}',b'')
    with pytest.raises(AgentUnavailable,match='AGENT_TOOL_EXECUTION_DETECTED'):
        layer1.call(batch,['식비'],runner=tool_runner)


def test_result_requires_exact_coverage_allowed_item_and_bound_identity():
    answer=dict(request_digest='digest',run_id='run',results=[dict(merchant_id='one',item='식비',confidence='높음',basis='카페')])
    batch=[dict(merchant_id='one')]
    assert layer1.validate(answer,batch,['식비'],'digest','run')
    for mutation in ('duplicate','missing','unknown','wrong_digest','private'):
        bad=copy.deepcopy(answer)
        if mutation=='duplicate':bad['results']*=2
        elif mutation=='missing':bad['results']=[]
        elif mutation=='unknown':bad['results'][0]['item']='unknown'
        elif mutation=='private':bad['results'][0]['basis']='카드 12345678'
        else:bad['request_digest']='other'
        with pytest.raises(ValueError):layer1.validate(bad,batch,['식비'],'digest','run')


def test_actual_screen_warning_function_uses_stored_period_and_marks_limitation():
    d=data([row(item='숙박비')])
    d['board_rows']=[dict(row_id='card-synthetic',payload_json=json.dumps(dict(row_id='card-synthetic',item='숙박비',
        service_period='2026-06-30~2026-07-02',amount_krw=1000)))]
    report,ids=scope.service_warnings(d,d['transactions'])
    assert report['count']==0 and not ids
    d['board_rows']=[]
    report,ids=scope.service_warnings(d,d['transactions'])
    assert report['count']==1 and ids==['synthetic']
    assert 'upper_bound' in report['basis']


def test_live_projection_is_readonly_and_does_not_hold_connection(tmp_path):
    path=tmp_path/'synthetic.sqlite'
    c=sqlite3.connect(path)
    source=row()
    c.execute('CREATE TABLE transactions ('+','.join(k+' '+('INTEGER' if isinstance(v,int) else 'TEXT') for k,v in source.items())+')')
    c.execute('INSERT INTO transactions VALUES ('+','.join('?' for _ in source)+')',tuple(source.values()))
    c.execute('CREATE TABLE trip_tabs(tab_id,display_key,starts_on,ends_on,deleted)')
    c.execute('CREATE TABLE review_decisions(transaction_id,item,display_tab_id)')
    c.execute('CREATE TABLE board_manual_overrides(row_id,field)')
    c.execute('CREATE TABLE transaction_review_holds(transaction_id,source_hash,kind)')
    c.execute('CREATE TABLE transaction_company_exclusions(transaction_id,source_hash,excluded)')
    c.execute('CREATE TABLE board_rows(row_id,payload_json)')
    c.execute('CREATE TABLE ledger_entries(item)')
    c.commit();c.close()
    before=path.read_bytes()
    found=scope.read_projection(path)
    assert found['transactions'][0]['transaction_id']=='synthetic'
    assert path.read_bytes()==before
    # An exclusive transaction after the function returns proves its read lock is gone.
    with sqlite3.connect(path,timeout=.1) as writer:
        writer.execute('BEGIN EXCLUSIVE')
