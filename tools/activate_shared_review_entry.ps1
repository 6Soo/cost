$ErrorActionPreference = 'Stop'
$entryPort = 56069
$entryScript = 'C:\AX\cost\tools\serve_review_entry.py'
$legacyScript = 'C:\AX\cost\tools\serve_review.py'
$outputPath = 'C:\AX\cost\docs\handoff\2026-10-01\shared-review-entry-runtime.json'
$listeners = @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq $entryPort)
if ($listeners.Count -gt 1) { throw 'MULTIPLE_ENTRY_LISTENERS' }
if ($listeners.Count -eq 1) {
    if ($listeners[0].LocalAddress -ne '127.0.0.1') { throw 'ENTRY_NOT_LOOPBACK' }
    $entryProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    $command = [string]$entryProcess.CommandLine
    if ($command.Contains($entryScript)) {
        @{ status='ALREADY_SHARED'; port=$entryPort; pid=$entryProcess.ProcessId } | ConvertTo-Json | Set-Content -Encoding UTF8 $outputPath
        exit 0
    }
    if (-not $command.Contains($legacyScript)) { throw 'ENTRY_PROCESS_UNVERIFIED' }
    # The exact legacy script and its live loopback listener establish identity.
    # No decisions are persisted by that read-only server. Source files remain.
    Stop-Process -Id $entryProcess.ProcessId
}
$newEntry = Start-Process -FilePath 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @($entryScript,'--port',"$entryPort") -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -PassThru -RedirectStandardOutput 'D:\WebLedgerHost\logs\shared-review-entry.out.log' -RedirectStandardError 'D:\WebLedgerHost\logs\shared-review-entry.err.log'
@{ status='START_REQUESTED'; port=$entryPort; launcher_pid=$newEntry.Id; destination='https://ledger.foresttour.kr/review' } | ConvertTo-Json | Set-Content -Encoding UTF8 $outputPath
