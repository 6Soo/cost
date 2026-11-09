"""Focused real-process checks for the WebLedger Windows lifetime helper."""

import os
import json
import shutil
import ctypes
from ctypes import wintypes
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.webledger_windows_lifecycle import mutex_name


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "webledger_windows_lifecycle.py"


def launch(port, code, role="Board"):
    return subprocess.Popen(
        [sys.executable, str(HELPER), "--role", role, "--port", str(port), "--",
         sys.executable, "-c", code],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def wait_for(process, timeout=8):
    return process.wait(timeout=timeout)


def test_mutex_is_port_scoped_for_intentional_blue_green_overlap():
    assert mutex_name(8751).endswith(".8751")
    assert mutex_name(8751) != mutex_name(8752)
    code = "import time; time.sleep(1)"
    first = launch(18751, code)
    time.sleep(.25)  # allow the suspended creator to publish its mutex
    second = launch(18751, code)
    prepared = launch(18752, code, role="Prepared")
    try:
        assert wait_for(second) == 75
        assert wait_for(first) == 0
        assert wait_for(prepared) == 0
    finally:
        for process in (first, second, prepared):
            if process.poll() is None:
                process.kill()


def test_parent_stop_cleans_descendant_tree(tmp_path):
    marker = tmp_path / 'tree.json'
    child_code = ("import subprocess,sys,time,json,os; from pathlib import Path; "
                  "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                  f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(),child.pid])); "
                  "time.sleep(60)")
    parent = launch(18751, child_code)
    try:
        deadline = time.monotonic() + 8
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.exists(), 'owned child must start before stop is tested'
        descendants = json.loads(marker.read_text())
        parent.kill()
        parent.wait(timeout=5)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]

        def running(pid):
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = wintypes.DWORD()
                assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                return code.value == 259
            finally:
                kernel.CloseHandle(handle)

        deadline = time.monotonic() + 5
        while any(running(pid) for pid in descendants) and time.monotonic() < deadline:
            time.sleep(.05)
        assert not any(running(pid) for pid in descendants), 'owned descendant survived parent stop'
        probe = launch(18751, "pass")
        assert wait_for(probe) == 0
    finally:
        if parent.poll() is None:
            parent.kill()


def test_child_crash_and_restart_releases_mutex():
    crashed = launch(18752, "raise SystemExit(23)")
    assert wait_for(crashed) == 23
    restarted = launch(18752, "pass")
    assert wait_for(restarted) == 0


def test_stop_cleanup_is_repeatable():
    for port in (18753, 18754, 18755):
        worker = launch(port, "import time; time.sleep(60)")
        try:
            time.sleep(.2)
            worker.kill()
            worker.wait(timeout=5)
        finally:
            if worker.poll() is None:
                worker.kill()
        assert wait_for(launch(port, "pass")) == 0


def test_absolute_task_entry_runs_from_unrelated_working_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / 'tools/webledger_task_entry.pyw'),
         '--role', 'Prepared', '--port', '18756', '--', sys.executable, '-c',
         'raise SystemExit(17)'], cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 17, result.stdout + result.stderr


