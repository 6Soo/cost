import copy
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from app.reservation_authority import (SCHEMA, TOKEN_ENV, TOKEN_FILE_ENV, AuthorityUnavailable,
                                       authority_digest, configured_token, fetch_authority,
                                       fetch_passenger_candidates)
from app.flight_passenger_matching import (build_user_assignment, candidate_matches,
                                           match_booking_passengers)

GUIDES_PATH = '/api/internal/guides'
TOURS_PATH = '/api/internal/tours?include_past=1'
GUIDE_1 = {'id': 1, 'nickname': 'alpha', 'real_name': '합성가이드A', 'flight_name_en': 'ALPHA/TEST',
           'status': 'active', 'phone': '010-1111-2222'}
GUIDE_2 = {'id': 2, 'nickname': 'beta', 'real_name': None, 'flight_name_en': None,
           'status': 'inactive', 'phone': '010-3333-4444'}
TOUR_1 = {'fldid': 't1', 'code': '1010_SYN', 'title': '합성 여행 1', 'leader': 'alpha', 'leader_guide_id': 1,
          'depart_date': '2026-10-20', 'return_date': '2026-10-23', 'capacity': 20, 'status': 'scheduled'}
TOUR_2 = {'fldid': 't2', 'code': None, 'title': '합성 여행 2', 'leader': None, 'leader_guide_id': None,
          'depart_date': None, 'return_date': None, 'capacity': None, 'status': 'planned', 'phone': 'x'}
GUIDES_OK = {'guides': [GUIDE_1, GUIDE_2]}
TOURS_OK = {'tours': [TOUR_1, TOUR_2]}


class _State:
    def __init__(self):
        self.routes = {}
        self.requests = []

    def set(self, path, payload=None, *, status=200, raw=None, delay=0, location=None):
        body = raw if raw is not None else json.dumps(payload if payload is not None else {}).encode('utf-8')
        self.routes[path] = {'status': status, 'body': body, 'delay': delay, 'location': location}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        state = self.server.state
        state.requests.append((self.path, self.headers.get('Authorization')))
        route = state.routes.get(self.path, {'status': 404, 'body': b'{}', 'delay': 0, 'location': None})
        if route['delay']:
            time.sleep(route['delay'])
        self.send_response(route['status'])
        if route['location']:
            self.send_header('Location', route['location'])
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(route['body'])))
        self.end_headers()
        try:
            self.wfile.write(route['body'])
        except OSError:
            pass

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    httpd.state = _State()
    httpd.state.set(GUIDES_PATH, copy.deepcopy(GUIDES_OK))
    httpd.state.set(TOURS_PATH, copy.deepcopy(TOURS_OK))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.state, f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()
    httpd.server_close()


def _expect(base, code, token='tok', **kwargs):
    with pytest.raises(AuthorityUnavailable) as info:
        fetch_authority(base, token, **kwargs)
    assert info.value.code == code
    return info.value


def test_success_sends_bearer_and_drops_extra_keys(server):
    state, base = server
    result = fetch_authority(base, 'tok-123')
    assert result['schema'] == SCHEMA
    assert [g['id'] for g in result['guides']] == [1, 2]
    assert [t['fldid'] for t in result['tours']] == ['t1', 't2']
    assert result['digest'] == authority_digest(result)
    assert set(result['guides'][0]) == {'id', 'nickname', 'real_name', 'flight_name_en', 'status'}
    assert set(result['tours'][0]) == {'fldid', 'code', 'title', 'leader', 'leader_guide_id',
                                       'depart_date', 'return_date', 'status'}
    assert {auth for _, auth in state.requests} == {'Bearer tok-123'}
    dumped = json.dumps(result, ensure_ascii=False)
    assert 'phone' not in dumped and '010-' not in dumped and 'capacity' not in dumped


def test_read_only_passenger_candidates_are_minimized_and_bound_to_requested_tour(server):
    state, base = server
    state.set('/api/internal/passenger-candidates?tourFldid=t1', {
        'tour_id': 't1', 'source_revision': 'roster-v7',
        'candidates': [{'kind': 'lead', 'reference_id': 'opaque-a', 'name_kr': '김알파',
                        'name_en': 'KIM/ALPHA', 'status': 'active', 'phone': 'private'}]})
    result = fetch_passenger_candidates('t1', base, 'tok-passenger')
    assert result == {'tour_id': 't1', 'source_revision': 'roster-v7', 'candidates': [
        {'kind': 'lead', 'reference_id': 'opaque-a', 'name_kr': '김알파',
         'name_en': 'KIM/ALPHA', 'status': 'active'}]}
    assert state.requests[-1] == ('/api/internal/passenger-candidates?tourFldid=t1',
                                  'Bearer tok-passenger')
    assert 'phone' not in json.dumps(result)


