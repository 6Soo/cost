import hashlib
import json

import pytest

from app import ai_review_repair as repair, source_recheck
from tests.test_ai_review_repair import add_projection, correction_for, make_manifest, prepare
from webapp.tests.test_automatic_classification_completion import setup
from tests.card_pipeline.fixtures import make_csv, domestic_row
from tests.card_pipeline.test_booking_mail import message, hotel

TRIPS = [dict(trip_id='A', starts_on='2026-06-01', ends_on='2026-06-05'),
         dict(trip_id='B', starts_on='2026-09-25', ends_on='2026-10-05')]


def reviewed(setup, tmp_path, *, kind='payment_outside_trip', day='2026-10-03'):
    c, batch, tid = setup[0].conn, setup[2], setup[3][0]['transaction_id']
    prepare(c)
    if day != '2026-10-03':
        batch=setup[1].pipeline.receive(make_csv([domestic_row(
            merchant='SYNTHETIC RECHECK', amount=4500, approval='SOURCE-CANCEL',date=day)]),'cancel.csv')['batch_id']
        tid=setup[1].pipeline.get_batch(batch)['rows'][0]['transaction_id']
        c.execute("UPDATE transactions SET classification_state='classified',classification_source='inference',"
            "item='식비',trip_id='A',display_tab_id='A',classification_basis='AUTO_INFERRED · synthetic' WHERE transaction_id=?",(tid,))
    c.execute('UPDATE transactions SET approval_date=? WHERE transaction_id=?', (day, tid))
    c.commit()
    add_projection(c, tid, batch)
    state = repair._state(c, tid)
    payload = state['board']['payload_json']
    c.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) VALUES (?,1,?,?,?,?,?,?,?)',
        ('card-'+tid, '{}', payload, '', 'create', 'automatic', 'synthetic', 'card-'+tid))
    c.commit()
    row = state['transaction']
    directory = tmp_path/'protected-review';directory.mkdir()
    content = c.execute('SELECT content_bytes FROM import_batches WHERE batch_id=?', (batch,)).fetchone()[0]
    (directory/'card.csv').write_bytes(content)
    originals = [dict(path='card.csv', role='card_original', sha256=hashlib.sha256(content).hexdigest())]
    for name, role in [('paid.txt', 'payment_confirmation'), ('cancelled.txt', 'cancellation_confirmation')]:
        body=hotel(ref='1234567890').replace('123,000원',str(row['amount_krw'])+'원')
        subject='[예약 확정 안내] 합성 숙소 예약이 확정되었습니다'
        if role=='cancellation_confirmation':
            body='예약번호 1234567890 예약이 취소되었습니다'
            subject='합성 예약이 취소되었습니다'
        data=json.dumps(message(body,subject=subject,identity=name,sent=day)).encode()
        (directory/name).write_bytes(data)
        originals.append(dict(path=name, role=role, sha256=hashlib.sha256(data).hexdigest()))
    review = dict(transaction_id=tid, before_tab='A', kind=kind, basis='PROC-073 · synthetic source review',
        card={k:row[k] for k in ('source_hash','approval_date','amount_krw','issuer','card_tail','merchant','approval_number')},
        originals=originals, reservation_status='cancelled', booking_ref='1234567890', cancelled_booking_ref='1234567890')
    document=dict(version=1, review_id='synthetic-source-review', reviews=[review])
    (directory/'manifest.json').write_text(json.dumps(document),encoding='utf-8')
    facts=source_recheck.load(c,TRIPS,directory)
    fact=facts[tid]
    correction=correction_for(c,tid,fact['display_tab_id'],item=fact['item'],basis=fact['basis'])
    manifest=make_manifest([correction]);manifest.update(scope=source_recheck.SCOPE,review_id=document['review_id'])
    return c, tid, directory, document, facts, manifest


def test_q2_automatic_row_moves_only_in_explicit_source_scope_and_replays(setup,tmp_path):
    c,tid,_,_,facts,manifest=reviewed(setup,tmp_path)
    ordinary=dict(manifest);ordinary.pop('scope')
    assert repair.preview(c,TRIPS,ordinary,evidence=facts)['summary']['to_apply']==0
    plan=repair.preview(c,TRIPS,manifest,evidence=facts)
    assert plan['summary']['to_apply']==1
    before=repair._financial_state(c)
    result=repair.apply(c,plan,TRIPS,manifest,request_id='source-recheck-synthetic',evidence=facts)
    assert result['applied_this_run']==1
    state=repair._state(c,tid)
    assert state['transaction']['trip_id']==state['ledger']['trip_id']==state['board']['display_tab_id']=='B'
    assert json.loads(state['board']['payload_json'])['trip_id']=='B'
    assert repair._financial_state(c)==before
    log=json.loads(c.execute('SELECT detail_json FROM change_log WHERE kind=?',(repair.RELEASE,)).fetchone()[0])
    assert log['source_recheck']['original_hashes']==facts[tid]['original_hashes']
    assert repair.apply(c,plan,TRIPS,manifest,request_id='source-recheck-synthetic',evidence=facts)['applied_this_run']==0
    assert not repair.preview(c,TRIPS,manifest,evidence=facts)['targets']


def test_cancelled_automatic_q2_payment_stays_positive_in_payment_quarter(setup,tmp_path):
    c,tid,_,_,facts,manifest=reviewed(setup,tmp_path,kind='cancelled_booking_payment',day='2026-06-17')
    plan=repair.preview(c,TRIPS,manifest,evidence=facts)
    assert plan['summary']['to_apply']==1
    original=repair._state(c,tid)['transaction']
    repair.apply(c,plan,TRIPS,manifest,request_id='cancelled-source-synthetic',evidence=facts)
    state=repair._state(c,tid)
    assert state['transaction']['display_tab_id']==state['ledger']['display_tab_id']=='quarter:2026:2'
    assert state['transaction']['trip_id']==state['ledger']['trip_id']==''
    assert state['transaction']['item']=='분기 기타비용'
    assert state['transaction']['amount_krw']==original['amount_krw']>0
    assert state['transaction']['source_hash']==original['source_hash']
    assert c.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==1
    assert json.loads(state['board']['payload_json'])['trip_id']==''


