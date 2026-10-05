$ErrorActionPreference='Stop'
$root='C:\Users\kkokk\.aside\u\1\sessions\2026-09-30_LYNKlijw6gqix4iY'
$report=@{checked_at=(Get-Date).ToUniversalTime().ToString('o');read_only=$true;files=@()}
foreach ($name in @('reserve-readonly-1day.json','reserve-db-url.json')) {
    $path=Join-Path $root $name
    $item=@{name=$name;exists=(Test-Path -LiteralPath $path)}
    if ($item.exists) {
        $data=Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $item.keys=@($data.PSObject.Properties.Name)
    }
    $report.files+= $item
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath 'C:\AX\cost\docs\handoff\2026-10-01\reserve-export-credential-shape.json' -Encoding UTF8
