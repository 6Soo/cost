"""Real Rust queue + HTTP + subprocess node, entirely on synthetic files."""
from contextlib import contextmanager
import datetime
import ipaddress
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest

from tools import m5_backup, m5_runtime, m5_p2_adapter

pytestmark = pytest.mark.costcore_bin
ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def start_server(config, binary, scheme='http'):
    server = m5_runtime.make_server(config, binary)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'{scheme}://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def raw_post(base, token_text, body):
    request = Request(base + '/v1/queue', data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                      headers={'Authorization': 'Bearer ' + token_text,
                               'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def self_signed_cert(tmp_path):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName('localhost'),
                x509.IPAddress(ipaddress.IPv4Address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


def tls_request(port, request_bytes):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection(('127.0.0.1', port), timeout=10) as sock:
        with context.wrap_socket(sock, server_hostname='localhost') as tls:
            tls.sendall(request_bytes)
            chunks = []
            while block := tls.recv(65536):
                chunks.append(block)
    return b''.join(chunks)


@pytest.fixture
def two_nodes(binary, tmp_path):
    core = tmp_path / 'core.sqlite'
    command(binary, 'migrate', '--core', core)
    tokens, nodes = {}, {}
    for name in ('node-a', 'node-b'):
        token = tmp_path / f'token-{name}'
        token.write_text(f'synthetic-{name}-' + 'a' * 40, encoding='utf-8')
        token.chmod(0o600)
        tokens[name] = token
        nodes[name] = {'token_file': str(token), 'kinds': ['p2_merchant'], 'daily_budget_limit': 3}
    config = {'core_db': str(core), 'port': 0, 'allow_replay': True, 'nodes': nodes}
    with start_server(config, binary) as base:
        yield core, tokens, base, config


@pytest.fixture
def binary():
    value = os.environ.get('COSTCORE_TEST_BIN', '')
    assert value and Path(value).is_file(), 'Build costcore and set COSTCORE_TEST_BIN (no skipped verification)'
    return Path(value).resolve()


def command(binary, *args, body=None, env=None, check=True):
    done = subprocess.run([str(binary), *map(str, args)],
                          input=json.dumps(body or {}, ensure_ascii=False).encode('utf-8'),
                          capture_output=True, timeout=40, cwd=ROOT, env=env)
    if check:
        assert done.returncode == 0, done.stderr.decode('utf-8', errors='replace')
    return done


@pytest.fixture
def service(binary, tmp_path):
    core = tmp_path / 'core.sqlite'
    command(binary, 'migrate', '--core', core)
    token = tmp_path / 'token'
    token.write_text('synthetic-' + 'a' * 40, encoding='utf-8')
    token.chmod(0o600)
    with sqlite3.connect(core) as db:
        db.execute('CREATE TABLE synthetic_p1(id INTEGER PRIMARY KEY, value TEXT)')
        db.execute("INSERT INTO synthetic_p1 VALUES(1, 'published-before-node')")
    originals = tmp_path / 'originals'
    originals.mkdir()
    (originals / 'synthetic.eml').write_bytes(b'Subject: synthetic\r\n\r\noriginal bytes')
    snapshot = tmp_path / 'snapshot'
    m5_backup.create_snapshot({'core': core}, {'mail': originals}, snapshot)
    config = {'core_db': str(core), 'port': 0, 'allow_replay': True,
              'backup_snapshot': str(snapshot), 'nodes': {'node-a': {
                  'token_file': str(token), 'kinds': ['p2_merchant'],
                  'daily_budget_limit': 3, 'backup': True}}}
    server = m5_runtime.make_server(config, binary)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        yield core, token, base, snapshot, config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def prepared(binary):
    body = {'merchants': [{'merchant_id': 'synthetic-a'}], 'allowed_items': ['사무용품비'],
            'policy': '합성 규칙', 'run_id': 'abc123'}
    payload = json.loads(command(binary, 'p2', '--operation', 'prepare', body=body).stdout)['result']
    # The Python subscription boundary must accept the real Rust digest.
    m5_p2_adapter._bound_request(payload)
    answer = {'request_digest': payload['request_digest'], 'run_id': payload['run_id'], 'results': [
        {'merchant_id': 'synthetic-a', 'item': '사무용품비', 'confidence': '높음', 'basis': '합성 구매 근거'}]}
    return payload, answer


def test_real_node_completes_one_persisted_job_and_restores_reverse_backup(binary, service, tmp_path):
    core, token, base, snapshot, _ = service
    payload, answer = prepared(binary)
    queued = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'synthetic-a', 'budget_key': 'p2', 'payload': payload})
    # A job remains durable while no node process is running.
    with sqlite3.connect(core) as db:
        assert db.execute('SELECT state FROM jobs').fetchone()[0] == 'queued'
        assert db.execute('SELECT value FROM synthetic_p1').fetchone()[0] == 'published-before-node'
    replay = tmp_path / 'replay.json'
    replay.write_text(json.dumps(answer, ensure_ascii=False), encoding='utf-8')
    destination = tmp_path / 'node-backups'
    node_config = tmp_path / 'node.json'
    node_config.write_text(json.dumps({'server_url': base, 'token_file': str(token),
        'allow_loopback_http': True, 'runner': 'replay', 'replay_file': str(replay),
        'backup_destination': str(destination)}), encoding='utf-8')
    first = command(binary, 'node', '--repo-root', ROOT, '--python', sys.executable,
                    '--config', node_config, '--once')
    summaries = [json.loads(line) for line in first.stdout.splitlines()]
    assert summaries[-1] == {'ok': True, 'claimed': 1, 'succeeded': 1}
    assert summaries[0]['backup']['ok'] is True
    restored = destination / summaries[0]['backup']['generation']
    assert m5_backup.verify_snapshot(restored)['snapshot_id'] == m5_backup.verify_snapshot(snapshot)['snapshot_id']
    with sqlite3.connect(restored / 'databases/core.sqlite') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT value FROM synthetic_p1').fetchone()[0] == 'published-before-node'
    assert (restored / 'originals/mail/synthetic.eml').read_bytes() == b'Subject: synthetic\r\n\r\noriginal bytes'
    state = m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': queued['job_id']})
    assert state['state'] == 'succeeded'
    second = command(binary, 'node', '--repo-root', ROOT, '--python', sys.executable,
                     '--config', node_config, '--once')
    repeated = [json.loads(line) for line in second.stdout.splitlines()]
    assert repeated[0]['backup']['code'] == 'NOT_DUE'
    assert repeated[-1] == {'ok': True, 'claimed': 0}
    with sqlite3.connect(core) as db:
        assert db.execute('SELECT attempts FROM jobs').fetchone()[0] == 1
        assert db.execute('SELECT value FROM synthetic_p1').fetchone()[0] == 'published-before-node'


def test_backup_requires_credentials_and_cannot_read_outside_manifest(binary, service, tmp_path):
    _, token, base, _, _ = service
    with pytest.raises(HTTPError) as error:
        urlopen(base + '/v1/backup/manifest', timeout=5)
    assert error.value.code == 401
    client = m5_runtime.Client(base, token, allow_loopback_http=True)
    with pytest.raises(m5_runtime.RuntimeErrorCode):
        client.download('/v1/backup/files/..%2Ftoken', tmp_path / 'leak')
    assert not (tmp_path / 'leak').exists()
    existing = tmp_path / 'existing'
    existing.write_bytes(b'preserved')
    with pytest.raises(m5_runtime.RuntimeErrorCode):
        client.download('/v1/backup/files/originals%2Fmail%2Fsynthetic.eml', existing)
    assert existing.read_bytes() == b'preserved'


def test_rust_preserves_auth_failure_from_nonzero_adapter_exit(binary, tmp_path):
    payload, _ = prepared(binary)
    fake_repo = tmp_path / 'adapter-repository'
    (fake_repo / 'tools').mkdir(parents=True)
    (fake_repo / 'tools/m5_p2_adapter.py').write_text(
        'import json,sys\nprint(json.dumps({"ok":False,"error":"AGENT_AUTH_REQUIRED"}))\nsys.exit(2)\n',
        encoding='utf-8')
    done = command(binary, 'p2', '--operation', 'codex', '--python', sys.executable,
                   '--repo-root', fake_repo, body={'request': payload}, check=False)
    assert done.returncode != 0
    assert json.loads(done.stdout)['error']['code'] == 'AGENT_AUTH_REQUIRED'


def test_https_server_enforces_auth_and_default_client_verifies_certificates(binary, service, tmp_path):
    _, token, base, _, config = service
    cert, key = self_signed_cert(tmp_path)
    token_text = token.read_text(encoding='utf-8').strip()
    with start_server(dict(config, tls_cert=str(cert), tls_key=str(key)), binary, scheme='https') as tls_base:
        port = urlsplit(tls_base).port
        anonymous = tls_request(port, b'GET /v1/backup/manifest HTTP/1.1\r\nHost: localhost\r\n\r\n')
        assert b'401' in anonymous.split(b'\r\n', 1)[0]
        authorized = tls_request(port, (
            'GET /v1/backup/manifest HTTP/1.1\r\nHost: localhost\r\n'
            f'Authorization: Bearer {token_text}\r\n\r\n').encode('ascii'))
        assert b'200' in authorized.split(b'\r\n', 1)[0]
        # 기본 클라이언트는 신뢰하지 않는 self-signed 인증서를 거부한다(검증 우회 없음).
        client = m5_runtime.Client(tls_base, token)
        with pytest.raises(m5_runtime.RuntimeErrorCode, match='NODE_CONNECTION_FAILED'):
            client.call({'operation': 'claim'})
    # 평문 HTTP 서버에 HTTPS 클라이언트로 접속하면 실패한다.
    plain = m5_runtime.Client(f'https://127.0.0.1:{urlsplit(base).port}', token)
    with pytest.raises(m5_runtime.RuntimeErrorCode, match='NODE_CONNECTION_FAILED'):
        plain.call({'operation': 'claim'})


def test_expired_lease_fences_old_node_and_new_node_completes_over_http(binary, two_nodes):
    core, tokens, base, _ = two_nodes
    payload, answer = prepared(binary)
    queued = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'fence-http', 'budget_key': 'p2', 'payload': payload})
    client_a = m5_runtime.Client(base, tokens['node-a'], allow_loopback_http=True)
    client_b = m5_runtime.Client(base, tokens['node-b'], allow_loopback_http=True)
    token_a = client_a.call({'operation': 'claim'})['job']['token']
    assert token_a['generation'] == 1
    # 노드 중단 모사: 완료 없이 임대 시각만 과거로 돌린다.
    with sqlite3.connect(core) as db:
        db.execute('UPDATE jobs SET lease_until=? WHERE job_id=?', ('1', queued['job_id']))
    with pytest.raises(m5_runtime.RuntimeErrorCode, match='NODE_LEASE_LOST'):
        client_a.call({'operation': 'heartbeat', 'token': token_a})
    # 만료 회수 뒤 첫 재시도는 30초 지연된다(설계된 재시도 지연).
    assert client_b.call({'operation': 'claim'})['job'] is None
    with sqlite3.connect(core) as db:
        db.execute('UPDATE jobs SET not_before=? WHERE job_id=?', ('1', queued['job_id']))
    token_b = client_b.call({'operation': 'claim'})['job']['token']
    assert token_b['generation'] == 2
    result = {'runner': 'replay', 'answer': answer}
    with pytest.raises(m5_runtime.RuntimeErrorCode, match='NODE_LEASE_LOST'):
        client_a.call({'operation': 'complete', 'token': token_a, 'result': result})
    # 소유자가 다른 토큰은 코어에 닿기 전에 서버가 거부한다.
    status, body = raw_post(base, tokens['node-b'].read_text(encoding='utf-8').strip(),
                            {'operation': 'complete', 'token': dict(token_b, owner='node-a'), 'result': result})
    assert status == 400 and body['code'] == 'NODE_LEASE_OWNER_INVALID'
    client_b.call({'operation': 'complete', 'token': token_b, 'result': result})
    state = m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': queued['job_id']})
    assert state['state'] == 'succeeded' and state['attempts'] == 2
    assert state['result'] == result
    with pytest.raises(m5_runtime.RuntimeErrorCode, match='NODE_LEASE_LOST'):
        client_a.call({'operation': 'complete', 'token': token_a, 'result': result})


