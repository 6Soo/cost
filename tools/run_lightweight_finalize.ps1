$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
$log='C:\AX\cost\.local-archive\lightweight-20261003\operational-finalize.log'
try {
    & 'C:\AX\cost\tools\run_operational_backup_restore.ps1' -RefreshCardCategories *> $log
    & 'D:\WebLedgerHost\venv\Scripts\python.exe' 'C:\AX\cost\tools\verify_lightweight_runtime.py' *>> $log
    if ($LASTEXITCODE -ne 0) { throw 'RUNTIME_VERIFICATION_FAILED' }
    'LIGHTWEIGHT_FINALIZED' | Add-Content -LiteralPath $log
} catch {
    $_.Exception.Message | Add-Content -LiteralPath $log
    'LIGHTWEIGHT_FINALIZE_FAILED' | Add-Content -LiteralPath $log
    exit 1
}
