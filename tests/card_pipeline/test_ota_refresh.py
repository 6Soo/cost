"""신규 카드 원본과 지연 메일에서 누락되던 대사 경계를 검증한다."""
import base64
import datetime
import json
from app.ota_mail import (authenticated_headers, body_text, extract_mail,
                          match_mail, reservation_cancelled, service_period)
from tests.card_pipeline.test_booking_mail import message, hotel


def save(tmp_path, mails):
    (tmp_path/'gmail-test.json').write_text(json.dumps({'responses':mails}),encoding='utf-8')


def row(**changes):
    return dict(transaction_id='card',source_hash='a'*64,merchant='AGODA',
                merchant_normalized='agoda',card_kind='해외',approval_date='2026-05-01',
                transaction_direction='purchase',amount_krw=None,
                foreign_currency='USD',foreign_amount='123.45',**changes)


def test_null_krw_keeps_exact_foreign_currency_match(tmp_path):
    mail=message('예약번호: 1738864710\n총 금액 USD 123.45\nCheck-in: August 1, 2026\nCheck-out: August 5, 2026',
                 subject='Payment confirmation',domain='agoda.com')
    save(tmp_path,[mail])
    result=match_mail(tmp_path,[row()])
    assert result['exact_matches']==1
    assert result['matches'][0]['period']=={'starts_on':'2026-08-01','ends_on':'2026-08-05'}
    assert row()['amount_krw'] is None


def test_delivery_after_midnight_does_not_discard_signed_receipt():
    mail=message(hotel())
    mail['internal_date']=str(int(mail['internal_date'])+24*60*60*1000)
    fact=extract_mail(mail)
    assert fact['paid_on']=='2026-05-01'
    assert fact['paid_amount_krw']==123000


def test_aligned_provider_subdomain_and_header_d_are_supported():
    mail=message(hotel(),domain='mail.trip.com')
    mail['payload']['headers'][-1]['value']='mx.google.com; dkim=pass header.d=trip.com'
    assert authenticated_headers(mail,('trip.com',))[1]=='trip.com'
    mail['payload']['headers'][-1]['value']='mx.google.com; dkim=pass header.d=trip.com.example'
    assert authenticated_headers(mail,('trip.com',)) is None
    mail['payload']['headers'][0]['value']='sender@trip.com.example'
    mail['payload']['headers'][-1]['value']='mx.google.com; dkim=pass header.d=trip.com'
    assert authenticated_headers(mail,('trip.com',)) is None


def test_standard_gmail_body_data_is_read():
    body='예약번호: 1738864710'
    encoded=base64.urlsafe_b64encode(body.encode()).decode().rstrip('=')
    assert body in body_text({'body':{'data':encoded}})


def test_same_source_twice_does_not_make_booking_ambiguous(tmp_path):
    mail=message('예약번호: 1738864710\n총 금액 USD 123.45\n체크인: 2026-08-01\n체크아웃: 2026-08-05',
                 subject='Payment confirmation',domain='agoda.com')
    save(tmp_path,[mail])
    assert match_mail(tmp_path,[row(),row()])['exact_matches']==1
    other=dict(row(),transaction_id='other',source_hash='b'*64)
    assert match_mail(tmp_path,[row(),other])['exact_matches']==0


def test_equal_hotel_candidates_keep_shared_period_without_booking_selection(tmp_path):
    save(tmp_path,[message(hotel(),identity='one'),message(hotel('2222222222222222'),identity='two')])
    card=dict(row(),merchant='TRIP.COM',merchant_normalized='trip.com',amount_krw=123000)
    result=match_mail(tmp_path,[card])
    candidate=result['type_only_candidates'][0]
    assert candidate['shared_period']=={'starts_on':'2026-05-22','ends_on':'2026-05-23'}
    assert 'booking_ref' not in candidate
    assert result['exact_matches']==0


def test_cancellation_policy_is_not_completed_cancellation():
    assert not reservation_cancelled('예약 취소 정책 및 위약금 안내')
    assert not reservation_cancelled('Cancellation policy')
    assert reservation_cancelled('예약이 무료로 취소되었습니다')
    assert reservation_cancelled('예약 취소 완료')


