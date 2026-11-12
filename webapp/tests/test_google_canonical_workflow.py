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
    assert '여행 상세' not in body and '최종 장부 선택 필요' in body


def test_missing_chosen_copy_never_falls_back_and_owner_can_reselect():
    snapshot = healthy_snapshot()
    trip = snapshot['trips'][0]
    key = trip['key']
    del trip['copies']['archive']
    trip['canonical_source'] = 'main'
    payload = page.owner_payload(snapshot, {'choices': {key: 'archive'}})
    resolved = payload['trips'][0]
    assert resolved['chosen_source'] is None
    assert resolved['verified'] is False
    assert resolved['income_total'] is None and resolved['expense_total'] is None
    assert resolved['net'] is None
    assert 'CHOSEN_COPY_MISSING' in resolved['blocked_by']
    body = page.render_html(payload, is_owner=True, csrf='token-syn')
    assert 'main 최종 장부로 선택' in body
    assert 'archive 최종 장부로 선택' not in body


@pytest.mark.parametrize('key,source', [('missing-syn', 'main'), ('<script>0630', 'archive')])
def test_choice_route_rejects_unknown_trip_or_missing_copy(tmp_path, monkeypatch, key, source):
    snapshot = tmp_path / 'snapshot.json'
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(snapshot))
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_ROWS', str(tmp_path / 'rows.json'))
    monkeypatch.setattr(page.google_authority, 'load_consistent', lambda *args: (healthy_snapshot(), {}))
    # The live /google-ledger routes were retired (ROUTES=(), 6c0a5e38), but the
    # choice dispatch still rejects unknown trips / missing copies with 400.
    # Re-enable the route in this harness to exercise that validation, as the
    # sibling test_choice_dispatch_validates_copy_owner_and_accepts_andre does.
    monkeypatch.setattr(page, 'ROUTES', ('/api/google-ledger/choice',))
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
