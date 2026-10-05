$ErrorActionPreference='Stop'
$sync=@(& w32tm /resync /rediscover 2>&1 | ForEach-Object { "$_" })
Start-Sleep -Seconds 5
@{sync=$sync;status=@(& w32tm /query /status 2>&1 | ForEach-Object { "$_" })} | ConvertTo-Json | Set-Content C:\AX\cost\docs\handoff\2026-10-01\clock-sync-final.json -Encoding UTF8
