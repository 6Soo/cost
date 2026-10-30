"""Missing roster/index must not hide readable income or fabricate attendance."""
import copy

import pytest
from playwright.sync_api import sync_playwright

from app import google_authority
from webapp import google_ledger_page as google, participant_income_page as page, site_shell


def original_income(monkeypatch, *, stale=False, detail=True):
    monkeypatch.setattr(google, 'enabled', lambda: True)
    monkeypatch.setattr(google, 'snapshot_path', lambda: 'synthetic-snapshot')
    monkeypatch.setattr(google, 'rows_path', lambda: 'synthetic-rows')
    monkeypatch.setattr(google, 'load_mapping', lambda path: {'sheet': 'trip'})
    monkeypatch.setattr(google, 'load_choices', lambda path: {})
    monkeypatch.setattr(google_authority, 'load_consistent', lambda *args: (
        {'synced_at':'2026-10-30T15:00:03.243126+09:00','rows_generation':'one'}, {}))
    monkeypatch.setattr(google, 'snapshot_for_display', lambda snapshot: dict(snapshot, sources={
        'main': {'status':'ok', 'stale':stale}}))
    monkeypatch.setattr(google, 'owner_payload', lambda *args: {
        'trips':[{'key':'sheet','chosen_source':'main','income_total':1000,'verified':False}]})
    monkeypatch.setattr(google, 'owner_income_names', lambda *args: None)
    raw = {'income':[{'row':6,'name':'<합성 이름>','nickname':'합성 별명', 'amount':1000,
                      'deposit':0,'balance':1000,'extra':None,'date':'2026-10-30'}]}
    monkeypatch.setattr(google, 'owner_rows', lambda *args: copy.deepcopy(raw) if detail else None)
    return raw


def test_original_rows_available_without_index_and_missing_roster_stays_readonly(monkeypatch, tmp_path):
    raw = original_income(monkeypatch)
    missing = tmp_path/'not-created.sqlite'
    monkeypatch.setenv('WEBLEDGER_PARTICIPANT_DB', str(missing))
    state = page.build_state('trip')
    assert state['configured'] is False
    assert state['google']['available'] is True
    assert state['google']['name_index_complete'] is False
    assert len(state['income_rows']) == len(state['unlinked_income']) == 1
    row = state['income_rows'][0]
    assert (row['ref'], row['amount'], row['cells']['E']) == ('main|sheet|6',1000,0)
    assert state['input_fingerprint'] == '' and not state['completion']['complete']
    assert not missing.exists()
    markup = site_shell.wrap_document(page.render_page(state), '/participants?trip=trip')
    assert 'id="site-shell-style"' in markup
    assert '&lt;합성 이름&gt;' in markup and '<합성 이름>' not in markup
    assert 'STORE_UNAVAILABLE' not in markup and '참가 확정 0명' not in markup
    assert '등록된 참가자가 없습니다' not in markup and 'action=\'/api/participants/link\'' not in markup
    assert '2026-10-30T15:00:03.243126' not in markup
    assert raw['income'][0]['deposit'] == 0


@pytest.mark.parametrize('stale,detail', [(True,True),(False,False)])
def test_fallback_does_not_claim_unavailable_or_stale_source_is_current(monkeypatch, stale, detail):
    original_income(monkeypatch, stale=stale, detail=detail)
    assert not page.google_context('trip')['available']


def test_generation_failure_never_uses_partial_private_rows(monkeypatch):
    original_income(monkeypatch)
    def fail(*args):
        raise google_authority.SnapshotError('GENERATION_MISMATCH')
    monkeypatch.setattr(google_authority, 'load_consistent', fail)
    context = page.google_context('trip')
    assert not context['available'] and context['amount_rows'] == []


def test_mobile_document_has_shell_and_local_scroll_without_squeezed_columns(monkeypatch, tmp_path):
    original_income(monkeypatch)
    monkeypatch.setenv('WEBLEDGER_PARTICIPANT_DB', str(tmp_path/'missing.sqlite'))
    monkeypatch.setattr(page, '_trip_options', lambda trip: [])
    state = page.build_state('trip')
    document = site_shell.wrap_document(page.render_page(state), '/participants?trip=trip')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page()
            tab.set_content(document)
            for theme in ('light','dark'):
                tab.emulate_media(color_scheme=theme)
                for width in (320,375,390,430,759,760,1280):
                    tab.set_viewport_size({'width':width,'height':844})
                    assert tab.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert tab.locator('.site-topbar').is_visible()
                    assert tab.locator('.participant-table-wrap').evaluate('(e)=>e.scrollWidth>=e.clientWidth')
                    assert tab.locator('table').evaluate('(e)=>e.getBoundingClientRect().width>=760')
                    assert tab.locator('[role=status]').filter(has_text='참가 명단 연결 필요').is_visible()
            tab.set_viewport_size({'width':640,'height':844})
            tab.evaluate('document.documentElement.style.zoom="200%"')
            assert tab.evaluate('document.documentElement.scrollWidth<=innerWidth')
            tab.locator('.participant-table-wrap').focus()
            assert tab.locator('.participant-table-wrap').evaluate('(e)=>e===document.activeElement')
        finally:
            browser.close()
