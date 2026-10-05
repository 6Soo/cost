param([ValidateSet('Probe','Board','Tunnel')][string]$Mode='Probe')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$evidenceRoot='C:\AX\cost\docs\handoff\2026-10-01'
function Has-Tokens([string]$CommandLine,[string[]]$Tokens) {
    $parts=@($Tokens | ForEach-Object { '"?' + [regex]::Escape($_) + '"?' })
    return $CommandLine -match ('(^|\s)' + ($parts -join '\s+') + '(\s|$)')
}
function Get-Board {
    $listeners=@(Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -eq 8751})
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') {throw 'BOARD_LISTENER_UNVERIFIED'}
    $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if (-not (Has-Tokens $p.CommandLine @('D:\WebLedgerHost\bin\launch_web_ledger.py','--checkout','C:\AX\cost','--data-root','D:\WebLedgerHost\data'))) {throw 'BOARD_IDENTITY_UNVERIFIED'}
    return $p
}
function Get-Tunnel {
    $all=@(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'")
    if ($all.Count -ne 1) {throw 'TUNNEL_COUNT_UNVERIFIED'}
    $p=$all[0]
    if ($p.ExecutablePath -ne 'D:\WebLedgerHost\bin\cloudflared.exe' -or
        -not (Has-Tokens $p.CommandLine @('--config','D:\WebLedgerHost\config\candidate.yml')) -or
        -not (Has-Tokens $p.CommandLine @('run','8259194a-39d3-45c2-8b95-c656ce02f3fb'))) {throw 'TUNNEL_IDENTITY_UNVERIFIED'}
    return $p
}
function Get-Task {
    $t=Get-ScheduledTask -TaskName 'WebLedger-Board'
    if ($t.Description -ne 'LOCAL-HOST-002 managed task: web ledger host runner.' -or $t.State -ne 'Running' -or
        -not (Has-Tokens $t.Actions[0].Arguments @('C:\AX\cost\tools\start_web_ledger_host.ps1'))) {throw 'TASK_IDENTITY_UNVERIFIED'}
    return $t
}
$result=@{mode=$Mode;started_at=(Get-Date).ToUniversalTime().ToString('o');automatic_recovery_verified=$false;actual_import_performed=$false}
try {
    $task=Get-Task
    $board=Get-Board
    $tunnel=Get-Tunnel
    $result.board_before_pid=$board.ProcessId
    $result.tunnel_before_pid=$tunnel.ProcessId
    if ($Mode -eq 'Board') {
        $parent=Get-CimInstance Win32_Process -Filter "ProcessId=$($board.ParentProcessId)"
        $stopParent=$parent -and (Has-Tokens $parent.CommandLine @('D:\WebLedgerHost\bin\launch_web_ledger.py','--checkout','C:\AX\cost','--data-root','D:\WebLedgerHost\data'))
        Stop-Process -Id $board.ProcessId
        if ($stopParent) {Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue}
    } elseif ($Mode -eq 'Tunnel') {Stop-Process -Id $tunnel.ProcessId}
    if ($Mode -ne 'Probe') {
        $deadline=(Get-Date).AddSeconds(45)
        do {
            Start-Sleep -Seconds 1
            try {
                $newBoard=Get-Board
                $newTunnel=Get-Tunnel
                $changed=if ($Mode -eq 'Board') {$newBoard.ProcessId -ne $board.ProcessId} else {$newTunnel.ProcessId -ne $tunnel.ProcessId}
                if ($changed -and (Invoke-WebRequest 'http://127.0.0.1:8751/readyz' -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) {
                    $result.automatic_recovery_verified=$true
                    break
                }
            } catch {}
        } while ((Get-Date) -lt $deadline)
        if (-not $result.automatic_recovery_verified) {throw 'AUTOMATIC_RECOVERY_NOT_OBSERVED'}
    }
    $result.board_after_pid=(Get-Board).ProcessId
    $result.tunnel_after_pid=(Get-Tunnel).ProcessId
    $result.task_state=[string](Get-Task).State
    $result.healthz=(Invoke-WebRequest 'http://127.0.0.1:8751/healthz' -UseBasicParsing -TimeoutSec 5).StatusCode
    $result.readyz=(Invoke-WebRequest 'http://127.0.0.1:8751/readyz' -UseBasicParsing -TimeoutSec 5).StatusCode
    $result.success=$true
} catch {
    $result.success=$false
    $result.failure_code=$_.Exception.Message
} finally {
    $result.completed_at=(Get-Date).ToUniversalTime().ToString('o')
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$evidenceRoot\managed-recovery-$($Mode.ToLower()).json" -Encoding UTF8
}
if (-not $result.success) {exit 2}
