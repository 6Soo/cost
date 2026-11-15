param([Parameter(Mandatory=$true)][string]$PreviousSha,[Parameter(Mandatory=$true)][string]$CandidateSha,[switch]$BackupProducts,[string]$ParticipantDb='',[string]$ParticipantSyncConfig='')
$ErrorActionPreference='Stop'
if($ParticipantSyncConfig -and ($ParticipantDb -or $ParticipantSyncConfig.Contains('"') -or -not (Test-Path -LiteralPath $ParticipantSyncConfig -PathType Leaf))){throw 'PARTICIPANT_SYNC_CONFIG_INVALID'}
if($ParticipantDb -and ($ParticipantDb.Contains('"') -or -not (Test-Path -LiteralPath $ParticipantDb -PathType Leaf))){throw 'PARTICIPANT_DB_UNAVAILABLE'}
if($PreviousSha -notmatch '^[a-f0-9]{40}$' -or $CandidateSha -notmatch '^[a-f0-9]{40}$'){throw 'SHA_INVALID'}
if(Test-Path -LiteralPath 'D:\WebLedgerHost\config\ledger-route.json' -PathType Leaf) {
    if($BackupProducts -or $ParticipantDb -or $ParticipantSyncConfig){throw 'CONTINUOUS_RELEASE_CODE_ONLY_REQUIRED'}
    & (Join-Path $PSScriptRoot 'switch_continuous_release.ps1') -PreviousSha $PreviousSha -CandidateSha $CandidateSha
    return
}
$previous="D:\WebLedgerHost\releases\$PreviousSha"
$release="D:\WebLedgerHost\releases\$CandidateSha"
$task=Get-ScheduledTask -TaskName WebLedger-Board
$gate=Get-Content D:\WebLedgerHost\config\v2-deploy-gate.json -Raw | ConvertFrom-Json
if($gate.status -ne 'PASS' -or $gate.candidate_sha -ne (Get-Content "$release\DEPLOYED_COMMIT" -Raw).Trim()){throw 'GATE_MISMATCH'}
if($task.Actions.Count -ne 1 -or -not $task.Actions[0].Arguments.Contains("$previous\tools\start_web_ledger_host.ps1")){throw 'TASK_MISMATCH'}
$old=$task.Actions[0]
$resumeSource=$false
$backup='D:\WebLedgerHost\data\backups\v2-owner-ui-'+(Get-Date -Format yyyyMMddTHHmmss)
New-Item -ItemType Directory -Path $backup | Out-Null
Export-ScheduledTask -TaskName WebLedger-Board | Set-Content "$backup\board-task.xml" -Encoding UTF8
function Stop-Children {
    foreach($port in @(8751,56069)){
        $listeners=@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        if($listeners.Count -gt 1){throw 'LISTENER_COUNT'}
        foreach($listener in $listeners){
            $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
            $marker=if($port -eq 8751){'launch_web_ledger.py'}else{'tools\serve_review_entry.py'}
            if($listener.LocalAddress -ne '127.0.0.1' -or -not $proc.CommandLine.Contains($marker)){throw 'PROCESS_MISMATCH'}
            $parent=Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)"
            Stop-Process -Id $proc.ProcessId
            if($parent -and $parent.CommandLine -and $parent.CommandLine.Contains($marker)){Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue}
        }
    }
}
function Wait-Ready {
    for($attempt=0;$attempt -lt 120;$attempt++){
        try{
            $health=Invoke-WebRequest http://127.0.0.1:8751/healthz -UseBasicParsing -TimeoutSec 2
            $ready=Invoke-WebRequest http://127.0.0.1:8751/readyz -UseBasicParsing -TimeoutSec 2
            if($health.StatusCode -eq 200 -and $ready.StatusCode -eq 200){return}
        }catch{}
        Start-Sleep -Milliseconds 500
    }
    throw 'NOT_READY'
}
try{
    Stop-ScheduledTask -TaskName WebLedger-Board
    Start-Sleep -Seconds 1
    Stop-Children
    for($settle=0;$settle -lt 60;$settle++){
        if((Get-ScheduledTask -TaskName WebLedger-Board).State -ne 'Running'){break}
        Start-Sleep -Milliseconds 250
    }
    if((Get-ScheduledTask -TaskName WebLedger-Board).State -eq 'Running'){throw 'TASK_DID_NOT_STOP'}
    if($BackupProducts){
        $resumeSource=(Get-ScheduledTask -TaskName WebLedger-SourceRefresh).State -eq 'Running'
        Stop-ScheduledTask -TaskName WebLedger-SourceRefresh
        foreach($collector in @(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'python.exe' -and $_.CommandLine -like '*C:\AX\cost\tools\refresh_review_source.py*'})){
            Stop-Process -Id $collector.ProcessId -ErrorAction SilentlyContinue
        }
        & D:\WebLedgerHost\venv\Scripts\python.exe "$release\tools\verify_operational_backup_restore.py" --evidence-out "$backup\restore-evidence.json"
        if($LASTEXITCODE -ne 0){throw 'BACKUP_RESTORE_FAILED'}
    }
    $newArguments=$old.Arguments.Replace($previous,$release) -replace '(?i)\s-LauncherPath\s+(?:"[^"]+"|\S+)',''
    if($ParticipantDb){
        if($newArguments -match '(?i)-ParticipantDb\s'){throw 'PARTICIPANT_DB_ALREADY_CONFIGURED'}
        $newArguments+=' -ParticipantDb "'+$ParticipantDb+'"'
    }
    if($ParticipantSyncConfig){
        if($newArguments -match '(?i)-ParticipantSyncConfig\s'){throw 'PARTICIPANT_SYNC_ALREADY_CONFIGURED'}
        $newArguments=$newArguments -replace '(?i) -ParticipantDb "[^"]+"',''
        $newArguments+=' -ParticipantSyncConfig "'+$ParticipantSyncConfig+'"'
    }
    $newArguments=$newArguments -replace '(?i)\s-LifecycleRole\s+(?:"[^"]+"|\S+)', ''
    $new=New-ScheduledTaskAction -Execute $old.Execute -Argument ($newArguments+' -LifecycleRole Board')
    Set-ScheduledTask -TaskName WebLedger-Board -Action $new | Out-Null
    Start-ScheduledTask -TaskName WebLedger-Board
    $startInfo=Get-ScheduledTaskInfo -TaskName WebLedger-Board
    @{phase='candidate_started';candidate_sha=$CandidateSha;state=[string](Get-ScheduledTask -TaskName WebLedger-Board).State;last_result=$startInfo.LastTaskResult;at=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath "$backup/candidate-start.json" -Encoding UTF8
    Wait-Ready
    if($resumeSource){Start-ScheduledTask -TaskName WebLedger-SourceRefresh}
    @{status='PASS';sha=$gate.candidate_sha;previous=$previous;schema='unchanged';backup=$backup} | ConvertTo-Json | Set-Content "$backup\deployment.json" -Encoding UTF8
    Write-Output 'OWNER_UI_DEPLOYMENT_PASS'
}catch{
    @{phase='candidate_failed';candidate_sha=$CandidateSha;error_id=$_.FullyQualifiedErrorId;exception_type=$_.Exception.GetType().Name;state=[string](Get-ScheduledTask -TaskName WebLedger-Board).State;at=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath "$backup/candidate-failure.json" -Encoding UTF8
    Stop-ScheduledTask -TaskName WebLedger-Board -ErrorAction SilentlyContinue
    Stop-Children
    Set-ScheduledTask -TaskName WebLedger-Board -Action $old | Out-Null
    Start-ScheduledTask -TaskName WebLedger-Board
    Wait-Ready
    if($resumeSource){Start-ScheduledTask -TaskName WebLedger-SourceRefresh}
    throw 'OWNER_UI_ROLLED_BACK'
}
