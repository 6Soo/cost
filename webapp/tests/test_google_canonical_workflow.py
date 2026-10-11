import json
from urllib.parse import urlparse

import pytest

from webapp import google_ledger_page as page
from webapp.tests import test_google_ledger_page as fixtures


def healthy_snapshot():
    snapshot = fixtures.snapshot_doc()
    snapshot['sources'] = fixtures._clean_sources()
    return snapshot


def test_duplicate_without_explicit_choice_has_no_verified_money():
    trip = page.owner_payload(healthy_snapshot(), {'choices': {}})['trips'][0]
    assert trip['verified'] is False and trip['net'] is None
    assert trip['chosen_source'] is None
    assert 'CHOICE_REQUIRED' in trip['blocked_by']


def test_viewer_uses_owner_choice_and_gets_only_canonical_detail_link():
    snapshot = healthy_snapshot()
    key = snapshot['trips'][0]['key']
    grants = {'grants': {'viewer-syn': [key]}}
    payload = page.viewer_payload(snapshot, grants, 'viewer-syn', mapping={key: 'tab-syn'},
                                  visible_tabs={'tab-syn'}, choices={'choices': {key: 'archive'}})
    trip, = payload['trips']
    assert trip['expense_total'] == 300 and trip['verified'] is True
    assert 'copies' not in trip and 'reported' not in trip
    body = page.render_html(payload, is_owner=False)
    assert '여행 상세' in body and 'source=archive' in body
    assert 'data-choice' not in body and 'main 상세' not in body


def test_duplicate_viewer_without_choice_does_not_guess_detail_source():
    snapshot = healthy_snapshot()
    key = snapshot['trips'][0]['key']
    payload = page.viewer_payload(snapshot, {'grants': {'viewer-syn': [key]}}, 'viewer-syn',
                                  mapping={key: 'tab-syn'}, visible_tabs={'tab-syn'})
    assert payload['trips'][0]['verified'] is False
    body = page.render_html(payload, is_owner=False)
    assert '여행 상세' not in body and '정본 선택 필요' in body


@pytest.mark.parametrize('key,source', [('missing-syn', 'main'), ('<script>0630', 'archive')])
def test_choice_route_rejects_unknown_trip_or_missing_copy(tmp_path, monkeypatch, key, source):
    snapshot = tmp_path / 'snapshot.json'
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(snapshot))
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_ROWS', str(tmp_path / 'rows.json'))
    monkeypatch.setattr(page.google_authority, 'load_consistent', lambda *args: (healthy_snapshot(), {}))
    handler = fixtures.FakeHandler('token-syn')
    page.dispatch(handler, urlparse('/api/google-ledger/choice'), is_owner=True, csrf='token-syn',
                  raw=json.dumps({'key': key, 'source': source}).encode())
    assert handler.sent[0][1] == 400
    assert not page.choice_path(snapshot).exists()


def test_same_choice_retry_does_not_duplicate_history(tmp_path):
    snapshot = tmp_path / 'snapshot.json'
    first = page.record_choice(snapshot, key='trip-syn', source='main', at='t1')
    second = page.record_choice(snapshot, key='trip-syn', source='main', at='t2')
    assert first == second and len(second['history']) == 1


@pytest.mark.parametrize('width', [390, 1440])
def test_browser_owner_selects_copy_and_viewer_follows_it(width):
    from unittest.mock import patch
    from playwright.sync_api import sync_playwright
    from webapp import ledger_board
    from webapp.tests import test_google_ledger_browser as browser_fixtures

    case = browser_fixtures.GoogleLedgerBrowserTests()
    case.setUp()
    try:
        key = '0630_오제'
        archive = browser_fixtures.workbook(key, ('ARCHIVE-SYN', 'SYN', 700000), ('SHOP-SYN', '식비', 110000))
        now = page.dt.datetime.now(page.google_authority.KST)
        page.google_authority.sync(case.snapshot, case.rows,
                                   fetcher=case.fetcher({'main': case.good['main'], 'archive': archive}), now=now)
        page.set_mapping(case.snapshot, key=key, tab_id='tab-syn', known_keys={key})
        page.set_grants(case.snapshot, user_id='viewer-syn', keys=[key], granted=True, at='t')
        visible = type('Access', (), {'visible_tabs': staticmethod(lambda user_id, now=None: {'tab-syn'})})
        with patch.object(page, 'caller', return_value=(True, 'owner-syn')), sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': width, 'height': 844})
            pg = context.new_page()
            pg.goto(case.base + '/google-ledger')
            pg.get_by_text('정본 선택 필요', exact=True).wait_for()
            pg.on('dialog', lambda dialog: dialog.accept())
            pg.get_by_role('button', name='archive 정본 선택', exact=True).click()
            pg.get_by_text('정본: archive', exact=True).wait_for()
            assert page.load_choices(case.snapshot)['choices'][key] == 'archive'
            assert pg.evaluate('document.documentElement.scrollWidth <= innerWidth')
            with patch.object(page, 'caller', return_value=(False, 'viewer-syn')), \
                    patch.object(ledger_board, '_ACCESS', visible()):
                pg.reload()
                assert pg.locator('[data-choice]').count() == 0
                pg.get_by_role('link', name='여행 상세', exact=True).click()
                pg.get_by_text('ARCHIVE-SYN', exact=True).wait_for()
                assert 'ALICE-NAME' not in pg.content()
            context.close()
            browser.close()
    finally:
        case.tearDown()