def test_complete_resend_is_idempotent_but_changed_result_is_rejected_over_http(binary, two_nodes):
    core, tokens, base, _ = two_nodes
    payload, answer = prepared(binary)
    queued = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'resend-http', 'budget_key': 'p2', 'payload': payload})
    client = m5_runtime.Client(base, tokens['node-a'], allow_loopback_http=True)
    token = client.call({'operation': 'claim'})['job']['token']
    result = {'runner': 'replay', 'answer': answer}
    client.call({'operation': 'complete', 'token': token, 'result': result})
    client.call({'operation': 'complete', 'token': token, 'result': result})
    # 검증은 통과하지만 저장된 결과와 다른 두 번째 유효 답변: 큐 fencing이 거부해야 한다.
    other_answer = {'request_digest': answer['request_digest'], 'run_id': answer['run_id'],
                    'results': [{'merchant_id': 'synthetic-a', 'item': '기존 항목 유지',
                                 'confidence': '낮음', 'basis': '다른 합성 근거'}]}
    changed = {'runner': 'replay', 'answer': other_answer}
    with pytest.raises(m5_runtime.RuntimeErrorCode, match='NODE_LEASE_LOST'):
        client.call({'operation': 'complete', 'token': token, 'result': changed})
    state = m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': queued['job_id']})
    assert state['state'] == 'succeeded' and state['attempts'] == 1
    assert state['result'] == result


