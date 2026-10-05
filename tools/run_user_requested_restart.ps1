$ErrorActionPreference = 'Stop'
$resultPath = 'C:\AX\cost\docs\handoff\2026-10-01\user-requested-restart.json'
try {
    $restartOutput = @(& 'C:\AX\cost\tools\restart_real_review_host.ps1')
    $health = Invoke-WebRequest 'http://127.0.0.1:8751/healthz' -UseBasicParsing -TimeoutSec 15
    $ready = Invoke-WebRequest 'http://127.0.0.1:8751/readyz' -UseBasicParsing -TimeoutSec 15
    $tasks = @(Get-ScheduledTask -TaskName 'WebLedger-Board','WebLedger-SourceRefresh' | Select-Object TaskName,State)
    @{success=$true; checked_at=(Get-Date).ToUniversalTime().ToString('o'); restart_output=$restartOutput; health_status=[int]$health.StatusCode; ready_status=[int]$ready.StatusCode; tasks=$tasks} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath $resultPath
} catch {
    @{success=$false; checked_at=(Get-Date).ToUniversalTime().ToString('o'); error_type=$_.Exception.GetType().Name; error=$_.Exception.Message} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $resultPath
    exit 1
}
