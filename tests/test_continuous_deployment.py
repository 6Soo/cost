import concurrent.futures
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
import shutil
import subprocess
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from tools.ledger_gateway import Gateway, atomic_json, read_route
from tools.gateway_route import change
from webapp import deployment_role


@contextmanager
def backend(label, entered=None, release=None, requests=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/slow':
                entered.set()
                release.wait(5)
            status = 401 if self.path.startswith('/api/') else 200
            self.send_response(status)
            self.end_headers()
            self.wfile.write(label.encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            requests.append((body, self.headers.get('Cookie'), self.headers.get('Authorization')))
            if self.path == '/disconnect':
                self.close_connection = True
                return
            self.send_response(200)
            self.send_header('Set-Cookie', 'synthetic=value; HttpOnly')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def gateway(tmp_path, port):
    route, status = tmp_path / 'route.json', tmp_path / 'status.json'
    atomic_json(route, dict(port=port, paused=False, generation='initial'))
    server = Gateway(0, route, status)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}', route, status
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read()


def test_prepared_release_switch_drains_old_request_and_queues_new_connection(tmp_path):
    entered, release = threading.Event(), threading.Event()
    with backend('old', entered, release) as old, backend('new') as new, gateway(tmp_path, old) as (url, route, status):
        with concurrent.futures.ThreadPoolExecutor() as pool:
            in_flight = pool.submit(get, url + '/slow')
            assert entered.wait(3)
            pause = pool.submit(change, route, status, 'pause', None, 3)
            for _ in range(100):
                if read_route(route)['paused']:
                    break
                time.sleep(.01)
            queued = pool.submit(get, url + '/healthz')
            time.sleep(.1)
            assert not queued.done() and not pause.done()
            release.set()
            assert in_flight.result() == b'old'
            pause.result()
            change(route, status, 'activate', new)
            assert queued.result() == b'new'
        assert get(url + '/readyz') == b'new'


def test_upload_cookies_auth_response_and_disconnect_are_never_replayed(tmp_path):
    requests = []
    with backend('old', requests=requests) as old, gateway(tmp_path, old) as (url, route, status):
        payload = bytes(range(256)) * 2048
        headers = {'Cookie': 'synthetic=session', 'Authorization': 'Bearer synthetic'}
        request = urllib.request.Request(url + '/upload', data=payload, headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.read() == payload
            assert response.headers['Set-Cookie'] == 'synthetic=value; HttpOnly'
        assert requests == [(payload, 'synthetic=session', 'Bearer synthetic')]
        with pytest.raises(Exception):
            urllib.request.urlopen(urllib.request.Request(url + '/disconnect', data=b'once'), timeout=5)
        assert len(requests) == 2
        with pytest.raises(urllib.error.HTTPError) as error:
            get(url + '/api/imports/ota')
        assert error.value.code == 401


def test_failed_candidate_and_drain_timeout_preserve_old_backend(tmp_path):
    entered, release = threading.Event(), threading.Event()
    with backend('old', entered, release) as old, gateway(tmp_path, old) as (url, route, status):
        with concurrent.futures.ThreadPoolExecutor() as pool:
            in_flight = pool.submit(get, url + '/slow')
            assert entered.wait(3)
            with pytest.raises(ValueError, match='DRAIN_TIMEOUT'):
                change(route, status, 'pause', timeout=.1)
            assert read_route(route)['port'] == old
            change(route, status, 'resume')
            release.set()
            assert in_flight.result() == b'old'
        change(route, status, 'pause')
        with socket.socket() as unused:
            unused.bind(('127.0.0.1', 0))
            unavailable = unused.getsockname()[1]
        with pytest.raises(OSError):
            change(route, status, 'activate', unavailable)
        assert read_route(route)['port'] == old
        change(route, status, 'resume')
        assert get(url + '/healthz') == b'old'


def test_background_writer_is_inactive_until_route_activation_and_fails_closed(tmp_path, monkeypatch):
    route = tmp_path / 'route.json'
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_ROUTE', str(route))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_PORT', '8752')
    calls = []

    @deployment_role.active_writer(default=False)
    def write():
        calls.append(True)
        return True

    assert write() is False  # Missing configuration refuses standby writes.
    atomic_json(route, dict(port=8751, paused=False))
    assert write() is False
    atomic_json(route, dict(port=8752, paused=True))
    assert write() is False
    atomic_json(route, dict(port=8752, paused=False))
    assert write() is True and calls == [True]
    route.write_text('{broken', encoding='utf-8')
    assert write() is False


def test_pause_waits_for_existing_background_writer(tmp_path, monkeypatch):
    route = tmp_path / 'route.json'
    atomic_json(route, dict(port=8751, paused=False))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_ROUTE', str(route))
    monkeypatch.setenv('WEBLEDGER_DEPLOYMENT_PORT', '8751')
    entered, release = threading.Event(), threading.Event()

    def work():
        with deployment_role.writer() as active:
            assert active
            entered.set()
            release.wait(3)

    def switch():
        with deployment_role.route_lock(route):
            atomic_json(route, dict(port=8751, paused=True))

    with concurrent.futures.ThreadPoolExecutor() as pool:
        worker = pool.submit(work)
        assert entered.wait(2)
        transition = pool.submit(switch)
        time.sleep(.05)
        assert not transition.done() and deployment_role.is_active()
        release.set()
        worker.result()
        transition.result()
    assert not deployment_role.is_active()


def test_host_runner_passes_durable_role_to_both_prepared_and_restarted_child(tmp_path):
    shell = shutil.which('powershell') or shutil.which('pwsh')
    assert shell, 'PowerShell is required for the host contract'
    data = tmp_path / 'data'
    data.mkdir()
    (tmp_path / 'config').mkdir()
    route = tmp_path / 'config' / 'ledger-route.json'
    atomic_json(route, dict(port=8751, paused=False))
    runner = Path(__file__).resolve().parents[1] / 'tools/start_web_ledger_host.ps1'
    script = tmp_path / 'check.ps1'
    script.write_text('''
function Get-NetTCPConnection { return @() }
function Get-CimInstance { return @() }
function Start-Process {
    param($FilePath,$ArgumentList,$WindowStyle,$PassThru,$WorkingDirectory)
    Write-Output ('ROLE=' + $env:WEBLEDGER_DEPLOYMENT_ROUTE + ';PORT=' + $env:WEBLEDGER_DEPLOYMENT_PORT) | Write-Host
    return [pscustomobject]@{Id=999999;HasExited=$false}
}
''' + f"& '{runner}' -Mode Run -Checkout '{tmp_path}' -DataRoot '{data}' "
        f"-ReviewConfig '{tmp_path / 'review.json'}' -OAuthFile '{tmp_path / 'oauth.json'}' "
        f"-SessionSecretFile '{tmp_path / 'secret.txt'}' -CloudflareConfigPath '{tmp_path / 'tunnel.yml'}' "
        f"-DeploymentRoute '{route}' -TunnelId synthetic -DisableEntry -BoardPort 8752 -SuperviseSeconds 1 -WatchIntervalSeconds 1\n",
        encoding='utf-8')
    result = subprocess.run([shell, '-NoProfile', '-File', str(script)], capture_output=True,
                            encoding='utf-8', errors='replace', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'ROLE={route};PORT=8752' in result.stdout