def test_failed_calls_consume_node_budget_and_p1_still_publishes(binary, two_nodes):
    core, tokens, _, config = two_nodes
    payload, _ = prepared(binary)
    spec = config['nodes']['node-a']
    limited = dict(config, nodes={'node-a': dict(spec, daily_budget_limit=1)})
    with start_server(limited, binary) as base:
        client = m5_runtime.Client(base, tokens['node-a'], allow_loopback_http=True)
        first = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
            'dedupe_key': 'budget-1', 'budget_key': 'p2', 'payload': payload})
        m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
            'dedupe_key': 'budget-2', 'budget_key': 'p2', 'payload': payload})
        p1 = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p1_publish',
            'dedupe_key': 'p1-post', 'payload': {'synthetic': True}})
        token = client.call({'operation': 'claim'})['job']['token']
        assert token['job_id'] == first['job_id']
        assert client.call({'operation': 'fail', 'token': token, 'failure': 'authentication'})['state'] == 'dead'
        # 실패 호출도 예산을 써서 다음 P2는 임대되지 않는다.
        assert client.call({'operation': 'claim'})['job'] is None
        with sqlite3.connect(core) as db:
            used, limit = db.execute("SELECT used_units,limit_units FROM budgets WHERE scope='p2'").fetchone()
        assert (used, limit) == (1, 1)
        # P1은 예산·P2 적체와 무관하게 서버 쪽에서 먼저 게시된다.
        p1_token = m5_runtime.core_call(binary, core, {'operation': 'claim', 'owner': 'server-p1',
            'kinds': ['p1_publish'], 'daily_budget_limit': 0, 'lease_seconds': 300})['job']['token']
        assert p1_token['job_id'] == p1['job_id']
        m5_runtime.core_call(binary, core, {'operation': 'complete', 'token': p1_token, 'result': {'posted': True}})
        assert m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': p1['job_id']})['state'] == 'succeeded'
        assert m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': first['job_id']})['state'] == 'dead'
        with sqlite3.connect(core) as db:
            assert db.execute("SELECT state FROM jobs WHERE dedupe_key='budget-2'").fetchone()[0] == 'queued'


