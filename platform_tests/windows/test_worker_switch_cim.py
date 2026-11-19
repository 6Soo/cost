"""Windows-only worker switch/restore contract against a real PowerShell CIM instance.

`switch_continuous_release.ps1` is a PowerShell script and the contract depends on
how Windows PowerShell unrolls a CimInstance returned from a function; a Linux run
has no PowerShell and no CIM, so this belongs on a Windows runner.
"""
import json
import shutil
import subprocess
from pathlib import Path


def test_worker_switch_and_restore_count_a_single_real_cim_process(tmp_path):
    """Windows PowerShell unrolls one CimInstance from a function; Count must still be 1."""
    shell = shutil.which('powershell') or shutil.which('pwsh')
    assert shell, 'PowerShell is required for the switch contract'
    old, new = 'a' * 40, 'b' * 40
    (tmp_path / 'releases' / new / 'tools').mkdir(parents=True)
    (tmp_path / 'releases' / new / 'tools' / 'webledger_worker.py').touch()
    script = Path(__file__).resolve().parents[2] / 'tools/switch_continuous_release.ps1'
    harness = tmp_path / 'worker.ps1'
    harness.write_text(r'''
param($Switch,$Root,$Old,$New)
$ErrorActionPreference='Stop'
$hostRoot=$Root
$source=[IO.File]::ReadAllText($Switch)
foreach($name in 'Get-WorkerProcess','Wait-WorkerRunning','Switch-WorkerRelease','Restore-WorkerRelease') {
    $match=[regex]::Match($source,"(?ms)^function $name\(.*?^}\r?$")
    if(-not $match.Success){throw "MISSING_$name"}
    . ([scriptblock]::Create($match.Value))
}
function Arguments([string]$Sha){'"'+$Root+'\releases\'+$Sha+'\tools\webledger_worker.py" --config "worker.json"'}
$global:action=[pscustomobject]@{Execute='pythonw.exe';Arguments=(Arguments $Old)}
$global:running=[Collections.Generic.List[string]]::new()
$global:running.Add($global:action.Arguments)
function Get-CimInstance { foreach($line in @($global:running)){ New-CimInstance -ClassName Win32_Process -ClientOnly -Property @{CommandLine=$line} } }
function Get-ScheduledTask { [pscustomobject]@{Actions=@($global:action)} }
function Stop-ScheduledTask { $global:running.Clear() }
function Start-ScheduledTask { if($global:running.Count){throw 'ALREADY_RUNNING'}; if(-not $global:refused){$global:running.Add($global:action.Arguments)} }
function Set-ScheduledTask { param($TaskName,$Action) $global:action=$Action }
function New-ScheduledTaskAction { param($Execute,$Argument) [pscustomobject]@{Execute=$Execute;Arguments=$Argument} }
function Start-Sleep {}
$single=Get-WorkerProcess $Old
$singleCount=@(Get-WorkerProcess $Old).Count
$previous=Switch-WorkerRelease $Old $New
$afterSwitch=@($global:running)
Restore-WorkerRelease $previous $New $Old
$afterRestore=@($global:running)
# A worker refused by a foreign single-instance holder exits at once; restore must report it.
$previous=Switch-WorkerRelease $Old $New
$global:refused=$true
$refusal=''
try {Restore-WorkerRelease $previous $New $Old} catch {$refusal=$_.Exception.Message}
[pscustomobject]@{single_count=$singleCount;unrolled_type=$single.GetType().Name;after_switch=$afterSwitch;after_restore=$afterRestore;refusal=$refusal} | ConvertTo-Json -Compress
''', encoding='utf-8')
    result = subprocess.run([shell, '-NoProfile', '-File', str(harness), '-Switch', str(script),
                             '-Root', str(tmp_path), '-Old', old, '-New', new],
                            capture_output=True, encoding='utf-8', errors='replace', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report['unrolled_type'] == 'CimInstance'
    assert report['single_count'] == 1
    switched = report['after_switch'] if isinstance(report['after_switch'], list) else [report['after_switch']]
    restored = report['after_restore'] if isinstance(report['after_restore'], list) else [report['after_restore']]
    assert len(switched) == 1 and new in switched[0]
    assert len(restored) == 1 and old in restored[0]
    assert report['refusal'] == 'PREVIOUS_WORKER_DID_NOT_START'
