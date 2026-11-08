"""OTA 근거 자료를 여러 곳에서 함께 대조하는 회귀. 모두 합성 자료다."""
import hashlib
import json
import sqlite3
import os

import pytest

from app import ota_sources
from app.ota_mail import (load_messages_from, load_reference_documents, match_mail,
                          reference_diagnosis)
from app.ota_portal import collect_portal_facts, extend_report, portal_matches
from webapp.card_flow import _mail_evidence_from_report, _review_evidence_labels


def portal_database(path, facts=None, *, status='observed', conflict=0, booking_status='completed'):
    """포털 DB 한 벌. 레거시 확정 양식도 같은 형태로 만든다."""
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
            payload.pop('booking_status',None)
            raw=json.dumps(payload,ensure_ascii=False,sort_keys=True)
            conn.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?)',
                (str(index),'agoda',payload['booking_number'],payload['service_start_on'],
                 payload['service_end_on'],changes.get('booking_status',booking_status)))
            conn.execute('INSERT INTO direct_source_records VALUES (?,?,?,?)',
                (str(index),'agoda_portal_detail',raw,hashlib.sha256(raw.encode()).hexdigest()))
            conn.executemany('INSERT INTO booking_source_evidence VALUES (?,?,?,?,?)',
                [(str(index),str(index),role,status,conflict) for role in
                 ('identity','service_period','portal_payment_claim','portal_card_observation','lifecycle')])
    return path


LEGACY_CONFIRMED='고객님의 예약은 확정되었으며 결제가 성공적으로 처리되었습니다'


def legacy_fact(**changes):
    """재현된 레거시 양식. completed 로 바꾸지 않고 그대로 쓴다."""
    fact=dict(provider='agoda',booking_number='synthetic-booking',
        service_start_on='2026-08-02',service_end_on='2026-08-03',
        reservation_status=LEGACY_CONFIRMED,payment_status='결제 완료됨',
        portal_payment_state='paid_today',refund_status='none_displayed',
        card_last4='1234',price_components=[
            dict(kind='paid_today',currency='KRW',decimal_text='30000',minor_units=30000,scale=0)])
    fact.update(changes)
    return fact


def card(**changes):
    return dict(dict(transaction_id='synthetic-card',source_hash='a'*64,merchant='AGODA_NICE-Agoda',
        merchant_normalized='agoda nice-agoda',card_kind='신용',approval_date='2026-07-11',
        transaction_direction='purchase',amount_krw=30000,card_tail='1234',foreign_amount=None,
        foreign_currency=''),**changes)


def sources_file(tmp_path, **payload):
    path=tmp_path/'ota-sources.json'
    path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    return path