def test_retry_delays_and_failure_classes_over_http(binary, two_nodes):
    core, tokens, base, _ = two_nodes
    payload, _ = prepared(binary)
    client = m5_runtime.Client(base, tokens['node-a'], allow_loopback_http=True)

    def enqueue(key, scope):
        return m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
            'dedupe_key': key, 'budget_key': scope, 'payload': payload})['job_id']

    def not_before(job_id):
        with sqlite3.connect(core) as db:
            return int(db.execute('SELECT not_before FROM jobs WHERE job_id=?', (job_id,)).fetchone()[0])

    retry = enqueue('retry-http', 'retry-scope')
    token = client.call({'operation': 'claim'})['job']['token']
    now = time.time()
    assert client.call({'operation': 'fail', 'token': token, 'failure': 'transient'})['state'] == 'queued'
    assert 25 <= not_before(retry) - now <= 40
    assert client.call({'operation': 'claim'})['job'] is None
    with sqlite3.connect(core) as db:
        db.execute('UPDATE jobs SET not_before=? WHERE job_id=?', ('1', retry))
    token = client.call({'operation': 'claim'})['job']['token']
    now = time.time()
    assert client.call({'operation': 'fail', 'token': token, 'failure': 'capacity'})['state'] == 'queued'
    # 호출자가 시각을 안 보내면 정책 기본값(3,600초)이 적용된다.
    assert abs(not_before(retry) - (now + 3600)) <= 20
    assert client.call({'operation': 'claim'})['job'] is None
    with sqlite3.connect(core) as db:
        db.execute('UPDATE jobs SET not_before=? WHERE job_id=?', ('1', retry))
    token = client.call({'operation': 'claim'})['job']['token']
    assert client.call({'operation': 'fail', 'token': token, 'failure': 'transient'})['state'] == 'dead'

    # 호출자가 대기 시각을 보내면 서버가 덮어쓰지 않고 그대로 쓴다(예산 간격 보호).
    caller = enqueue('caller-capacity-http', 'caller-scope')
    token = client.call({'operation': 'claim'})['job']['token']
    assert token['job_id'] == caller
    now = time.time()
    assert client.call({'operation': 'fail', 'token': token, 'failure': 'capacity',
                        'retry_after_seconds': 1800})['state'] == 'queued'
    assert abs(not_before(caller) - (now + 1800)) <= 20
    assert client.call({'operation': 'claim'})['job'] is None
    with sqlite3.connect(core) as db:
        db.execute('UPDATE jobs SET not_before=? WHERE job_id=?', ('1', caller))

    # 진전하지 않는 값은 조용히 3,600초로 대체되지 않고 명시 거부된다.
    token = client.call({'operation': 'claim'})['job']['token']
    assert token['job_id'] == caller
    for bad in (0, -1, '1800'):
        with pytest.raises(m5_runtime.RuntimeErrorCode, match='NODE_REQUEST_REFUSED'):
            client.call({'operation': 'fail', 'token': token, 'failure': 'capacity',
                         'retry_after_seconds': bad})
    with sqlite3.connect(core) as db:
        # 거부 뒤에도 임대가 그대로 살아 있다(조용한 3,600초 대체 없음).
        assert db.execute('SELECT state FROM jobs WHERE job_id=?',
                          (caller,)).fetchone() == ('leased',)
    assert client.call({'operation': 'fail', 'token': token, 'failure': 'capacity',
                        'retry_after_seconds': 1800})['state'] == 'queued'

    auth = enqueue('auth-http', 'auth-scope')
    token = client.call({'operation': 'claim'})['job']['token']
    assert token['job_id'] == auth
    assert client.call({'operation': 'fail', 'token': token, 'failure': 'authentication'})['state'] == 'dead'
    tool = enqueue('tool-http', 'tool-scope')
    token = client.call({'operation': 'claim'})['job']['token']
    assert token['job_id'] == tool
    assert client.call({'operation': 'fail', 'token': token, 'failure': 'tool'})['state'] == 'dead'


