"""Interactive, loopback-only Drive read authorization into a NEW dedicated ADC file.

The authorization URL is written to a private local request file, never printed.
Existing Gmail/Google credentials are never replaced. Open the URL with Aside.
"""
import argparse
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
TOKEN_URIS = {'https://oauth2.googleapis.com/token', 'https://accounts.google.com/o/oauth2/token'}
AUTH_URIS = {'https://accounts.google.com/o/oauth2/auth', 'https://accounts.google.com/o/oauth2/v2/auth'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def load_client(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    client = data.get('installed')
    if (not isinstance(client, dict) or client.get('token_uri') not in TOKEN_URIS
            or client.get('auth_uri') not in AUTH_URIS
            or not client.get('client_id') or not client.get('client_secret')):
        raise ValueError('DRIVE_AUTH_INSTALLED_CLIENT_REQUIRED')
    return client


def authorization_url(client, state, redirect):
    return client['auth_uri'] + '?' + urllib.parse.urlencode({
        'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
        'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent', 'state': state,
        'include_granted_scopes': 'false'})


def callback_code(path, expected_state):
    parsed = urllib.parse.urlsplit(path)
    query = urllib.parse.parse_qs(parsed.query)
    states, codes = query.get('state', []), query.get('code', [])
    if parsed.path != '/' or len(states) != 1 or not secrets.compare_digest(states[0], expected_state):
        raise ValueError('DRIVE_AUTH_STATE_INVALID')
    if 'error' in query:
        raise ValueError('DRIVE_AUTH_REFUSED')
    if len(codes) != 1 or not codes[0]:
        raise ValueError('DRIVE_AUTH_CODE_INVALID')
    return codes[0]


def exchange(client, code, redirect, account, opener=None):
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    body = urllib.parse.urlencode({'client_id': client['client_id'],
        'client_secret': client['client_secret'], 'code': code, 'grant_type': 'authorization_code',
        'redirect_uri': redirect}).encode()
    with opener(client['token_uri'], body, timeout=30) as response:
        token = json.load(response)
    if SCOPE not in str(token.get('scope', '')).split() or not token.get('refresh_token') or not token.get('access_token'):
        raise ValueError('DRIVE_AUTH_OFFLINE_SCOPE_REQUIRED')
    request = urllib.request.Request('https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)',
        headers={'Authorization': 'Bearer ' + token['access_token']})
    with opener(request, timeout=30) as response:
        identity = json.load(response)
    if identity.get('user', {}).get('emailAddress') != account:
        raise ValueError('DRIVE_AUTH_ACCOUNT_MISMATCH')
    return {'type': 'authorized_user', 'client_id': client['client_id'],
            'client_secret': client['client_secret'], 'refresh_token': token['refresh_token'],
            'token_uri': client['token_uri'], 'scopes': [SCOPE]}


def save_new(path, credentials):
    descriptor = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(credentials, stream)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-file', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--request-file', required=True)
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args(argv)
    destination, request_file = Path(args.destination).resolve(), Path(args.request_file).resolve()
    if destination.exists() or request_file.exists() or not destination.parent.is_dir():
        parser.error('DRIVE_AUTH_NEW_OUTPUTS_REQUIRED')
    client = load_client(args.client_file)
    state, received = secrets.token_urlsafe(32), {}
    redirect = f'http://127.0.0.1:{args.port}/'

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path == '/start':
                self.send_response(302)
                self.send_header('Location', authorization_url(client, state, redirect))
                self.end_headers()
                return
            try:
                received['code'] = callback_code(self.path, state)
                status, text = 200, 'Google authorization received. You may close this tab.'
            except ValueError as error:
                if str(error) == 'DRIVE_AUTH_REFUSED': received['error'] = str(error)
                status, text = 400, 'Authorization callback rejected.'
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(text.encode())

        def log_message(self, *args):
            pass

    with HTTPServer(('127.0.0.1', args.port), Callback) as server:
        server.timeout = 1
        with request_file.open('x', encoding='utf-8') as stream:
            json.dump({'url': authorization_url(client, state, redirect), 'scope': SCOPE}, stream)
        print(json.dumps({'status': 'WAITING_FOR_USER_GOOGLE_CONSENT', 'loopback_only': True}), flush=True)
        deadline = time.monotonic() + args.timeout
        while not received and time.monotonic() < deadline:
            server.handle_request()
    if 'code' not in received:
        print(json.dumps({'status': 'BLOCKED', 'code': received.get('error', 'DRIVE_AUTH_TIMEOUT')}))
        return 1
    try:
        credentials = exchange(client, received['code'], redirect, args.account)
        save_new(destination, credentials)
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'DRIVE_AUTH_EXCHANGE_OR_SAVE_FAILED'}))
        return 1
    print(json.dumps({'status': 'DRIVE_READONLY_ADC_SAVED', 'existing_credentials_changed': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