class TestExplicitSourceRegistry:
    def test_source_lineage_registry_assigns_stable_registered_id(self,tmp_path):
        portal=tmp_path/'portal.sqlite'
        sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,
            portal_databases=[str(portal)],
            source_lineage_ids={str(portal):'agoda-primary-source'})
        found=ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'ota-mail',
                                          portal_default=tmp_path/'missing.sqlite')
        assert found['source_lineage_ids']=={str(portal.resolve()):'agoda-primary-source'}
        assert ota_sources.source_lineage_id(found['source_lineage_ids'],portal)=='agoda-primary-source'

    def test_no_manifest_keeps_the_single_previous_paths(self,tmp_path):
        found=ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'ota-mail',
                                          portal_default=tmp_path/'portal.sqlite')
        assert found['manifest_present'] is False
        assert [str(p) for p in found['mail_directories']]==[str(tmp_path/'ota-mail')]
        assert [str(p) for p in found['portal_databases']]==[str(tmp_path/'portal.sqlite')]
        assert found['missing']==[] and found['diagnostics']==[]
        assert found['reference_documents']==[]

    def test_manifest_adds_sources_and_removes_duplicates(self,tmp_path):
        second=tmp_path/'more-mail';second.mkdir()
        portal=tmp_path/'more-portal.sqlite';portal.write_bytes(b'synthetic')
        sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,
            mail_directories=[str(second),str(second)],
            portal_databases=[str(portal),str(portal)])
        found=ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'ota-mail',
                                          portal_default=tmp_path/'portal.sqlite')
        assert [str(p) for p in found['mail_directories']]==[str(tmp_path/'ota-mail'),str(second)]
        # The default portal file was never created, so only the registered one remains.
        assert [str(p) for p in found['portal_databases']]==[str(portal)]
        assert found['missing']==[]

    def test_a_missing_default_portal_does_not_fail_when_the_manifest_registers_one(self,tmp_path):
        """The release-folder default has no outputs/; the registered copy is the source."""
        portal=tmp_path/'registered.sqlite';portal.write_bytes(b'synthetic')
        sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,
            portal_databases=[str(portal)])
        found=ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'ota-mail',
                                          portal_default=tmp_path/'release-outputs'/'absent.sqlite')
        assert [str(p) for p in found['portal_databases']]==[str(portal)]
        assert found['missing']==[] and found['diagnostics']==[]

    def test_a_present_default_portal_is_kept_beside_the_registered_one(self,tmp_path):
        default=tmp_path/'default.sqlite';default.write_bytes(b'synthetic')
        portal=tmp_path/'registered.sqlite';portal.write_bytes(b'synthetic')
        sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,
            portal_databases=[str(portal)])
        found=ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'ota-mail',
                                          portal_default=default)
        assert [str(p) for p in found['portal_databases']]==[str(default),str(portal)]

    def test_a_registered_path_that_is_gone_is_reported_not_hidden(self,tmp_path):
        sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,
            mail_directories=[str(tmp_path/'absent-mail')],
            portal_databases=[str(tmp_path/'absent.sqlite')],
            reference_documents=[str(tmp_path/'absent.json')])
        found=ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'ota-mail',
                                          portal_default=tmp_path/'portal.sqlite')
        assert {item['kind'] for item in found['missing']}=={
            'mail_directory','portal_database','reference_document'}
        assert len(found['diagnostics'])==3

    def test_reference_documents_are_optional_and_absolute_only(self,tmp_path):
        reference=tmp_path/'reference.json';reference.write_text('{}',encoding='utf-8')
        sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,
                     reference_documents=[str(reference)])
        found=ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'m',
                                          portal_default=tmp_path/'p.sqlite')
        assert [str(p) for p in found['reference_documents']]==[str(reference)]
        sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,
                     reference_documents=['relative.json'])
        with pytest.raises(ota_sources.OtaSourcesError):
            ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'m',
                                        portal_default=tmp_path/'p.sqlite')

    def test_a_wrong_schema_is_an_error_not_a_default(self,tmp_path):
        sources_file(tmp_path,schema_version='ota-sources-v0',mail_directories=[])
        with pytest.raises(ota_sources.OtaSourcesError):
            ota_sources.resolve_sources(tmp_path,mail_default=tmp_path/'m',
                                        portal_default=tmp_path/'p.sqlite')


def mail_message(message_id, identity, body, sent='2026-07-11'):
    return {'id':message_id,'internal_date':'1783728000000',
            'payload':{'headers':[{'name':'From','value':'예약@example.com'},
                                  {'name':'Date','value':'Fri, 11 Jul 2026 09:00:00 +0900'},
                                  {'name':'Subject','value':identity}],
                       'body':{'content':body}}}


def write_mail(path, messages):
    path.mkdir(parents=True,exist_ok=True)
    (path/'gmail.json').write_text(json.dumps({'responses':messages},ensure_ascii=False),encoding='utf-8')
    return path


