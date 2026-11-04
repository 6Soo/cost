"""Synthetic provider coverage. No customer messages or financial writes."""
import base64
from copy import deepcopy
import json
import hashlib

from app import flight_evidence
from webapp.flight_search_evidence import build_search_index, _jeju_itinerary
from webapp.flight_booking_projection import query_booking_reservations


def mail(mid,body,subject='고객님의 제주항공 여정확인서(e-ticket) 입니다.',sender='reservation@jejuair.net'):
    return {'id':mid,'internalDate':'1790000000000','owner_collected':True,
      'payload':{'mimeType':'text/plain','headers':[{'name':'From','value':sender},{'name':'Subject','value':subject}],
       'body':{'data':base64.urlsafe_b64encode(body.encode()).decode()}}}


def jeju_body(ref='ABC123',return_day='2026.11.26',name='KIM ALPHA'):
    return (f'예약번호\n{ref}\n여정 정보\n가는편\nSTANDARD\n편명 7C1001\n서울(인천)\n(ICN)\n시즈오카\n(FSZ)\n'
      '2026.11.22 (일) 07:05\n2026.11.22 (일) 09:00\n오는편\nSTANDARD\n편명 7C1002\n시즈오카\n(FSZ)\n서울(인천)\n(ICN)\n'
      f'{return_day} (목) 10:00\n{return_day} (목) 12:00\n운임 정보\n성인 1\n{name}\n100,000 원')


def write_mail(tmp_path,messages):
    (tmp_path/'gmail-synthetic.json').write_text(json.dumps({'responses':messages}),encoding='utf-8')


def test_direct_airline_is_searchable_by_destination_airport_date_and_name(tmp_path):
    write_mail(tmp_path,[mail('synthetic',jeju_body())])
    original={'ABC123':{'source_digests':['trip-proof'],'passengers':[], 'legs':[]}}
    before=deepcopy(original)
    index=build_search_index([tmp_path],original)
    assert original==before
    assert set(index)=={'ABC123','jeju:ABC123'}  # No provider/reference collision.
    for query in ('시즈오카','FSZ','24일 시즈오카','KIM ALPHA'):
        result=query_booking_reservations(index,query)
        assert result['total']==1
        row=result['reservations'][0]
        assert row['provider']=='jeju' and row['booking_ref']=='ABC123'
        assert row['passengers']==['KIM ALPHA'] and row['linked_cards']==[]


def test_amended_itinerary_and_cancellation_keep_conflict_flags(tmp_path):
    write_mail(tmp_path,[mail('original',jeju_body()),mail('changed',jeju_body(return_day='2026.11.25')),
      mail('cancel','예약번호 ABC123','예약 취소 요청 접수')])
    row=build_search_index([tmp_path],{})['jeju:ABC123']
    assert row['conflict'] is True
    assert row['cancellation_status']=='CONFLICT'
    assert len(row['source_digests'])>=2


def test_booker_greeting_spoofed_sender_and_missing_itinerary_do_not_create_passengers(tmp_path):
    body=jeju_body().replace('성인 1\nKIM ALPHA','예약자 이름\nLEE BOOKER')
    assert _jeju_itinerary(body)['passengers']==[]
    write_mail(tmp_path,[mail('spoof',jeju_body(),sender='x@jejuair.net.example'),
                         mail('no-evidence','예약번호 ABC123\n시즈오카\n성인 1\nKIM ALPHA')])
    assert build_search_index([tmp_path],{})=={}
    assert _jeju_itinerary(jeju_body())['passengers']==[{'surname':'','given_name':'KIM ALPHA'}]


def test_trip_flattened_route_notice_adds_search_facts_without_changing_financial_index(tmp_path):
    text='예약번호 1234567890123\n서울 - 시즈오카 현\n|\n2026년 11월 22일 07:10\nKIM\n(성)\nALPHA\n(이름)'
    write_mail(tmp_path,[mail('notice',text,'항공편 변경 안내','noreply@trip.com')])
    original={'1234567890123':{'source_digests':['existing-proof'],'passengers':[{'surname':'KIM','given_name':'ALPHA'}],
      'legs':[],'cancellation_status':'CONFLICT','conflict':True}}
    before=deepcopy(original)
    result=query_booking_reservations(build_search_index([tmp_path],original),'시즈오카')
    assert result['total']==1 and result['reservations'][0]['cancelled']
    assert result['reservations'][0]['conflict'] is True
    assert original==before


def test_all_original_passengers_remain_in_one_booking_projection():
    evidence={'source_digests':['synthetic'],'passengers':[{'surname':'KIM','given_name':'ALPHA'},
       {'surname':'LEE','given_name':'BETA'}], 'legs':[{'destination_city':'시즈오카'}]}
    result=query_booking_reservations({'SYNTH':evidence},'시즈오카')
    assert result['total']==1
    assert result['reservations'][0]['passengers']==['KIM ALPHA','LEE BETA']


def test_search_schema_invalidates_old_trip_only_cache(tmp_path,monkeypatch):
    from webapp import flight_booking_index,flight_search_evidence
    monkeypatch.setattr('app.ota_sources.mail_stamps',lambda directories:[])
    sources={'mail_directories':[tmp_path]}
    before=flight_booking_index._key(sources)
    monkeypatch.setattr(flight_search_evidence,'SEARCH_SCHEMA','synthetic-next-search-schema')
    assert flight_booking_index._key(sources)!=before


def test_display_route_enrichment_preserves_unchanged_financial_source_binding(tmp_path):
    mid='existing-notice'
    proof=hashlib.sha256(mid.encode()).hexdigest()
    text='예약번호 1234567890123\n서울 - 시즈오카 현\n|\n2026년 11월 22일\nKIM\n(성)\nALPHA\n(이름)'
    write_mail(tmp_path,[mail(mid,text,'항공편 변경 안내','noreply@trip.com')])
    original={'1234567890123':{'source_digests':[proof],'digest':'existing-financial-evidence',
       'booking_ref':'1234567890123','passengers':[{'surname':'KIM','given_name':'ALPHA'}],'legs':[]}}
    updated=build_search_index([tmp_path],original)
    assert updated['1234567890123']['digest']=='existing-financial-evidence'
    assert updated['1234567890123']['source_digests']==[proof]
    assert updated['1234567890123']['legs']
    linked=[{'transaction_id':'synthetic-verified-manual-link'}]
    result=query_booking_reservations(updated,'시즈오카',cards={'1234567890123':linked})
    assert result['reservations'][0]['linked_cards'] is linked
