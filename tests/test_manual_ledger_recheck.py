import hashlib
import json

import openpyxl
import pytest

from app import ai_review_repair as repair, source_recheck
from app.google_authority import SPREADSHEET_IDS
from app.google_expense_rows import day
from app.manual_ledger_recheck import same_transaction
from tests.test_source_recheck import reviewed, TRIPS
from tests.test_ai_review_repair import correction_for, make_manifest
from webapp.tests.test_automatic_classification_completion import setup


def book(path, sheet, *, amount=4500, date='26.06.17', payee='ACTUAL SELLER', period='1001_1002'):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = sheet
    labels = ('거래일자', '항목', '내용', '기간', '예약번호', '증빙유형', '금액(원)')
    for col, label in enumerate(labels, 2): ws.cell(1, col, label)
    for col, value in enumerate((date, payee, '항공_합성', period, None, '국민', amount), 2): ws.cell(2, col, value)
    wb.save(path)


def case(setup, tmp_path, *, owner=False, baseline=False):
    c, tid, directory, doc, _, _ = reviewed(setup, tmp_path, day='2026-06-17')
    trips = [dict(t, display_key='0601_SYNTHETIC' if t['trip_id']=='A' else '1001_SYNTHETIC') for t in TRIPS]
    review = doc['reviews'][0]; review['kind'] = 'manual_ledger_attribution'
    for role, sheet in (('archive','0601_SYNTHETIC'), ('main','1001_SYNTHETIC')):
        path=directory/(role+'.xlsx'); book(path,sheet,amount=4500 if role=='main' or baseline else 9999)
        review['originals'].append(dict(path=path.name, role='manual_ledger', ledger_source=role,
            spreadsheet_id=SPREADSHEET_IDS[role],sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if owner:
        state=repair._state(c,tid);payload=json.loads(state['board']['payload_json']);payload['confirmed_by']='owner'
        initial=dict(payload,display_tab_id=None,trip_id='',source_event_id=tid,
            amount_krw=state['transaction']['amount_krw'],source_fact_digest=state['transaction']['source_hash'])
        c.execute('UPDATE board_revisions SET actor=?,new_json=? WHERE row_id=?',('owner',json.dumps(initial),'card-'+tid))
        c.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?',(json.dumps(payload),'card-'+tid));c.commit()
    (directory/'manifest.json').write_text(json.dumps(doc),encoding='utf-8')
    return c,tid,directory,doc,trips


def load_case(c,tid,directory,doc,trips):
    facts=source_recheck.load(c,trips,directory);fact=facts[tid]
    manifest=make_manifest([correction_for(c,tid,fact['display_tab_id'],item=fact['item'],basis=fact['basis'])])
    manifest.update(scope=source_recheck.SCOPE,review_id=doc['review_id'])
    return facts,manifest


@pytest.mark.parametrize('owner',[False,True])
def test_original_date_amount_cross_quarter_corrects_item_and_three_projections(setup,tmp_path,owner):
    c,tid,directory,doc,trips=case(setup,tmp_path,owner=owner)
    facts,manifest=load_case(c,tid,directory,doc,trips);plan=repair.preview(c,trips,manifest,evidence=facts)
    assert plan['summary']['to_apply']==1
    before=repair._state(c,tid);financial=repair._financial_state(c)
    repair.apply(c,plan,trips,manifest,request_id='manual-ledger-source',evidence=facts)
    state=repair._state(c,tid)
    assert state['transaction']['item']==state['ledger']['item']=='항공료'
    assert state['transaction']['trip_id']==state['ledger']['trip_id']==state['board']['display_tab_id']=='B'
    assert state['transaction']['description'].startswith('항공료')
    assert state['ledger']['description']==state['transaction']['description']==json.loads(state['board']['payload_json'])['description']
    assert state['transaction']['amount_krw']==before['transaction']['amount_krw']
    assert state['transaction']['source_hash']==before['transaction']['source_hash']
    assert repair._financial_state(c)==financial
    assert repair.apply(c,plan,trips,manifest,request_id='manual-ledger-source',evidence=facts)['applied_this_run']==0
    restore=repair.restore_preview(c,'manual-ledger-source')
    repair.restore(c,restore,'manual-ledger-source')
    restored=repair._state(c,tid)
    for field in ('item','description','display_tab_id','trip_id'):
        assert restored['transaction'][field]==before['transaction'][field]
        assert restored['ledger'][field]==before['ledger'][field]


@pytest.mark.parametrize('guard',['baseline','two_targets','wrong_period','changed_bytes','later_owner','selected_initial_trip','manual_override','p2','ordinary_scope'])
def test_original_ledger_review_does_not_waive_protections(setup,tmp_path,guard):
    c,tid,directory,doc,trips=case(setup,tmp_path,owner=True,baseline=guard=='baseline')
    if guard=='baseline':
        with pytest.raises(ValueError,match='ALREADY_PRESENT'):load_case(c,tid,directory,doc,trips)
        return
    if guard=='two_targets':
        path=directory/'main.xlsx';wb=openpyxl.load_workbook(path);ws=wb.active
        for col in range(2,9):ws.cell(3,col,ws.cell(2,col).value)
        wb.save(path)
    elif guard=='wrong_period':book(directory/'main.xlsx','1001_SYNTHETIC',period='0601_0602')
    elif guard=='changed_bytes':(directory/'main.xlsx').write_bytes(b'changed')
    if guard in ('two_targets','wrong_period'):
        doc['reviews'][0]['originals'][-1]['sha256']=hashlib.sha256((directory/'main.xlsx').read_bytes()).hexdigest()
        (directory/'manifest.json').write_text(json.dumps(doc),encoding='utf-8')
    if guard in ('two_targets','wrong_period','changed_bytes'):
        with pytest.raises(ValueError,match='AMBIGUOUS|PERIOD_INVALID|ORIGINAL_CHANGED'):load_case(c,tid,directory,doc,trips)
        return
    if guard=='later_owner':
        c.execute("INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) VALUES (?,2,'{}','{}','','exception','owner','synthetic','later')",('card-'+tid,))
    elif guard=='selected_initial_trip':
        raw=json.loads(c.execute('SELECT new_json FROM board_revisions WHERE row_id=?',('card-'+tid,)).fetchone()[0]);raw['display_tab_id']='A';c.execute('UPDATE board_revisions SET new_json=? WHERE row_id=?',(json.dumps(raw),'card-'+tid))
    elif guard=='manual_override':c.execute("INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?,'display_tab_id','manual')",('card-'+tid,))
    elif guard=='p2':c.execute("UPDATE transactions SET classification_source='ai_inference' WHERE transaction_id=?",(tid,))
    c.commit();facts,manifest=load_case(c,tid,directory,doc,trips)
    if guard=='ordinary_scope':manifest.pop('scope')
    assert not repair.preview(c,trips,manifest,evidence=facts)['targets']


def test_matching_accepts_date_or_distinctive_merchant_with_same_amount():
    card=dict(amount_krw=5000,approval_date='2026-04-18',merchant='PAYMENT GATEWAY')
    original=dict(amount=5000,cells=dict(B='26.04.18',C='OTHER SELLER'))
    assert same_transaction(card,original)
    assert not same_transaction(card,dict(original,amount=5001))
    assert same_transaction(dict(card,merchant='SYNTHETIC HOTEL'),dict(original,cells=dict(B='26.05.01',C='SYNTHETIC')))
    assert not same_transaction(dict(card,merchant='ONE HOTEL'),dict(original,cells=dict(B='26.05.01',C='OTHER HOTEL')))
    assert not same_transaction(dict(card,merchant='THE HOTEL'),dict(original,cells=dict(B='26.05.01',C='THE HOTELS')))
    assert not same_transaction(dict(card,merchant='NICE PAYMENT GATEWAY'),dict(original,cells=dict(B='26.05.01',C='OTHER PAYMENT GATEWAY')))
    assert not same_transaction(dict(card,merchant='NICEPAYMENTGATEWAY'),dict(original,cells=dict(B='26.05.01',C='PAYMENTGATEWAY')))
    assert not same_transaction(dict(card,merchant='THEHOTEL'),dict(original,cells=dict(B='26.05.01',C='THEHOTELS')))
    assert not same_transaction(dict(card,merchant='THEHOTELALPHA'),dict(original,cells=dict(B='26.05.01',C='THEHOTELBETA')))
    assert not same_transaction(dict(card,merchant='ONE TOKYO JPN'),dict(original,cells=dict(B='26.05.01',C='OTHER TOKYO JP')))


def test_short_year_is_explicit_not_inferred_from_current_date():
    assert day('26.04.18',2026)=='2026-04-18'
    assert day('25.04.18',2026) is None
    assert day('26.04.18') is None
    assert day('26.02.30',2026) is None