class TestMultipleMailSources:
    def test_same_message_in_two_directories_is_one_message(self,tmp_path):
        message=mail_message('m1','합성 예약 확정','예약 번호: SYNT12345678')
        first=write_mail(tmp_path/'one',[message])
        second=write_mail(tmp_path/'two',[dict(message)])
        messages,_=load_messages_from([first,second])
        assert list(messages)==['m1']
        report=match_mail([first,second],[card()])
        assert report['messages_read']==1
        assert len(report['mail_sources'])==2

    def test_one_directory_alone_does_not_end_the_read(self,tmp_path):
        empty=tmp_path/'empty';empty.mkdir()
        filled=write_mail(tmp_path/'filled',[mail_message('m1','합성 예약 확정','예약 번호: SYNT12345678')])
        messages,inventory=load_messages_from([empty,filled])
        assert list(messages)==['m1']
        assert [entry['messages'] for entry in inventory]==[0,1]

    def test_same_id_with_a_different_body_still_stops(self,tmp_path):
        first=write_mail(tmp_path/'one',[mail_message('m1','제목','본문 하나')])
        second=write_mail(tmp_path/'two',[mail_message('m1','제목','본문 둘')])
        with pytest.raises(ValueError,match='OTA_MESSAGE_CONTENT_CONFLICT'):
            load_messages_from([first,second])

    def test_every_collection_scope_is_kept(self,tmp_path):
        first=write_mail(tmp_path/'one',[mail_message('m1','합성 예약 확정','예약 번호: SYNT12345678')])
        (first/'collection.json').write_text(json.dumps({'fetched':1,'query_exhausted':True}),encoding='utf-8')
        second=write_mail(tmp_path/'two',[mail_message('m2','합성 예약 확정','예약 번호: SYNT12345679')])
        report=match_mail([first,second],[card()])
        assert sorted(report['mail_collections'])==sorted([str(first),str(second)])
        assert report['mail_collections'][str(first)]['query_exhausted'] is True

    def test_a_missing_registered_directory_is_reported(self,tmp_path):
        filled=write_mail(tmp_path/'filled',[mail_message('m1','합성 예약 확정','예약 번호: SYNT12345678')])
        report=match_mail([filled,tmp_path/'absent'],[card()])
        assert [entry['error'] for entry in report['mail_source_errors']]==['directory_not_found']


class TestMultiplePortalDatabases:
    def test_identical_facts_in_two_databases_stay_one_booking(self,tmp_path):
        first=portal_database(tmp_path/'one.sqlite')
        second=portal_database(tmp_path/'two.sqlite')
        matches=portal_matches([first,second],[card()])
        assert len(matches)==1
        assert matches[0]['booking_ref']=='synthetic-booking'

    def test_a_conflict_between_databases_is_not_resolved(self,tmp_path):
        first=portal_database(tmp_path/'one.sqlite')
        second=portal_database(tmp_path/'two.sqlite',[dict(card_last4='9876')])
        assert portal_matches([first,second],[card()])==[]

    def test_a_booking_in_another_database_makes_it_ambiguous(self,tmp_path):
        first=portal_database(tmp_path/'one.sqlite')
        second=portal_database(tmp_path/'two.sqlite',[{'booking_number':'other-booking'}])
        # 한 DB에서만 매칭된 뒤 합치는 방식이 아니라 전체 예약에서 모호성을 본다.
        assert portal_matches([first,second],[card()])==[]

    def test_numeric_source_ids_from_two_databases_do_not_merge_evidence(self,tmp_path):
        # 두 DB가 같은 숫자 id 를 쓴다. 역할을 합쳐 five-role 처럼 꾸미면 안 된다.
        first=portal_database(tmp_path/'one.sqlite')
        with sqlite3.connect(first) as conn:
            conn.execute("DELETE FROM booking_source_evidence WHERE evidence_role!='identity'")
        second=portal_database(tmp_path/'two.sqlite')
        with sqlite3.connect(second) as conn:
            conn.execute("DELETE FROM booking_source_evidence WHERE evidence_role='identity'")
        assert portal_matches([first,second],[card()])==[]

    def test_the_original_database_is_never_written(self,tmp_path):
        path=portal_database(tmp_path/'one.sqlite')
        before=path.read_bytes()
        portal_matches([path],[card()])
        assert path.read_bytes()==before


