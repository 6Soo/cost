import hashlib
import json

import pytest

from app.participant_roster import ParticipantStore, RosterError
from app.participant_sync import prepare_document_batches, scan_inbox


def source(root):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
    pdf=root/'sources'/'certificate.pdf'
    pdf.parent.mkdir(parents=True)
    writer=PdfWriter()
    page=writer.add_blank_page(width=400,height=200)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                           NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    contents=DecodedStreamObject()
    contents.set_data(b'BT /F1 12 Tf 20 100 Td (OVERSEAS TRAVEL INSURANCE) Tj ET')
    page[NameObject('/Contents')]=contents
    writer.add_blank_page(width=400,height=200)
    writer.write(pdf)
    data={'schema_version':1,'kind':'synthetic','created_at':'2026-01-01',
          'query_basis':'synthetic','notes':[], 'contracts':[{
              'contract_id':'synthetic-contract','travel_start':'2026-03-02','travel_end':'2026-03-04',
              'insured_count':1,'insurance_status':'completed_or_expired','trip_mapping_status':'unresolved',
              'cost_trip_id':None,'already_registered':False,'source_pdf':'sources/certificate.pdf',
              'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
              'items':[{'source_row':'1','masked_name':'김*람','status':'unresolved'}]}]}
    path=root/'manifest.json'
    path.write_text(json.dumps(data),encoding='utf-8')
    return path,data,pdf


TRIPS=[{'tab_id':'trip-synthetic','destination':'오제','starts_on':'2026-03-01','ends_on':'2026-03-05'}]
MAPPING={'synthetic-trip':'trip-synthetic'}


def test_verified_document_uses_same_registration_and_replay_preserves_identity(tmp_path):
    path,data,pdf=source(tmp_path/'review')
    inbox=tmp_path/'inbox'
    original=pdf.read_bytes()
    report=prepare_document_batches(path,inbox,mapping=MAPPING,trips=TRIPS)
    store=ParticipantStore.open(tmp_path/'participant.sqlite')
    try:
        first=scan_inbox(inbox,store,mapping=MAPPING,expected_web_db=tmp_path/'participant.sqlite')
        assert first[0]['status']=='registered', first
        person=store.participants('trip-synthetic')[0]
        assert person['display_name']=='김*람'
        assert person['authority']=='verified_insurance_document'
        before=list(store.conn.iterdump())
        prepare_document_batches(path,inbox,mapping=MAPPING,trips=TRIPS)
        second=scan_inbox(inbox,store,mapping=MAPPING)
        assert first[0]['new_participants']==1 and second[0]['reused'] is True
        assert list(store.conn.iterdump())==before
        assert pdf.read_bytes()==original
        assert report[0]['trip_id']=='trip-synthetic'
    finally:
        store.close()


def test_ambiguous_or_absent_google_trip_does_not_register(tmp_path):
    path,_,_=source(tmp_path/'review')
    for mapping,trips in [({},TRIPS),(dict(MAPPING,other='other'),TRIPS+[dict(TRIPS[0],tab_id='other')])]:
        result=prepare_document_batches(path,tmp_path/'inbox',mapping=mapping,trips=trips)
        assert result[0]['status']=='held'
        assert result[0]['code']=='TRIP_MAPPING_REQUIRED'
        assert not (tmp_path/'inbox').exists()


def test_original_hash_and_registration_evidence_are_required(tmp_path):
    path,data,pdf=source(tmp_path/'review')
    original=pdf.read_bytes()
    pdf.write_bytes(b'changed')
    assert prepare_document_batches(path,tmp_path/'inbox',mapping=MAPPING,trips=TRIPS)[0]['code']=='SOURCE_HASH_MISMATCH'
    pdf.write_bytes(original)
    data['contracts'][0].update(already_registered=True,cost_trip_id='trip-synthetic')
    path.write_text(json.dumps(data),encoding='utf-8')
    assert prepare_document_batches(path,tmp_path/'inbox',mapping=MAPPING,trips=TRIPS)[0]['status']=='held'
    result=prepare_document_batches(path,tmp_path/'inbox',mapping=MAPPING,trips=TRIPS,
                                    registered_people={'trip-synthetic':[{'participant_id':'p','display_name':'김가람'}]})
    assert result[0]['status']=='existing_registration'


