"""Real Rust queue + HTTP + subprocess node, entirely on synthetic files."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from tools import m5_backup, m5_runtime, m5_p2_adapter

pytestmark = pytest.mark.costcore_bin
ROOT = Path(__file__).resolve().parents[1]


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