def test_passenger_candidates_require_exact_unique_english_identity_only():
    passenger = {'surname': 'KIM', 'given_name': 'JI-WON'}
    candidates = [
        {'kind': 'lead', 'reference_id': 'opaque-a', 'name_kr': '김지원', 'name_en': 'KIM/JI WON'},
        {'kind': 'companion', 'reference_id': 'opaque-b', 'name_kr': '김지언', 'name_en': 'KIM/JI WON'},
        {'kind': 'guide', 'reference_id': 'opaque-c', 'name_kr': '이알파', 'name_en': 'LEE/ALPHA'},
    ]
    result = candidate_matches(passenger, candidates)
    assert result['status'] == 'AMBIGUOUS'
    assert [item['reference_id'] for item in result['candidates']] == ['opaque-b', 'opaque-a']
    hangul_only = candidate_matches(passenger, [{'kind': 'lead', 'reference_id': 'opaque-d',
                                                  'name_kr': '김지원', 'name_en': None}])
    assert hangul_only['status'] == 'UNMATCHED'


def test_booking_passengers_remain_unconfirmed_candidates_and_are_source_scoped():
    evidence = {'booking_ref': 'SYNTH-100', 'source_digests': ['sha-mail-a'],
                'passengers': [{'surname': 'KIM', 'given_name': 'ALPHA'}]}
    authority = {'tour_id': 'tour-a', 'source_revision': 'roster-2', 'candidates': [
        {'kind': 'lead', 'reference_id': 'opaque-a', 'name_kr': '김알파',
         'name_en': 'KIM/ALPHA', 'status': 'active'}]}
    result = match_booking_passengers(evidence, authority)
    passenger = result['passengers'][0]
    assert passenger['status'] == 'EXACT_CANDIDATE'
    assert passenger['assignment_status'] == 'PENDING_USER_CONFIRMATION'
    assert passenger['confirmed'] is False
    assert passenger['actual_boarding_confirmed'] is False
    assert passenger['source_digests'] == ['sha-mail-a']
    assert match_booking_passengers(evidence, authority)['passengers'][0]['proposal_id'] == passenger['proposal_id']


def test_manual_passenger_assignment_requires_current_explicit_candidate_and_never_confirms_boarding():
    evidence = {'booking_ref': 'SYNTH-101', 'source_digests': ['sha-mail-b'],
                'passengers': [{'surname': 'KIM', 'given_name': 'ALPHA'}]}
    authority = {'tour_id': 'tour-b', 'source_revision': 'roster-v8', 'candidates': [
        {'kind': 'lead', 'reference_id': 'opaque-lead', 'name_kr': '김알파',
         'name_en': 'KIM/ALPHA', 'status': 'active'}]}
    proposal = match_booking_passengers(evidence, authority)['passengers'][0]
    with pytest.raises(ValueError, match='PASSENGER_CANDIDATES_STALE'):
        build_user_assignment(proposal, candidate_reference_id='opaque-lead', actor='owner',
                              current_source_revision='roster-v9')
    assignment = build_user_assignment(proposal, candidate_reference_id='opaque-lead', actor='owner',
                                       current_source_revision='roster-v8')
    assert assignment['assignment_status'] == 'USER_ASSIGNED'
    assert assignment['confirmed'] is True
    assert assignment['actual_boarding_confirmed'] is False
    assert assignment['assignment_id'] == build_user_assignment(
        proposal, candidate_reference_id='opaque-lead', actor='owner',
        current_source_revision='roster-v8')['assignment_id']


def test_digest_stable_across_fetches_and_reordered_source(server):
    state, base = server
    first = fetch_authority(base, 'tok')
    assert fetch_authority(base, 'tok')['digest'] == first['digest']
    state.set(GUIDES_PATH, {'guides': list(reversed(GUIDES_OK['guides']))})
    state.set(TOURS_PATH, {'tours': list(reversed(TOURS_OK['tours']))})
    assert fetch_authority(base, 'tok')['digest'] == first['digest']


@pytest.mark.parametrize('status, code', [(401, 'unauthorized'), (403, 'unauthorized'), (500, 'unavailable')])
def test_http_errors_map_to_codes(server, status, code):
    state, base = server
    state.set(GUIDES_PATH, status=status)
    _expect(base, code)


def test_redirect_is_not_followed(server):
    state, base = server
    state.set(GUIDES_PATH, status=302, location='/elsewhere')
    _expect(base, 'redirected')


def test_connection_refused_is_unavailable():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    _expect(f'http://127.0.0.1:{port}', 'unavailable')


def test_slow_server_times_out(server):
    state, base = server
    state.set(GUIDES_PATH, GUIDES_OK, delay=2)
    _expect(base, 'timeout', timeout=0.5)


