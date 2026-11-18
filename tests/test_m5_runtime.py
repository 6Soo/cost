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


@pytest.mark.parametrize('web_args', [
    ['--port', '8751'],
    ['--port=8790'],
    ['--host', '127.0.0.1', '--port', '8752'],
    # argparse 접두 축약: `--po 8751`이 `--port`로 해석된다.
    ['--p', '8751'],
    ['--po', '8752'],
    ['--por=8790'],
    # 공백이 섞인 값.
    ['--port', ' 8751 '],
    ['--port', '8751\n'],
])
def test_web_runtime_arguments_cannot_bypass_the_reserved_ports(service, web_args):
    _, _, _, config = service
    with pytest.raises(runtime.RuntimeErrorCode, match='SERVER_QUEUE_PORT_RESERVED'):
        runtime.make_server(dict(config, web_args=web_args), 'synthetic-executable')


def test_argparse_really_abbreviates_the_port_flag(service):
    """검사가 막는 축약형이 실제로 웹 런타임에서 `--port`로 해석됨을 근거로 고정한다."""
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--port', type=int)
    for shape in (['--p', '8751'], ['--po', '8751'], ['--por=8751']):
        assert parser.parse_args(shape).port == 8751
    # 짧은 단일 문자 축약은 없으므로 `-p`는 거부된다(검사 대상 아님).
    with pytest.raises(SystemExit):
        parser.parse_args(['-p', '8751'])


@pytest.mark.parametrize('web_args', [
    ['--port', '0'],
    ['--port=60204'],
    ['--port', 'not-a-number'],
    ['--report-port', '8751'],
    ['--behind-proxy', '--environment', 'local-synthetic'],
])
def test_non_reserved_web_arguments_are_allowed(service, web_args):
    _, _, _, config = service
    assert runtime.reserved_port_argument(web_args) == []
    server = runtime.make_server(dict(config, port=0, web_args=web_args), 'synthetic-executable')
    server.server_close()


def test_web_runtime_environment_port_is_reported_not_silently_trusted(monkeypatch):
    """`PORT` 환경변수는 argv 검사를 우회할 수 있으므로 한계를 있는 그대로 고정한다.

    서버 자신의 포트는 이미 예약 포트를 거부한다. 웹 런타임이 자식 프로세스로 받는 `PORT`는
    이 검사가 보지 못하므로, 설정의 `web_args`로는 줄 수 없고 배포 환경에서만 의미가 있다.
    검사는 그 사실을 `reserved_port_argument`가 다루지 않는다고 명시해 둔다.
    """
    assert runtime.reserved_port_argument(['--po', '8751']) == [8751]
    monkeypatch.setenv('PORT', '8751')
    # argv 기반 검사는 환경변수를 신뢰하지도, 검사하지도 않는다(오탐 금지).
    assert runtime.reserved_port_argument(['--environment', 'local-synthetic']) == []


def test_non_list_web_arguments_are_rejected(service):
    _, _, _, config = service
    with pytest.raises(runtime.RuntimeErrorCode, match='SERVER_WEB_ARGS_INVALID'):
        runtime.make_server(dict(config, web_args='--port 8751'), 'synthetic-executable')


@pytest.mark.parametrize('value', ['8751', '8752', '8790', ' 8751 '])
def test_inherited_port_environment_is_refused(service, monkeypatch, value):
    """argv 검사를 통과해도 상속된 PORT가 예약 포트면 서버가 시작되지 않는다."""
    _, _, _, config = service
    monkeypatch.setenv('PORT', value)
    with pytest.raises(runtime.RuntimeErrorCode, match='SERVER_WEB_PORT_RESERVED'):
        runtime.make_server(dict(config, web_args=['--port', '0']), 'synthetic-executable')


@pytest.mark.parametrize('value', [None, '', '7420', '0', 'not-a-number'])
def test_non_reserved_port_environment_still_starts(service, monkeypatch, value):
    _, _, _, config = service
    if value is None:
        monkeypatch.delenv('PORT', raising=False)
    else:
        monkeypatch.setenv('PORT', value)
    server = runtime.make_server(dict(config, port=0, web_args=['--port', '0']),
                                 'synthetic-executable')
    server.server_close()


@pytest.mark.parametrize('web_args', [['--port', '0'], [], ['--environment', 'local-synthetic']])
def test_web_child_environment_never_keeps_a_reserved_inherited_port(web_args):
    child = runtime.web_child_environment({'PORT': '8751', 'KEEP': 'yes'}, web_args)
    assert child['KEEP'] == 'yes', '관련 없는 환경은 보존한다'
    assert runtime.reserved_environment_port(child['PORT']) is None
    assert child['PORT'] == '0'


