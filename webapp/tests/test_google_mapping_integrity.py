import json
import urllib.request
import urllib.error

import pytest

from webapp import google_ledger_page as gl
from webapp.tests import test_google_viewer_http as existing


def post(app, path, payload):
    request = urllib.request.Request(f'http://127.0.0.1:{app.port}{path}',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json',
            existing.access_control.SyntheticSessionAdapter.HEADER: existing.OWNER,
            'X-CSRF-Token': existing.board_mod.CSRF_TOKEN})
    try:
        response = urllib.request.urlopen(request)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.read().decode()


def test_duplicate_cost_tab_is_refused_without_modifying_mapping(tmp_path):
    snapshot = tmp_path / 'snapshot.json'
    gl.set_mapping(snapshot, key='trip-one', tab_id='cost-one', known_keys={'trip-one', 'trip-two'})
    before = gl.mapping_path(snapshot).read_bytes()
    with pytest.raises(ValueError, match='COST_TAB_ALREADY_MAPPED'):
        gl.set_mapping(snapshot, key='trip-two', tab_id='cost-one', known_keys={'trip-one', 'trip-two'})
    assert gl.mapping_path(snapshot).read_bytes() == before


def test_legacy_ambiguous_mapping_is_denied_for_list_and_detail():
    assert gl.viewer_allowed_keys({'grants': {'viewer': ['trip-one', 'trip-two']}}, 'viewer',
                                  {'trip-one': 'cost-one', 'trip-two': 'cost-one'}, {'cost-one'}) == set()


@pytest.mark.parametrize('granted', ['false', 'true', 0, 1, None])
def test_grants_require_a_real_boolean(tmp_path, granted):
    snapshot = tmp_path / 'snapshot.json'
    with pytest.raises(ValueError, match='GRANT_INVALID'):
        gl.set_grants(snapshot, user_id='viewer', keys=['trip-one'], granted=granted, at='synthetic')
    assert not gl.grants_path(snapshot).exists()


@pytest.fixture
def app():
    case = existing.GoogleViewerHttpTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


def test_mapping_http_requires_a_current_cost_tab(app):
    status, body = post(app, '/api/google-ledger/mapping',
                            {'key': '0630_오제', 'tab_id': 'does-not-exist'})
    assert (status, json.loads(body)['code']) == (400, 'COST_TAB_UNKNOWN')
    assert not gl.mapping_path(app.snapshot).exists()


def test_http_rejects_string_boolean_and_unknown_trip_grant(app):
    for data in ({'keys': ['0630_오제'], 'granted': 'false'},
                 {'keys': ['unknown-trip'], 'granted': True}):
        status, body = post(app, '/api/google-ledger/grants',
                                dict(data, user_id=existing.VIEWER))
        assert status == 400, body
    assert not gl.grants_path(app.snapshot).exists()


def test_settings_http_rejects_non_object_json_without_writes(app):
    for route in ('choice', 'mapping', 'grants'):
        for body in ([], None, 'invalid', 123):
            status, response = post(app, '/api/google-ledger/' + route, body)
            assert (status, json.loads(response)['code']) == (400, 'INVALID_VALUE')
    assert not gl.choice_path(app.snapshot).exists()
    assert not gl.mapping_path(app.snapshot).exists()
    assert not gl.grants_path(app.snapshot).exists()
