"""메일 누락 구간의 보존 포털 근거를 합성 자료로 검증한다."""
import hashlib
import json
import sqlite3

import pytest

from app.ota_mail import match_mail
from app.ota_portal import extend_report, portal_matches


def portal_database(path, facts=None, *, status='observed', conflict=0):
    fact=dict(provider='agoda',booking_number='synthetic-booking',
        service_start_on='2026-08-02',service_end_on='2026-08-03',
        reservation_status='completed',payment_status='paid',collection_model='agoda_collect',
        refund_status='none_displayed',card_last4='1234',price_components=[
            dict(kind='paid_today',currency='KRW',decimal_text='30000',minor_units=30000,scale=0)])
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE bookings(id TEXT,provider TEXT,booking_number TEXT,service_start_on TEXT,service_end_on TEXT,status TEXT);
            CREATE TABLE direct_source_records(id TEXT,source_kind TEXT,payload_json TEXT,source_sha256 TEXT);
            CREATE TABLE booking_source_evidence(booking_id TEXT,direct_source_record_id TEXT,evidence_role TEXT,evidence_status TEXT,conflict_count INTEGER);
        ''')
        for index,changes in enumerate(facts or [{}]):
            payload=dict(fact,**changes)
            raw=json.dumps(payload,ensure_ascii=False,sort_keys=True)
            conn.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?)',
                (str(index),'agoda',payload['booking_number'],payload['service_start_on'],payload['service_end_on'],'completed'))
            conn.execute('INSERT INTO direct_source_records VALUES (?,?,?,?)',
                (str(index),'agoda_portal_detail',raw,hashlib.sha256(raw.encode()).hexdigest()))
            conn.executemany('INSERT INTO booking_source_evidence VALUES (?,?,?,?,?)',
                [(str(index),str(index),role,status,conflict) for role in
                 ('identity','service_period','portal_payment_claim','portal_card_observation','lifecycle')])
    return path


def card(**changes):
    return dict(dict(transaction_id='synthetic-card',source_hash='a'*64,merchant='AGODA_NICE-Agoda',
        merchant_normalized='agoda nice-agoda',card_kind='신용',approval_date='2026-07-11',
        transaction_direction='purchase',amount_krw=30000,card_tail='1234',foreign_amount=None,
        foreign_currency=''),**changes)


def test_portal_primary_evidence_does_not_require_mail_or_payment_day(tmp_path):
    path=portal_database(tmp_path/'portal.sqlite')
    before=path.read_bytes()
    result=extend_report(match_mail(tmp_path/'missing-mail',[card()]),path,[card(),card()])
    assert result['exact_matches']==1
    assert result['matches'][0]['booking_ref']=='synthetic-booking'
    assert result['matches'][0]['period']=={'starts_on':'2026-08-02','ends_on':'2026-08-03'}
    assert result['matches'][0]['evidence_kind']=='portal_payment_claim'
    assert result['rules'][0]['origin']=='ota-portal-live'
    assert result['coverage']['unmatched_purchase_rows']==0
    assert result['unmatched_transactions']==[]
    assert path.read_bytes()==before


@pytest.mark.parametrize('changes',[
    {'card_tail':'9876'}, {'merchant':'AGODAEVIL'}, {'amount_krw':29999},
    {'transaction_direction':'refund'}, {'duplicate_of':'other'}, {'parse_error':'bad'},
])
def test_card_mismatch_or_invalid_row_is_not_linked(tmp_path,changes):
    assert portal_matches(portal_database(tmp_path/'portal.sqlite'),[card(**changes)])==[]


@pytest.mark.parametrize('changes',[
    {'reservation_status':'cancelled'}, {'payment_status':'scheduled'}, {'refund_status':'refunded'},
    {'collection_model':'hotel_collect'}, {'service_start_on':'bad-date'},
    {'price_components':[dict(kind='gross_total',currency='KRW',decimal_text='30000',minor_units=30000,scale=0)]},
    {'price_components':[dict(kind='paid_today',currency='KRW',decimal_text='30000',minor_units=31000,scale=0)]},
])
def test_unverified_or_conflicting_portal_fact_is_not_used(tmp_path,changes):
    assert portal_matches(portal_database(tmp_path/'portal.sqlite',[changes]),[card()])==[]


def test_real_multiple_cards_or_bookings_stay_ambiguous(tmp_path):
    path=portal_database(tmp_path/'portal.sqlite')
    assert portal_matches(path,[card(),card(transaction_id='other',source_hash='b'*64)])==[]
    path2=portal_database(tmp_path/'portal2.sqlite',[{}, {'booking_number':'other-booking'}])
    assert portal_matches(path2,[card()])==[]


def test_source_hash_and_evidence_roles_are_required(tmp_path):
    path=portal_database(tmp_path/'portal.sqlite')
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM booking_source_evidence WHERE evidence_role='portal_card_observation'")
    assert portal_matches(path,[card()])==[]
    bad=portal_database(tmp_path/'bad.sqlite',conflict=1)
    assert portal_matches(bad,[card()])==[]
    tampered=portal_database(tmp_path/'tampered.sqlite')
    with sqlite3.connect(tampered) as conn:
        conn.execute("UPDATE direct_source_records SET source_sha256='invalid'")
    with pytest.raises(ValueError,match='PAYLOAD_HASH_MISMATCH'):
        portal_matches(tampered,[card()])


def test_mail_and_portal_disagreement_blocks_booking_and_old_trip_inference(tmp_path):
    path=portal_database(tmp_path/'portal.sqlite')
    result=match_mail(tmp_path/'missing-mail',[card()])
    result['matches']=[dict(source_hash='a'*64,booking_ref='different-booking',item='숙박비',
                            source_sha256='c'*64,period=None)]
    result['rules']=[dict(optional={'source_hash':'a'*64},effects={'item':'숙박비','description':'예약 different-booking'})]
    result=extend_report(result,path,[card()])
    assert result['matches'][0]['booking_link_conflict']
    assert result['matches'][0]['period'] is None
    assert result['rules']==[]
    from webapp.card_flow import _mail_evidence_from_report,_review_evidence_labels
    labels=_review_evidence_labels(card(),_mail_evidence_from_report(result,['a'*64])['a'*64])
    assert labels==['예약 근거 충돌 · 연결 확인 필요']


@pytest.mark.parametrize('trip_end,expected_trip',[('2026-08-06',True),('2026-08-02',False)])
def test_card_flow_uses_portal_without_mail_and_keeps_user_answer(tmp_path,monkeypatch,trip_end,expected_trip):
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    from tests.card_pipeline.fixtures import make_csv,domestic_row
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    monkeypatch.setenv('WEBLEDGER_OTA_MAIL_DIR',str(tmp_path/'no-mail'))
    monkeypatch.setenv('WEBLEDGER_AGODA_PORTAL_DB',str(portal_database(tmp_path/'portal.sqlite')))
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        flow=CardFlow(board)
        trip=board.create_trip(starts_on='2026-08-01',ends_on=trip_end,
                              destination='합성 여행',client_request_id='synthetic-trip')['tab_id']
        flow.trip_valid=lambda identity:identity==trip
        batch=flow.pipeline.receive(make_csv([domestic_row(merchant='AGODA_NICE-Agoda',amount=30000,
            approval='synthetic-payment',date='2026-07-11')]),'synthetic.csv')['batch_id']
        original=flow.pipeline.get_batch(batch)['rows'][0]
        flow.pipeline.save_rule({'conditions':{'merchant_normalized':original['merchant']},
            'optional':{'source_hash':original['source_hash'],'inferred_assignment':{
                'trip_id':trip,'confidence':'낮음','basis':'과거 추론'}},'effects':{'item':'숙박비'}})
        rules=flow.pipeline.list_rules()
        for _ in range(2):
            flow.classify(batch)
            current=flow.state(batch)['rows'][0]
            assert current['classification_source']=='rule'
            assert current['trip_id']==(trip if expected_trip else '') and not current['decided']
            assert current['review_evidence_labels']==['예약 근거 있음']
            for field in ('transaction_id','source_hash','approval_date','amount_krw'):
                assert current[field]==original[field]
        assert flow.pipeline.list_rules()==rules
        assert board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0]==0
        if expected_trip:
            flow.trip_valid=lambda identity:False
            flow.classify(batch)
            current=flow.pipeline.get_batch(batch)['rows'][0]
            assert current['classification_source']=='rule' and current['item']=='숙박비'
            assert current['trip_id']==''
        flow.pipeline.save_decision(current['transaction_id'],current['revision'],item='사무용품비',
            description='직접 분류',display_tab_id='unclassified',trip_id='',
            request_id='synthetic-answer',tab_validator=flow.tab_valid)
        flow.classify(batch)
        current=flow.state(batch)['rows'][0]
        assert current['item']=='사무용품비' and current['decided']
    finally:
        board.close()


def test_canonical_conflict_refreshes_portal_cache_even_without_count_change(tmp_path,monkeypatch):
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    from tests.card_pipeline.fixtures import make_csv,domestic_row
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    monkeypatch.setenv('WEBLEDGER_OTA_MAIL_DIR',str(tmp_path/'no-mail'))
    monkeypatch.setenv('WEBLEDGER_AGODA_PORTAL_DB',str(portal_database(tmp_path/'portal.sqlite')))
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        flow=CardFlow(board)
        batch=flow.pipeline.receive(make_csv([domestic_row(merchant='AGODA',amount=30000,
            approval='synthetic-payment')]),'synthetic.csv')['batch_id']
        row=flow.pipeline.get_batch(batch)['rows'][0]
        assert flow.review_mail_evidence([row])[row['source_hash']]['booking_match']
        board.conn.execute('UPDATE transactions SET conflict_reason=? WHERE transaction_id=?',
                           ('synthetic source conflict',row['transaction_id']))
        evidence=flow.review_mail_evidence([row])[row['source_hash']]
        assert not evidence.get('booking_match')
        assert evidence.get('mail_link_absent')
    finally:
        board.close()


@pytest.mark.parametrize('width,height',[(390,844),(1440,900)])
def test_portal_evidence_and_classification_render_through_real_http(tmp_path,monkeypatch,width,height):
    import threading
    from unittest.mock import patch
    from playwright.sync_api import sync_playwright
    from webapp import ledger_board
    from webapp.card_flow import CardFlow
    from tests.card_pipeline.fixtures import make_csv,domestic_row
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW','1')
    monkeypatch.setenv('WEBLEDGER_OTA_MAIL_DIR',str(tmp_path/'no-mail'))
    monkeypatch.setenv('WEBLEDGER_AGODA_PORTAL_DB',str(portal_database(tmp_path/'portal.sqlite')))
    ledger_board.bind_access(None)
    server=ledger_board.serve(port=0,db_path=tmp_path/'board.sqlite',with_worker=False,seed_demo=False)
    flow=CardFlow(server.card_store)
    batch=flow.pipeline.receive(make_csv([domestic_row(merchant='AGODA_NICE-Agoda',amount=30000,
        approval='synthetic-payment',date='2026-07-11')]),'synthetic.csv')['batch_id']
    trip=server.card_store.create_trip(starts_on='2026-08-01',ends_on='2026-08-06',
        destination='합성 여행',client_request_id='synthetic-trip')['tab_id']
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    errors=[]
    try:
        with patch.object(CardFlow,'trip_valid',lambda self,identity:identity==trip),sync_playwright() as api:
            browser=api.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':width,'height':height})
            page.on('pageerror',lambda error:errors.append(str(error)))
            assert page.goto(f'http://127.0.0.1:{server.server_address[1]}/import').status==200
            page.locator('#questions .ri-flag').first.wait_for()
            assert '예약 근거 있음' in page.locator('#questions .ri-flag').first.inner_text()
            assert '메일 연결 없음' not in page.locator('#questions').inner_text()
            assert page.locator('#questions .review-item[open]').count()==1
            assert page.locator('#questions summary').first.evaluate('el=>el.getBoundingClientRect().height')<=96
            assert page.evaluate('document.documentElement.scrollWidth')==width
            flow.classify(batch)
            page.reload()
            page.locator('#preview [data-edit]').first.wait_for()
            assert page.locator('#questions .review-item').count()==0
            assert '숙박비' in page.locator('#preview').inner_text()
            assert '추론 배정' not in page.locator('#preview').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth')==width
            assert errors==[]
            assert server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0]==0
            browser.close()
    finally:
        server.shutdown();server.server_close();server.card_store.close()
        thread.join(timeout=3);ledger_board.bind_store(None)
