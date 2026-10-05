$ErrorActionPreference='Stop'
$root='C:\Users\kkokk\.aside\u\1\sessions\2026-09-30_LYNKlijw6gqix4iY'
$result=@{recorded_at=(Get-Date).ToUniversalTime().ToString('o');read_only=$true;source_root_exists=(Test-Path -LiteralPath $root);candidates=@()}
if ($result.source_root_exists) {
    $result.candidates=@(Get-ChildItem -LiteralPath $root -File -Recurse -Depth 3 | Where-Object {
        $_.Name -match 'reserve|reservation|access|snapshot|export|authority' -and $_.Name -notmatch 'token|secret|auth-cache|db-url|credential|readonly' -and $_.Extension -in '.json','.jsonl','.csv','.xlsx'
    } | ForEach-Object {@{file=$_.FullName.Substring($root.Length + 1);bytes=$_.Length}})
}
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath 'C:\AX\cost\docs\handoff\2026-10-01\reserve-snapshot-location-probe.json' -Encoding UTF8
