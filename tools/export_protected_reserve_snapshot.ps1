$ErrorActionPreference='Stop'
$root='C:\Users\kkokk\.aside\u\1\sessions\2026-09-30_LYNKlijw6gqix4iY'
$reportPath='C:\AX\cost\docs\handoff\2026-10-01\reserve-protected-export.json'
$previousUrl=$env:TURSO_DATABASE_URL
$previousToken=$env:TURSO_AUTH_TOKEN
try {
    $credential=Get-Content -LiteralPath (Join-Path $root 'reserve-readonly-1day.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $env:TURSO_DATABASE_URL=$credential.url
    $env:TURSO_AUTH_TOKEN=$credential.authToken
    $directory='D:\WebLedgerHost\review\reservation-access'
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $tag=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffffffZ')
    $output=Join-Path $directory "snapshot-$tag.json"
    $log=Join-Path $directory "export-$tag.log"
    Push-Location 'C:\AX\reservation'
    try {
        $ErrorActionPreference='Continue'
        & 'C:\AX\reservation\node_modules\.bin\tsx.cmd' 'scripts\export-access.ts' --output $output *> $log
        $exportExit=$LASTEXITCODE
        $ErrorActionPreference='Stop'
        if ($exportExit -ne 0) {throw 'RESERVE_READ_ONLY_EXPORT_FAILED'}
    } finally {Pop-Location}
    $document=Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json
    $keys=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($person in $document.persons) {
        foreach ($identifier in $person.assignments) { [void]$keys.Add([string]$identifier) }
    }
    @{success=$true;checked_at=(Get-Date).ToUniversalTime().ToString('o');protected_path=$output;file_sha256=(Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant();schema_version=$document.schema_version;snapshot_revision=$document.snapshot_revision;persons=@($document.persons).Count;event_identifier_count=$keys.Count;read_only=$true;operationally_applied=$false} | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding UTF8
} catch {
    @{success=$false;checked_at=(Get-Date).ToUniversalTime().ToString('o');error_type=$_.Exception.GetType().Name;failure_code='RESERVE_READ_ONLY_EXPORT_FAILED';read_only=$true;operationally_applied=$false} | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding UTF8
    exit 1
} finally {
    $env:TURSO_DATABASE_URL=$previousUrl
    $env:TURSO_AUTH_TOKEN=$previousToken
}
