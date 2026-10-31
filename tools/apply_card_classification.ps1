param([Parameter(Mandatory=$true)][string]$ReleaseSha, [switch]$Apply, [switch]$Reconsider, [string]$EvidenceCache)
$ErrorActionPreference='Stop'
if($ReleaseSha -notmatch '^[a-f0-9]{40}$'){throw 'INVALID_SHA'}
$release=Join-Path 'D:/WebLedgerHost/releases' $ReleaseSha
$python='D:/WebLedgerHost/venv/Scripts/python.exe'
$script=Join-Path $release 'tools/complete_card_classification.py'
if((Get-Content -LiteralPath (Join-Path $release 'DEPLOYED_COMMIT') -Raw).Trim() -ne $ReleaseSha){throw 'RELEASE_MARKER_INVALID'}
$reviewArguments=@()
if($Reconsider){$reviewArguments += '--reconsider'}
if($EvidenceCache){$reviewArguments += @('--evidence-cache',$EvidenceCache)}
if(-not $Apply){ & $python $script @reviewArguments; exit $LASTEXITCODE }
$deploy=Get-Content -LiteralPath "D:/WebLedgerHost/releases/deploy-evidence-$ReleaseSha.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if(!$deploy.runtime_sha_verified -or $deploy.blob_mismatches -ne 0){throw 'UNVERIFIED_RELEASE'}
$boardTask=Get-ScheduledTask -TaskName WebLedger-Board
if(!$boardTask.Actions[0].Arguments.Contains($ReleaseSha)){throw 'RUNTIME_SHA_MISMATCH'}
$evidence=Join-Path 'D:/WebLedgerHost/data/backups' ('card-classification-'+(Get-Date -Format yyyyMMddTHHmmssfff))
New-Item -ItemType Directory -Path $evidence | Out-Null
$resume=@()
try {
    foreach($name in @('WebLedger-Board','WebLedger-SourceRefresh')){
        $task=Get-ScheduledTask -TaskName $name
        Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $evidence ($name+'.xml')) -Encoding UTF8
        if($task.State -eq 'Running'){$resume += $name; Stop-ScheduledTask -TaskName $name}
    }
    $listeners=@(Get-NetTCPConnection -LocalPort 8751 -State Listen -ErrorAction SilentlyContinue)
    if($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1'){throw 'LISTENER_UNVERIFIED'}
    $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if(!$proc.CommandLine.Contains('D:\WebLedgerHost\bin\launch_web_ledger.py') -or !$proc.CommandLine.Contains($ReleaseSha)){throw 'PROCESS_UNVERIFIED'}
    $parent=Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)"
    Stop-Process -Id $proc.ProcessId
    if($parent -and $parent.CommandLine -and $parent.CommandLine.Contains('D:\WebLedgerHost\bin\launch_web_ledger.py')){Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue}
    foreach($collector in @(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'python.exe' -and $_.CommandLine -like '*C:\AX\cost\tools\refresh_review_source.py*'})){
        Stop-Process -Id $collector.ProcessId -ErrorAction SilentlyContinue
    }
    for($attempt=0;$attempt -lt 40;$attempt++){
        if(@(Get-ScheduledTask -TaskName WebLedger-Board,WebLedger-SourceRefresh | Where-Object State -eq Running).Count -eq 0){break}
        Start-Sleep -Milliseconds 250
    }
    $backup=Join-Path $evidence 'backup-restore.json'
    & $python (Join-Path $release 'tools/verify_operational_backup_restore.py') --evidence-out $backup
    if($LASTEXITCODE -ne 0){throw 'FRESH_BACKUP_RESTORE_FAILED'}
    Write-Output 'CLASSIFICATION_BACKUP_RESTORE_PASS'
    $previewText= & $python $script @reviewArguments --report (Join-Path $evidence 'preview.json')
    if($LASTEXITCODE -ne 0){throw 'CLASSIFICATION_PREVIEW_FAILED'}
    $preview=$previewText | ConvertFrom-Json
    if($preview.status -ne 'PREVIEW' -or !$preview.protected_source_and_user_data_unchanged){throw 'CLASSIFICATION_PREVIEW_UNVERIFIED'}
    $appliedText= & $python $script @reviewArguments --apply --expected-digest $preview.digest --backup-evidence $backup --report (Join-Path $evidence 'applied.json')
    if($LASTEXITCODE -ne 0){throw 'CLASSIFICATION_APPLY_FAILED'}
    $applied=$appliedText | ConvertFrom-Json
    if($applied.status -ne 'APPLIED' -or $applied.after.unclassified_purchases -ne 0 -or $applied.after.unclassified_all_directions -ne 0){throw 'CLASSIFICATION_RESULT_UNVERIFIED'}
    $repeatText= & $python $script @reviewArguments --report (Join-Path $evidence 'repeat-preview.json')
    if($LASTEXITCODE -ne 0 -or ($repeatText|ConvertFrom-Json).to_classify -ne 0){throw 'CLASSIFICATION_REPEAT_NOT_NOOP'}
    @{status='PASS';release_sha=$ReleaseSha;evidence_directory=$evidence;result=$applied;repeat_to_classify=0} | ConvertTo-Json -Depth 8 -Compress
} finally {
    foreach($name in $resume){Start-ScheduledTask -TaskName $name}
    if($resume -contains 'WebLedger-Board'){
        $ready=$false
        for($attempt=0;$attempt -lt 60;$attempt++){
            try{
                $health=Invoke-WebRequest 'http://127.0.0.1:8751/healthz' -UseBasicParsing -TimeoutSec 2
                $probe=Invoke-WebRequest 'http://127.0.0.1:8751/readyz' -UseBasicParsing -TimeoutSec 2
                if($health.StatusCode -eq 200 -and $probe.StatusCode -eq 200){$ready=$true;break}
            }catch{}
            Start-Sleep -Milliseconds 500
        }
        if(!$ready){throw 'CLASSIFICATION_APPLIED_HOST_NOT_READY'}
    }
}