@pytest.mark.parametrize('guard',['owner','later_owner','p2','q1','projection','refund','missing_history'])
def test_source_scope_preserves_protection_boundaries(setup,tmp_path,guard):
    c,tid,_,_,facts,manifest=reviewed(setup,tmp_path)
    if guard=='owner':
        state=repair._state(c,tid);payload=json.loads(state['board']['payload_json']);payload['confirmed_by']='owner'
        c.execute('UPDATE board_revisions SET actor=?,new_json=? WHERE row_id=?',('owner',json.dumps(payload),'card-'+tid))
    elif guard=='later_owner':
        c.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) VALUES (?,2,?,?,?,?,?,?,?)',
            ('card-'+tid,'{}','{}','','move','owner','synthetic','owner-edit'))
    elif guard=='p2':c.execute("UPDATE transactions SET classification_source='ai_inference' WHERE transaction_id=?",(tid,))
    elif guard=='q1':
        trips=[dict(t,starts_on='2026-01-01',ends_on='2026-01-05') if t['trip_id']=='A' else t for t in TRIPS]
        c.commit();assert not repair.preview(c,trips,manifest,evidence=facts)['targets'];return
    elif guard=='projection':c.execute("UPDATE ledger_entries SET display_tab_id='B' WHERE transaction_id=?",(tid,))
    elif guard=='refund':c.execute("UPDATE transactions SET transaction_direction='refund' WHERE transaction_id=?",(tid,))
    elif guard=='missing_history':c.execute('DELETE FROM board_revisions WHERE row_id=?',('card-'+tid,))
    c.commit();before=repair._state(c,tid)
    assert not repair.preview(c,TRIPS,manifest,evidence=facts)['targets']
    assert repair._state(c,tid)==before


def test_changed_original_and_card_binding_are_rejected(setup,tmp_path):
    c,tid,directory,doc,_,_=reviewed(setup,tmp_path)
    (directory/'paid.txt').write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='ORIGINAL_CHANGED'):source_recheck.load(c,TRIPS,directory)
    doc['reviews'][0]['originals']=doc['reviews'][0]['originals'][:1]
    doc['reviews'][0]['card']['source_hash']='changed'
    (directory/'manifest.json').write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError,match='SOURCE_CHANGED'):source_recheck.load(c,TRIPS,directory)


def test_cancelled_booking_identity_must_match(setup,tmp_path):
    c,_,directory,doc,_,_=reviewed(setup,tmp_path,kind='cancelled_booking_payment')
    doc['reviews'][0]['cancelled_booking_ref']='another-booking'
    (directory/'manifest.json').write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError,match='CANCELLATION_INVALID'):source_recheck.load(c,TRIPS,directory)


@pytest.mark.parametrize('wrong',['opaque_bytes','policy_only','different_booking','different_amount','different_date'])
def test_role_and_hash_alone_cannot_assert_cancellation(setup,tmp_path,wrong):
    c,_,directory,doc,_,_=reviewed(setup,tmp_path,kind='cancelled_booking_payment')
    review=doc['reviews'][0]
    role='payment_confirmation' if wrong in ('different_amount','different_date') else 'cancellation_confirmation'
    original=next(o for o in review['originals'] if o['role']==role)
    data=(directory/original['path']).read_bytes()
    if wrong=='opaque_bytes':data=b'no reservation or cancellation facts'
    else:
        mail=json.loads(data)
        if wrong=='policy_only':mail['payload']['headers'][1]['value']='예약 취소 정책 안내'
        if wrong=='different_booking':mail['payload']['body']['content']=mail['payload']['body']['content'].replace('1234567890','9999999999')
        if wrong=='different_amount':mail['payload']['body']['content']=hotel(ref='1234567890')
        if wrong=='different_date':mail=message(mail['payload']['body']['content'],sent='2026-01-01')
        data=json.dumps(mail).encode()
    (directory/original['path']).write_bytes(data);original['sha256']=hashlib.sha256(data).hexdigest()
    (directory/'manifest.json').write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError,match='CANCELLATION_INVALID'):source_recheck.load(c,TRIPS,directory)


def test_offline_cli_checks_the_explicit_backend_while_gateway_is_paused(setup,tmp_path,monkeypatch):
    import sqlite3
    from tools import apply_ai_quarter_review as cli
    c,_,_,_,_,manifest=reviewed(setup,tmp_path)
    host=tmp_path/'host';(host/'data').mkdir(parents=True);(host/'config').mkdir()
    with sqlite3.connect(host/'data/board.sqlite') as copy:c.backup(copy)
    (host/'config/ledger-route.json').write_text(json.dumps(dict(port=8752,paused=True,generation='synthetic')),encoding='utf-8')
    path=tmp_path/'corrections.json';path.write_text(json.dumps(manifest),encoding='utf-8')
    observed={}
    def writer_gate(*args,**kwargs):
        observed.update(kwargs)
        raise ValueError('EXPECTED_WRITER_GATE')
    monkeypatch.setattr(cli,'require_offline_backup',writer_gate)
    assert cli.main(['--host-root',str(host),'--manifest',str(path),'--request-id','synthetic',
        '--apply','--expected-digest','synthetic','--backup-evidence',str(tmp_path/'backup.json')])==1
    assert observed['board_port']==8752 and observed['isolated_copy'] is False
