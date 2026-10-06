$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\AX\cost'
$arguments = @(
    '-u', 'C:\AX\cost\tools\refresh_review_source.py',
    '--config', 'D:\WebLedgerHost\config\real-review.json',
    '--master', 'C:\AX\cost\ledger\master_ledger.csv',
    '--bundle-root', 'D:\WebLedgerHost\review\refreshed',
    '--source-config', 'C:\AX\cost\config\review_source.json',
    '--timeout', '30', '--attempts', '2', '--max-bytes', '20971520',
    '--watch', '--interval', '300'
)
& 'D:\WebLedgerHost\venv\Scripts\python.exe' @arguments *> 'D:\WebLedgerHost\logs\source-refresh-watch.log'
exit $LASTEXITCODE
