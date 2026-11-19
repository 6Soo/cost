import copy
import json
from pathlib import Path
import re
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


@pytest.mark.parametrize(('status','reason','limit'), [
    ('success', None, False), ('failed', 'AGENT_RATE_LIMITED', True),
    ('failed', 'ValueError', False),
])
def test_layer1_public_summary_atomic_schema(tmp_path, status, reason, limit):
    db = tmp_path/'board.sqlite'
    layer1.write_public_summary(db, dict(started_at='2026-11-13T00:00:00+00:00',
        finished_at='2026-11-13T00:01:00+00:00', target_groups=3, target_rows=7,
        model_calls=2, successful_calls=1, failed_calls=int(status == 'failed'),
        applied_rows=0, limit_failure=limit, status=status), failure_reason_code=reason)
    path = tmp_path/'p2-runs'/'latest.json'
    summary = json.loads(path.read_text(encoding='utf-8'))
    assert summary['status'] == status and summary['failure_reason_code'] == reason
    assert summary['target_groups'] == 3 and summary['target_rows'] == 7
    assert summary['limit_failure'] is limit
    assert not path.with_suffix('.tmp').exists()
    assert 'synthetic' not in json.dumps(summary)


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


def policy_dir(tmp_path, *, retired=(), extra=None):
    """Synthetic policy set: the four surviving exceptions plus a canonical target for each retired ID."""
    canonical = dict({'ITEM-037': ('TRIP-070', 'trip.md'), 'ITEM-038': ('TRIP-071', 'trip.md'),
                      'ITEM-044': ('DATE-054', 'date.md')}, **{old: (new, name) for old, new, name in retired})
    files = {f'{index}.md': f'### {identity} · 합성 예외 {identity}\n\n*사용자 예외 · 결정 2026-11-19*\n\n'
                            f'{identity} 본문이며 다른 항목을 판정하지 않는다.\n\n- 예: 합성 근거\n'
             for index, identity in enumerate(i for i in layer1.POLICY_EXCEPTION_IDS
                                              if i not in ('ITEM-037', 'ITEM-038', 'ITEM-044'))}
    for index, (old, (new, name)) in enumerate(canonical.items()):
        files.setdefault(name, '')
        files[name] += (f'### {new} · 정본 {new}\n\n*사용자 예외 · 결정 2026-11-19*\n\n'
                        f'{new} 정본이며 다른 항목을 판정하지 않는다.\n\n')
    files.update(extra or {})
    files.setdefault('RETIRED_IDS.md', '# 폐지·통합 ID\n\n| 과거 ID | 과거 규칙 제목 | 결정 유형 | 상태 | 현행 정본 ID |\n')
    files['RETIRED_IDS.md'] += ''.join(f'| `{old}` | 옛 {old} | 사용자 예외 · 결정 2026-10-12 | **폐지·통합** | '
                                       f'[`{new}`](./{name}) |\n'
                                       for old, (new, name) in canonical.items() if old in layer1.POLICY_EXCEPTION_IDS)
    for name, text in files.items():
        (tmp_path/name).write_text(text, encoding='utf-8')
    return tmp_path


def test_layer1_policy_exceptions_keep_seven_sections_after_abolished_ids():
    # The real policy set must still hand layer 1 all seven item exceptions even though
    # ITEM-037/038/044 became TRIP-070/071/DATE-054 in the consolidated documents.
    text = layer1.policy_text()
    identities = re.findall(r'(?m)^### ([A-Z]+-\d+)', text)
    assert identities == ['ITEM-024', 'ITEM-028', 'ITEM-029', 'TRIP-070', 'TRIP-071', 'DATE-054', 'ITEM-050']
    core = layer1.ROOT.joinpath('docs/DECISION_POLICY.md').read_text(encoding='utf-8')
    assert text.startswith(core.split('### 3.3 항목',1)[1].split('### 3.4',1)[0])
    assert '- 출처:' not in text


def test_layer1_policy_text_refuses_missing_section_instead_of_stopiteration(tmp_path):
    policy = policy_dir(tmp_path)
    (policy/'trip.md').write_text((policy/'trip.md').read_text(encoding='utf-8')
                                  .replace('### TRIP-071 · 정본 TRIP-071\n', ''), encoding='utf-8')
    with pytest.raises(ValueError, match='POLICY_SECTION_MISSING:TRIP-071'):
        layer1.policy_text(policy)


