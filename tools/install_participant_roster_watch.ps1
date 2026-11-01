$ErrorActionPreference = 'Stop'
$name = 'COST-InsuranceRosterSync'
$description = 'COST insurance roster inbox sync: idempotent participant registration.'
$runner = 'C:\AX\cost\tools\watch_participant_rosters.ps1'
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Description -ne $description -or $existing.Actions.Count -ne 1 -or
        $existing.Actions[0].Arguments -ne "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"") {
        throw 'INSURANCE_ROSTER_TASK_IDENTITY_UNVERIFIED'
    }
} else {
    $account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory 'C:\AX\cost'
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $description
    Register-ScheduledTask -TaskName $name -InputObject $definition | Out-Null
}
Start-ScheduledTask -TaskName $name
$running = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $task = Get-ScheduledTask -TaskName $name
    if ($task.State -eq 'Running') { $running = $true; break }
    Start-Sleep -Milliseconds 250
}
if (-not $running) { throw 'INSURANCE_ROSTER_TASK_NOT_RUNNING' }
[ordered]@{
    recorded_at = (Get-Date).ToUniversalTime().ToString('o')
    task_name = $name
    state = [string]$task.State
    actual_google_write = $false
    actual_finance_write = $false
} | ConvertTo-Json | Set-Content -LiteralPath 'C:\AX\cost\.local-archive\participant-rosters\watch-installed.json' -Encoding UTF8