class TestLegacyConfirmedPaid:
    def test_the_legacy_shape_is_linkable_with_all_five_roles(self,tmp_path):
        path=tmp_path/'legacy.sqlite'
        with sqlite3.connect(path) as conn:
            conn.executescript('''
                CREATE TABLE bookings(id TEXT,provider TEXT,booking_number TEXT,service_start_on TEXT,service_end_on TEXT,status TEXT);
                CREATE TABLE direct_source_records(id TEXT,source_kind TEXT,payload_json TEXT,source_sha256 TEXT);
                CREATE TABLE booking_source_evidence(booking_id TEXT,direct_source_record_id TEXT,evidence_role TEXT,evidence_status TEXT,conflict_count INTEGER);
            ''')
            raw=json.dumps(legacy_fact(),ensure_ascii=False,sort_keys=True)
            conn.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?)',
                ('0','agoda','synthetic-booking','2026-08-02','2026-08-03','confirmed'))
            conn.execute('INSERT INTO direct_source_records VALUES (?,?,?,?)',
                ('0','agoda_portal_detail',raw,hashlib.sha256(raw.encode()).hexdigest()))
            conn.executemany('INSERT INTO booking_source_evidence VALUES (?,?,?,?,?)',
                [('0','0',role,'observed',0) for role in
                 ('identity','service_period','portal_payment_claim','portal_card_observation','lifecycle')])
        matches=portal_matches(path,[card()])
        assert len(matches)==1
        assert matches[0]['payment_format']=='legacy_confirmed_paid'
        assert matches[0]['period']=={'starts_on':'2026-08-02','ends_on':'2026-08-03'}
        assert '예약 확정' in matches[0]['basis']

    @pytest.mark.parametrize('changes,booking_status',[
        ({'payment_status':'해당 요금은 체크인 시 결제될 예정입니다'},'confirmed'),
        ({'portal_payment_state':'scheduled'},'confirmed'),
        ({'reservation_status':LEGACY_CONFIRMED},'completed'),
        ({'reservation_status':'cancelled'},'confirmed'),
        ({'refund_status':'refunded'},'confirmed'),
        ({'collection_model':'hotel_collect'},'confirmed'),
        ({'card_last4':'9876'},'confirmed'),
        ({'price_components':[dict(kind='paid_today',currency='KRW',decimal_text='30000',
                                   minor_units=31000,scale=0)]},'confirmed'),
    ])
    def test_scheduled_or_weaker_legacy_facts_are_not_payment_evidence(self,tmp_path,changes,booking_status):
        path=portal_database(tmp_path/'legacy.sqlite',[changes],booking_status=booking_status)
        assert portal_matches(path,[card()])==[]

    def test_canonical_still_works_beside_the_legacy_shape(self,tmp_path):
        assert len(portal_matches(portal_database(tmp_path/'canonical.sqlite'),[card()]))==1

    def test_payment_link_is_not_the_same_as_service_completion(self,tmp_path):
        path=tmp_path/'legacy.sqlite'
        with sqlite3.connect(path) as conn:
            conn.executescript('''
                CREATE TABLE bookings(id TEXT,provider TEXT,booking_number TEXT,service_start_on TEXT,service_end_on TEXT,status TEXT);
                CREATE TABLE direct_source_records(id TEXT,source_kind TEXT,payload_json TEXT,source_sha256 TEXT);
                CREATE TABLE booking_source_evidence(booking_id TEXT,direct_source_record_id TEXT,evidence_role TEXT,evidence_status TEXT,conflict_count INTEGER);
            ''')
            raw=json.dumps(legacy_fact(),ensure_ascii=False,sort_keys=True)
            conn.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?)',
                ('0','agoda','synthetic-booking','2026-08-02','2026-08-03','confirmed'))
            conn.execute('INSERT INTO direct_source_records VALUES (?,?,?,?)',
                ('0','agoda_portal_detail',raw,hashlib.sha256(raw.encode()).hexdigest()))
            conn.executemany('INSERT INTO booking_source_evidence VALUES (?,?,?,?,?)',
                [('0','0',role,'observed',0) for role in
                 ('identity','service_period','portal_payment_claim','portal_card_observation','lifecycle')])
        report=extend_report(match_mail(tmp_path/'no-mail',[card()]),path,[card()])
        fact=report['matches'][0]
        # 예약 상태를 완료로 고치지 않는다. 이용 완료를 주장하지도 않는다.
        assert fact['reservation_status']=='observed'
        assert fact['payment_format']=='legacy_confirmed_paid'