def test_canonical_rule_follows_abolished_id_mapping_and_keeps_cycles_out():
    sections = {'TRIP-071': '### TRIP-071 · 정본', 'ITEM-028': '### ITEM-028 · 정본'}
    owners = {'TRIP-071': 'trip.md', 'ITEM-028': 'item.md'}
    retired = {'ITEM-037': ('TRIP-070', 'trip.md'), 'TRIP-070': ('TRIP-071', 'trip.md'),
               'TRIP-072': ('TRIP-073', 'trip.md'), 'TRIP-073': ('TRIP-072', 'trip.md')}
    assert layer1.canonical_rule('ITEM-028', sections, owners, retired) == sections['ITEM-028']
    assert layer1.canonical_rule('ITEM-037', sections, owners, retired) == sections['TRIP-071']
    with pytest.raises(ValueError, match='POLICY_SECTION_MISSING:TRIP-072'):
        layer1.canonical_rule('TRIP-072', sections, owners, retired)
    retired['ITEM-037'] = ('TRIP-071', 'item.md')
    with pytest.raises(ValueError, match='POLICY_RETIRED_FILE_MISMATCH:TRIP-071'):
        layer1.canonical_rule('ITEM-037', sections, owners, retired)




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


def test_stage2_canonical_name_removes_single_space_city_country_suffix():
    assert layer1.canonical_merchant_name('ALPICO KOTSU NAGANO JP') == 'alpico kotsu'
    assert layer1.canonical_merchant_name('ALPICO KOTSU TOKYO JP') == 'alpico kotsu'


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
    c.execute('CREATE TABLE ledger_entries(item,transaction_id,trip_id,display_tab_id)')
    c.commit();c.close()
    before=path.read_bytes()
    found=scope.read_projection(path)
    assert found['transactions'][0]['transaction_id']=='synthetic'
    assert path.read_bytes()==before
    # An exclusive transaction after the function returns proves its read lock is gone.
    with sqlite3.connect(path,timeout=.1) as writer:
        writer.execute('BEGIN EXCLUSIVE')


@pytest.mark.parametrize('field', ['trip_id', 'display_tab_id'])
def test_selection_excludes_preexisting_ledger_attribution_disagreement(field):
    d = data([row(), row(transaction_id='consistent'), row(transaction_id='unrecorded')])
    conflict = dict(transaction_id='synthetic', trip_id='open', display_tab_id='open')
    conflict[field] = 'closed'
    d['ledger_entries'] = [conflict, dict(transaction_id='consistent', trip_id='open', display_tab_id='open')]
    report, scoped, eligible, general = scope.select(d)
    assert len(scoped) == 3
    assert report['projection_attribution_disagreements'] == 1
    assert report['protected']['PROJECTION_ATTRIBUTION_DISAGREEMENT'] == 1
    assert {r['transaction_id'] for r in eligible} == {'consistent', 'unrecorded'}
    assert general == eligible


def test_preview_excludes_live_projection_conflict_before_correction(tmp_path, monkeypatch):
    from tools.p2_batch import preview
    path = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE transactions(transaction_id,trip_id,display_tab_id)')
        conn.execute("INSERT INTO transactions VALUES ('synthetic','open','open')")
        conn.execute('CREATE TABLE ledger_entries(transaction_id,trip_id,display_tab_id)')
        conn.execute("INSERT INTO ledger_entries VALUES ('synthetic','closed','closed')")
        conn.execute('CREATE TABLE trip_tabs(tab_id)')
    (tmp_path / 'normalized-proposals.jsonl').write_text(json.dumps(dict(
        merchant_id='merchant', item='교통비', basis='synthetic', execution={})), encoding='utf-8')
    (tmp_path / 'before-state.json').write_text(json.dumps({'merchant': [row()]}), encoding='utf-8')
    def forbidden(*args, **kwargs):
        pytest.fail('conflicting attribution reached correction preview')
    monkeypatch.setattr(preview.classification_correction, 'preview', forbidden)
    report = preview.run(path, tmp_path)
    assert report['passed'] == 0
    assert report['excluded_by_reason'] == {'PROJECTION_ATTRIBUTION_DISAGREEMENT': 1}
