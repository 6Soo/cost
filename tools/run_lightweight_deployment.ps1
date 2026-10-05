$ErrorActionPreference='Stop'
$log='C:\AX\cost\.local-archive\lightweight-20261003\operational-deployment.log'
try {
    & 'C:\AX\cost\tools\run_operational_backup_restore.ps1' -DeployLightweight *> $log
    'LIGHTWEIGHT_MAINTENANCE_FINISHED' | Add-Content -LiteralPath $log
} catch {
    $_.Exception.Message | Add-Content -LiteralPath $log
    'LIGHTWEIGHT_MAINTENANCE_FAILED' | Add-Content -LiteralPath $log
    exit 1
}