def test_conflicting_english_and_korean_dates_are_not_selected():
    assert service_period('체크인: 2026-08-01\nCheck-in: August 2, 2026\n체크아웃: 2026-08-05') is None


def test_actual_weekday_date_formats_keep_checkout_date():
    assert service_period('Check in\nWednesday July 8, 2026\nCheck out\nThursday July 9, 2026')=={'starts_on':'2026-07-08','ends_on':'2026-07-09'}
    assert service_period('체크인:\nSun 20 Sep 2026\n체크아웃:\nTue 22 Sep 2026')=={'starts_on':'2026-09-20','ends_on':'2026-09-22'}


def test_upload_classification_uses_local_mail_and_preserves_owner_answer(tmp_path,monkeypatch):
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    monkeypatch.setenv('WEBLEDGER_OTA_MAIL_DIR',str(tmp_path))
    save(tmp_path,[message(hotel())])
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        flow=CardFlow(board)
        data='카드사,카드번호,승인번호,승인일,가맹점,승인금액\n국민,1234,87654321,2026-05-01,TRIP.COM,123000\n'.encode('utf-8')
        batch=flow.pipeline.receive(data,'synthetic.csv')
        flow.classify(batch['batch_id'])
        transaction=board.conn.execute('SELECT transaction_id,revision,item FROM transactions').fetchone()
        assert transaction[2]=='숙박비'
        assert flow.pipeline.list_rules()==[]
        flow.pipeline.save_decision(transaction[0],transaction[1],item='사무용품비',description='직접 확인',display_tab_id='unclassified',trip_id='',request_id='synthetic-owner-answer',tab_validator=flow.tab_valid)
        flow.classify(batch['batch_id'])
        assert board.conn.execute('SELECT item,decided_at IS NOT NULL FROM transactions').fetchone()==('사무용품비',1)
    finally:board.close()


def test_cancelled_booking_blocks_stale_trip_inference(tmp_path,monkeypatch):
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    monkeypatch.setenv('WEBLEDGER_OTA_MAIL_DIR',str(tmp_path))
    save(tmp_path,[message(hotel()),message('예약번호: 1111111111111111',
        subject='예약 취소 완료',identity='cancel',sent='2026-05-03')])
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        flow=CardFlow(board)
        batch=flow.pipeline.receive('카드사,카드번호,승인번호,승인일,가맹점,승인금액\n국민,1234,87654321,2026-05-01,TRIP.COM,123000\n'.encode(),'synthetic.csv')
        original=flow.pipeline.get_batch(batch['batch_id'])['rows'][0]
        flow.pipeline.save_rule({'conditions':{'merchant_normalized':'TRIP.COM'},
            'optional':{'source_hash':original['source_hash'],'inferred_assignment':{
                'trip_id':'old-trip','confidence':'중간','basis':'과거 추론'}},
            'effects':{'item':'숙박비'}})
        flow.trip_valid=lambda identity:identity=='old-trip'
        flow.classify(batch['batch_id'])
        result=flow.pipeline.get_batch(batch['batch_id'])['rows'][0]
        assert result['trip_id']==''
        assert result['classification_source']!='inference'
        assert len(flow.pipeline.list_rules())==1
    finally:board.close()


def test_current_receipt_supersedes_automatic_history_but_not_edited_rules():
    from app.classify import classify_transaction
    card=dict(row(),merchant='TRIP.COM',merchant_normalized='trip.com',amount_krw=123000)
    old={'conditions':{'merchant_normalized':'trip.com'},'effects':{'item':'현지경비'},
         'optional':{},'origin':'history-recovery-20261003','version':1,'rule_id':'old'}
    current={'conditions':{'merchant_normalized':'trip.com'},'effects':{'item':'숙박비'},
             'optional':{'source_hash':card['source_hash']},'origin':'ota-mail-live','rule_id':'current'}
    result=classify_transaction(card,rules=[old,current])
    assert result['item']=='숙박비'
    assert result['classification_source']=='rule'
    edited=dict(old,version=2)
    assert classify_transaction(card,rules=[edited,current])['classification_source']=='rule_conflict'
    owner=dict(old,origin='owner-confirmed')
    assert classify_transaction(card,rules=[owner,current])['classification_source']=='rule_conflict'


