param(
    [Parameter(Mandatory=$true)][string]$CandidateSha,
    [Parameter(Mandatory=$true)][string]$PreviousSha,
    [Parameter(Mandatory=$true)][string]$ReviewEvidence,
    [switch]$Apply
)
$ErrorActionPreference='Stop'
if($CandidateSha -notmatch '^[a-f0-9]{40}$' -or $PreviousSha -notmatch '^[a-f0-9]{40}$'){throw 'INVALID_SHA'}
if($CandidateSha -eq $PreviousSha){throw 'IDENTICAL_RELEASE_SHA'}
if(-not $Apply) {
    @{status='PREVIEW';candidate_sha=$CandidateSha;previous_sha=$PreviousSha;executed=@();scope='verified code release only; no migrations or data reprocessing'} | ConvertTo-Json -Compress
    return
}
$releaseRoot='D:\WebLedgerHost\releases'
$candidate=Join-Path $releaseRoot $CandidateSha
$previous=Join-Path $releaseRoot $PreviousSha
$evidenceDir=Split-Path -Parent $ReviewEvidence
$review=Get-Content -LiteralPath $ReviewEvidence -Raw -Encoding UTF8 | ConvertFrom-Json
if($review.status -ne 'PASS' -or $review.candidate_sha -ne $CandidateSha){throw 'REVIEW_MISMATCH'}
$audit=Get-Content -LiteralPath (Join-Path $releaseRoot "release-audit-$CandidateSha.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedFiles=(git ls-tree -r --name-only $CandidateSha | Measure-Object).Count
if($audit.release_sha -ne $CandidateSha -or $audit.blob_mismatches -ne 0 -or $audit.tracked_files -ne $expectedFiles){throw 'RELEASE_AUDIT_FAILED'}
if((Get-Content -LiteralPath (Join-Path $candidate 'DEPLOYED_COMMIT') -Raw).Trim() -ne $CandidateSha){throw 'RELEASE_MARKER_FAILED'}
if((Get-Content -LiteralPath (Join-Path $previous 'DEPLOYED_COMMIT') -Raw).Trim() -ne $PreviousSha){throw 'ROLLBACK_MARKER_FAILED'}
$prior=Get-Content -LiteralPath (Join-Path $releaseRoot "deploy-evidence-$PreviousSha.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if(-not $prior.runtime_sha_verified -or $prior.blob_mismatches -ne 0){throw 'PRIOR_RELEASE_UNVERIFIED'}
$protected=Get-Content -LiteralPath (Join-Path $evidenceDir 'protection-before.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if(@($protected.PSObject.Properties | Where-Object {$_.MemberType -eq 'NoteProperty'}).Count -ne 13){throw 'PROTECTION_BASELINE_INVALID'}
$task=Get-ScheduledTask -TaskName WebLedger-Board
if($task.State -ne 'Running' -or !$task.Actions[0].Arguments.Contains($PreviousSha)){throw 'TASK_SHA_INVALID'}
$listeners=@(Get-NetTCPConnection -LocalPort 8751 -State Listen)
if($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1'){throw 'LISTENER_INVALID'}
$proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
if(!$proc.CommandLine.Contains($PreviousSha)){throw 'PROCESS_SHA_INVALID'}
$sourceWasRunning=(Get-ScheduledTask -TaskName WebLedger-SourceRefresh).State -eq 'Running'
$gatePath='D:\WebLedgerHost\config\v2-deploy-gate.json'
$beforeGate=Join-Path $evidenceDir 'gate-before.json'
Copy-Item -LiteralPath $gatePath -Destination $beforeGate
$gate=[ordered]@{status='PASS';candidate_sha=$CandidateSha;previous_sha=$PreviousSha;schema='unchanged';scope=$review.scope;targeted_tests=$review.test_evidence;financial_apply='not included; normal owner authentication and existing single-group approval required';backup_restore='fresh full backup and isolated restore required before task switch'}
[IO.File]::WriteAllText($gatePath,($gate|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
try {
    & (Join-Path $PSScriptRoot 'switch_verified_release.ps1') -PreviousSha $PreviousSha -CandidateSha $CandidateSha -BackupProducts
    $task=Get-ScheduledTask -TaskName WebLedger-Board
    $listeners=@(Get-NetTCPConnection -LocalPort 8751 -State Listen)
    if($task.State -ne 'Running' -or !$task.Actions[0].Arguments.Contains($CandidateSha) -or $listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1'){throw 'POSTDEPLOY_RUNTIME_INVALID'}
    $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if(!$proc.CommandLine.Contains($CandidateSha)){throw 'POSTDEPLOY_PROCESS_SHA_INVALID'}
    $http=[ordered]@{}
    foreach($route in @('/healthz','/readyz','/api/imports/ota','/api/imports/ota/summary','/api/maintenance/refund-pair/synthetic/preview')) {
        try {$code=[int](Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri ('http://127.0.0.1:8751'+$route)).StatusCode}
        catch {$code=[int]$_.Exception.Response.StatusCode}
        $http[$route]=$code
        if(($route -in @('/healthz','/readyz') -and $code -ne 200) -or ($route -like '/api/*' -and $code -ne 401)){throw 'HTTP_SMOKE_FAILED'}
    }
    & 'D:\WebLedgerHost\venv\Scripts\python.exe' (Join-Path $PSScriptRoot 'verify_protected_release_state.py') --evidence-dir $evidenceDir --phase after
    if($LASTEXITCODE -ne 0){throw 'PROTECTED_TABLES_CHANGED'}
    if($sourceWasRunning -and (Get-ScheduledTask -TaskName WebLedger-SourceRefresh).State -ne 'Running'){throw 'SOURCE_TASK_NOT_RESUMED'}
    $backup=Get-ChildItem -LiteralPath 'D:\WebLedgerHost\data\backups' -Directory -Filter 'v2-owner-ui-*' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $restore=Get-Content -LiteralPath (Join-Path $backup.FullName 'restore-evidence.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if(!$restore.live_state_unchanged -or $restore.restored_server_started){throw 'FRESH_RESTORE_INVALID'}
    $evidence=[ordered]@{release_sha=$CandidateSha;prior_sha=$PreviousSha;tracked_files=$audit.tracked_files;blob_mismatches=0;runtime_sha_verified=$true;listener_count=1;http_codes=$http;fresh_backup_restore=$true;protected_tables=13;protected_tables_unchanged_after_deploy=$true;financial_apply='NOT_RUN';recorded_at=(Get-Date).ToUniversalTime().ToString('o')}
    $json=$evidence|ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText((Join-Path $releaseRoot "deploy-evidence-$CandidateSha.json"),$json,[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $evidenceDir 'deploy-evidence.json'),$json,[Text.UTF8Encoding]::new($false))
    $evidence|ConvertTo-Json -Compress -Depth 6
} catch {
    $failedTask=Get-ScheduledTask -TaskName WebLedger-Board
    if($failedTask.Actions[0].Arguments.Contains($CandidateSha)) {
        Copy-Item -LiteralPath $beforeGate -Destination $gatePath -Force
        & (Join-Path $PSScriptRoot 'switch_verified_release.ps1') -PreviousSha $CandidateSha -CandidateSha $PreviousSha
    }
    throw 'DEPLOYMENT_FAILED_VERIFY_PRIOR_RELEASE'
}
