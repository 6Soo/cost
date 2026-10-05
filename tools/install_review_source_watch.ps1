$ErrorActionPreference = 'Stop'
$name = 'WebLedger-SourceRefresh'
$description = 'SOURCE-REFRESH-001 managed task: explicit selected source collector.'
$runner = 'C:\AX\cost\tools\watch_review_source.ps1'
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Description -ne $description -or
        $existing.Actions.Count -ne 1 -or
        $existing.Actions[0].Arguments -ne "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"") {
        throw 'SOURCE_TASK_IDENTITY_UNVERIFIED'
    }
} else {
    $account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory 'C:\AX\cost'
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $description
    $existing = Register-ScheduledTask -TaskName $name -InputObject $definition
}
if ($existing.State -ne 'Running') { Start-ScheduledTask -InputObject $existing }
$running = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $task = Get-ScheduledTask -TaskName $name
    if ($task.State -eq 'Running') { $running = $true; break }
    Start-Sleep -Milliseconds 250
}
if (-not $running) { throw 'SOURCE_TASK_NOT_RUNNING' }
[ordered]@{
    recorded_at = (Get-Date).ToUniversalTime().ToString('o')
    task_name = $name
    state = [string]$task.State
    run_level = [string]$task.Principal.RunLevel
    logon_type = [string]$task.Principal.LogonType
    trigger_count = @($task.Triggers).Count
    actual_import_performed = $false
} | ConvertTo-Json | Set-Content -LiteralPath 'C:\AX\cost\docs\handoff\2026-10-01\source-refresh-watch-installed.json' -Encoding UTF8
