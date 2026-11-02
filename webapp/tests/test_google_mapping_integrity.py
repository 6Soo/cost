import json
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pytest

from webapp import google_ledger_page as gl
from webapp import google_ledger_actions
from webapp.tests import test_google_viewer_http as existing


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def get_without_following_redirect(app, path, user):
    request = Request(f'http://127.0.0.1:{app.port}{path}', headers={
        existing.access_control.SyntheticSessionAdapter.HEADER: user})
    try:
        response = build_opener(_NoRedirect).open(request)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read().decode()


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


def test_current_source_api_checks_owner_mapping_viewer_grant_and_assignment(app, monkeypatch):
    tab = app.trip
    key = '0630_오제'
    gl.set_mapping(app.snapshot, key=key, tab_id=tab, known_keys={key, '0107_대만'})
    mapping_before = gl.mapping_path(app.snapshot).read_bytes()
    source_before = app.snapshot.read_bytes()
    target_url = 'https://synthetic.invalid/google-sheet'
    monkeypatch.setattr(google_ledger_actions, 'source_url', lambda source, sheet: target_url)

    status, headers, body = get_without_following_redirect(
        app, f'/api/google-ledger/source?trip={tab}', existing.OWNER)
    assert status == 302 and headers['Location'] == target_url
    assert headers['Cache-Control'] == 'no-store' and body == ''

    app.link_and_assign(existing.VIEWER, tab)
    status, _, body = get_without_following_redirect(
        app, f'/api/google-ledger/source?trip={tab}', existing.VIEWER)
    assert status == 404 and 'ALICE-NAME' not in body

    app.grant_and_link(existing.VIEWER, key, tab)
    grants_before = gl.grants_path(app.snapshot).read_bytes()
    mapping_before = gl.mapping_path(app.snapshot).read_bytes()
    status, headers, body = get_without_following_redirect(
        app, f'/api/google-ledger/source?trip={tab}', existing.VIEWER)
    assert status == 302 and headers['Location'] == target_url and body == ''

    app.access.apply_assignment_snapshot(
        user_id=existing.VIEWER,
        items=[{'tab_id': tab, 'snapshot_revision': 2, 'state': existing.access_control.ASSIGN_REVOKED}],
        source_version='source-revoked', validity=existing.access_control.DEFAULT_VALIDITY,
        now=None, complete=False)
    status, _, body = get_without_following_redirect(
        app, f'/api/google-ledger/source?trip={tab}', existing.VIEWER)
    assert status == 404 and 'ALICE-NAME' not in body
    assert gl.mapping_path(app.snapshot).read_bytes() == mapping_before
    assert gl.grants_path(app.snapshot).read_bytes() == grants_before
    assert app.snapshot.read_bytes() == source_before


@pytest.mark.parametrize('loader,path_of,body', [
    (gl.load_choices, gl.choice_path, '{'),
    (gl.load_choices, gl.choice_path, '{"choices":[],"history":[]}'),
    (gl.load_mapping, gl.mapping_path, '[]'),
    (gl.load_grants, gl.grants_path, '{"grants":{"viewer":"trip"},"history":[]}'),
])
def test_corrupt_settings_are_refused_and_preserved(tmp_path, loader, path_of, body):
    from app.google_authority import SnapshotError
    snapshot = tmp_path / 'snapshot.json'
    path = path_of(snapshot)
    path.write_text(body, encoding='utf-8')
    with pytest.raises(SnapshotError, match='SETTINGS_UNAVAILABLE'):
        loader(snapshot)
    assert path.read_text(encoding='utf-8') == body


def test_corrupt_mapping_read_through_current_source_api_fails_closed_and_preserves_file(app):
    gl.set_mapping(app.snapshot, key='0630_오제', tab_id=app.trip, known_keys={'0630_오제'})
    mapping = gl.mapping_path(app.snapshot)
    mapping.write_text('[]', encoding='utf-8')
    before = mapping.read_bytes()
    status, body = app.call(f'/api/google-ledger/source?trip={app.trip}', user=existing.OWNER)
    assert status == 404 and 'ALICE-NAME' not in body
    assert mapping.read_bytes() == before