MALFORMED = [
    pytest.param(GUIDES_PATH, None, id='non-json'),
    pytest.param(GUIDES_PATH, {'guides': {'id': 1}}, id='guides-not-list'),
    pytest.param(GUIDES_PATH, {'guides': [dict(GUIDE_1, id='1')]}, id='guide-id-string'),
    pytest.param(GUIDES_PATH, {'guides': [GUIDE_1, dict(GUIDE_2, id=1)]}, id='guide-id-duplicated'),
    pytest.param(TOURS_PATH, {'tours': [dict(TOUR_1, leader_guide_id=99)]}, id='tour-unknown-leader'),
    pytest.param(TOURS_PATH, {'tours': [dict(TOUR_1, depart_date='2026-13-01')]}, id='tour-bad-date'),
    pytest.param(TOURS_PATH, {'tours': [TOUR_1, dict(TOUR_2, fldid='t1')]}, id='tour-fldid-duplicated'),
]


@pytest.mark.parametrize('path, payload', MALFORMED)
def test_malformed_payloads_fail_closed(server, path, payload):
    state, base = server
    if payload is None:
        state.set(path, raw=b'not json')
    else:
        state.set(path, payload)
    _expect(base, 'malformed')


@pytest.mark.parametrize('path, payload, code', [
    pytest.param(GUIDES_PATH, {'guides': []}, 'empty', id='empty-guides'),
    pytest.param(TOURS_PATH, {'tours': []}, 'empty', id='empty-tours'),
])
def test_empty_lists_fail_closed(server, path, payload, code):
    state, base = server
    state.set(path, payload)
    _expect(base, code)


def test_oversized_body_is_malformed():
    class Response:
        status = 200

        def read(self, size=-1):
            return (b' ' * 2_000_001)[:size]

        def close(self):
            pass

    _expect('https://reserve.example.test', 'malformed', opener=lambda request, timeout: Response())


def test_injected_opener_receives_request_and_timeout():
    seen = []
    bodies = {'guides': json.dumps(GUIDES_OK).encode(), 'tours': json.dumps(TOURS_OK).encode()}

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self, size=-1):
            return self.body[:size]

        def close(self):
            pass

    def opener(request, timeout):
        seen.append((request.full_url, request.get_header('Authorization'), timeout))
        return Response(bodies['guides' if 'guides' in request.full_url else 'tours'])

    result = fetch_authority('https://reserve.example.test/', 'tok', timeout=3, opener=opener)
    assert [s[0] for s in seen] == ['https://reserve.example.test/api/internal/guides',
                                    'https://reserve.example.test/api/internal/tours?include_past=1']
    assert {s[1] for s in seen} == {'Bearer tok'} and {s[2] for s in seen} == {3}
    assert len(result['guides']) == 2


def test_missing_token_makes_no_request(server, monkeypatch):
    state, base = server
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(TOKEN_FILE_ENV, raising=False)
    _expect(base, 'not_configured', token='')
    _expect(base, 'not_configured', token=None)
    assert state.requests == []


@pytest.mark.parametrize('base', ['http://reserve.example.test', 'ftp://reserve.example.test', 'https://'])
def test_non_https_remote_base_is_not_configured(base):
    _expect(base, 'not_configured')


def test_configured_token_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(TOKEN_FILE_ENV, raising=False)
    default = tmp_path / 'default.txt'
    default.write_text('  deftok  \nignored\n', encoding='utf-8')
    file_env = tmp_path / 'env.txt'
    file_env.write_text(' filetok \n', encoding='utf-8')
    assert configured_token(default) == 'deftok'
    monkeypatch.setenv(TOKEN_FILE_ENV, str(file_env))
    assert configured_token(default) == 'filetok'
    monkeypatch.setenv(TOKEN_ENV, '  envtok  ')
    assert configured_token(default) == 'envtok'
    monkeypatch.setenv(TOKEN_ENV, '   ')
    assert configured_token(default) == 'filetok'
    monkeypatch.setenv(TOKEN_FILE_ENV, str(tmp_path / 'missing.txt'))
    assert configured_token(default) == 'deftok'
    assert configured_token(tmp_path / 'missing2.txt') == ''
    assert configured_token() == ''


def test_error_text_never_contains_token(server):
    state, base = server
    token = 'secret-token-do-not-leak'
    state.set(GUIDES_PATH, status=401)
    with pytest.raises(AuthorityUnavailable) as info:
        fetch_authority(base, token)
    assert token not in str(info.value) and token not in repr(info.value)
    state.set(GUIDES_PATH, {'guides': {}})
    with pytest.raises(AuthorityUnavailable) as info:
        fetch_authority(base, token)
    assert token not in str(info.value) and token not in repr(info.value)
