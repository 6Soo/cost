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


@pytest.mark.parametrize('services', [1, 0, 2])
def test_gateway_install_changes_only_one_service_and_preserves_origin_comments(tmp_path, services):
    shell = shutil.which('powershell') or shutil.which('pwsh')
    assert shell, 'PowerShell is required for the installation contract'
    source = Path(__file__).resolve().parents[1] / 'tools/install_ledger_gateway.ps1'
    config = tmp_path / 'tunnel.yml'
    original = '# Existing origin http://127.0.0.1:8751\r\ningress:\r\n'
    original += '  - hostname: synthetic.invalid\r\n    service: http://127.0.0.1:8751 # preserve\r\n' * services
    original += '  - service: http_status:404\r\n'
    config.write_bytes(original.encode())
    script = tmp_path / 'check.ps1'
    script.write_text(r'''
param($Source,$Config)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'ConvertTo-GatewayOrigin'},$true)
Invoke-Expression $definition.Extent.Text
try {
    $result=ConvertTo-GatewayOrigin ([IO.File]::ReadAllText($Config))
    [pscustomobject]@{status='PASS';result=$result} | ConvertTo-Json -Compress
} catch {
    if($_.Exception.Message -ne 'ORIGIN_CONFIG_MISMATCH'){throw}
    [pscustomobject]@{status='REJECTED'} | ConvertTo-Json -Compress
}
''', encoding='utf-8')
    result = subprocess.run([shell, '-NoProfile', '-File', str(script), '-Source', str(source),
                             '-Config', str(config)], capture_output=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == ('PASS' if services == 1 else 'REJECTED')
    if services == 1:
        expected = original.replace('service: http://127.0.0.1:8751', 'service: http://127.0.0.1:8790')
        assert report['result'] == expected
    assert config.read_bytes() == original.encode()


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


@pytest.mark.parametrize('failure', ['', 'direct_parent', 'adopted_backend', 'prepare', 'before_listen', 'drain', 'takeover', 'identity', 'candidate_identity', 'multiple_supervisors', 'late_duplicate', 'late_replacement'])
def test_windows_switch_preserves_serving_backend_or_completes_handoff(tmp_path, failure):
    """Execute the switch script with synthetic task/process and route APIs."""
    shell = shutil.which('powershell') or shutil.which('pwsh')
    assert shell, 'PowerShell is required for the switch contract'
    root = tmp_path / 'host'
    (root / 'config').mkdir(parents=True)
    (root / 'releases').mkdir()
    old, new = 'a' * 40, 'b' * 40
    candidate = root / 'releases' / new / 'webapp'
    candidate.mkdir(parents=True)
    (candidate / 'deployment_role.py').touch()
    atomic_json(root / 'config/ledger-route.json', dict(port=8751, paused=False))
    atomic_json(root / 'config/v2-deploy-gate.json', dict(status='PASS', candidate_sha=new))
    source = (Path(__file__).resolve().parents[1] / 'tools/switch_continuous_release.ps1').read_text(encoding='utf-8')
    source = source.replace("$hostRoot='D:\\WebLedgerHost'", f"$hostRoot='{root}'")
    # Only the external controller invocation is replaced; real script flow,
    # task actions, error handling, and filesystem evidence remain exercised.
    source = source.replace('& $python @parameters', 'Invoke-SyntheticRoute @parameters')
    switch = tmp_path / 'switch.ps1'
    switch.write_text(source, encoding='utf-8')
    harness = tmp_path / 'harness.ps1'
    harness.write_text(r'''
param($Switch,$Old,$New,$Failure,$Root)
$ErrorActionPreference='Stop'
$global:events=[Collections.Generic.List[string]]::new()
$global:oldSha=$Old
$global:newSha=$New
$global:board=[pscustomobject]@{State='Running';Actions=@([pscustomobject]@{Execute='powershell';Arguments="-File $Old/start.ps1 -BoardPort 8751"});Principal=@{};Settings=@{}}
$global:prepared=$null
$global:ports=@{8751=$Old}
$global:supervisors=@{8751=$true;8752=$false}
$global:starting=$false
$global:oldStopped=$false
$global:takeoverFailed=$false
function Get-ScheduledTask {
    param($TaskName)
    if($TaskName -eq 'WebLedger-Board'){return $global:board}
    if($TaskName -eq 'WebLedger-Prepared'){return $global:prepared}
}
function New-ScheduledTaskAction {param($Execute,$Argument); [pscustomobject]@{Execute=$Execute;Arguments=$Argument}}
function Register-ScheduledTask {
    param($TaskName,$Action,$Principal,$Settings)
    $global:prepared=[pscustomobject]@{State='Ready';Actions=@($Action)}
}
function Start-ScheduledTask {
    param($TaskName)
    $global:events.Add('start:'+$TaskName)
    $task=Get-ScheduledTask $TaskName
    if($TaskName -eq 'WebLedger-Board' -and $task.Actions[0].Arguments.Contains($global:newSha) -and $Failure -eq 'takeover' -and -not $global:takeoverFailed){$global:takeoverFailed=$true;throw 'SYNTHETIC_TAKEOVER_FAILURE'}
    $task.State='Running'
    $port=if($task.Actions[0].Arguments.Contains('-BoardPort 8752')){8752}else{8751}
    $global:ports[$port]=if($task.Actions[0].Arguments.Contains($global:newSha)){$global:newSha}else{$global:oldSha}
    $global:supervisors[$port]=$true
    if($TaskName -eq 'WebLedger-Prepared' -and $Failure -eq 'before_listen'){$global:starting=$true}
}
function Stop-ScheduledTask {param($TaskName); $global:events.Add('stop:'+$TaskName); if($TaskName -eq 'WebLedger-Board'){$global:oldStopped=$true}; (Get-ScheduledTask $TaskName).State='Ready'}
function Set-ScheduledTask {param($TaskName,$Action); $global:board.Actions=@($Action)}
function Unregister-ScheduledTask {param($TaskName,[switch]$Confirm); $global:prepared=$null}
function Export-ScheduledTask {param($TaskName); '<synthetic/>'}
function Get-NetTCPConnection {
    param($LocalPort,$State)
    if($LocalPort -eq 8790 -or ($global:ports.ContainsKey([int]$LocalPort) -and -not ($LocalPort -eq 8752 -and $global:starting))){
        [pscustomobject]@{LocalAddress='127.0.0.1';OwningProcess=[int]$LocalPort}
    }
}
function Get-CimInstance {
    param($ClassName,$Filter)
    if(-not $Filter){
        if($global:supervisors[8751] -and $Failure -ne 'identity' -and -not ($Failure -eq 'late_replacement' -and $global:oldStopped)){[pscustomobject]@{ProcessId=28751;ParentProcessId=99999;Name='powershell.exe';CommandLine=($global:oldSha+'\tools\start_web_ledger_host.ps1 -BoardPort 8751')}}
        if($Failure -eq 'multiple_supervisors' -or ($Failure -in @('late_duplicate','late_replacement') -and $global:oldStopped)){[pscustomobject]@{ProcessId=12345;ParentProcessId=99999;Name='powershell.exe';CommandLine=($global:oldSha+'\tools\start_web_ledger_host.ps1 -BoardPort 8751')}}
        if($global:supervisors[8752]){[pscustomobject]@{ProcessId=28752;ParentProcessId=99999;Name='powershell.exe';CommandLine=($global:newSha+'\tools\start_web_ledger_host.ps1 -BoardPort 8752 -DisableEntry')}}
        return
    }
    $processId=[int]($Filter -replace 'ProcessId=','')
    if($processId -eq 28751 -and $Failure -eq 'late_replacement' -and $global:oldStopped){return}
    if($processId -eq 8790){$line='ledger_gateway.py';$parent=99999}
    elseif($global:ports.ContainsKey($processId)){$line=$global:ports[$processId]+' launch_web_ledger.py';$parent=$processId+$(if($Failure -eq 'direct_parent'){20000}elseif($Failure -eq 'adopted_backend'){30000}else{10000})}
    elseif($processId -in @(18751,18752) -and $global:ports.ContainsKey($processId-10000)){$line=$global:ports[$processId-10000]+' launch_web_ledger.py';$parent=$processId+10000}
    elseif($processId -in @(28751,28752) -and $global:ports.ContainsKey($processId-20000) -and $global:supervisors[$processId-20000]){
        $line=if(($Failure -eq 'identity' -and $processId -eq 28751) -or ($Failure -eq 'candidate_identity' -and $processId -eq 28752)){'unrelated supervisor'}else{$global:ports[$processId-20000]+'\tools\start_web_ledger_host.ps1 -BoardPort '+($processId-20000)+$(if($processId -eq 28752){' -DisableEntry'}else{''})}
        $parent=99999
    }
    else{return}
    $name=if($processId -in @(28751,28752)){'powershell.exe'}else{'python.exe'}
    [pscustomobject]@{ProcessId=$processId;ParentProcessId=$parent;CommandLine=$line;Name=$name}
}
function Stop-Process {
    param($Id)
    $global:events.Add('kill:'+$Id)
    if($Id -in @(28751,28752)){$global:supervisors[[int]$Id-20000]=$false;if($Id -eq 28752 -and $global:starting){$global:ports.Remove(8752)};return}
    if($global:supervisors[[int]$Id]){return} # A surviving supervisor restarts its backend.
    $global:ports.Remove([int]$Id)
}
function Invoke-WebRequest {
    param($Uri,$TimeoutSec,[switch]$UseBasicParsing)
    if("$Uri" -match ':8752/' -and $Failure -eq 'prepare'){throw 'SYNTHETIC_NOT_READY'}
    [pscustomobject]@{StatusCode=200}
}
function Start-Sleep {}
function Invoke-SyntheticRoute {
    $action=$args[1]
    $global:events.Add('route:'+$action)
    if($action -eq 'pause' -and $Failure -eq 'drain'){throw 'SYNTHETIC_DRAIN_TIMEOUT'}
    $global:LASTEXITCODE=0
}
try { & $Switch -PreviousSha $Old -CandidateSha $New; $outcome='PASS';$errorText='' } catch { $outcome='FAILED';$errorText=$_.Exception.Message }
[pscustomobject]@{outcome=$outcome;error=$errorText;events=@($global:events);board=$global:board.Actions[0].Arguments;old_alive=$global:ports.ContainsKey(8751);new_alive=$global:ports.ContainsKey(8752);prepared_exists=($null -ne $global:prepared)} | ConvertTo-Json -Compress
''', encoding='utf-8')
    result = subprocess.run([shell, '-NoProfile', '-File', str(harness), '-Switch', str(switch),
                             '-Old', old, '-New', new, '-Failure', failure or 'none', '-Root', str(root)],
                            capture_output=True, encoding='utf-8', errors='replace', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert not report['prepared_exists']
    if not failure or failure in ('direct_parent', 'adopted_backend'):
        assert report['outcome'] == 'PASS', report
        assert new in report['board'] and report['new_alive'] and not report['old_alive']
        assert report['events'].index('route:pause') < report['events'].index('kill:8751') < report['events'].index('route:activate')
        assert report['events'].index('kill:28751') < report['events'].index('kill:8751')
        assert 'kill:28752' in report['events']
    else:
        assert report['outcome'] == 'FAILED', report
        if failure in ('multiple_supervisors', 'late_duplicate', 'late_replacement'):
            assert 'SUPERVISOR_AMBIGUOUS' in report['error']
        if failure in ('late_duplicate', 'late_replacement'):
            assert 'kill:28751' not in report['events'] and 'kill:8751' not in report['events']
        assert old in report['board'] and report['old_alive'], report
        if failure == 'candidate_identity':
            assert report['new_alive'] and 'kill:8752' not in report['events']
        else:
            assert not report['new_alive'], report
        if failure in ('prepare', 'before_listen', 'drain', 'identity', 'candidate_identity', 'multiple_supervisors'):
            assert 'stop:WebLedger-Board' not in report['events'], report