def test_web_child_environment_preserves_an_explicit_safe_port():
    child = runtime.web_child_environment({'PORT': '8752'}, ['--po', '60204'])
    assert child['PORT'] == '60204'


def test_server_launch_passes_a_controlled_environment_to_the_web_child(monkeypatch):
    """실제 `Popen` 호출부가 env를 넘기는지 근거로 고정한다(상속 PORT 무력화 경로)."""
    import inspect
    source = inspect.getsource(runtime.main)
    assert 'env=web_child_environment(os.environ' in source


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


@pytest.mark.parametrize('code,failure', [
    ('AGENT_RATE_LIMITED', 'capacity'),
    ('AGENT_AUTH_REQUIRED', 'authentication'),
    ('AGENT_TOOL_EXECUTION_DETECTED', 'tool'),
    ('AGENT_TIMEOUT', 'transient'),
    ('P2_EXECUTION_FAILED', 'transient'),
])
def test_node_once_classifies_execution_failures_for_the_queue(code, failure):
    token = {'job_id': 1, 'owner': 'node-a', 'generation': 1}

    class Client:
        def __init__(self):
            self.failed = []
        def call(self, body):
            if body['operation'] == 'claim':
                return {'job': {'token': token, 'payload': {}}}
            self.failed.append(body)
            return {'state': 'queued'}

    client = Client()

    def execute(payload):
        raise runtime.RuntimeErrorCode(code)

    assert runtime.node_once(client, execute) == {'claimed': 1, 'failed': 1}
    expected = {'operation': 'fail', 'token': token, 'failure': failure}
    # 노드는 대기 시각 키를 지어내지 않는다. 없으면 서버 코어의 유일한 정책 상수가 적용된다.
    assert client.failed == [expected]


def test_node_once_forward_capacity_retry_after_from_the_provider():
    token = {'job_id': 1, 'owner': 'node-a', 'generation': 1}

    class Client:
        def __init__(self):
            self.failed = []
        def call(self, body):
            if body['operation'] == 'claim':
                return {'job': {'token': token, 'payload': {}}}
            self.failed.append(body)
            return {'state': 'queued'}

    client = Client()

    def execute(payload):
        raise runtime.RuntimeErrorCode('AGENT_RATE_LIMITED', retry_after=1800)

    assert runtime.node_once(client, execute) == {'claimed': 1, 'failed': 1}
    assert client.failed == [{'operation': 'fail', 'token': token, 'failure': 'capacity',
                             'retry_after_seconds': 1800}]


@pytest.mark.parametrize('delay', [None, 0, -5, '1800', True, 1.5])
def test_node_once_omits_unusable_provider_delays_so_the_server_owns_the_default(delay):
    token = {'job_id': 1, 'owner': 'node-a', 'generation': 1}

    class Client:
        def __init__(self):
            self.failed = []
        def call(self, body):
            if body['operation'] == 'claim':
                return {'job': {'token': token, 'payload': {}}}
            self.failed.append(body)
            return {'state': 'queued'}

    client = Client()

    def execute(payload):
        raise runtime.RuntimeErrorCode('AGENT_RATE_LIMITED', retry_after=delay)

    assert runtime.node_once(client, execute) == {'claimed': 1, 'failed': 1}
    # 파이썬 쪽에 기본값 상수를 두지 않는다: 키 생략 → Rust 코어 상수만이 기본값 출처다.
    assert client.failed == [{'operation': 'fail', 'token': token, 'failure': 'capacity'}]
    assert not hasattr(runtime, 'DEFAULT_CAPACITY_RETRY_SECONDS')


def test_node_once_lease_lost_mid_execution_sends_neither_complete_nor_fail(monkeypatch):
    original_event = threading.Event
    heartbeat_fired = original_event()

    class FastStop:
        def __init__(self):
            self._real = original_event()
            self._first = True
        def wait(self, timeout=None):
            if timeout == 60 and self._first:
                self._first = False
                return False
            return self._real.wait(timeout)
        def set(self):
            self._real.set()
        def is_set(self):
            return self._real.is_set()

    monkeypatch.setattr(runtime.threading, 'Event', FastStop)
    token = {'job_id': 1, 'owner': 'node-a', 'generation': 1}

    class Client:
        def __init__(self):
            self.calls = []
        def call(self, body):
            self.calls.append(body)
            if body['operation'] == 'claim':
                return {'job': {'token': token, 'payload': {}}}
            if body['operation'] == 'heartbeat':
                heartbeat_fired.set()
                raise runtime.RuntimeErrorCode('NODE_LEASE_LOST')
            pytest.fail('complete/fail must not be sent after the lease is lost')

    client = Client()

    def execute(payload):
        assert heartbeat_fired.wait(5), 'heartbeat did not fire'
        return {'runner': 'replay', 'answer': {'synthetic': True}}

    with pytest.raises(runtime.RuntimeErrorCode, match='NODE_LEASE_LOST'):
        runtime.node_once(client, execute)
    assert [body['operation'] for body in client.calls] == ['claim', 'heartbeat']


