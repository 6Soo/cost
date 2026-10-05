$ErrorActionPreference = 'Stop'
$managedTask = Get-ScheduledTask -TaskName 'WebLedger-Board' -ErrorAction SilentlyContinue
$resumeSupervisor = $false
if ($managedTask) {
    if ($managedTask.Description -ne 'LOCAL-HOST-002 managed task: web ledger host runner.' -or
        $managedTask.Actions[0].Arguments -notmatch '(?i)(^|\s)"?C:\\AX\\cost\\tools\\start_web_ledger_host\.ps1"?(\s|$)') {
        throw 'SUPERVISOR_IDENTITY_UNVERIFIED'
    }
    if ($managedTask.State -eq 'Running') {
        Stop-ScheduledTask -InputObject $managedTask
        $resumeSupervisor = $true
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if ((Get-ScheduledTask -TaskName 'WebLedger-Board').State -ne 'Running') { break }
            Start-Sleep -Milliseconds 200
        }
        if ((Get-ScheduledTask -TaskName 'WebLedger-Board').State -eq 'Running') {
            throw 'SUPERVISOR_STOP_FAILED'
        }
    }
}
try {
$listeners = @(Get-NetTCPConnection -LocalPort 8751 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 1) { throw 'MULTIPLE_LISTENERS' }
if ($listeners.Count -eq 1) {
    $ledgerChild = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if ($ledgerChild.CommandLine -notlike '*D:\WebLedgerHost\bin\launch_web_ledger.py*') {
        throw 'LEDGER_PROCESS_IDENTITY_UNVERIFIED'
    }
    $ledgerParent = Get-CimInstance Win32_Process -Filter "ProcessId=$($ledgerChild.ParentProcessId)"
    Stop-Process -Id $ledgerChild.ProcessId
    if ($ledgerParent.CommandLine -like '*D:\WebLedgerHost\bin\launch_web_ledger.py*') {
        Stop-Process -Id $ledgerParent.ProcessId -ErrorAction SilentlyContinue
    }
}
$previousReviewConfig = $env:WEBLEDGER_REVIEW_CONFIG
# The reservation source configuration is restored and set the same way the
# review configuration is, and from the same kind of explicit path. Without
# this the direct restart would drop it: the launcher reads the value from
# the environment, and a restart that starts the process without one produces
# a host whose source configuration is whatever this shell happened to
# inherit. Absent stays absent — the link screen shows the
# configuration-required state and nothing else — so nothing here searches
# for a source or invents one.
$previousReserveSource = $env:WEBLEDGER_RESERVE_SOURCE
$reserveSourceConfig = 'D:\WebLedgerHost\config\reserve-source.json'
$launchTag = Get-Date -Format 'yyyyMMddTHHmmss'
try {
    $env:WEBLEDGER_REVIEW_CONFIG = 'D:\WebLedgerHost\config\real-review.json'
    if (Test-Path -LiteralPath $reserveSourceConfig -PathType Leaf) {
        # Read once and handed over as one line. A file that is not there is left
        # absent rather than replaced with an empty value: an empty value would
        # read as a configuration with nothing in it instead of no
        # configuration at all.
        $reserveSourceText = Get-Content -LiteralPath $reserveSourceConfig -Raw -Encoding UTF8
        $reserveSourceJson = $reserveSourceText | ConvertFrom-Json
        foreach ($field in @('path', 'file_sha256', 'digest')) {
            $value = $reserveSourceJson.$field
            if (-not $value -or ($value -isnot [string]) -or -not $value.Trim()) {
                throw 'RESERVE_SOURCE_CONFIG_INVALID'
            }
        }
        $env:WEBLEDGER_RESERVE_SOURCE = ($reserveSourceJson | ConvertTo-Json -Compress -Depth 4)
    } else {
        Remove-Item Env:\WEBLEDGER_RESERVE_SOURCE -ErrorAction SilentlyContinue
    }
    $app = Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @('-u','D:\WebLedgerHost\bin\launch_web_ledger.py','--checkout','C:\AX\cost','--data-root','D:\WebLedgerHost\data','--oauth-file','D:\WebLedgerHost\secrets\google-oauth-pc-client.json','--session-secret-file','D:\WebLedgerHost\secrets\session-secret.txt') -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -RedirectStandardOutput "D:\WebLedgerHost\logs\real-review-final-$launchTag.out.log" -RedirectStandardError "D:\WebLedgerHost\logs\real-review-final-$launchTag.err.log" -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $newListeners = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8751 })
        if ($newListeners.Count -eq 1 -and $newListeners[0].LocalAddress -eq '127.0.0.1') {
            $newProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($newListeners[0].OwningProcess)"
            if ($newProcess.CommandLine -like '*D:\WebLedgerHost\bin\launch_web_ledger.py*') {
                $ready = $true
                break
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'LEDGER_RESTART_NOT_READY' }
    Write-Output "LEDGER_LAUNCHER_STARTED $($app.Id)"
} finally {
    $env:WEBLEDGER_REVIEW_CONFIG = $previousReviewConfig
    if ($null -eq $previousReserveSource) {
        Remove-Item Env:\WEBLEDGER_RESERVE_SOURCE -ErrorAction SilentlyContinue
    } else {
        $env:WEBLEDGER_RESERVE_SOURCE = $previousReserveSource
    }
}
} finally {
    if ($resumeSupervisor) { Start-ScheduledTask -InputObject $managedTask }
}
