from pathlib import Path
from unittest.mock import patch
import pytest
from webapp.ledger_store import LedgerStore
from webapp import ledger_board as board
from app import google_authority as ga

@pytest.fixture
def store(tmp_path):
    result=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    yield result
    result.close()

def create(store, owner, request):
    return store.create_trip(starts_on='2026-10-22',ends_on='2026-10-23',destination='합성',
        display_key=('andre::2026::1022_합성' if owner=='andre' else '1022_합성'),
        client_request_id=request,actor='google-sync')

def test_same_schedule_has_separate_owner_ids_and_idempotent_replay(store):
    a=create(store,'aslan','a');b=create(store,'andre','b')
    assert a['tab_id']!=b['tab_id']
    assert create(store,'andre','b')==b
    assert create(store,'andre','c')['tab_id']==b['tab_id']
    assert store.find_trip_by_schedule('2026-10-22','합성')['tab_id']==a['tab_id']
    assert store.find_trip_by_schedule('2026-10-22','합성',owner_id='andre')['tab_id']==b['tab_id']
    assert len(store.list_trips())==2

def test_owner_survives_manual_rename_without_overwriting_user_metadata(store):
    store.save_owner_profile(expected_revision=0,client_request_id='profile',assignee_name='아슬란 기본담당')
    b=create(store,'andre','b')
    current=store.get_trip(b['tab_id'])
    assert current['prepared_by_name']=='김동언'
    assert current['assignee_source']=='google_workbook'
    from webapp.sheets_export import _assignee_confirmed
    assert _assignee_confirmed(store.conn,b['tab_id'],current['assignee_source'],current['prepared_by_name'])
    store.save_trip_meta(tab_id=b['tab_id'],expected_revision=current['revision'],
        client_request_id='rename',display_key='사용자가 정한 이름',prepared_by_name='수동 담당자')
    actual=store.get_trip(b['tab_id'])
    assert actual['owner_id']=='andre'
    assert actual['source_trip_key']=='andre::2026::1022_합성'
    assert actual['display_title']=='사용자가 정한 이름'
    assert actual['prepared_by_name']=='수동 담당자'
    assert create(store,'andre','c')['tab_id']==b['tab_id']

def test_trips_ui_exposes_owner_filter_without_source_writes(store):
    create(store,'aslan','a');create(store,'andre','b')
    before=list(store.conn.iterdump())
    with patch.object(board,'_STORE',store),patch.object(board,'current_role',return_value='owner'):
        html=board.trips_page(role='owner')
    assert 'trip-management-owner' in html
    assert "data-owner='andre'" in html and "data-owner='aslan'" in html
    assert '김동언(안드레)' in html
    assert list(store.conn.iterdump())==before

def test_andre_income_references_agree_across_rows_participants_and_insurance(tmp_path,monkeypatch):
    import datetime as dt
    from webapp import google_ledger_page as google, participant_income_page as participants
    from webapp import insurance_income_match_service as insurance, participant_trip_panel as panel
    key='andre::2026::1022_Synthetic';sheet='1022_Synthetic';source='andre_main'
    stamp=dt.datetime.now(ga.KST).isoformat()
    block={'total':100,'sheet_total':100,'row_sum':100,'verified':True}
    trip={'key':key,'sheet':sheet,'owner_id':'andre','canonical_source':source,
          'closure':'unknown','closure_current':False,'verified':True,'review':[],
          'income_total':100,'expense_total':0,'net':100,
          'copies':{source:{'sheet':sheet,'layout':'rev','income':block,'expense':block,'flags':[]}}}
    snapshot={'synced_at':stamp,'rows_generation':'synthetic','sources':{
        source:{'status':'ok','stale':False,'last_ok_at':stamp}},'trips':[trip]}
    raw={'row':6,'cells':{'B':'2026-10-22','C':'Synthetic Person','D':'','E':100,'F':0,'G':0},'amount':100}
    rows={source:{'trips':{sheet:{'income':[raw],'expense':[]}}}}
    monkeypatch.setattr(google,'enabled',lambda:True)
    monkeypatch.setattr(google,'_snapshot_path',lambda:tmp_path/'snapshot.json')
    monkeypatch.setattr(google,'_rows_path',lambda:tmp_path/'rows.json')
    monkeypatch.setattr(google,'load_mapping',lambda *args:{key:'andre-trip'})
    monkeypatch.setattr(google,'load_choices',lambda *args:{'choices':{}})
    monkeypatch.setattr(ga,'load_consistent',lambda *args:(snapshot,rows))
    monkeypatch.setattr(participants,'open_store',lambda **kwargs:None)
    context=participants.google_context('andre-trip')
    assert context['available'] and context['sheet']==sheet
    state=participants.build_state('andre-trip')
    reference=state['income_rows'][0]['ref']
    assert reference=='andre_main|1022_Synthetic|6'
    other=insurance._income_context([{'tab_id':'andre-trip','display_key':key}])
    assert other['rows_by_trip']['andre-trip'][0]['ref']==reference
