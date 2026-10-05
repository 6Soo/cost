import sqlite3
import pytest
from app import Pipeline,StoreError
from app.review_holds import active_holds


def setup():
    pipe=Pipeline(sqlite3.connect(':memory:',isolation_level=None))
    content=('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
             'Date,Post Date,Authorization Code,Cancel,Status\n'
             '국민,1234,domestic,purchase,합성상점,37000,,,37000,2026-10-01,2026-10-02,A123,,매입\n').encode()
    batch=pipe.receive(content,'synthetic.csv')['batch_id']
    pipe.classify_batch(batch)
    row=pipe.get_batch(batch)['rows'][0]
    pipe.save_decision(row['transaction_id'],row['revision'],item='숙박비',display_tab_id='unclassified',
                       tab_validator=lambda _:True,request_id='first')
    row=pipe.get_batch(batch)['rows'][0]
    return pipe,batch,row


def test_hold_blocks_confirmed_cost_and_invalidates_previous_preview():
    pipe,batch,row=setup()
    old=pipe.preview(batch,tab_validator=lambda _:True)
    assert old['ready']==1
    pipe.store.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                            (row['transaction_id'],row['source_hash'],'refund_pending','실제 환불 확인 대기'))
    current=pipe.preview(batch,tab_validator=lambda _:True)
    assert current['ready']==0
    assert current['rows'][0]['blocked']=='review_hold'
    with pytest.raises(StoreError):pipe.commit(batch,old['digest'],'commit',tab_validator=lambda _:True)
    assert pipe.store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0


def test_saving_an_answer_keeps_hold_until_explicitly_released():
    pipe,batch,row=setup()
    pipe.store.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                            (row['transaction_id'],row['source_hash'],'user_hold','사용자 보류'))
    args=dict(item='숙박비',display_tab_id='unclassified',tab_validator=lambda _:True)
    pipe.save_decision(row['transaction_id'],row['revision'],request_id='edit',**args)
    assert active_holds(pipe.store.conn)
    row2=pipe.get_batch(batch)['rows'][0]
    pipe.save_decision(row2['transaction_id'],row2['revision'],request_id='resolve',resolve_hold=True,**args)
    assert not active_holds(pipe.store.conn)
    assert pipe.preview(batch,tab_validator=lambda _:True)['ready']==1
    row3=pipe.get_batch(batch)['rows'][0]
    assert (row3['source_hash'],row3['amount_krw'])==(row['source_hash'],row['amount_krw'])


def test_source_mismatch_never_releases_a_hold_for_different_original():
    pipe,batch,row=setup()
    pipe.store.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                            (row['transaction_id'],'a'*64,'user_hold','사용자 보류'))
    pipe.save_decision(row['transaction_id'],row['revision'],item='숙박비',request_id='resolve',resolve_hold=True)
    assert active_holds(pipe.store.conn)[row['transaction_id']]['kind']=='evidence_pending'