class TestReferenceDocuments:
    def test_booking_keyed_dictionary_is_read(self,tmp_path):
        path=tmp_path/'reference.json'
        path.write_text(json.dumps({'SYNT12345678':{'message_id':'m1','item':'숙박비','amount':30000}},
                                   ensure_ascii=False),encoding='utf-8')
        found=load_reference_documents([path])
        assert found['by_booking_ref']['SYNT12345678']['documents']==[str(path)]

    def test_records_list_and_nested_rows_are_read(self,tmp_path):
        path=tmp_path/'reference.json'
        path.write_text(json.dumps({'records':[
            {'booking_ref':'SYNT12345678','item':'숙박비'},
            {'rows':[{'bookingRefs':['SYNT22222222'],'message_id':'m2'}]}]},ensure_ascii=False),encoding='utf-8')
        found=load_reference_documents([path])
        assert sorted(found['by_booking_ref'])==['SYNT12345678','SYNT22222222']

    def test_missing_and_unreadable_files_are_reported(self,tmp_path):
        broken=tmp_path/'broken.json';broken.write_text('{',encoding='utf-8')
        found=load_reference_documents([tmp_path/'absent.json',broken])
        assert len(found['errors'])==2

    def test_a_reference_never_becomes_a_payment_match(self,tmp_path):
        reference=tmp_path/'reference.json'
        reference.write_text(json.dumps({'records':[{'booking_ref':'synthetic-booking',
            'transaction_id':'synthetic-card','item':'숙박비'}]},ensure_ascii=False),encoding='utf-8')
        report=match_mail(tmp_path/'no-mail',[card()])
        loaded=load_reference_documents([reference])
        report['reference_sources']=loaded
        assert report['exact_matches']==0
        assert report['unmatched_transactions']
        diagnosis=reference_diagnosis(loaded,row=card())
        assert diagnosis['reason']=='reference_only'
        assert diagnosis['unverified_reference'] is True

    def test_only_a_same_content_reference_is_reference_only(self,tmp_path):
        path=tmp_path/'reference.json'
        path.write_text(json.dumps({'records':[
            {'booking_ref':'synthetic-booking','item':'숙박비'},
            {'booking_ref':'synthetic-booking','item':'항공료'}]},ensure_ascii=False),encoding='utf-8')
        loaded=load_reference_documents([path])
        assert loaded['by_booking_ref']['synthetic-booking']['conflicting'] is True
        diagnosis=reference_diagnosis(loaded,row=card(),
                                      booking_ref='synthetic-booking')
        assert diagnosis['reason']=='reference_content_conflict'
        assert diagnosis['conflicting'] is True

    def test_a_uid_or_amount_alone_does_not_identify_a_transaction(self,tmp_path):
        path=tmp_path/'reference.json'
        path.write_text(json.dumps({'records':[{'booking_ref':'x','uid':'u1','event_id':'e1',
            'amount':30000,'approval_date':'2026-07-11'}]},ensure_ascii=False),encoding='utf-8')
        loaded=load_reference_documents([path])
        assert loaded['by_transaction_id']=={}
        assert loaded['by_source_hash']=={}
        assert reference_diagnosis(loaded,row=card()) is None

    def test_diagnosis_counts_are_summaries_only(self,tmp_path):
        path=tmp_path/'reference.json'
        path.write_text(json.dumps({'records':[{'booking_ref':'synthetic-booking',
            'transaction_id':'synthetic-card','note':'원문 내용은 화면에 내보내지 않는다'}]},
            ensure_ascii=False),encoding='utf-8')
        diagnosis=reference_diagnosis(load_reference_documents([path]),row=card())
        assert diagnosis['documents']==1
        assert '원문 내용은' not in json.dumps(diagnosis,ensure_ascii=False)


