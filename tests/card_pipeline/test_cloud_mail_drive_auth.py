"""Synthetic OAuth values only; no real consent, credentials, or network."""
import io
import json
import urllib.parse

import pytest

from tools import authorize_cloud_mail_drive as auth


CLIENT = {'client_id': 'synthetic-client', 'client_secret': 'synthetic-secret',
          'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
          'token_uri': 'https://oauth2.googleapis.com/token'}


@pytest.mark.parametrize('path', ['/?state=wrong&code=x', '/other?state=held&code=x',
                                 '/?state=held&state=held&code=x', '/?state=held&code=x&code=y',
                                 '/?state=held', '/?state=held&error=access_denied'])
def test_callback_rejects_wrong_state_path_duplicate_or_refusal(path):
    with pytest.raises(ValueError, match='DRIVE_AUTH_'): auth.callback_code(path, 'held')


def test_request_has_only_drive_readonly_state_and_offline_access():
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(auth.authorization_url(CLIENT, 'held', 'http://127.0.0.1:8769/')).query)
    assert query['scope'] == [auth.SCOPE] and query['state'] == ['held']
    assert query['access_type'] == ['offline'] and query['include_granted_scopes'] == ['false']
    assert auth.callback_code('/?state=held&code=synthetic', 'held') == 'synthetic'


@pytest.mark.parametrize('failure', ['wrong-account', 'missing-refresh', 'wrong-scope', None])
def test_exchange_checks_identity_and_scope_before_returning_adc(failure):
    token = {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'scope': auth.SCOPE}
    if failure == 'missing-refresh': del token['refresh_token']
    if failure == 'wrong-scope': token['scope'] = 'https://www.googleapis.com/auth/gmail.readonly'
    calls = []
    def open_(request, *args, **kwargs):
        calls.append(request)
        data = token if isinstance(request, str) else {'user': {'emailAddress':
            'other@example.invalid' if failure == 'wrong-account' else 'owner@example.invalid'}}
        return io.StringIO(json.dumps(data))
    if failure:
        with pytest.raises(ValueError, match='DRIVE_AUTH_'):
            auth.exchange(CLIENT, 'synthetic-code', 'http://127.0.0.1:8769/', 'owner@example.invalid', open_)
    else:
        adc = auth.exchange(CLIENT, 'synthetic-code', 'http://127.0.0.1:8769/', 'owner@example.invalid', open_)
        assert adc['type'] == 'authorized_user' and adc['scopes'] == [auth.SCOPE]
        assert 'access_token' not in adc


def test_new_adc_file_never_overwrites_existing_credentials(tmp_path):
    path = tmp_path / 'credentials.json'
    path.write_text('synthetic existing', encoding='utf-8')
    with pytest.raises(FileExistsError): auth.save_new(path, {'refresh_token': 'synthetic'})
    assert path.read_text() == 'synthetic existing'


def test_rejects_token_endpoint_that_could_receive_a_secret(tmp_path):
    path = tmp_path / 'client.json'
    path.write_text(json.dumps({'installed': {**CLIENT, 'token_uri': 'https://example.invalid/token'}}))
    with pytest.raises(ValueError, match='INSTALLED_CLIENT_REQUIRED'): auth.load_client(path)


def test_loopback_start_redirect_and_invalid_callback_do_not_save_credentials(tmp_path, monkeypatch):
    import socket
    import threading
    import time
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    client_file, request_file, destination = [tmp_path / name for name in
        ('client.json', 'request.json', 'new-adc.json')]
    client_file.write_text(json.dumps({'installed': CLIENT}))
    results = []
    monkeypatch.setattr(auth, 'exchange', lambda *a: pytest.fail('refused consent must not exchange'))
    worker = threading.Thread(target=lambda: results.append(auth.main([
        '--client-file', str(client_file), '--destination', str(destination),
        '--account', 'owner@example.invalid', '--request-file', str(request_file),
        '--port', str(port), '--timeout', '10'])), daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while not request_file.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert request_file.exists()
    opener = urllib.request.build_opener(auth.NoRedirect())
    base = f'http://127.0.0.1:{port}'
    with pytest.raises(urllib.error.HTTPError) as redirect:
        opener.open(base + '/start')
    assert redirect.value.code == 302
    url = redirect.value.headers['Location']
    assert url == json.loads(request_file.read_text())['url']
    with pytest.raises(urllib.error.HTTPError) as rejected:
        opener.open(base + '/?state=wrong&code=synthetic')
    assert rejected.value.code == 400 and worker.is_alive()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['state'][0]
    with pytest.raises(urllib.error.HTTPError):
        opener.open(base + '/?' + urllib.parse.urlencode({'state': state, 'error': 'access_denied'}))
    worker.join(3)
    assert not worker.is_alive() and results == [1] and not destination.exists()