@pytest.mark.parametrize('mode', ['legacy', 'owned', 'rollback', 'unknown'])
def test_task_action_migrates_emergency_wrapper_without_fixed_mutex(tmp_path, mode):
    script = tmp_path / 'action.ps1'
    source = ROOT / 'tools/switch_continuous_release.ps1'
    script.write_text(r'''
param($Source,$Mode)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'ConvertTo-OwnedTaskArguments'},$true)
Invoke-Expression $definition.Extent.Text
$entry='D:\WebLedgerHost\releases\'+('a'*40)+'\tools\webledger_task_entry.pyw'
$python='C:\Python\pythonw.exe'
$command='"C:\ProgramData\AX\WindowlessTasks\windowless_command.pyw" "C:\logs\board.log" "-" "C:\Windows\powershell.exe" -File D:\host.ps1 -BoardPort 8751'
$arguments=$command.Replace('windowless_command.pyw','webledger_board_job.pyw')
if($Mode -eq 'owned'){$arguments='"'+$entry+'" --role Board --port 8752 -- "'+$python+'" '+$command}
if($Mode -eq 'unknown'){$arguments='"C:\unknown\webledger_board_job.pyw" -File D:\host.ps1'}
$argumentEntry=$entry
if($Mode -eq 'rollback'){
 $argumentEntry='D:\WebLedgerHost\releases\'+('b'*40)+'\tools\webledger_task_entry.pyw'
 $arguments='"'+$argumentEntry+'" --role Board --port 8752 -- "'+$python+'" '+$command
}
try {
 $result=ConvertTo-OwnedTaskArguments $python $arguments $entry 8751 'Prepared' $argumentEntry
 @{result=$result;status='PASS'}|ConvertTo-Json -Compress
}catch{
 if($Mode -ne 'unknown'){throw}
 @{status='REJECTED';reason=$_.Exception.Message}|ConvertTo-Json -Compress
}
''', encoding='utf-8')
    result = subprocess.run([shutil.which('powershell'), '-NoProfile', '-File', str(script),
                             '-Source', str(source), '-Mode', mode], capture_output=True,
                            encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    if mode == 'unknown':
        assert report['status'] == 'REJECTED'
        return
    value = report['result']
    assert value.count('webledger_task_entry.pyw') == 1
    assert 'webledger_board_job.pyw' not in value
    assert 'windowless_command.pyw' in value and 'C:\\logs\\board.log' in value
    assert '--role Prepared --port 8751 --' in value
    assert ('a' * 40) in value and ('b' * 40) not in value


def test_owner_log_replaces_the_hidden_console_wrapper(tmp_path):
    log = tmp_path / "logs" / "board.log"
    result = subprocess.run(
        [sys.executable, str(HELPER), "--role", "Board", "--port", "18761", "--log", str(log), "--",
         sys.executable, "-c", "import sys; print('to stdout'); print('to stderr', file=sys.stderr); raise SystemExit(3)"],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 3, result.stdout + result.stderr
    assert result.stdout == "" and result.stderr == ""
    text = log.read_text(encoding="utf-8")
    assert text.lstrip().startswith("START ")
    assert "to stdout" in text and "to stderr" in text
    assert text.rstrip().endswith("EXIT 3")


def test_owner_log_rotates_once_past_its_limit(tmp_path):
    from tools.webledger_windows_lifecycle import LOG_LIMIT_BYTES
    log = tmp_path / "board.log"
    log.write_bytes(b"x" * (LOG_LIMIT_BYTES + 1))
    subprocess.run([sys.executable, str(HELPER), "--role", "Board", "--port", "18762", "--log", str(log), "--",
                    sys.executable, "-c", "print('fresh')"], cwd=ROOT, check=True, timeout=20)
    assert (tmp_path / "board.previous.log").stat().st_size == LOG_LIMIT_BYTES + 1
    assert "fresh" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize('owner_logs', [True, False])
def test_task_action_moves_the_console_wrapper_into_an_owner_that_logs(tmp_path, owner_logs):
    script = tmp_path / 'action.ps1'
    source = ROOT / 'tools/switch_continuous_release.ps1'
    script.write_text(r'''
param($Source,[string]$OwnerLogs)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'ConvertTo-OwnedTaskArguments'},$true)
Invoke-Expression $definition.Extent.Text
$entry='D:\WebLedgerHost\releases\'+('a'*40)+'\tools\webledger_task_entry.pyw'
$python='C:/Python/pythonw.exe'
$wrapped='"'+$entry+'" --role Board --port 8752 -- "'+$python+'" "C:\ProgramData\AX\WindowlessTasks\windowless_command.pyw" "C:\logs\board.log" "-" "C:\Windows\powershell.exe" -File D:\host.ps1 -BoardPort 8752'
$logged='"'+$entry+'" --role Board --port 8752 --log "C:\logs\board.log" -- "C:\Windows\powershell.exe" -File D:\host.ps1 -BoardPort 8752'
$capable=$OwnerLogs -eq 'True'
@{
 from_wrapped=(ConvertTo-OwnedTaskArguments $python $wrapped $entry 8751 'Board' $entry $capable);
 from_logged=(ConvertTo-OwnedTaskArguments $python $logged $entry 8751 'Board' $entry $capable)
}|ConvertTo-Json -Compress
''', encoding='utf-8')
    result = subprocess.run([shutil.which('powershell'), '-NoProfile', '-File', str(script),
                             '-Source', str(source), '-OwnerLogs', str(owner_logs)], capture_output=True,
                            encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    for value in report.values():
        assert '--role Board --port 8751' in value
        assert value.endswith('"C:\\Windows\\powershell.exe" -File D:\\host.ps1 -BoardPort 8752')
        if owner_logs:
            assert '--port 8751 --log "C:\\logs\\board.log" -- "C:\\Windows\\powershell.exe"' in value
            assert 'windowless_command.pyw' not in value
        else:
            assert '--log' not in value
            assert '-- "C:/Python/pythonw.exe" "C:\\ProgramData\\AX\\WindowlessTasks\\windowless_command.pyw" "C:\\logs\\board.log" "-" "C:\\Windows\\powershell.exe"' in value