def test_server_rejects_invalid_p2_results_before_queue_commit(binary, two_nodes, tmp_path):
    core, tokens, base, config = two_nodes
    payload, answer = prepared(binary)
    token_text = tokens['node-a'].read_text(encoding='utf-8').strip()
    queued = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'invalid-result', 'budget_key': 'p2', 'payload': payload})
    client = m5_runtime.Client(base, tokens['node-a'], allow_loopback_http=True)
    token = client.call({'operation': 'claim'})['job']['token']
    valid = {'runner': 'replay', 'answer': answer}
    for bad in ({'runner': 'replay', 'answer': None},
                {'runner': 'other', 'answer': answer},
                {'runner': 'replay', 'answer': dict(answer, request_digest='0' * 64)}):
        status, body = raw_post(base, token_text, {'operation': 'complete', 'token': token, 'result': bad})
        assert status == 400 and body['code'] == 'P2_RESULT_INVALID'
        with sqlite3.connect(core) as db:
            assert db.execute('SELECT state FROM jobs WHERE job_id=?', (queued['job_id'],)).fetchone()[0] == 'leased'
    client.call({'operation': 'complete', 'token': token, 'result': valid})
    assert m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': queued['job_id']})['state'] == 'succeeded'

    # 재생을 허용하지 않는 서버는 replay 결과를 거부한다.
    with start_server(dict(config, allow_replay=False), binary) as strict_base:
        strict = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
            'dedupe_key': 'strict-replay', 'budget_key': 'p2', 'payload': payload})
        strict_client = m5_runtime.Client(strict_base, tokens['node-a'], allow_loopback_http=True)
        strict_token = strict_client.call({'operation': 'claim'})['job']['token']
        status, body = raw_post(strict_base, token_text,
                                {'operation': 'complete', 'token': strict_token, 'result': valid})
        assert status == 400 and body['code'] == 'P2_REPLAY_FORBIDDEN'
        assert m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': strict['job_id']})['state'] == 'leased'

    # P2가 아닌 kind의 작업 토큰으로는 P2 완료를 제출할 수 없다.
    p1 = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p1_publish',
        'dedupe_key': 'p1-kind', 'payload': {'synthetic': True}})
    p1_token = m5_runtime.core_call(binary, core, {'operation': 'claim', 'owner': 'node-a',
        'kinds': ['p1_publish'], 'daily_budget_limit': 0, 'lease_seconds': 300})['job']['token']
    assert p1_token['job_id'] == p1['job_id']
    status, body = raw_post(base, token_text, {'operation': 'complete', 'token': p1_token, 'result': valid})
    assert status == 400 and body['code'] == 'P2_JOB_INVALID'


