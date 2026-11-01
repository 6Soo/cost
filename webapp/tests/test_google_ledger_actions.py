import datetime as dt
from urllib.parse import urlparse

import pytest

from app import google_sheet_navigation as nav, sync_schedule
from webapp import google_ledger_actions as actions, google_ledger_page as page
from webapp.tests.test_google_ledger_page import FakeHandler
from webapp.tests.test_trip_google_income import income_context


@pytest.mark.parametrize('owner,viewer,raw,token,code', [
    (False, None, b'{}', 'csrf', 403),
    (False, 'viewer-syn', b'{}', 'csrf', 403),
    (False, 'viewer-syn', None, '', 403),
    (True, None, b'{}', '', 403),
    (True, None, None, '', 200),
])
def test_sync_permissions(income_context, owner, viewer, raw, token, code):
    handler = FakeHandler(token)
    actions.dispatch(handler, urlparse('/api/google-ledger/sync'), is_owner=owner,
                     viewer_user_id=viewer, raw=raw, csrf='csrf')
    assert handler.sent[0][1] == code


def test_refresh_starts_once_and_get_does_not_start(income_context, monkeypatch):
    started = []
    class Thread:
        def __init__(self, **kwargs): pass
        def start(self): started.append(1)
    monkeypatch.setattr(actions.threading, 'Thread', Thread)
    monkeypatch.setattr(actions, '_state', {'status': 'idle'})
    for raw in (None, b'{}', b'{}'):
        actions.dispatch(FakeHandler('csrf'), urlparse('/api/google-ledger/sync'),
                         is_owner=True, raw=raw, csrf='csrf')
    assert started == [1]


@pytest.mark.parametrize('failed', [False, True])
def test_refresh_uses_scheduler_lock_and_records_real_result(income_context, monkeypatch, failed):
    monkeypatch.setattr(actions, '_state', {'status': 'running'})
    def sync(path, rows, **kwargs):
        with pytest.raises(sync_schedule.LockHeld):
            with sync_schedule.SyncLock(path.with_name('sync.lock'), now=dt.datetime.now(dt.timezone.utc)):
                pass
        return {'synced_at': 'new', 'sources': {'main': {'status': 'error' if failed else 'ok'}}}
    monkeypatch.setattr(actions.ga, 'sync', sync)
    actions._refresh()
    assert actions._state['status'] == ('error' if failed else 'done')
    state = sync_schedule.read_state(page._snapshot_path().with_name('sync-state.json'))
    assert state['consecutive_failures'] == int(failed)


def test_refresh_respects_backoff_and_never_calls_google(income_context, monkeypatch):
    path = page._snapshot_path().with_name('sync-state.json')
    sync_schedule.record_result(path, ok=False, now=dt.datetime.now(actions.ga.KST), error_code='TEST')
    monkeypatch.setattr(actions.ga, 'sync', lambda *a, **kw: pytest.fail('backoff bypass'))
    actions._refresh()
    assert actions._state['status'] == 'error'
    assert '대기' in actions._state['message']


def test_source_resolves_selected_copy_and_redirects_to_gid(income_context, monkeypatch):
    snapshot, key = income_context
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {key: 'archive'}})
    calls = []
    monkeypatch.setattr(actions, 'source_url', lambda source, sheet: calls.append((source, sheet)) or
                        'https://docs.google.com/spreadsheets/d/fixed/edit#gid=42')
    handler = FakeHandler()
    handler.send_response = lambda code: calls.append(code)
    handler.send_header = lambda name, value: calls.append((name, value))
    handler.end_headers = lambda: None
    actions.dispatch(handler, urlparse('/api/google-ledger/source'), is_owner=True,
                     query={'trip': ['trip-syn']})
    assert calls[0] == ('archive', snapshot['trips'][0]['copies']['archive']['sheet'])
    assert 302 in calls
    assert ('Location', 'https://docs.google.com/spreadsheets/d/fixed/edit#gid=42') in calls


@pytest.mark.parametrize('granted,visible', [(False, True), (True, False)])
def test_source_enforces_current_grant_and_trip_access(income_context, monkeypatch, granted, visible):
    if not granted:
        monkeypatch.setattr(page, 'load_grants', lambda *a: {'grants': {}})
    monkeypatch.setattr(actions, 'source_url', lambda *a: pytest.fail('source leaked'))
    handler = FakeHandler()
    actions.dispatch(handler, urlparse('/api/google-ledger/source'), is_owner=False,
                     viewer_user_id='viewer-syn', viewer_tabs={'trip-syn'} if visible else set(),
                     query={'trip': ['trip-syn']})
    assert handler.sent[0][1] == 404


def test_navigation_parses_google_js_escapes_without_executing():
    markup = r'items.push({name: "여행\x26\u0027 사본", pageUrl: "https:\/\/example.com", gid: "0",initialSheet: false});'
    assert nav.parse_tabs(markup) == {"여행&' 사본": '0'}
    assert nav.parse_tabs('<html>Login required</html>') == {}


def test_navigation_rejects_ambiguous_titles():
    with pytest.raises(actions.ga.SourceError):
        nav.parse_tabs('items.push({name: "same", pageUrl: "a", gid: "1"});'
                       'items.push({name: "same", pageUrl: "b", gid: "2"});')


def test_income_has_real_sync_button_and_access_checked_link(income_context, monkeypatch):
    body = page.trip_income_html('trip-syn')
    assert 'data-google-sync' in body and 'role=\'status\'' in body
    assert '/api/google-ledger/source?trip=trip-syn' in body
    monkeypatch.setattr('webapp.ledger_board.current_role', lambda: 'viewer')
    from types import SimpleNamespace
    monkeypatch.setattr('webapp.ledger_board.current_request_session', lambda: SimpleNamespace(user_id='viewer-syn'))
    monkeypatch.setattr('webapp.ledger_board.viewer_visible_tabs', lambda *a: {'trip-syn'})
    assert 'data-google-sync' not in page.trip_income_html('trip-syn')
