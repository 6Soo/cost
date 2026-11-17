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
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_BYTES = 4 * 1024 * 1024
KIND = 'p2_merchant'


class RuntimeErrorCode(Exception):
    pass


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
    if port in (8751, 8752, 8790):
        raise RuntimeErrorCode('SERVER_QUEUE_PORT_RESERVED')
    if not local and not (config.get('tls_cert') and config.get('tls_key')):
        raise RuntimeErrorCode('SERVER_TLS_REQUIRED')
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

        def do_POST(self):
            header = self.headers.get('Authorization', '')
            identity = next((name for name, (token, _) in nodes.items()
                             if hmac.compare_digest(header.encode('utf-8'), ('Bearer ' + token).encode('ascii'))), None)
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
                    keys = {'heartbeat': {'operation', 'token'},
                            'complete': {'operation', 'token', 'result'},
                            'fail': {'operation', 'token', 'failure'}}[operation]
                    if set(body) != keys or not isinstance(body['token'], dict):
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
    def __init__(self, base_url, token_file, *, allow_loopback_http=False):
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
            if not lost.is_set():
                client.call({'operation': 'fail', 'token': token, 'failure': failure})
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
