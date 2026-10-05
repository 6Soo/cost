$ErrorActionPreference = 'Stop'
$result = 'C:\AX\cost\.local-archive\lightweight-20261003\operational-snapshot-result.txt'
try {
    $env:PYTHONIOENCODING='utf-8'
    & 'D:\WebLedgerHost\venv\Scripts\python.exe' 'C:\AX\cost\tools\lightweight_operational_snapshot.py' *> $result
    if ($LASTEXITCODE -ne 0) { throw 'SNAPSHOT_FAILED' }
} catch {
    'OPERATIONAL_SNAPSHOT_FAILED' | Add-Content -LiteralPath $result
    exit 1
}
