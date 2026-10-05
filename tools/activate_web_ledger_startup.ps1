$ErrorActionPreference = 'Stop'
$checkout = 'C:\AX\cost'
$evidenceRoot = Join-Path $checkout 'docs\handoff\2026-10-01'
$parameters = @{
    Checkout = $checkout
    LauncherPath = 'D:\WebLedgerHost\bin\launch_web_ledger.py'
    DataRoot = 'D:\WebLedgerHost\data'
    ReviewConfig = 'D:\WebLedgerHost\config\real-review.json'
    OAuthFile = 'D:\WebLedgerHost\secrets\google-oauth-pc-client.json'
    SessionSecretFile = 'D:\WebLedgerHost\secrets\session-secret.txt'
    Python = 'D:\WebLedgerHost\venv\Scripts\python.exe'
    CloudflareExe = 'D:\WebLedgerHost\bin\cloudflared.exe'
    CloudflareConfigPath = 'D:\WebLedgerHost\config\candidate.yml'
    TunnelId = '8259194a-39d3-45c2-8b95-c656ce02f3fb'
    RunLevel = 'Highest'
}
Start-Transcript -Path (Join-Path $evidenceRoot 'startup-activation.log') -Force
try {
    & (Join-Path $checkout 'tools\install_web_ledger_startup.ps1') @parameters
    if ($LASTEXITCODE -ne 0) { throw 'STARTUP_PLAN_FAILED' }
    & (Join-Path $checkout 'tools\install_web_ledger_startup.ps1') @parameters -Install
    if ($LASTEXITCODE -ne 0) { throw 'STARTUP_INSTALL_FAILED' }
    $task = Get-ScheduledTask -TaskName 'WebLedger-Board' -ErrorAction Stop
    if ($task.Description -ne 'LOCAL-HOST-002 managed task: web ledger host runner.') {
        throw 'TASK_IDENTITY_MISMATCH'
    }
    Start-ScheduledTask -InputObject $task
    Start-Sleep -Seconds 5
    $task = Get-ScheduledTask -TaskName 'WebLedger-Board'
    $info = Get-ScheduledTaskInfo -TaskName 'WebLedger-Board'
    $result = [ordered]@{
        task_name = $task.TaskName
        state = [string]$task.State
        description = $task.Description
        run_level = [string]$task.Principal.RunLevel
        logon_type = [string]$task.Principal.LogonType
        working_directory = $task.Actions[0].WorkingDirectory
        last_result = $info.LastTaskResult
        login_trigger_count = @($task.Triggers).Count
        observed_at = (Get-Date).ToUniversalTime().ToString('o')
    }
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceRoot 'startup-installed-runtime.json') -Encoding UTF8
} finally {
    Stop-Transcript
}
