"""Provider-neutral M5 transport. Rust owns queue transitions and P2 validation.

No node listener, tunnel, remote shell, filesystem command, or ledger-write API.
The Python transport is transitional until the M6 web-runtime retirement.
"""
from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_BYTES = 4 * 1024 * 1024
KIND = 'p2_merchant'
RESERVED_PORTS = (8751, 8752, 8790)


def reserved_environment_port(value):
    """환경변수 PORT 값이 예약 포트면 그 번호를, 아니면 None을 돌려준다."""
    if value is None:
        return None
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return port if port in RESERVED_PORTS else None


def web_child_environment(base, web_args):
    """웹 자식 프로세스의 환경을 만든다. 상속된 `PORT`가 예약 포트를 차지하지 못하게 한다.

    `run_candidate.resolve_port()`는 argv `--port`가 없으면 `os.environ["PORT"]`를 쓰고,
    없으면 `DEFAULT_PORT`(8751, 운영 포트)를 쓴다. 부모 환경을 검사만 하면 부모가 `PORT`를
    다시 설정하거나 `web_args`로 `--port`가 빠진 경로에서 새는 값이 남는다. 자식 env를
    직접 통제하는 편이 확실하므로, 예약 포트가 상속되면 **argv에 `--port`가 있는지와 무관하게**
    그 키를 지우고 안전한 값으로 덮어쓴다.
    """
    child = dict(base)
    if reserved_environment_port(child.get('PORT')) is not None:
        child['PORT'] = safe_web_port(web_args)
    return child


def safe_web_port(web_args):
    """자식 env의 대체 포트. argv로 이미 정한 포트가 있으면 그 값을, 없으면 0(임의)을 쓴다.

    `--port`가 argv에 있으면 `run_candidate`가 env를 보지 않으므로 값은 상관없다. 없으면
    예약 포트가 아닌 값이어야 하므로 0(에페머럴)으로 두어 운영 포트를 절대 재사용하지 않는다.
    """
    for index, value in enumerate(web_args):
        name, separator, inline = value.partition('=')
        if '--port'.startswith(name) and len(name) > 2:
            raw = inline if separator else (web_args[index + 1] if index + 1 < len(web_args) else None)
            try:
                parsed = int(str(raw).strip())
            except (TypeError, ValueError):
                continue
            if parsed not in RESERVED_PORTS:
                return str(parsed)
    return '0'


def reserved_port_argument(argv):
    """실행 인자에서 예약 포트를 찾는다.

    `argparse`는 접두 축약을 허용하므로 `--po 8751`이 `--port`로 해석된다. 따라서 정확한
    `--port`/`--port=`뿐 아니라 그것으로 축약될 수 있는 모든 접두(`--p`, `--po`, ...)와
    공백이 섞인 값(` 8751`)까지 함께 거부 대상으로 잡는다.
    """
    option = '--port'
    found = set()
    for index, value in enumerate(argv):
        name, separator, inline = value.partition('=')
        candidate = None
        if option.startswith(name) and len(name) > 2:
            # 축약형이거나 정확한 이름이다. 값은 같은 인자에 붙었거나 다음 인자다.
            candidate = inline if separator else (argv[index + 1] if index + 1 < len(argv) else None)
        if candidate is None:
            continue
        try:
            if int(candidate.strip()) in RESERVED_PORTS:
                found.add(int(candidate.strip()))
        except (TypeError, ValueError):
            continue
    return sorted(found)


class RuntimeErrorCode(Exception):
    def __init__(self, code, retry_after=None):
        super().__init__(code)
        # 제공자·서버가 권고한 대기 초. 없으면 None이며 서버 정책 기본값을 쓴다.
        self.retry_after = retry_after


def private_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def token_from(path):
    file = Path(path)
    if not file.is_absolute() or file.is_symlink() or not file.is_file():
        raise RuntimeErrorCode('NODE_CREDENTIAL_INVALID')
    if os.name != 'nt' and file.stat().st_mode & 0o077:
        raise RuntimeErrorCode('NODE_CREDENTIAL_PERMISSIONS')
    token = file.read_text(encoding='utf-8').strip()
    if len(token) < 32 or len(token) > 256 or not token.isascii() or any(c.isspace() for c in token):
        raise RuntimeErrorCode('NODE_CREDENTIAL_INVALID')
    return token


