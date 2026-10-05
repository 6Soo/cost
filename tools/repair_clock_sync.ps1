$ErrorActionPreference='Stop'
$result=@{}
try {
 Set-Service W32Time -StartupType Automatic
 Start-Service W32Time
 $result.resync=@(& w32tm /resync /rediscover 2>&1 | ForEach-Object { "$_" })
 $result.resync_exit=$LASTEXITCODE
 $result.time_status=@(& w32tm /query /status 2>&1 | ForEach-Object { "$_" })
 $result.service=(Get-Service W32Time).Status.ToString()
 & C:\AX\cost\tools\run_user_requested_restart.ps1
 $result.restart_exit=$LASTEXITCODE
} catch { $result.error=$_.Exception.Message }
$result | ConvertTo-Json -Depth 4 | Set-Content C:\AX\cost\docs\handoff\2026-10-01\clock-sync-repair.json -Encoding UTF8