def test_killed_node_process_leaves_durable_lease_and_reconnect_completes_once(binary, service, tmp_path):
    core, token, base, _, _ = service
    payload, answer = prepared(binary)
    queued = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'crash-reconnect', 'budget_key': 'p2', 'payload': payload})
    replay = tmp_path / 'replay.json'
    replay.write_text(json.dumps(answer, ensure_ascii=False), encoding='utf-8')
    node_config = tmp_path / 'node.json'
    node_config.write_text(json.dumps({'server_url': base, 'token_file': str(token),
        'allow_loopback_http': True, 'runner': 'replay', 'replay_file': str(replay)}), encoding='utf-8')
    sleeper = tmp_path / 'slow.bat'
    sleeper.write_text('@echo off\r\nping -n 61 127.0.0.1 > nul\r\n', encoding='ascii')
    proc = subprocess.Popen([sys.executable, '-I', str(ROOT / 'tools/m5_runtime.py'), 'node',
                             '--config', str(node_config), '--once'],
                            cwd=ROOT, env=dict(os.environ, COSTCORE_RUNTIME_BINARY=str(sleeper)),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                _, err = proc.communicate()
                pytest.fail(f'node exited early rc={proc.returncode}: {err.decode("utf-8", "replace")[:400]}')
            with sqlite3.connect(core) as db:
                state = db.execute('SELECT state FROM jobs WHERE job_id=?', (queued['job_id'],)).fetchone()[0]
            if state == 'leased':
                break
            time.sleep(0.2)
        else:
            pytest.fail('node did not claim the job before the deadline')
        killed = subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=15)
        assert killed.returncode == 0, killed.stderr.decode('utf-8', 'replace')
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    with sqlite3.connect(core) as db:
        state, attempts, result = db.execute(
            'SELECT state,attempts,result_json FROM jobs WHERE job_id=?', (queued['job_id'],)).fetchone()
    assert (state, attempts, result) == ('leased', 1, '')
    with sqlite3.connect(core) as db:
        db.execute('UPDATE jobs SET lease_until=? WHERE job_id=?', ('1', queued['job_id']))
    # 만료 회수는 첫 재시도에 30초 지연을 건다. 회수를 일으킨 뒤 지연을 해제하고 재접속한다.
    assert m5_runtime.core_call(binary, core, {'operation': 'claim', 'owner': 'node-a',
        'kinds': ['p2_merchant'], 'daily_budget_limit': 3, 'lease_seconds': 300})['job'] is None
    with sqlite3.connect(core) as db:
        db.execute('UPDATE jobs SET not_before=? WHERE job_id=?', ('1', queued['job_id']))
    reconnect = command(binary, 'node', '--repo-root', ROOT, '--python', sys.executable,
                        '--config', node_config, '--once')
    summaries = [json.loads(line) for line in reconnect.stdout.splitlines()]
    assert summaries[-1] == {'ok': True, 'claimed': 1, 'succeeded': 1}
    state = m5_runtime.core_call(binary, core, {'operation': 'status', 'job_id': queued['job_id']})
    assert state['state'] == 'succeeded' and state['attempts'] == 2
    assert state['result'] == {'runner': 'replay', 'answer': answer}
    again = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'crash-reconnect', 'budget_key': 'p2', 'payload': payload})
    assert again['job_id'] == queued['job_id']