def test_scanner_mismatched_db_refuses_before_writes(tmp_path):
    store=ParticipantStore.open(tmp_path/'participant.sqlite')
    try:
        before=list(store.conn.iterdump())
        with pytest.raises(RosterError,match='PARTICIPANT_DB_MISMATCH'):
            scan_inbox(tmp_path/'absent',store,mapping={},expected_web_db=tmp_path/'other.sqlite')
        assert list(store.conn.iterdump())==before
    finally:
        store.close()


def test_bad_review_manifest_does_not_block_existing_canonical_batches(tmp_path):
    import sqlite3
    from app.participant_sync import sync_once
    path,_,_=source(tmp_path/'review')
    inbox=tmp_path/'inbox'
    prepare_document_batches(path,inbox,mapping=MAPPING,trips=TRIPS)
    path.write_text('invalid',encoding='utf-8')
    mapping=tmp_path/'mapping.json'
    mapping.write_text(json.dumps(MAPPING),encoding='utf-8')
    board=tmp_path/'board.sqlite'
    c=sqlite3.connect(board)
    c.execute('CREATE TABLE trip_tabs(tab_id TEXT, destination TEXT, starts_on TEXT, ends_on TEXT, deleted INTEGER)')
    c.execute("INSERT INTO trip_tabs VALUES ('trip-synthetic','오제','2026-03-01','2026-03-05',0)")
    c.commit();c.close()
    store=ParticipantStore.open(tmp_path/'participant.sqlite')
    try:
        result=sync_once({'db':str(tmp_path/'participant.sqlite'),'inbox':str(inbox),
                          'mapping':str(mapping),'trip_db':str(board),'review_manifest':str(path)},store)
        assert result['status']=='partial'
        assert result['sources'][0]['code']=='DOCUMENT_SOURCE_UNAVAILABLE'
        assert result['batches'][0]['status']=='registered'
        assert result['participant_count']==1
    finally:
        store.close()


def test_incomplete_generated_batch_preserves_user_edits(tmp_path):
    path,_,_=source(tmp_path/'review')
    inbox=tmp_path/'inbox'
    report=prepare_document_batches(path,inbox,mapping=MAPPING,trips=TRIPS)
    batch=inbox/report[0]['batch_id']
    (batch/'manifest.json').unlink()  # Interrupted publication, synthetic fixture only.
    target=batch/'participants.json'
    target.write_text('{"user_edit":true}',encoding='utf-8')
    result=prepare_document_batches(path,inbox,mapping=MAPPING,trips=TRIPS)
    assert result[0]['code']=='DERIVED_BATCH_CONFLICT'
    assert target.read_text(encoding='utf-8')=='{"user_edit":true}'


def test_overseas_certificate_never_assigns_to_domestic_date_candidate(tmp_path):
    from app.participant_sync import document_info
    path,_,pdf=source(tmp_path/'review')
    assert document_info(pdf)=={'region':'overseas','pages':[1,2]}
    result=prepare_document_batches(path,tmp_path/'inbox',mapping=MAPPING,
                                     trips=[dict(TRIPS[0],destination='양평')])
    assert result[0]['status']=='held'
    assert result[0]['code']=='TRIP_REGION_CONFLICT'
    assert not (tmp_path/'inbox').exists()


def test_matching_hash_does_not_make_an_unreadable_pdf_valid(tmp_path):
    path,data,pdf=source(tmp_path/'review')
    pdf.write_bytes(b'invalid PDF')
    data['contracts'][0]['sha256']=hashlib.sha256(pdf.read_bytes()).hexdigest()
    path.write_text(json.dumps(data),encoding='utf-8')
    result=prepare_document_batches(path,tmp_path/'inbox',mapping=MAPPING,trips=TRIPS)
    assert result[0]['status']=='held'
    assert result[0]['code']=='DOCUMENT_PRODUCT_UNVERIFIED'
