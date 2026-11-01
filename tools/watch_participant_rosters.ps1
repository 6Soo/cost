$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\AX\cost'
$python = 'D:\WebLedgerHost\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = 'python.exe' }
$args = @(
    '-u', 'C:\AX\cost\tools\ingest_participant_roster.py',
    '--watch', '--interval', '60',
    '--inbox', 'C:\AX\cost\.local-archive\participant-rosters\inbox',
    '--db', 'C:\AX\cost\.local-archive\participant-rosters\participant.sqlite',
    '--mapping', 'D:\WebLedgerHost\data\google-authority\google-tab-mapping.json',
    '--report-dir', 'C:\AX\cost\.local-archive\participant-rosters\receipts'
)
& $python @args *> 'C:\AX\cost\.local-archive\participant-rosters\watch.log'
exit $LASTEXITCODE
