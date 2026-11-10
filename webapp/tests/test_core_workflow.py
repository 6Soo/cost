from copy import deepcopy
from types import SimpleNamespace

import pytest

from webapp import expense_amount_group_service as groups, trip_workflow as workflow
from webapp.tests.test_expense_amount_group_authority import context


def test_all_trip_audit_reuses_input_once_without_copy_or_identity_claims(context, monkeypatch):
    board, snapshot, private, mapping, payload, detail, costs = context
    before = deepcopy((snapshot, private, payload, detail, costs))
    board.list_trips = lambda include_archived=True: [
        {'tab_id':'trip-a'}, {'tab_id':'trip-missing'}, {'tab_id':'quarter:2026-Q1'},
        {'tab_id':'refunds'}, {'tab_id':'trip-deleted','deleted':True}]
    calls = []
    monkeypatch.setattr(groups.google_authority, 'load_consistent', lambda *args: (
        calls.append(True) or snapshot, private))
    result = groups.audit_all_trips(board)
    assert calls == [True]
    assert (result['trip_count'],result['comparable_trip_count'],result['unavailable_trip_count']) == (2,1,1)
    assert result['trips'][0]['groups'][0] == {
        'status':'matched','cost_count':1,'google_count':1,'count_difference':0,
        'google_row_numbers':[7],'copy_review_required':False}
    assert result['trips'][1]['summary'] is None
    assert result['copy_authorization'] == 'EXISTING_EXPORT_PREVIEW_REQUIRED'
    assert all(value not in repr(result) for value in ('다른 가맹점','수입 전용 합성','amount_krw','group_id'))
    assert (snapshot, private, payload, detail, costs) == before
    payload['sources']['main']['stale'] = True
    second = groups.audit_all_trips(board)
    assert len(calls) == 2 and second['comparable_trip_count'] == 0


def test_audit_owner_check_precedes_all_source_reads():
    board = SimpleNamespace(current_role=lambda:'viewer')
    assert groups.audit_all_trips(board) == {'available':False,'reason':'OWNER_REQUIRED','trips':[]}
    assert workflow.build_state(board, 'trip', [], {}) is None


@pytest.fixture
def workflow_context(monkeypatch):
    board = SimpleNamespace(current_role=lambda:'owner')
    trip = {'key':'sheet','closure':'closed','closure_current':True,
            'review':[], 'copies':{'archive':{'sheet':'archive-sheet'}},
            'tab_id':'trip', 'visual_closed':True}
    board.live_trips = lambda include_archived=True: [trip]
    payload = {'trips':[trip], 'sources':{role:{'status':'ok','stale':False} for role in ('main','archive')}}
    monkeypatch.setattr(workflow.google,'enabled',lambda:True)
    monkeypatch.setattr(groups,'_source_bundle',lambda: ({},{},{'sheet':'trip'},payload))
    monkeypatch.setattr(workflow,'_receipts',lambda tid:{'available':False,'reason':'STORE_UNAVAILABLE'})
    return board, trip, payload


@pytest.mark.parametrize('case,expected', [('closed','closed'),('open','open'),('stale','unknown'),
                                         ('duplicate','closed'),('old_closure','unknown'),('identity','unknown'),
                                         ('no_archive','unknown')])
def test_closure_requires_current_google_archive_evidence(workflow_context, case, expected):
    board, trip, payload = workflow_context
    # The settlement step must follow build_state.closure, not the visual list
    # marker, so exercise both sources with deliberately different values.
    trip['visual_closed'] = case in {'open', 'stale', 'identity', 'no_archive'}
    if case == 'open':
        trip['closure']='open'; trip['copies']={'main':{'sheet':'main'}}
    if case == 'stale': payload['sources']['archive']['stale']=True
    if case == 'duplicate': trip['review']=['DUPLICATE_IN_BOTH']
    if case == 'old_closure': trip['closure_current']=False
    if case == 'identity': trip['review']=['POSSIBLE_DUPLICATE']
    if case == 'no_archive': trip['copies']={}
    state = workflow.build_state(board,'trip',[{'blocked':True}],{'available':True})
    assert state['closure'] == expected
    assert state['google_available'] is True  # Amount-group equality never changes closure evidence.
    assert state['displayed_holds'] == 1
    markup = workflow.render(board,'trip',[],{'available':False})
    closure_label = {'closed': '마감', 'open': '미마감', 'unknown': '확인 중'}[expected]
    assert f'href="#trip-close">{closure_label}</a>' in markup
    assert ('<span class="step-state">완료</span>' in markup
            if expected == 'closed' else '<span class="step-state">완료</span>' not in markup)
    assert 'expense-reconciliation' not in markup
    assert 'form' not in markup and '<details' not in markup
    assert ('data-state="done"' in markup if expected == 'closed'
            else 'data-state="todo"' in markup)


def test_refund_and_quarter_are_not_actual_trip_closure(workflow_context):
    board, _, _ = workflow_context
    for tid in ('refunds','unclassified','quarter:2026-Q1'):
        assert workflow.render(board,tid,[],{}) == ''


def test_source_failure_is_cached_only_within_the_audit(context, monkeypatch):
    board, *_ = context
    board.list_trips = lambda include_archived=True: [{'tab_id':'trip-a'},{'tab_id':'trip-b'}]
    calls = []
    def unavailable(*args):
        calls.append(True)
        raise ValueError('C:/private/customer-source')
    monkeypatch.setattr(groups.google_authority,'load_consistent',unavailable)
    first = groups.audit_all_trips(board)
    assert len(calls) == 1 and first['unavailable_trip_count'] == 2
    assert 'customer-source' not in repr(first)
    groups.audit_all_trips(board)
    assert len(calls) == 2


def test_review_actions_use_current_trip_and_do_not_claim_missing_sources_are_empty(workflow_context):
    board, _, _ = workflow_context
    markup = workflow.render(board, 'trip', [{'row_id': 'expense-a', 'blocked': True,
                                            'source_merchant': 'Synthetic merchant'}], {'available': False})
    assert 'href="#view-expense"' in markup
    assert 'href="/receipts?trip=trip"' in markup
    assert 'href="#view-income"' in markup
    assert '/import' not in markup


def test_workflow_steps_fit_mobile_and_retain_keyboard_links(workflow_context, monkeypatch):
    from playwright.sync_api import sync_playwright
    from webapp import ledger_design_assets, site_shell
    board, _, _ = workflow_context
    monkeypatch.setattr(workflow.google,'format_display_time',lambda value:'2026-10-30 15:00')
    document = ("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
                '<style>'+ledger_design_assets.STYLE+'</style></head><body><main>'+
                workflow.render(board,'trip',[],{'available':False})+'</main></body></html>')
    document=site_shell.wrap_document(document,'/board?tab=trip')
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        try:
            tab=browser.new_page()
            tab.set_content(document)
            for theme in ('light','dark'):
                tab.emulate_media(color_scheme=theme)
                for width in (320,390,759,760,1280):
                    tab.set_viewport_size({'width':width,'height':844})
                    steps=tab.locator('.settlement-steps')
                    assert tab.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert steps.locator('li').count()==5
                    assert steps.locator('a').evaluate_all(
                        '(links)=>links.every(link=>link.getBoundingClientRect().height>=44)')
                    assert steps.locator('a[href="#view-expense"]').count()==1
                    assert steps.locator('a[href="#trip-close"]').count()==1
        finally:
            browser.close()
