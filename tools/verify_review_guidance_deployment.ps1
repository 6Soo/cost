$ErrorActionPreference = 'Stop'
$guidanceEvidence = 'C:\AX\cost\docs\handoff\2026-10-01\review-guidance-deployment.json'
try {
    $guidanceConfig = Get-Content -LiteralPath 'D:\WebLedgerHost\config\real-review.json' -Raw -Encoding UTF8 | ConvertFrom-Json
    $sourceRoot = 'D:\WebLedgerHost\review\refreshed\3fc09872dec0d692-160b204dc024a387-cde8196ee1f5a2b7'
    foreach ($entry in @(@('snapshot_path','snapshot.xlsx'),@('review_path','review.csv'),@('master_path','master.csv'))) {
        $actual = [IO.Path]::GetFullPath([string]$guidanceConfig.($entry[0]))
        $expected = [IO.Path]::GetFullPath((Join-Path $sourceRoot $entry[1]))
        if (-not [string]::Equals($actual,$expected,[StringComparison]::OrdinalIgnoreCase)) { throw 'ACTIVE_SOURCE_CHANGED' }
    }
    if ((Get-FileHash -LiteralPath $guidanceConfig.snapshot_path -Algorithm SHA256).Hash.ToLower() -ne $guidanceConfig.snapshot_sha256) { throw 'SNAPSHOT_HASH_MISMATCH' }
    $listeners = @(Get-NetTCPConnection -LocalPort 8751 -State Listen -ErrorAction Stop)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw 'LISTENER_UNVERIFIED' }
    $hostProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if ($hostProcess.CommandLine -notlike '*D:\WebLedgerHost\bin\launch_web_ledger.py*' -or $hostProcess.CommandLine -notlike '*C:\AX\cost*') { throw 'RUNNING_CHECKOUT_UNVERIFIED' }
    $codeHashes = @{}
    foreach ($codeFile in @('real_review_ui.py','review_guidance_ui.py','review_guidance.py','ledger_board.py','ledger_store.py','classification_rules.py')) {
        $codeHashes[$codeFile] = (Get-FileHash -LiteralPath ('C:\AX\cost\webapp\'+$codeFile) -Algorithm SHA256).Hash.ToLower()
    }
    $env:PYTHONIOENCODING = 'utf-8'
    & 'C:\Users\kkokk\AppData\Local\Programs\Python\Python314\python.exe' 'C:\AX\cost\tools\verify_review_block_kinds_runtime.py' --checkout 'C:\AX\cost' --source-root $sourceRoot --evidence 'C:\AX\cost\docs\handoff\2026-10-01\review-guidance-actual-evidence.json' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'ACTUAL_SOURCE_RENDER_VERIFICATION_FAILED' }
    $publicStatuses = @{}
    foreach ($route in @('healthz','readyz')) {
        $response = Invoke-WebRequest -Uri ('https://ledger.foresttour.kr/'+$route) -UseBasicParsing -TimeoutSec 15
        $publicStatuses[$route] = [int]$response.StatusCode
    }
    @{success=$true; checked_at=(Get-Date).ToUniversalTime().ToString('o');
      running_checkout='C:\AX\cost'; ledger_pid=$hostProcess.ProcessId;
      active_source_verified=$true; code_hashes=$codeHashes; public_statuses=$publicStatuses;
      authenticated_production_ui_checked=$false; source_decision_writes=0; ledger_row_writes=0} |
      ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $guidanceEvidence -Encoding UTF8
} catch {
    @{success=$false; checked_at=(Get-Date).ToUniversalTime().ToString('o'); error=$_.Exception.Message} |
      ConvertTo-Json | Set-Content -LiteralPath $guidanceEvidence -Encoding UTF8
    exit 1
}