def test_pop3_preserves_provider_signature_and_original_sent_day():
    mail=message(hotel())
    mail['payload']['headers'].append({'name':'X-Gmail-Fetch-Info','value':'synthetic@example.test POP3'})
    mail['internal_date']=str(int(mail['internal_date'])+7*86400000)
    assert authenticated_headers(mail,('trip.com',))
    assert extract_mail(mail)['paid_on']=='2026-05-01'


def test_agoda_family_rule_keeps_details_and_rejects_similar_names():
    from app.rules import normalize_rule,rule_matches
    from app.classify import classify_transaction
    from tools.recover_history_rules import owner_answer_drafts
    rule=normalize_rule(owner_answer_drafts([])[0])
    for name in ('AGODA_NICE','AGODA.COM NEW HOTEL','Agoda','아고다'):
        card=dict(row(),merchant=name)
        assert rule_matches(rule,card)[0]
        assert classify_transaction(card,rules=[rule])['item']=='숙박비'
    assert not rule_matches(rule,dict(row(),merchant='AGODAEVIL'))[0]
    old={'conditions':{'merchant_normalized':'agoda'},'optional':{},'effects':{'item':'현지경비'},'origin':'history-recovery-20261003','version':1}
    assert classify_transaction(row(),rules=[rule,old])['item']=='숙박비'
    detail={'conditions':{'merchant_normalized':'agoda'},'optional':{'source_hash':'a'*64},
            'effects':{'item':'숙박비','description':'예약 근거'},'origin':'history-recovery-20261003','version':1}
    assert classify_transaction(row(),rules=[rule,detail])['description']=='예약 근거'


def test_scheduled_agoda_charge_matches_card_without_claiming_receipt(tmp_path):
    from app.ota_mail import scheduled_charge_day
    text='예약번호: 1738864710\n총 금액 USD 123.45\nCheck-in: August 1, 2026\nCheck-out: August 5, 2026\n요금 자동 결제일은 [ May 20, 2026 ]입니다.'
    save(tmp_path,[message(text,subject='Agoda 예약 확정서',domain='agoda.com')])
    card=dict(row(),approval_date='2026-05-20')
    result=match_mail(tmp_path,[card])
    assert result['exact_matches']==1
    assert result['matches'][0]['evidence_kind']=='scheduled_charge'
    assert match_mail(tmp_path,[row()])['exact_matches']==0
    assert scheduled_charge_day(text+'\n요금 자동 결제일은 [ May 21, 2026 ]입니다.') is None
    assert scheduled_charge_day(text.replace('자동 결제일은','체크인일은')) is None


def test_booking_completed_payment_amount_layout_is_read(tmp_path):
    save(tmp_path,[message('예약번호: 1738864710\n결제 완료\n¥87,560',
                          subject='결제가 완료되었습니다',domain='booking.com')])
    card=dict(row(),merchant='BOOKING.COM',foreign_currency='JPY',foreign_amount='87560')
    result=match_mail(tmp_path,[card])
    assert result['exact_matches']==1
    assert result['matches'][0]['period'] is None
    assert result['matches'][0]['evidence_kind']=='payment_receipt'
    assert 'booking_period' not in result['rules'][0]['optional']
    assert result['booking_evidence_gaps']==[{
        'provider':'booking','booking_ref':'1738864710','source_hash':card['source_hash'],
        'reason':'service_period_not_collected'}]


def test_lodging_payment_link_survives_conflicting_periods(tmp_path):
    save(tmp_path,[message('예약번호: 1738864710\n총 금액 USD 123.45',
                          subject='Payment confirmation',domain='agoda.com'),
        message('예약번호: 1738864710\n체크인: 2026-08-01\n체크아웃: 2026-08-03',
                subject='Agoda 예약 확정서',domain='agoda.com',identity='stay-one'),
        message('예약번호: 1738864710\n체크인: 2026-08-02\n체크아웃: 2026-08-03',
                subject='Agoda 예약 확정서',domain='agoda.com',identity='stay-two')])
    result=match_mail(tmp_path,[row()])
    assert result['exact_matches']==1
    assert result['matches'][0]['period'] is None
    assert result['matches'][0]['period_conflict']
    assert result['booking_evidence_gaps']==[]


