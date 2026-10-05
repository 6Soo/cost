$ErrorActionPreference = 'Stop'
$root = 'C:\AX\cost'
$stamp = Get-Date -Format 'yyyyMMddTHHmmss'
$stdout = "D:\WebLedgerHost\logs\source-refresh-$stamp.out.log"
$stderr = "D:\WebLedgerHost\logs\source-refresh-$stamp.err.log"
$arguments = @(
    '-u', "$root\tools\refresh_review_source.py",
    '--config', 'D:\WebLedgerHost\config\real-review.json',
    '--master', "$root\ledger\master_ledger.csv",
    '--bundle-root', 'D:\WebLedgerHost\review\refreshed',
    '--source-url', 'https://docs.google.com/spreadsheets/d/1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU/export?format=xlsx',
    '--timeout', '30', '--attempts', '2', '--max-bytes', '20971520'
)
$collector = Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -Wait
$result = [ordered]@{
    recorded_at = (Get-Date).ToUniversalTime().ToString('o')
    exit_code = $collector.ExitCode
    output_log = $stdout
    error_log = $stderr
    actual_import_performed = $false
}
if (Test-Path -LiteralPath $stdout) {
    $line = [string](Get-Content -LiteralPath $stdout | Select-Object -Last 1)
    $result.code = ($line | ConvertFrom-Json).code
}
$result | ConvertTo-Json | Set-Content -LiteralPath "$root\docs\handoff\2026-10-01\source-refresh-activation.json" -Encoding UTF8
if ($collector.ExitCode -ne 0) { throw 'SOURCE_REFRESH_ACTIVATION_FAILED' }