class TestUnlinkedDiagnosis:
    def test_a_missing_source_is_not_reported_as_missing_evidence(self,tmp_path):
        report=match_mail(tmp_path/'no-mail',[card()])
        assert report['unmatched_transactions']
        report['ota_source_inventory']={'diagnostics':['등록된 portal_database 이(가) 없습니다: /absent.sqlite']}
        evidence=_mail_evidence_from_report(report,{card()['source_hash']})
        assert evidence[card()['source_hash']]['mail_link_absent'] is True
        assert evidence[card()['source_hash']]['source_diagnostic']=='registered_source_missing'
        labels=_review_evidence_labels(card(),evidence[card()['source_hash']])
        assert labels[0]=='등록된 근거 자료 없음 · 확인 필요'

    def test_two_real_transactions_of_the_same_amount_stay_separate(self,tmp_path):
        rows=[card(),card(transaction_id='other',source_hash='b'*64)]
        report=match_mail(tmp_path/'no-mail',rows)
        hashes={row['source_hash'] for row in rows}
        reasons={fact['source_hash']:fact['reason']
                 for fact in extend_report(report,[],rows)['portal_diagnoses']}
        assert set(reasons)==hashes
        assert len(report['unmatched_transactions'])==2

    def test_a_confirmed_paid_match_stays_booking_evidence(self,tmp_path):
        source_hash='a'*64
        report=match_mail(tmp_path/'no-mail',[card()])
        report['matches']=[dict(source_hash=source_hash,booking_ref='synthetic-booking',
            item='숙박비',source_sha256='c'*64,reservation_status='observed',
            payment_format='legacy_confirmed_paid')]
        evidence=_mail_evidence_from_report(report,{source_hash})
        assert evidence[source_hash]['booking_match'] is True
        assert _review_evidence_labels(card(),evidence[source_hash])[0]=='예약 근거 있음'


@pytest.mark.parametrize('reverse',[False,True])
def test_paid_and_future_observations_conflict_in_both_orders(tmp_path,reverse):
    paid=portal_database(tmp_path/'paid.sqlite')
    future=portal_database(tmp_path/'future.sqlite',[{'payment_status':'will be charged on a future date'}])
    paths=[paid,future]
    assert portal_matches(paths[::-1] if reverse else paths,[card()])==[]


@pytest.mark.parametrize('changes,reason',[
    ({'payment_status':'will be charged on a future date'},'future_payment'),
    ({'payment_status':'unknown'},'unverified_payment'),
    ({'service_start_on':None},'missing_period'),
])
def test_portal_diagnosis_reads_the_rejected_fact(tmp_path,changes,reason):
    portal=portal_database(tmp_path/'portal.sqlite',[changes])
    report=extend_report(match_mail([], [card()]),portal,[card()])
    assert report['portal_diagnoses'][0]['reason']==reason
    assert report['unmatched_transactions'][0]['reason']==reason
    assert report['unmatched_reason_counts']=={reason:1}
    evidence=_mail_evidence_from_report(report,{card()['source_hash']})
    assert evidence[card()['source_hash']]['link_diagnosis']==reason
    assert _review_evidence_labels(card(),evidence[card()['source_hash']])[0] != '예약 근거 확인 필요'


def test_regular_shop_is_not_given_an_ota_diagnosis():
    row=card(merchant='synthetic shop',merchant_normalized='synthetic shop')
    report=extend_report(match_mail([], [row]),[],[row])
    assert report['portal_diagnoses']==[]
    assert _review_evidence_labels(row)==[]


def test_missing_source_warning_is_visible_even_on_a_matched_booking():
    labels=_review_evidence_labels(card(),{'booking_match':True,'source_diagnostic':'source_read_failed'})
    assert '근거 자료 읽기 실패 · 확인 필요' in labels