def test_cancelled_booking_keeps_charge_link_but_never_active_trip(tmp_path):
    save(tmp_path,[message('예약번호: 1738864710\n총 금액 USD 123.45',
                          subject='Payment confirmation',domain='agoda.com'),
        message('예약번호: 1738864710',subject='취소됨 - 합성 숙소 예약',
                domain='agoda.com',identity='cancel',sent='2026-05-03')])
    result=match_mail(tmp_path,[row()])
    assert result['exact_matches']==1
    assert result['matches'][0]['reservation_status']=='cancelled'
    assert result['matches'][0]['period'] is None
    assert result['cancelled_reservation_matches']==1
    assert result['booking_evidence_gaps']==[]
    assert 'booking_period' not in result['rules'][0]['optional']


def test_payment_without_period_still_rejects_unverified_or_duplicate_cards(tmp_path):
    mail=message('예약번호: 1738864710\n결제 완료\n¥87,560',
                 subject='결제가 완료되었습니다',domain='booking.com')
    card=dict(row(),merchant='BOOKING.COM',foreign_currency='JPY',foreign_amount='87560')
    save(tmp_path,[mail])
    assert match_mail(tmp_path,[card,dict(card,transaction_id='other',source_hash='b'*64)])['exact_matches']==0
    mail['payload']['headers'][-1]['value']='dkim=fail header.i=@booking.com'
    save(tmp_path,[mail])
    assert match_mail(tmp_path,[card])['exact_matches']==0


def test_old_reservation_and_new_receipt_remove_stale_trip_inference(tmp_path,monkeypatch):
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    from tests.card_pipeline.fixtures import make_csv,domestic_row
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    monkeypatch.setenv('WEBLEDGER_OTA_MAIL_DIR',str(tmp_path))
    save(tmp_path,[message('예약번호: 1738864710\n결제 완료\nKRW 30,000',
                          subject='결제가 완료되었습니다',domain='booking.com'),
        message('예약번호: 1738864710\n체크인: 2026-08-01\n체크아웃: 2026-08-03',
                subject='숙박 예약이 확정되었습니다',domain='booking.com',identity='stay',sent='2026-03-01')])
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        flow=CardFlow(board)
        trip=board.create_trip(starts_on='2026-08-01',ends_on='2026-08-03',
                              destination='합성 여행',client_request_id='synthetic-trip')['tab_id']
        flow.trip_valid=lambda identity:identity==trip
        batch=flow.pipeline.receive(make_csv([domestic_row(merchant='BOOKING.COM',amount=30000,
            approval='synthetic-payment',date='2026-05-01')]),'synthetic.csv')['batch_id']
        original=flow.pipeline.get_batch(batch)['rows'][0]
        flow.pipeline.save_rule({'conditions':{'merchant_normalized':'BOOKING.COM'},
            'optional':{'source_hash':original['source_hash'],'inferred_assignment':{
                'trip_id':trip,'confidence':'낮음','basis':'결제 뒤 가까운 여행으로 추론'}},
            'effects':{'item':'숙박비'}})
        rules=flow.pipeline.list_rules()
        flow.classify(batch)
        first=flow.state(batch)['rows'][0]
        assert first['classification_source']=='rule'
        assert first['trip_id']==trip
        assert first['review_evidence_labels']==['예약 근거 있음']
        assert not first['decided']
        flow.classify(batch)
        again=flow.state(batch)['rows'][0]
        for field in ('source_hash','transaction_id','amount_krw','approval_date'):
            assert original[field]==again[field]
        assert again['classification_source']=='rule' and again['trip_id']==trip
        assert flow.pipeline.list_rules()==rules
        assert board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0]==0
        flow.pipeline.save_decision(again['transaction_id'],again['revision'],item='사무용품비',
            description='직접 확인',display_tab_id='unclassified',trip_id='',
            request_id='synthetic-answer',tab_validator=flow.tab_valid)
        flow.classify(batch)
        assert board.conn.execute('SELECT item,decided_at IS NOT NULL FROM transactions').fetchone()==('사무용품비',1)
    finally:
        board.close()
