$ErrorActionPreference='Stop'
$result=@{checked_at=(Get-Date).ToUniversalTime().ToString('o');read_only=$true;operational_changes=$false;tasks=@();source=@{}}
foreach ($name in @('WebLedger-Board','WebLedger-SourceRefresh')) {
    $task=Get-ScheduledTask -TaskName $name
    $info=Get-ScheduledTaskInfo -TaskName $name
    $result.tasks+=@{name=$name;state=$task.State.ToString();description=$task.Description;action_count=@($task.Actions).Count;last_task_result=$info.LastTaskResult;logon_trigger_count=@($task.Triggers | Where-Object {$_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger'}).Count;reserve_config_argument_present=($task.Actions[0].Arguments -match '-ReserveSourceConfig\s+')}
}
$validation=Get-Content -LiteralPath 'C:\AX\cost\docs\handoff\2026-10-01\reserve-protected-validation.json' -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $validation.success) {throw 'RESERVE_PREPARED_VALIDATION_MISSING'}
$prepared=$validation.prepared_config
$config=Get-Content -LiteralPath $prepared -Raw -Encoding UTF8 | ConvertFrom-Json
$result.source=@{prepared_config_exists=(Test-Path -LiteralPath $prepared -PathType Leaf);snapshot_exists=(Test-Path -LiteralPath $config.path -PathType Leaf);snapshot_hash_matches=((Get-FileHash -LiteralPath $config.path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $config.file_sha256);config_file_sha256=(Get-FileHash -LiteralPath $prepared -Algorithm SHA256).Hash.ToLowerInvariant();runtime_config_exists=(Test-Path -LiteralPath 'D:\WebLedgerHost\config\reserve-source.json' -PathType Leaf);persons=$validation.persons;source_identifiers=$validation.unique_source_identifiers;available_targets=$validation.available_targets}
$listeners=@(Get-NetTCPConnection -LocalPort 8751 -State Listen)
$result.board_listener_count=$listeners.Count
$result.board_loopback=($listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq '127.0.0.1')
$result.health_status=[int](Invoke-WebRequest 'http://127.0.0.1:8751/healthz' -UseBasicParsing -TimeoutSec 15).StatusCode
$result.ready_status=[int](Invoke-WebRequest 'http://127.0.0.1:8751/readyz' -UseBasicParsing -TimeoutSec 15).StatusCode
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'C:\AX\cost\docs\handoff\2026-10-01\reserve-integration-readiness.json' -Encoding UTF8
