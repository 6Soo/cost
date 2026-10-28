"""상시 예약 메일 수집. 공급사 발신 메일과 kew2000@hanmail.net 수신 메일을 Gmail에서 가져와 ota-mail 폴더에 보존한다.

메일 원본 헤더(발신 인증)를 그대로 저장해야 예약 근거로 쓸 수 있으므로 Gmail API의 full 형식을 저장한다."""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

SUPPLIER_DOMAINS = ('trip.com', 'trip.co.kr', 'klook.com', 'agoda.com', 'booking.com', 'agoda-messaging.com',
                    'toyoko-inn.com', 'toyoko-inn.co.jp', 'forest.go.kr', 'foresttrip.go.kr')
# 공급사 발신 여부와 관계없이 항상 수집한다.
ALWAYS_RECIPIENTS = ('kew2000@hanmail.net', 'kew2000@daum.net')
OVERLAP_DAYS = 2
API = 'https://gmail.googleapis.com/gmail/v1/users/me'


def build_query(after: str) -> str:
    senders = ' OR '.join(f'from:{domain}' for domain in SUPPLIER_DOMAINS)
    recipients = ' OR '.join(f'to:{address} OR cc:{address}' for address in ALWAYS_RECIPIENTS)
    # Toyoko Inn sender addresses vary; subject matching is a separate discovery path.
    return f'after:{after.replace("-", "/")} ({senders} OR {recipients} OR subject:토요코인)'


class GmailApi:
    """Gmail REST 호출. 액세스 토큰은 저장된 갱신 토큰으로 새로 받는다."""

    def __init__(self, token_file: Path, client_file: Path):
        self.token = json.loads(Path(token_file).read_text(encoding='utf-8'))
        data = json.loads(Path(client_file).read_text(encoding='utf-8'))
        self.client = data.get('installed') or data['web']
        self._access = None

    def _access_token(self) -> str:
        if self._access is None:
            body = urllib.parse.urlencode({
                'client_id': self.client['client_id'], 'client_secret': self.client['client_secret'],
                'refresh_token': self.token['refresh_token'], 'grant_type': 'refresh_token'}).encode()
            with urllib.request.urlopen(self.client['token_uri'], body, timeout=30) as response:
                self._access = json.loads(response.read())['access_token']
        return self._access

    def _get(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self._access_token()})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def list_ids(self, query: str) -> list:
        ids, page = [], None
        while True:
            params = {'q': query, 'maxResults': 500, **({'pageToken': page} if page else {})}
            data = self._get(f'{API}/messages?' + urllib.parse.urlencode(params))
            ids += [item['id'] for item in data.get('messages', [])]
            page = data.get('nextPageToken')
            if not page:
                return ids

    def get_full(self, message_id: str) -> dict:
        return self._get(f'{API}/messages/{message_id}?format=full')


def stored_ids(directory: Path) -> set:
    """이미 저장된 메일 파일의 ID. 같은 ID를 다시 받으면 내용이 달라 충돌하므로 건너뛴다."""
    ids = set()
    for path in Path(directory).glob('gmail*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        rows = data.get('responses', data) if isinstance(data, dict) else data
        ids.update(row['id'] for row in rows if isinstance(row, dict) and row.get('id'))
    return ids


def sync_unified_store(directory: Path) -> None:
    """운영이 단일 DB를 쓰면 새 수집을 같은 DB에 넣는다. 실패한 원문은 폴더에 남는다."""
    from app import ota_sources
    from app.ota_store import OtaStore
    manifest = ota_sources.read_manifest(ota_sources.manifest_path(Path(directory).parent))
    if not manifest or not manifest.get('unified_database'):
        return
    resolved = ota_sources.resolve_sources(Path(directory).parent)
    if resolved['missing']:
        raise ValueError('OTA_STORE_COLLECTOR_TARGET_MISSING')
    store = OtaStore(resolved['unified_database'])
    try:
        store.conn.execute('BEGIN IMMEDIATE')
        store.import_mail(directory)
        store.conn.commit()
    finally:
        store.close()


def collect(client, directory: Path, now: datetime | None = None) -> dict:
    """마지막 수집 이후 메일을 새 파일로 저장하고 collection.json을 갱신한다. 이미 받은 메일은 다시 받지 않는다."""
    directory = Path(directory)
    now = now or datetime.now()
    state_path = directory / 'collection.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.is_file() else {}
    known = set(state.get('message_ids', []))
    start = state.get('before') or '2026-04-01'
    after = (date.fromisoformat(start) - timedelta(days=OVERLAP_DAYS)).isoformat()
    query = build_query(after)
    assert all(f'to:{address}' in query for address in ALWAYS_RECIPIENTS), 'always-collected recipient missing from query'
    listed = client.list_ids(query)
    stored = stored_ids(directory)
    fresh = [message_id for message_id in listed if message_id not in known and message_id not in stored]
    messages = [client.get_full(message_id) for message_id in fresh]
    if messages:
        stamp = now.strftime('%Y%m%dT%H%M%S')
        (directory / f'gmail-auto-{stamp}.json').write_text(
            json.dumps({'responses': messages}, ensure_ascii=False), encoding='utf-8')
    state.update({
        'account': state.get('account', 'kkokkohero6@gmail.com'),
        'after': after, 'before': now.date().isoformat(), 'query': query,
        'query_exhausted': True, 'fetched': len(messages),
        'matched_message_count': len(listed),
        'message_ids': sorted(known | set(listed)),
        'last_run': now.isoformat(timespec='seconds'),
    })
    temp = state_path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, state_path)
    sync_unified_store(directory)
    return {'matched': len(listed), 'fetched': len(messages), 'query': query}


