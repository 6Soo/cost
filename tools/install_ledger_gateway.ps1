param([switch]$Apply)
$ErrorActionPreference='Stop'
if(-not $Apply){@{status='PREVIEW';scope='loopback gateway and rolling tunnel origin change; no customer data'}|ConvertTo-Json -Compress; return}
function ConvertTo-GatewayOrigin([string]$ConfigText) {
    $pattern='(?m)^([ \t]*service:[ \t]*)http://127\.0\.0\.1:8751([ \t]*(?:#[^\r\n]*)?\r?)$'
    if(([regex]::Matches($ConfigText,$pattern)).Count -ne 1){throw 'ORIGIN_CONFIG_MISMATCH'}
    return [regex]::Replace($ConfigText,$pattern,'$1http://127.0.0.1:8790$2')
}
$hostRoot='D:\WebLedgerHost'
$route="$hostRoot\config\ledger-route.json"
$status="$hostRoot\config\ledger-gateway-status.json"
$config="$hostRoot\config\candidate.yml"
$python="$hostRoot\venv\Scripts\python.exe"
$gateway=Join-Path $PSScriptRoot 'ledger_gateway.py'
$lease=[IO.File]::Open("$hostRoot\config\continuous-deploy.lock",'OpenOrCreate','ReadWrite','None')
$registered=$false
$configChanged=$false
$newTunnel=$null
try {
    if((Test-Path -LiteralPath $route) -or (Get-ScheduledTask -TaskName WebLedger-Gateway -ErrorAction SilentlyContinue)){throw 'GATEWAY_ALREADY_CONFIGURED'}
    if(@(Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue).Count){throw 'GATEWAY_PORT_OCCUPIED'}
    if(@(Get-NetTCPConnection -LocalPort 20249 -State Listen -ErrorAction SilentlyContinue).Count){throw 'TUNNEL_METRICS_PORT_OCCUPIED'}
    $task=Get-ScheduledTask -TaskName WebLedger-Board
    if($task.State -ne 'Running' -or $task.Actions[0].Arguments -notmatch '-BoardPort 8751( |$)'){throw 'BOARD_NOT_READY_FOR_INSTALL'}
    foreach($path in @('/healthz','/readyz')) {
        if((Invoke-WebRequest "http://127.0.0.1:8751$path" -UseBasicParsing -TimeoutSec 5).StatusCode -ne 200){throw 'BOARD_NOT_READY'}
    }
    $original=[IO.File]::ReadAllText($config)
    $updated=ConvertTo-GatewayOrigin $original
    $oldTunnels=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'cloudflared.exe' -and $_.CommandLine.Contains($config) -and $_.CommandLine.Contains('8259194a-39d3-45c2-8b95-c656ce02f3fb')})
    if($oldTunnels.Count -ne 1){throw 'EXISTING_TUNNEL_IDENTITY_FAILED'}
    $backup="$hostRoot\config\gateway-install-$(Get-Date -Format yyyyMMddTHHmmss)"
    New-Item -ItemType Directory -Path $backup | Out-Null
    Copy-Item -LiteralPath $config -Destination "$backup\candidate.yml"
    Export-ScheduledTask -TaskName WebLedger-Board | Set-Content "$backup\board-task.xml" -Encoding UTF8
    [IO.File]::WriteAllText($route,'{"port":8751,"paused":false,"generation":"installed"}',[Text.UTF8Encoding]::new($false))
    $action=New-ScheduledTaskAction -Execute $python -Argument ('"'+$gateway+'" --port 8790 --route "'+$route+'" --status "'+$status+'"')
    $trigger=New-ScheduledTaskTrigger -AtLogOn -User $task.Principal.UserId
    Register-ScheduledTask -TaskName WebLedger-Gateway -Action $action -Trigger $trigger -Principal $task.Principal -Settings $task.Settings | Out-Null
    $registered=$true
    Start-ScheduledTask -TaskName WebLedger-Gateway
    $ready=$false
    for($attempt=0;$attempt -lt 40;$attempt++) {
        try {
            if((Invoke-WebRequest http://127.0.0.1:8790/readyz -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){$ready=$true; break}
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    if(-not $ready){throw 'GATEWAY_NOT_READY'}
    [IO.File]::WriteAllText($config,$updated,[Text.UTF8Encoding]::new($false))
    $configChanged=$true
    # Keep the registered old connector serving until the new connector is ready.
    $newTunnel=Start-Process "$hostRoot\bin\cloudflared.exe" -ArgumentList @('tunnel','--config',$config,'--metrics','127.0.0.1:20249','run','8259194a-39d3-45c2-8b95-c656ce02f3fb') -WindowStyle Hidden -PassThru -RedirectStandardOutput "$backup\tunnel.stdout.log" -RedirectStandardError "$backup\tunnel.stderr.log"
    $connected=$false
    for($attempt=0;$attempt -lt 80;$attempt++) {
        if($newTunnel.HasExited){throw 'NEW_TUNNEL_EXITED'}
        try {if((Invoke-WebRequest http://127.0.0.1:20249/ready -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200){$connected=$true; break}} catch {}
        Start-Sleep -Milliseconds 250
    }
    if(-not $connected){throw 'NEW_TUNNEL_NOT_CONNECTED'}
    foreach($oldTunnel in $oldTunnels){Stop-Process -Id $oldTunnel.ProcessId}
    @{status='PASS';gateway_port=8790;backend_port=8751;rolling_connector=$true;backup=$backup;at=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content "$backup\installed.json" -Encoding UTF8
    Write-Output 'GATEWAY_INSTALLED'
} catch {
    if($configChanged){[IO.File]::WriteAllText($config,$original,[Text.UTF8Encoding]::new($false))}
    if($newTunnel -and -not $newTunnel.HasExited){Stop-Process -Id $newTunnel.Id}
    if($registered){Stop-ScheduledTask -TaskName WebLedger-Gateway; Unregister-ScheduledTask -TaskName WebLedger-Gateway -Confirm:$false}
    # Preserve partial files for review; never silently enable a cold deploy.
    throw
} finally {$lease.Dispose()}
