param([switch]$InferAssignments)
$ErrorActionPreference='Stop'
$log='C:\AX\cost\.local-archive\lightweight-20261003\rule-recovery\operational.log'
try {
    & 'C:\AX\cost\tools\run_operational_backup_restore.ps1' -ApplyHistoryRules -InferAssignments:$InferAssignments *> $log
    'HISTORY_RULES_MAINTENANCE_FINISHED' | Add-Content -LiteralPath $log
} catch {
    $_.Exception.Message | Add-Content -LiteralPath $log
    'HISTORY_RULES_MAINTENANCE_FAILED' | Add-Content -LiteralPath $log
    exit 1
}