@pytest.mark.parametrize('content', ['short', 'a' * 31, 'a' * 257, '한글토큰' + 'a' * 40, 'a' * 32 + ' b'])
def test_token_from_rejects_invalid_content(tmp_path, content):
    file = tmp_path / 'token'
    file.write_text(content, encoding='utf-8')
    with pytest.raises(runtime.RuntimeErrorCode, match='NODE_CREDENTIAL_INVALID'):
        runtime.token_from(file)


def test_token_from_rejects_relative_path_and_non_file(tmp_path):
    with pytest.raises(runtime.RuntimeErrorCode, match='NODE_CREDENTIAL_INVALID'):
        runtime.token_from('relative-token')
    with pytest.raises(runtime.RuntimeErrorCode, match='NODE_CREDENTIAL_INVALID'):
        runtime.token_from(tmp_path)
    file = tmp_path / 'token'
    file.write_text('synthetic-' + 'a' * 40 + '\n', encoding='utf-8')
    assert runtime.token_from(file) == 'synthetic-' + 'a' * 40


def valid_config(tmp_path):
    core = tmp_path / 'core.sqlite'
    sqlite3.connect(core).close()
    token = tmp_path / 'token'
    token.write_text('synthetic-' + 'a' * 40, encoding='utf-8')
    token.chmod(0o600)
    return {'core_db': str(core), 'port': 0, 'nodes': {'node-a': {
        'token_file': str(token), 'kinds': ['p2_merchant'], 'daily_budget_limit': 3}}}


def test_server_rejects_invalid_core_path_and_bind(tmp_path):
    config = valid_config(tmp_path)
    with pytest.raises(runtime.RuntimeErrorCode, match='CORE_PATH_INVALID'):
        runtime.make_server(dict(config, core_db='relative.sqlite'), 'synthetic-executable')
    with pytest.raises(runtime.RuntimeErrorCode, match='CORE_PATH_INVALID'):
        runtime.make_server(dict(config, core_db=str(tmp_path / 'missing.sqlite')), 'synthetic-executable')
    with pytest.raises(runtime.RuntimeErrorCode, match='SERVER_BIND_INVALID'):
        runtime.make_server(dict(config, bind='not-an-ip'), 'synthetic-executable')


def test_server_rejects_invalid_node_identities_kinds_and_budgets(tmp_path):
    config = valid_config(tmp_path)
    spec = config['nodes']['node-a']
    with pytest.raises(runtime.RuntimeErrorCode, match='NODE_ID_INVALID'):
        runtime.make_server(dict(config, nodes={'bad name!': spec}), 'synthetic-executable')
    with pytest.raises(runtime.RuntimeErrorCode, match='NODE_KINDS_INVALID'):
        runtime.make_server(dict(config, nodes={'node-a': dict(spec, kinds=['p1'])}), 'synthetic-executable')
    for cap in (31, -1, '3', True):
        with pytest.raises(runtime.RuntimeErrorCode, match='NODE_BUDGET_INVALID'):
            runtime.make_server(dict(config, nodes={'node-a': dict(spec, daily_budget_limit=cap)}),
                                'synthetic-executable')
    with pytest.raises(runtime.RuntimeErrorCode, match='NODES_INVALID'):
        runtime.make_server(dict(config, nodes={}), 'synthetic-executable')


def test_server_rejects_duplicate_node_credentials(tmp_path):
    config = valid_config(tmp_path)
    spec = config['nodes']['node-a']
    with pytest.raises(runtime.RuntimeErrorCode, match='NODE_CREDENTIAL_DUPLICATE'):
        runtime.make_server(dict(config, nodes={'node-a': spec, 'node-b': dict(spec)}),
                            'synthetic-executable')


def test_client_download_limit_must_be_a_positive_int(tmp_path):
    token = tmp_path / 'token'
    token.write_text('synthetic-' + 'a' * 40, encoding='utf-8')
    token.chmod(0o600)
    for limit in (0, -1, True, '1024'):
        with pytest.raises(runtime.RuntimeErrorCode, match='NODE_DOWNLOAD_LIMIT_INVALID'):
            runtime.Client('https://example.com', token, max_download_bytes=limit)
