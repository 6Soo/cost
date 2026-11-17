"""Synthetic transport tests; no credentials, external networks or models."""
import json
from pathlib import Path
import sqlite3
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tools import m5_runtime as runtime


@pytest.fixture
def service(tmp_path, monkeypatch):
    core = tmp_path / 'core.sqlite'
    sqlite3.connect(core).close()
    token = tmp_path / 'token'
    token.write_text('synthetic-' + 'a' * 40, encoding='utf-8')
    token.chmod(0o600)
    config = {'core_db': str(core), 'port': 0, 'nodes': {'node-a': {
        'token_file': str(token), 'kinds': ['p2_merchant'], 'daily_budget_limit': 3}}}
    calls = []
    def core_call(binary, path, body):
        calls.append(body)
        return {'job': None} if body['operation'] == 'claim' else {'state': 'succeeded'}
    monkeypatch.setattr(runtime, 'core_call', core_call)
    server = runtime.make_server(config, 'synthetic-executable')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        yield base, token, calls, config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_no_node_listener_and_authenticated_identity_is_server_selected(service):
    base, token, calls, _ = service
    client = runtime.Client(base, token, allow_loopback_http=True)
    assert runtime.node_once(client, lambda _: pytest.fail('nothing was queued')) == {'claimed': 0}
    assert calls == [{'operation': 'claim', 'owner': 'node-a', 'kinds': ['p2_merchant'],
                      'daily_budget_limit': 3, 'lease_seconds': 300}]


def test_unauthenticated_and_override_requests_never_reach_core(service):
    base, token, calls, _ = service
    request = Request(base + '/v1/queue', data=b'{"operation":"claim"}', method='POST')
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 401
    client = runtime.Client(base, token, allow_loopback_http=True)
    for body in ({'operation': 'claim', 'owner': 'other'}, {'operation': 'enqueue'},
                 {'operation': 'status', 'job_id': 1},
                 {'operation': 'heartbeat', 'token': {'job_id': 1, 'owner': 'other', 'generation': 1}}):
        with pytest.raises(runtime.RuntimeErrorCode, match='NODE_REQUEST_REFUSED'):
            client.call(body)
    assert calls == []


@pytest.mark.parametrize('url', ['http://example.com', 'http://localhost',
    'https://name:password@example.com', 'https://example.com?token=secret',
    'https://example.com/elsewhere', 'https://example.com#secret'])
def test_tls_and_url_constraints(service, url):
    _, token, _, _ = service
    with pytest.raises(runtime.RuntimeErrorCode):
        runtime.Client(url, token, allow_loopback_http=True)


def test_server_public_bind_requires_tls_and_reserved_ports_are_refused(service):
    _, _, _, config = service
    with pytest.raises(runtime.RuntimeErrorCode, match='SERVER_TLS_REQUIRED'):
        runtime.make_server(dict(config, bind='0.0.0.0'), 'synthetic-executable')
    with pytest.raises(runtime.RuntimeErrorCode, match='SERVER_QUEUE_PORT_RESERVED'):
        runtime.make_server(dict(config, port=8751), 'synthetic-executable')


def test_lost_completion_response_resends_identical_result_without_rerunning():
    class Client:
        def __init__(self):
            self.completed = []
        def call(self, body):
            if body['operation'] == 'claim':
                return {'job': {'token': {'job_id': 1, 'owner': 'node-a', 'generation': 1}, 'payload': {}}}
            self.completed.append(body)
            if len(self.completed) == 1:
                raise runtime.RuntimeErrorCode('NODE_CONNECTION_FAILED')
            return {'state': 'succeeded'}
    calls = []
    client = Client()
    result = {'runner': 'replay', 'answer': {'synthetic': True}}
    assert runtime.node_once(client, lambda payload: calls.append(payload) or result) == {'claimed': 1, 'succeeded': 1}
    assert len(calls) == 1
    assert client.completed[0] == client.completed[1]
