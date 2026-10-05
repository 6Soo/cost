$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\AX\cost'
$arguments = @(
    '-u', 'C:\AX\cost\tools\refresh_review_source.py',
    '--config', 'D:\WebLedgerHost\config\real-review.json',
    '--master', 'C:\AX\cost\ledger\master_ledger.csv',
    '--bundle-root', 'D:\WebLedgerHost\review\refreshed',
    '--source-url', 'https://docs.google.com/spreadsheets/d/1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU/export?format=xlsx',
    '--timeout', '30', '--attempts', '2', '--max-bytes', '20971520',
    '--watch', '--interval', '15'
)
& 'D:\WebLedgerHost\venv\Scripts\python.exe' @arguments *> 'D:\WebLedgerHost\logs\source-refresh-watch.log'
exit $LASTEXITCODE