def core_call(binary, core, body):
    done = subprocess.run([str(binary), 'queue', '--core', str(core)],
                          input=json.dumps(body, ensure_ascii=False), encoding='utf-8',
                          capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        reply = json.loads(done.stdout)
    except (ValueError, TypeError):
        raise RuntimeErrorCode('QUEUE_BRIDGE_INVALID') from None
    if done.returncode or reply.get('ok') is not True:
        code = (reply.get('error') or {}).get('code', 'QUEUE_BRIDGE_FAILED')
        allowed = {'lease_lost', 'invalid_input', 'dedupe_conflict', 'QUEUE_INPUT_INVALID',
                   'QUEUE_BUDGET_REQUIRED', 'CORE_SCHEMA_MISMATCH'}
        raise RuntimeErrorCode(code if code in allowed else 'QUEUE_BRIDGE_FAILED')
    return reply['result']


def make_server(config, binary):
    core = Path(config['core_db'])
    if not core.is_absolute() or not core.is_file() or core.is_symlink():
        raise RuntimeErrorCode('CORE_PATH_INVALID')
    host, port = config.get('bind', '127.0.0.1'), config.get('port', 0)
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        raise RuntimeErrorCode('SERVER_BIND_INVALID') from None
    if type(port) is not int or port in RESERVED_PORTS:
        raise RuntimeErrorCode('SERVER_QUEUE_PORT_RESERVED')
    web_args = config.get('web_args')
    if web_args is not None:
        if not isinstance(web_args, list) or not all(isinstance(value, str) for value in web_args):
            raise RuntimeErrorCode('SERVER_WEB_ARGS_INVALID')
        # 웹 런타임도 같은 예약 포트를 쓰지 못하게 한다(설정 경로로 우회 금지).
        if reserved_port_argument(web_args):
            raise RuntimeErrorCode('SERVER_QUEUE_PORT_RESERVED')
    if not local and not (config.get('tls_cert') and config.get('tls_key')):
        raise RuntimeErrorCode('SERVER_TLS_REQUIRED')
    # 상속된 PORT가 예약 포트면 웹 자식이 그것을 쓰게 된다. 여기서 먼저 명시 거부한다.
    with_reserved = reserved_environment_port(os.environ.get('PORT'))
    if with_reserved is not None:
        raise RuntimeErrorCode('SERVER_WEB_PORT_RESERVED')
    nodes = {}
    for identity, spec in config['nodes'].items():
        if (not identity or len(identity) > 128 or not identity.isascii()
                or not all(c.isalnum() or c in '-_' for c in identity)):
            raise RuntimeErrorCode('NODE_ID_INVALID')
        if spec.get('kinds') != [KIND]:
            raise RuntimeErrorCode('NODE_KINDS_INVALID')
        cap = spec.get('daily_budget_limit', 30)
        if type(cap) is not int or not 0 <= cap <= 30:
            raise RuntimeErrorCode('NODE_BUDGET_INVALID')
        token = token_from(spec['token_file'])
        if token in [entry[0] for entry in nodes.values()]:
            raise RuntimeErrorCode('NODE_CREDENTIAL_DUPLICATE')
        nodes[identity] = (token, cap)
    if not nodes or len(nodes) > 32:
        raise RuntimeErrorCode('NODES_INVALID')
    backup_root, backup_manifest, backup_files = None, None, {}
    if config.get('backup_snapshot'):
        from tools import m5_backup
        backup_root = Path(config['backup_snapshot'])
        if not backup_root.is_absolute():
            raise RuntimeErrorCode('BACKUP_PATH_INVALID')
        try:
            m5_backup.verify_snapshot(backup_root)
            backup_manifest = m5_backup._read_manifest(backup_root)
            backup_files = {row['path']: row for row in backup_manifest['files']}
        except m5_backup.BackupError:
            raise RuntimeErrorCode('BACKUP_SNAPSHOT_INVALID') from None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def reply(self, status, body):
            payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(payload)

        def identity(self):
            header = self.headers.get('Authorization', '')
            return next((name for name, (token, _) in nodes.items()
                         if hmac.compare_digest(header.encode('utf-8'), ('Bearer ' + token).encode('ascii'))), None)

        def do_GET(self):
            identity = self.identity()
            if identity is None:
                self.reply(401, {'ok': False, 'code': 'NODE_AUTH_REQUIRED'})
                return
            if backup_root is None or config['nodes'][identity].get('backup') is not True:
                self.reply(403, {'ok': False, 'code': 'NODE_BACKUP_FORBIDDEN'})
                return
            if self.path == '/v1/backup/manifest':
                self.reply(200, backup_manifest)
                return
            prefix = '/v1/backup/files/'
            relative = unquote(self.path[len(prefix):]) if self.path.startswith(prefix) else ''
            if relative not in backup_files:
                self.reply(404, {'ok': False, 'code': 'NOT_FOUND'})
                return
            try:
                from tools import m5_backup
                path = m5_backup._member_path(backup_root, relative, must_exist=True)
                with path.open('rb') as source:
                    size = os.fstat(source.fileno()).st_size
                    if size != backup_files[relative]['size']:
                        raise RuntimeErrorCode('BACKUP_SNAPSHOT_INVALID')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(size))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    while block := source.read(1024 * 1024):
                        self.wfile.write(block)
            except (OSError, RuntimeErrorCode, m5_backup.BackupError):
                self.close_connection = True

        def do_POST(self):
            identity = self.identity()
            if identity is None:
                self.reply(401, {'ok': False, 'code': 'NODE_AUTH_REQUIRED'})
                return
            if self.path != '/v1/queue':
                self.reply(404, {'ok': False, 'code': 'NOT_FOUND'})
                return
            try:
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                    raise RuntimeErrorCode('REQUEST_LENGTH_INVALID')
                length = int(self.headers['Content-Length'])
                if not 0 < length <= MAX_BYTES:
                    raise RuntimeErrorCode('REQUEST_LENGTH_INVALID')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise RuntimeErrorCode('REQUEST_INVALID')
                operation = body.get('operation')
                if operation == 'claim':
                    if set(body) != {'operation'}:
                        raise RuntimeErrorCode('REQUEST_INVALID')
                    request = {'operation': 'claim', 'owner': identity, 'kinds': [KIND],
                               'daily_budget_limit': nodes[identity][1], 'lease_seconds': 300}
                elif operation in ('heartbeat', 'complete', 'fail'):
                    optional = {'retry_after_seconds'} if operation == 'fail' else set()
                    required = {'heartbeat': {'operation', 'token'},
                                'complete': {'operation', 'token', 'result'},
                                'fail': {'operation', 'token', 'failure'}}[operation]
                    # 그 밖의 키는 거부하되, fail의 대기 시각만 선택 키로 받는다.
                    if (not required <= set(body) or set(body) - required - optional
                            or not isinstance(body['token'], dict)):
                        raise RuntimeErrorCode('REQUEST_INVALID')
                    if 'retry_after_seconds' in body:
                        delay = body['retry_after_seconds']
                        if delay is None:
                            body = {key: value for key, value in body.items()
                                    if key != 'retry_after_seconds'}
                        elif type(delay) is not int:
                            raise RuntimeErrorCode('REQUEST_INVALID')
                    if body['token'].get('owner') != identity:
                        raise RuntimeErrorCode('NODE_LEASE_OWNER_INVALID')
                    request = dict(body)
                    if operation == 'heartbeat':
                        request['lease_seconds'] = 300
                    if operation == 'complete':
                        validate_completion(binary, core, body['token'], body['result'],
                                            allow_replay=config.get('allow_replay') is True)
                else:
                    raise RuntimeErrorCode('NODE_OPERATION_FORBIDDEN')
                result = core_call(binary, core, request)
                self.reply(200, {'ok': True, 'result': result})
            except (ValueError, KeyError, TypeError, UnicodeError):
                self.reply(400, {'ok': False, 'code': 'REQUEST_INVALID'})
            except RuntimeErrorCode as exc:
                self.reply(409 if str(exc) == 'lease_lost' else 400,
                           {'ok': False, 'code': str(exc)})
            except Exception:
                self.reply(503, {'ok': False, 'code': 'NODE_SERVICE_UNAVAILABLE'})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    if config.get('tls_cert') and config.get('tls_key'):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config['tls_cert'], config['tls_key'])
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def validate_completion(binary, core, token, result, *, allow_replay):
    import sqlite3
    if not isinstance(result, dict) or result.get('runner') not in ('codex', 'replay'):
        raise RuntimeErrorCode('P2_RESULT_INVALID')
    if result['runner'] == 'replay' and not allow_replay:
        raise RuntimeErrorCode('P2_REPLAY_FORBIDDEN')
    with sqlite3.connect(Path(core).as_uri() + '?mode=ro', uri=True) as conn:
        conn.execute('PRAGMA query_only=ON')
        row = conn.execute('SELECT kind,payload_json FROM jobs WHERE job_id=?', (token.get('job_id'),)).fetchone()
    if not row or row[0] != KIND:
        raise RuntimeErrorCode('P2_JOB_INVALID')
    done = subprocess.run([str(binary), 'p2', '--operation', 'validate'],
                          input=json.dumps({'request': json.loads(row[1]), 'answer': result.get('answer')}),
                          encoding='utf-8', capture_output=True, timeout=15,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if done.returncode or json.loads(done.stdout).get('ok') is not True:
        raise RuntimeErrorCode('P2_RESULT_INVALID')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeErrorCode('NODE_REDIRECT_FORBIDDEN')


class Client:
    def __init__(self, base_url, token_file, *, allow_loopback_http=False,
                 max_download_bytes=16 * 1024 ** 3):
        url = urlsplit(base_url)
        local = False
        try:
            local = ipaddress.ip_address(url.hostname or '').is_loopback
        except ValueError:
            pass
        if (url.scheme != 'https' and not (allow_loopback_http and local and url.scheme == 'http')):
            raise RuntimeErrorCode('NODE_HTTPS_REQUIRED')
        if not url.netloc or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise RuntimeErrorCode('NODE_URL_INVALID')
        self.base, self.token = base_url.rstrip('/'), token_from(token_file)
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        if type(max_download_bytes) is not int or max_download_bytes <= 0:
            raise RuntimeErrorCode('NODE_DOWNLOAD_LIMIT_INVALID')
        self.max_download_bytes = max_download_bytes

    def get_json(self, path):
        if path != '/v1/backup/manifest':
            raise RuntimeErrorCode('NODE_BACKUP_PATH_INVALID')
        request = Request(self.base + path, headers={'Authorization': 'Bearer ' + self.token})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise RuntimeErrorCode('NODE_RESPONSE_TOO_LARGE')
                return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, ValueError):
            raise RuntimeErrorCode('NODE_BACKUP_FAILED') from None

    def download(self, path, target):
        if not path.startswith('/v1/backup/files/') or any(c in path for c in ('?', '#', '\\', '\r', '\n')):
            raise RuntimeErrorCode('NODE_BACKUP_PATH_INVALID')
        request = Request(self.base + path, headers={'Authorization': 'Bearer ' + self.token})
        try:
            with self.opener.open(request, timeout=60) as response:
                length = response.headers.get('Content-Length', '')
                if not length.isdecimal() or int(length) > self.max_download_bytes:
                    raise RuntimeErrorCode('NODE_RESPONSE_TOO_LARGE')
                expected, written = int(length), 0
                with Path(target).open('xb') as destination:
                    while block := response.read(min(1024 * 1024, expected - written + 1)):
                        written += len(block)
                        if written > expected:
                            raise RuntimeErrorCode('NODE_RESPONSE_TOO_LARGE')
                        destination.write(block)
                if written != expected:
                    raise RuntimeErrorCode('NODE_BACKUP_INCOMPLETE')
        except (HTTPError, URLError, TimeoutError, OSError):
            raise RuntimeErrorCode('NODE_BACKUP_FAILED') from None

    def call(self, body):
        payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
        request = Request(self.base + '/v1/queue', data=payload,
                          headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}, method='POST')
        try:
            with self.opener.open(request, timeout=30) as response:
                value = json.loads(response.read(MAX_BYTES + 1))
        except HTTPError as exc:
            raise RuntimeErrorCode('NODE_LEASE_LOST' if exc.code == 409 else 'NODE_REQUEST_REFUSED') from None
        except (URLError, TimeoutError, ValueError):
            raise RuntimeErrorCode('NODE_CONNECTION_FAILED') from None
        if value.get('ok') is not True:
            raise RuntimeErrorCode('NODE_REQUEST_REFUSED')
        return value['result']