def owner_record(message_id: str, headers: dict, body: str) -> dict:
    """소유자 Gmail MCP로 읽은 메일을 저장 형식으로 만든다. 발신 인증 헤더는 없고 owner_collected로 표시한다."""
    from base64 import urlsafe_b64encode
    from email.utils import parsedate_to_datetime
    names = ('From', 'To', 'Cc', 'Date', 'Subject', 'Message-Id')
    found = [{'name': name, 'value': headers[name]} for name in names if headers.get(name)]
    try:
        internal = int(parsedate_to_datetime(headers.get('Date', '')).timestamp() * 1000)
    except (TypeError, ValueError):
        internal = None
    data = urlsafe_b64encode(body.encode('utf-8')).decode('ascii')
    return {'id': message_id, 'internal_date': str(internal) if internal else None, 'owner_collected': True,
            'payload': {'headers': found, 'mime_type': 'text/plain', 'body': {'data': data}}}


def owner_raw_record(message_id: str, raw: str, *, internal_date=None) -> dict:
    """소유자 연결에서 받은 원본 MIME의 문자셋을 보존해 예약 근거로 만든다."""
    from base64 import urlsafe_b64decode
    from email import policy
    from email.parser import BytesParser

    message = BytesParser(policy=policy.default).parsebytes(
        urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))

    def part_payload(part):
        payload = {'mime_type': part.get_content_type(),
                   'headers': [{'name': name, 'value': str(value)} for name, value in part.items()]}
        if part.is_multipart():
            payload['parts'] = [part_payload(child) for child in part.iter_parts()]
        elif part.get_content_maintype() == 'text' and part.get_content_disposition() != 'attachment':
            data = part.get_payload(decode=True) or b''
            payload['body'] = {'content': data.decode(part.get_content_charset() or 'utf-8', errors='strict')}
        return payload

    return {'id': message_id, 'internal_date': internal_date, 'owner_collected': True,
            'raw': raw, 'payload': part_payload(message)}


def write_owner_batch(directory: Path, records: list, now: datetime) -> Path | None:
    """owner_record로 만든 메일을 새 파일로 쓰고 collection.json의 수집 ID 목록에 더한다."""
    directory = Path(directory)
    state_path = directory / 'collection.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.is_file() else {}
    known = set(state.get('message_ids', []))
    fresh = [record for record in records if record['id'] not in known]
    if not fresh:
        sync_unified_store(directory)
        return None
    path = directory / f'gmail-owner-{now.strftime("%Y%m%dT%H%M%S")}.json'
    path.write_text(json.dumps({'responses': fresh}, ensure_ascii=False), encoding='utf-8')
    state['message_ids'] = sorted(known | {record['id'] for record in fresh})
    state['last_owner_run'] = now.isoformat(timespec='seconds')
    temp = state_path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, state_path)
    sync_unified_store(directory)
    return path


SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'


def authorization_url(client_id: str, redirect_uri: str) -> str:
    query = urllib.parse.urlencode({'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
                                    'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent'})
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + query


def authorize(client_file: Path, token_file: Path, port: int = 8765, timeout: int = 600) -> None:
    """루프백 주소로 승인 코드를 받아 갱신 토큰을 저장한다. 토큰 값은 출력하지 않는다."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    client = json.loads(Path(client_file).read_text(encoding='utf-8'))['installed']
    redirect_uri = f'http://127.0.0.1:{port}/'
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            received.update(params)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('승인이 끝났습니다. 이 창을 닫아도 됩니다.'.encode('utf-8'))

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = timeout
    print('승인 주소:', authorization_url(client['client_id'], redirect_uri), flush=True)
    while 'code' not in received and 'error' not in received:
        server.handle_request()
    server.server_close()
    if 'error' in received:
        raise RuntimeError('authorization refused: ' + received['error'])
    body = urllib.parse.urlencode({'client_id': client['client_id'], 'client_secret': client['client_secret'],
                                   'code': received['code'], 'grant_type': 'authorization_code',
                                   'redirect_uri': redirect_uri}).encode()
    with urllib.request.urlopen(client['token_uri'], body, timeout=30) as response:
        token = json.loads(response.read())
    if 'refresh_token' not in token:
        raise RuntimeError('no refresh token returned')
    Path(token_file).write_text(json.dumps({'refresh_token': token['refresh_token'], 'scope': token.get('scope', SCOPE)}),
                                encoding='utf-8')
    print('토큰 저장 완료', flush=True)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='예약 메일 상시 수집')
    parser.add_argument('--directory')
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--client-file', required=True)
    parser.add_argument('--authorize', action='store_true')
    args = parser.parse_args(argv)
    if args.authorize:
        authorize(Path(args.client_file), Path(args.token_file))
        return 0
    client = GmailApi(args.token_file, args.client_file)
    result = collect(client, Path(args.directory))
    print(f"matched {result['matched']} fetched {result['fetched']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