def test_reference_links_by_verified_booking_and_ignores_structural_keys(tmp_path):
    path=tmp_path/'ref.json'
    path.write_text(json.dumps({'rows':[{'booking_number':'synthetic-booking','booking_id':1}]}),encoding='utf-8')
    references=load_reference_documents([path])
    assert set(references['by_booking_ref'])=={'synthetic-booking'}
    report={'matches':[dict(source_hash=card()['source_hash'],booking_ref='synthetic-booking')],
            'reference_sources':references}
    evidence=_mail_evidence_from_report(report,{card()['source_hash']})
    assert evidence[card()['source_hash']]['reference_only']=='reference_only'


def test_different_mail_metadata_is_not_a_reference_conflict(tmp_path):
    path=tmp_path/'ref.json'
    path.write_text(json.dumps({'records':[
        {'booking_ref':'synthetic-booking','message_id':'m1','item':'숙박비'},
        {'booking_ref':'synthetic-booking','message_id':'m2','status':'confirmed'}]},ensure_ascii=False),encoding='utf-8')
    assert load_reference_documents([path])['by_booking_ref']['synthetic-booking']['conflicting'] is False


@pytest.fixture
def source_flow(tmp_path,monkeypatch):
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    monkeypatch.delenv('WEBLEDGER_OTA_SOURCES',raising=False)
    monkeypatch.setenv('WEBLEDGER_OTA_MAIL_DIR',str(tmp_path/'mail'))
    monkeypatch.setenv('WEBLEDGER_AGODA_PORTAL_DB',str(tmp_path/'optional.sqlite'))
    (tmp_path/'mail').mkdir()
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        yield CardFlow(board)
    finally:
        board.close()


def test_explicit_missing_manifest_is_reported_on_review(source_flow,tmp_path,monkeypatch):
    monkeypatch.setenv('WEBLEDGER_OTA_SOURCES',str(tmp_path/'absent.json'))
    assert source_flow.review_mail_evidence([card()])[card()['source_hash']]['source_diagnostic']=='source_read_failed'


def test_optional_missing_default_does_not_make_registry_unhealthy(source_flow,tmp_path):
    sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,reference_documents=[])
    assert source_flow._ota_report()['ota_source_errors']==[]


def test_reference_content_change_invalidates_cache_even_with_same_size_and_time(source_flow,tmp_path):
    path=tmp_path/'ref.json';path.write_text('{"rows":[{"booking_ref":"one"}]}',encoding='utf-8')
    sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,reference_documents=[str(path)])
    first=source_flow._ota_report();stamp=path.stat()
    path.write_text('{"rows":[{"booking_ref":"two"}]}',encoding='utf-8')
    os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    second=source_flow._ota_report()
    assert 'one' in first['reference_sources']['by_booking_ref']
    assert 'two' in second['reference_sources']['by_booking_ref']
    assert first is not second


def test_registered_source_deletion_invalidates_cached_report(source_flow,tmp_path):
    path=tmp_path/'ref.json';path.write_text('{}',encoding='utf-8')
    sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,reference_documents=[str(path)])
    assert source_flow._ota_report()['ota_source_errors']==[]
    path.unlink()
    report=source_flow._ota_report()
    assert report['ota_source_errors']
    assert report['ota_source_inventory']['missing']


def test_registered_missing_source_cannot_supply_ledger_authority(tmp_path):
    from app.ota_mail import ledger_metadata
    row=dict(card(),item='숙박비')
    report=extend_report(match_mail([], [row]),portal_database(tmp_path/'portal.sqlite'),[row])
    report['ota_source_errors']=[{'error':'file_not_found'}]
    assert ledger_metadata(report,row)['booking_ref']==''