def node_once(client, execute):
    job = client.call({'operation': 'claim'}).get('job')
    if job is None:
        return {'claimed': 0}
    token, stop, lost = job['token'], threading.Event(), threading.Event()

    def heartbeat():
        while not stop.wait(60):
            try:
                client.call({'operation': 'heartbeat', 'token': token})
            except RuntimeErrorCode:
                lost.set()
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        try:
            result = execute(job['payload'])
        except RuntimeErrorCode as exc:
            code = str(exc)
            failure = ('capacity' if 'RATE_LIMIT' in code else 'authentication' if 'AUTH' in code
                       else 'tool' if 'TOOL' in code else 'transient')
            body = {'operation': 'fail', 'token': token, 'failure': failure}
            if failure == 'capacity':
                # 제공자가 권고한 대기 시각만 싣는다. 없으면 키를 생략해 서버가 유일한
                # 정책 상수(`jobs::DEFAULT_CAPACITY_RETRY_SECONDS`)를 적용하게 한다.
                delay = getattr(exc, 'retry_after', None)
                if type(delay) is int and delay > 0:
                    body['retry_after_seconds'] = delay
            if not lost.is_set():
                client.call(body)
            return {'claimed': 1, 'failed': 1}
        if lost.is_set():
            raise RuntimeErrorCode('NODE_LEASE_LOST')
        # A response may be lost after commit. Resend the identical result and
        # fencing token; queue.complete is idempotent for this exact pair.
        for attempt in range(2):
            try:
                client.call({'operation': 'complete', 'token': token, 'result': result})
                break
            except RuntimeErrorCode as exc:
                if str(exc) != 'NODE_CONNECTION_FAILED' or attempt:
                    raise
        return {'claimed': 1, 'succeeded': 1}
    finally:
        stop.set()
        thread.join(timeout=35)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('server', 'node'))
    parser.add_argument('--config', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    binary = os.environ.get('COSTCORE_RUNTIME_BINARY')
    try:
        if not binary:
            raise RuntimeErrorCode('COSTCORE_BINARY_REQUIRED')
        config = private_json(args.config)
        if args.mode == 'server':
            server = make_server(config, binary)
            web = None
            try:
                if config.get('web_args'):
                    web = subprocess.Popen([sys.executable, '-I', str(ROOT / 'run_candidate.py'),
                                            *config['web_args'], '--no-worker'],
                                           # 상속된 PORT가 예약 포트면 자식 env에서 덮어쓴다.
                                           env=web_child_environment(os.environ, config['web_args']),
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                server.timeout = 1
                print(json.dumps({'ok': True, 'queue_port': server.server_port}), flush=True)
                while web is None or web.poll() is None:
                    server.handle_request()
            finally:
                server.server_close()
                if web is not None and web.poll() is None:
                    web.terminate()
                    try:
                        web.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        web.kill()
                        web.wait()
        else:
            client = Client(config['server_url'], config['token_file'],
                            allow_loopback_http=config.get('allow_loopback_http') is True)
            runner = config.get('runner', 'codex')
            if runner not in ('codex', 'replay'):
                raise RuntimeErrorCode('P2_RUNNER_INVALID')

            def execute(payload):
                import tempfile
                from app.connected_agent_provider import AgentUnavailable, _run_bounded
                request = {'request': payload}
                if runner == 'replay':
                    request['answer'] = private_json(config['replay_file'])
                try:
                    with tempfile.TemporaryDirectory(prefix='cost-node-empty-') as cwd:
                        done = _run_bounded([binary, 'p2', '--operation', runner, '--python', sys.executable,
                                             '--repo-root', str(ROOT)], cwd=cwd, env=dict(os.environ),
                                            input_bytes=json.dumps(request, ensure_ascii=False).encode('utf-8'), timeout=270)
                except (AgentUnavailable, subprocess.TimeoutExpired):
                    raise RuntimeErrorCode('P2_EXECUTION_FAILED') from None
                answer = json.loads(done.stdout)
                if done.returncode or answer.get('ok') is not True:
                    code = (answer.get('error') or {}).get('code', 'P2_EXECUTION_FAILED')
                    if not isinstance(code, str) or not code.replace('_', '').isalnum():
                        code = 'P2_EXECUTION_FAILED'
                    raise RuntimeErrorCode(code)
                return {'runner': runner, 'answer': answer['result']}

            while True:
                try:
                    if config.get('backup_destination'):
                        from tools.m5_backup import pull_snapshot
                        backup = pull_snapshot(client, config['backup_destination'])
                        print(json.dumps({'backup': backup}), flush=True)
                    summary = node_once(client, execute)
                    print(json.dumps({'ok': True, **summary}), flush=True)
                except RuntimeErrorCode as exc:
                    if args.once:
                        raise
                    print(json.dumps({'ok': False, 'code': str(exc)}), flush=True)
                if args.once:
                    break
                time.sleep(15)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, RuntimeErrorCode) else 'M5_RUNTIME_FAILED'
        print(json.dumps({'ok': False, 'code': code}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