def test_dedupe_and_budget_required_over_queue_bridge(binary, service):
    core, _, _, _, _ = service
    payload, _ = prepared(binary)
    first = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'dedupe-bridge', 'budget_key': 'p2', 'payload': payload})
    repeated = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
        'dedupe_key': 'dedupe-bridge', 'budget_key': 'p2', 'payload': payload})
    assert repeated['job_id'] == first['job_id']
    with pytest.raises(m5_runtime.RuntimeErrorCode, match='dedupe_conflict'):
        m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
            'dedupe_key': 'dedupe-bridge', 'budget_key': 'p2', 'payload': dict(payload, run_id='def456')})
    with pytest.raises(m5_runtime.RuntimeErrorCode, match='QUEUE_BUDGET_REQUIRED'):
        m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p2_merchant',
            'dedupe_key': 'no-budget', 'payload': payload})
    p1 = m5_runtime.core_call(binary, core, {'operation': 'enqueue', 'kind': 'p1_publish',
        'dedupe_key': 'p1-no-budget', 'payload': {'synthetic': True}})
    assert p1['job_id'] > 0


def test_rust_codex_exec_maps_adapter_envelopes_without_a_model(binary, tmp_path):
    payload, answer = prepared(binary)
    fake_repo = tmp_path / 'adapter-repository'
    (fake_repo / 'tools').mkdir(parents=True)
    script_path = fake_repo / 'tools/m5_p2_adapter.py'

    def run(script):
        script_path.write_text(script, encoding='utf-8')
        return command(binary, 'p2', '--operation', 'codex', '--python', sys.executable,
                       '--repo-root', fake_repo, body={'request': payload}, check=False)

    def envelope_script(envelope, exit_code=0):
        # python -I의 로케일 stdout에서도 안전하도록 ASCII(\uXXXX) 직렬화를 쓴다.
        literal = json.dumps(json.dumps(envelope))
        return f'import sys\nsys.stdout.write({literal})\n' + (f'sys.exit({exit_code})\n' if exit_code else '')

    unknown = run(envelope_script({'ok': False, 'error': 'PROVIDER_SPECIFIC_LEAK'}, 2))
    assert unknown.returncode != 0
    assert json.loads(unknown.stdout)['error']['code'] == 'AGENT_EXECUTION_FAILED'
    assert b'PROVIDER_SPECIFIC_LEAK' not in unknown.stdout

    malformed = run('import sys\nsys.stdout.write("not-json")\n')
    assert malformed.returncode != 0
    assert json.loads(malformed.stdout)['error']['code'] == 'AGENT_RESPONSE_INVALID'

    extra = run(envelope_script({'ok': True, 'result': answer, 'extra': 1}))
    assert extra.returncode != 0
    assert json.loads(extra.stdout)['error']['code'] == 'AGENT_RESPONSE_INVALID'

    valid = run(envelope_script({'ok': True, 'result': answer}))
    assert valid.returncode == 0, valid.stderr.decode('utf-8', 'replace')
    assert json.loads(valid.stdout) == {'ok': True, 'result': answer}
