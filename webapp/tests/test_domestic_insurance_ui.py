"""Domestic N/A is distinct from missing overseas evidence, without source writes."""
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from webapp import ledger_board as board, ledger_design as design
from webapp import google_ledger_page as google, participant_income_page as people
from webapp import trip_insurance_policy as policy, trip_workflow as workflow
from webapp.tests.test_trip_google_income import income_context
from webapp.tests.test_core_workflow import workflow_context


@pytest.fixture
def trips(monkeypatch):
    data=[dict(tab_id='trip-syn', destination='통영', display_key='0704_통영',
               starts_on='2026-07-04', ends_on='2026-07-05')]
    monkeypatch.setattr(board,'live_trips',lambda **kwargs:data)
    monkeypatch.setattr(board,'current_role',lambda:'owner')
    return data


@pytest.mark.parametrize('destination,domestic', [('통영',True),('제주',True),('야마가타',False),('',False),('제주도',False)])
def test_income_keeps_totals_and_only_hides_domestic_insurance(income_context,trips,destination,domestic):
    trips[0]['destination']=destination
    before=deepcopy(income_context)
    body=google.trip_income_html('trip-syn')
    assert 'INCOME-NAME' in body and '1,000원' in body
    assert ('<th>보험 명단</th>' in body) is not domestic
    assert ('participant-insurance-cell' in body) is not domestic
    assert income_context==before


def test_domestic_panel_and_header_have_no_loading_or_warning(trips,monkeypatch):
    monkeypatch.setattr(board,'data_status_mark',lambda:'')
    body=design._participant_trip_panel('trip-syn',{})
    assert '국내여행 · 보험 가입 대상 아님' in body
    assert 'participant-trip-panel' not in body and 'data-auto-load' not in body
    assert '확인 필요' not in body and "role='alert'" not in body
    assert 'trip-region-badge' in design._head_html(trips[0])
    trips[0]['destination']='오제'
    assert 'data-auto-load' in design._participant_trip_panel('trip-syn',{})
    assert 'trip-region-badge' not in design._head_html(trips[0])


def test_domestic_workflow_keeps_primary_and_tools_separate(workflow_context,trips):
    b,_,_=workflow_context
    trips[0]['tab_id']='trip'
    before=deepcopy(trips)
    body=workflow.render(b,'trip',[],{})
    assert '보험 후보 비교' not in body
    primary,tools=body.split("<details class='trip-workflow-tools'>")
    assert primary.count("class='trip-workflow-card'")==2
    assert tools.count("class='trip-workflow-card'")==4
    assert '지출 검토·복사' in primary and '수입·마감 확인' in primary
    assert trips==before


def test_domestic_lazy_endpoint_skips_all_roster_reads_and_retains_owner_gate(trips,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('must not read/reconcile domestic roster')
    monkeypatch.setattr(people,'build_state',forbidden)
    output=[]
    handler=SimpleNamespace(_send=lambda body:output.append(body),
                            _send_json=lambda value,status:output.append((value,status)))
    route=urlparse('/api/participants/trip-panel')
    people.dispatch(handler,route,is_owner=True,query={'trip':['trip-syn']})
    assert output==[policy.notice()]
    output.clear()
    people.dispatch(handler,route,is_owner=False,query={'trip':['trip-syn']})
    assert output[0][1]==403


def test_missing_duplicate_and_deleted_trip_are_not_assumed_domestic(trips):
    assert not policy.domestic_trip('missing')
    trips.append(dict(trips[0]))
    assert not policy.domestic_trip('trip-syn')
    trips[:]=[dict(trips[0],deleted=True)]
    assert not policy.domestic_trip('trip-syn')


def test_viewer_domestic_income_remains_grant_protected(income_context,trips,monkeypatch):
    monkeypatch.setattr(board,'current_role',lambda:'viewer')
    monkeypatch.setattr(board,'current_request_session',lambda:SimpleNamespace(user_id='viewer-syn'))
    monkeypatch.setattr(board,'viewer_visible_tabs',lambda session:{'trip-syn'})
    assert 'INCOME-NAME' in google.trip_income_html('trip-syn')
    monkeypatch.setattr(google,'load_grants',lambda *args:{'grants':{}})
    assert 'INCOME-NAME' not in google.trip_income_html('trip-syn')
