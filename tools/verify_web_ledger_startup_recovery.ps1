$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'WebLedger-Board'
if ($task.State -ne 'Running' -or $task.Description -ne 'LOCAL-HOST-002 managed task: web ledger host runner.') {
    throw 'SUPERVISOR_NOT_RUNNING'
}
$listeners = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 56069 })
if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') {
    throw 'ENTRY_LISTENER_UNVERIFIED'
}
$entryProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listeners[0].OwningProcess)"
$marker = '(?i)(^|\s)"?C:\\AX\\cost\\tools\\serve_review_entry\.py"?(\s|$)'
if ($entryProcess.CommandLine -notmatch $marker -or $entryProcess.CommandLine -notmatch '(^|\s)--port\s+56069(\s|$)') {
    throw 'ENTRY_PROCESS_UNVERIFIED'
}
$beforeId = $entryProcess.ProcessId
$tunnelsBefore = @(Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'").Count
$boardBefore = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8751 })[0].OwningProcess
Stop-Process -Id $beforeId -ErrorAction Stop
$recoveredId = 0
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 2
    $current = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 56069 })
    if ($current.Count -eq 1 -and $current[0].OwningProcess -ne $beforeId) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($current[0].OwningProcess)"
        if ($current[0].LocalAddress -eq '127.0.0.1' -and $process.CommandLine -match $marker) {
            $recoveredId = $process.ProcessId
            break
        }
    }
}
$result = [ordered]@{
    entry_before_pid = $beforeId
    entry_recovered_pid = $recoveredId
    recovery_verified = ($recoveredId -gt 0)
    board_pid_unchanged = (@(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8751 })[0].OwningProcess -eq $boardBefore)
    tunnel_count_before = $tunnelsBefore
    tunnel_count_after = @(Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'").Count
    task_state = [string](Get-ScheduledTask -TaskName 'WebLedger-Board').State
    observed_at = (Get-Date).ToUniversalTime().ToString('o')
}
$result | ConvertTo-Json | Set-Content -LiteralPath 'C:\AX\cost\docs\handoff\2026-10-01\startup-recovery-runtime.json' -Encoding UTF8
if ($recoveredId -eq 0) { throw 'ENTRY_RECOVERY_FAILED' }
