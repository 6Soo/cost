$ErrorActionPreference = 'Stop'
$blockEvidencePath = 'C:\AX\cost\docs\handoff\2026-10-01\review-block-kind-deployment.json'
try {
    $blockConfig = Get-Content -LiteralPath 'D:\WebLedgerHost\config\real-review.json' -Raw -Encoding UTF8 | ConvertFrom-Json
    $verifiedRoot = 'D:\WebLedgerHost\review\refreshed\3fc09872dec0d692-160b204dc024a387-cde8196ee1f5a2b7'
    $sourceMatches = $true
    foreach ($entry in @(@('snapshot_path', 'snapshot.xlsx'), @('review_path', 'review.csv'), @('master_path', 'master.csv'))) {
        $actualSource = [IO.Path]::GetFullPath([string]$blockConfig.($entry[0]))
        $expectedSource = [IO.Path]::GetFullPath((Join-Path $verifiedRoot $entry[1]))
        if (-not [string]::Equals($actualSource, $expectedSource, [StringComparison]::OrdinalIgnoreCase)) { $sourceMatches = $false }
    }
    if (-not $sourceMatches) { throw 'ACTIVE_SOURCE_CHANGED_SINCE_VERIFICATION' }
    if ((Get-FileHash -LiteralPath $blockConfig.snapshot_path -Algorithm SHA256).Hash.ToLower() -ne $blockConfig.snapshot_sha256) { throw 'ACTIVE_SNAPSHOT_HASH_MISMATCH' }
    $listeners = @(Get-NetTCPConnection -LocalPort 8751 -State Listen -ErrorAction Stop)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw 'LEDGER_LISTENER_IDENTITY_UNVERIFIED' }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if ($process.CommandLine -notlike '*D:\WebLedgerHost\bin\launch_web_ledger.py*' -or $process.CommandLine -notlike '*C:\AX\cost*') { throw 'LEDGER_PROCESS_IDENTITY_UNVERIFIED' }
    $codeHashes = @{}
    foreach ($codeFile in @('review_context.py', 'real_review_ui.py', 'ledger_design.py')) {
        $codeHashes[$codeFile] = (Get-FileHash -LiteralPath ('C:\AX\cost\webapp\' + $codeFile) -Algorithm SHA256).Hash.ToLower()
    }
    $publicStatuses = @{}
    foreach ($path in @('healthz', 'readyz')) {
        $response = Invoke-WebRequest -Uri ('https://ledger.foresttour.kr/' + $path) -UseBasicParsing -TimeoutSec 15
        $publicStatuses[$path] = [int]$response.StatusCode
    }
    @{success=$true; checked_at=(Get-Date).ToUniversalTime().ToString('o');
      active_source_matches_verified_bundle=$true; snapshot_hash_verified=$true;
      running_checkout='C:\AX\cost'; ledger_pid=$process.ProcessId;
      code_hashes=$codeHashes; public_statuses=$publicStatuses;
      authenticated_production_ui_checked=$false; data_writes=0} |
      ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $blockEvidencePath -Encoding UTF8
} catch {
    @{success=$false; checked_at=(Get-Date).ToUniversalTime().ToString('o'); error=$_.Exception.Message} |
      ConvertTo-Json | Set-Content -LiteralPath $blockEvidencePath -Encoding UTF8
    exit 1
}