def test_missing_source_blocks_evidence_authority_but_completes_expense_destination(source_flow,tmp_path):
    from app import StoreError
    raw=('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
         'Date,Post Date,Authorization Code,Cancel,Status\n'
         '국민,1234,domestic,purchase,AGODA,30000,,,30000,2026-07-11,2026-07-12,A1,,매입\n').encode('utf-8')
    batch=source_flow.pipeline.receive(raw,'synthetic.csv')['batch_id']
    sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,portal_databases=[str(tmp_path/'missing.sqlite')])
    before=source_flow.board.conn.execute('SELECT * FROM transactions').fetchall()
    with pytest.raises(StoreError) as error:
        source_flow._classify_evidence(batch)
    assert error.value.code=='OTA_EVIDENCE_UNAVAILABLE'
    assert before==source_flow.board.conn.execute('SELECT * FROM transactions').fetchall()
    # DEST-03 completes ordinary expense classification without pretending the
    # unavailable reservation evidence became a verified booking/payment link.
    financial = ('transaction_id,source_hash,amount_krw,raw_row_json')
    original = source_flow.board.conn.execute('SELECT '+financial+' FROM transactions').fetchall()
    result = source_flow.classify(batch)
    assert result['booking_evidence_unavailable'] is True
    row = source_flow.pipeline.get_batch(batch)['rows'][0]
    assert row['classification_state'] == 'classified'
    assert row['display_tab_id'] == 'quarter:2026:3'
    assert source_flow.board.conn.execute('SELECT '+financial+' FROM transactions').fetchall() == original
    assert source_flow._ota_report()['ota_source_inventory']['missing']
    assert source_flow.preview_metadata()(dict(card(),item='숙박비'))['booking_ref'] == ''


def test_preview_without_readable_manifest_keeps_authority_empty_and_review_reports_error(source_flow,tmp_path,monkeypatch):
    monkeypatch.setenv('WEBLEDGER_OTA_SOURCES',str(tmp_path/'absent.json'))
    assert source_flow.preview_metadata()(dict(card(),item='숙박비'))['booking_ref']==''
    assert source_flow.review_mail_evidence([card()])[card()['source_hash']]['source_diagnostic']=='source_read_failed'


def test_real_separate_ids_sharing_one_source_hash_are_still_ambiguous(tmp_path):
    rows=[card(),card(transaction_id='other-real-transaction')]
    report=extend_report(match_mail([],rows),portal_database(tmp_path/'portal.sqlite'),rows)
    assert report['matches']==[]
    assert report['portal_diagnoses'][0]['reason']=='ambiguous_transaction'


def test_manifest_content_change_invalidates_cache_with_same_size_and_timestamp(source_flow,tmp_path):
    one=tmp_path/'one.json';one.write_text('{}',encoding='utf-8')
    two=tmp_path/'two.json';two.write_text('{}',encoding='utf-8')
    manifest=sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,reference_documents=[str(one)])
    first=source_flow._ota_report();stamp=manifest.stat()
    manifest.write_text(manifest.read_text().replace('one.json','two.json'),encoding='utf-8')
    os.utime(manifest,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    second=source_flow._ota_report()
    assert first is not second
    assert second['ota_source_inventory']['reference_documents']==[str(two)]


@pytest.mark.parametrize('value',[None,False,'',{}])
def test_manifest_lists_reject_wrong_types(tmp_path,value):
    sources_file(tmp_path,schema_version=ota_sources.SCHEMA_VERSION,reference_documents=value)
    with pytest.raises(ota_sources.OtaSourcesError):
        ota_sources.resolve_sources(tmp_path)


def test_reference_conflict_across_documents_is_diagnostic_only(tmp_path):
    paths=[]
    for index,amount in enumerate([30000,35000]):
        path=tmp_path/f'ref{index}.json'
        path.write_text(json.dumps({'records':[{'booking_ref':'synthetic-booking','amount':amount}]}),encoding='utf-8')
        paths.append(path)
    loaded=load_reference_documents(paths)
    assert loaded['by_booking_ref']['synthetic-booking']['conflicting']
    assert reference_diagnosis(loaded,booking_ref='synthetic-booking')['unverified_reference']


def test_external_numeric_booking_id_is_read_but_short_internal_id_is_not(tmp_path):
    path=tmp_path/'ref.json'
    path.write_text(json.dumps({'records':[{'booking_id':'1234567890'},{'booking_id':'1'},
                                         {'booking_id':1}]}),encoding='utf-8')
    assert set(load_reference_documents([path])['by_booking_ref'])=={'1234567890'}
