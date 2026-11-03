param(
    [Parameter(Mandatory=$true)][string]$PreviousSha,
    [Parameter(Mandatory=$true)][string]$CandidateSha
)
$ErrorActionPreference='Stop'
if($CandidateSha -notmatch '^[a-f0-9]{40}$' -or $PreviousSha -notmatch '^[a-f0-9]{40}$' -or $CandidateSha -eq $PreviousSha){throw 'SHA_INVALID'}
$hostRoot='D:\WebLedgerHost'
$route="$hostRoot\config\ledger-route.json"
$status="$hostRoot\config\ledger-gateway-status.json"
$python="$hostRoot\venv\Scripts\python.exe"
$controller=Join-Path $PSScriptRoot 'gateway_route.py'
$lease=[IO.File]::Open("$hostRoot\config\continuous-deploy.lock",'OpenOrCreate','ReadWrite','None')
$registered=$false
$paused=$false
$oldStopped=$false
$switched=$false
$candidateStarted=$false
$oldSupervisor=$null
$preparedSupervisor=$null
function Route-Control([string]$Action,[int]$Port=0) {
    $parameters=@($controller,$Action,'--route',$route,'--status',$status)
    if($Port){$parameters+=@('--port',[string]$Port)}
    & $python @parameters
    if($LASTEXITCODE -ne 0){throw "ROUTE_CONTROL_FAILED_$Action"}
}
function Wait-Backend([int]$Port,[string]$Sha) {
    for($attempt=0;$attempt -lt 120;$attempt++) {
        $listeners=@(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if($listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq '127.0.0.1') {
            $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
            if(-not $process.CommandLine.Contains($Sha)){throw 'BACKEND_SHA_MISMATCH'}
            try {
                $health=Invoke-WebRequest "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 2
                $ready=Invoke-WebRequest "http://127.0.0.1:$Port/readyz" -UseBasicParsing -TimeoutSec 2
                if($health.StatusCode -eq 200 -and $ready.StatusCode -eq 200){return}
            } catch {}
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'PREPARED_BACKEND_NOT_READY'
}
function Wait-BoardTask {
    for($attempt=0;$attempt -lt 40;$attempt++) {
        if((Get-ScheduledTask -TaskName WebLedger-Board).State -eq 'Running'){return}
        Start-Sleep -Milliseconds 250
    }
    throw 'BOARD_SUPERVISOR_NOT_RUNNING'
}
function Stop-Backend([int]$Port,[string]$Sha) {
    $listeners=@(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach($listener in $listeners) {
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if($listener.LocalAddress -ne '127.0.0.1' -or -not $process.CommandLine.Contains($Sha) -or -not $process.CommandLine.Contains('launch_web_ledger.py')){throw 'BACKEND_STOP_IDENTITY_FAILED'}
        $parent=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)"
        Stop-Process -Id $process.ProcessId -ErrorAction Stop
        if($parent -and $parent.CommandLine -and $parent.CommandLine.Contains($Sha) -and $parent.CommandLine.Contains('launch_web_ledger.py')){Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue}
    }
}
function Get-BackendSupervisor([int]$Port,[string]$Sha,[bool]$Prepared=$false) {
    $listeners=@(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1'){throw 'SUPERVISOR_LISTENER_INVALID'}
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if(-not $process -or -not $process.CommandLine.Contains($Sha) -or -not $process.CommandLine.Contains('launch_web_ledger.py')){throw 'SUPERVISOR_BACKEND_IDENTITY_INVALID'}
    $candidates=@(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('powershell.exe','pwsh.exe') -and $_.CommandLine -and
        $_.CommandLine.Contains("$Sha\tools\start_web_ledger_host.ps1") -and
        $_.CommandLine -match "-BoardPort $Port( |$)"
    })
    if($candidates.Count -ne 1){throw 'SUPERVISOR_AMBIGUOUS'}
    $supervisor=$candidates[0]
    $isPrepared=$supervisor.CommandLine -match '(?i)(^|\s)-DisableEntry(\s|$)'
    if([bool]$isPrepared -ne $Prepared){throw 'SUPERVISOR_ROLE_MISMATCH'}
    return @{pid=[int]$supervisor.ProcessId;sha=$Sha;port=$Port;created=$supervisor.CreationDate;prepared=$Prepared}
}
function Get-PreparedSupervisor([int]$Port,[string]$Sha) {
    $candidates=@(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('powershell.exe','pwsh.exe') -and $_.CommandLine -and
        $_.CommandLine.Contains("$Sha\tools\start_web_ledger_host.ps1") -and
        $_.CommandLine -match "-BoardPort $Port( |$)"
    })
    if($candidates.Count -gt 1){throw 'PREPARED_SUPERVISOR_AMBIGUOUS'}
    if(-not $candidates.Count){return $null}
    if($candidates[0].CommandLine -notmatch '(?i)(^|\s)-DisableEntry(\s|$)'){throw 'PREPARED_SUPERVISOR_INVALID'}
    return @{pid=[int]$candidates[0].ProcessId;sha=$Sha;port=$Port;created=$candidates[0].CreationDate;prepared=$true}
}
function Wait-PreparedSupervisor([int]$Port,[string]$Sha) {
    for($attempt=0;$attempt -lt 120;$attempt++) {
        $identity=Get-PreparedSupervisor $Port $Sha
        if($identity){return $identity}
        Start-Sleep -Milliseconds 500
    }
    throw 'PREPARED_SUPERVISOR_NOT_STARTED'
}
function Get-VerifiedSupervisorProcess($Identity) {
    if(-not $Identity){return $null}
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($Identity.pid)"
    if(-not $process){return $null}
    $isPrepared=$process.CommandLine -match '(?i)(^|\s)-DisableEntry(\s|$)'
    if(($Identity.created -and $process.CreationDate -ne $Identity.created) -or $process.Name -notin @('powershell.exe','pwsh.exe') -or -not $process.CommandLine.Contains("$($Identity.sha)\tools\start_web_ledger_host.ps1") -or $process.CommandLine -notmatch "-BoardPort $($Identity.port)( |$)" -or ([bool]$Identity.prepared -ne [bool]$isPrepared)){throw 'SUPERVISOR_IDENTITY_CHANGED'}
    $candidates=@(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('powershell.exe','pwsh.exe') -and $_.CommandLine -and
        $_.CommandLine.Contains("$($Identity.sha)\tools\start_web_ledger_host.ps1") -and
        $_.CommandLine -match "-BoardPort $($Identity.port)( |$)"
    })
    if($candidates.Count -ne 1 -or $candidates[0].ProcessId -ne $Identity.pid){throw 'SUPERVISOR_AMBIGUOUS'}
    return $process
}
function Stop-VerifiedSupervisor($Identity) {
    $process=Get-VerifiedSupervisorProcess $Identity
    if(-not $process){return}
    Stop-Process -Id $process.ProcessId -ErrorAction Stop
}
try {
    $task=Get-ScheduledTask -TaskName WebLedger-Board
    $old=$task.Actions[0]
    if($task.State -ne 'Running' -or $task.Actions.Count -ne 1 -or -not $old.Arguments.Contains($PreviousSha)){throw 'CURRENT_TASK_MISMATCH'}
    $gate=Get-Content "$hostRoot\config\v2-deploy-gate.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if($gate.status -ne 'PASS' -or $gate.candidate_sha -ne $CandidateSha){throw 'GATE_MISMATCH'}
    $state=Get-Content $route -Raw -Encoding UTF8 | ConvertFrom-Json
    $oldPort=[int]$state.port
    if($state.paused -or $oldPort -notin @(8751,8752) -or $old.Arguments -notmatch "-BoardPort $oldPort( |$)"){throw 'CURRENT_ROUTE_MISMATCH'}
    $gateway=@(Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue)
    if($gateway.Count -ne 1 -or $gateway[0].LocalAddress -ne '127.0.0.1'){throw 'GATEWAY_UNAVAILABLE'}
    $gatewayProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($gateway[0].OwningProcess)"
    if(-not $gatewayProcess.CommandLine.Contains('ledger_gateway.py')){throw 'GATEWAY_IDENTITY_FAILED'}
    $newPort=if($oldPort -eq 8751){8752}else{8751}
    $canPrepare=Test-Path -LiteralPath "$hostRoot\releases\$CandidateSha\webapp\deployment_role.py" -PathType Leaf
    if(@(Get-NetTCPConnection -LocalPort $newPort -State Listen -ErrorAction SilentlyContinue).Count){throw 'PREPARED_PORT_OCCUPIED'}
    if(Get-ScheduledTask -TaskName WebLedger-Prepared -ErrorAction SilentlyContinue){throw 'PREPARED_TASK_EXISTS'}
    if(Get-PreparedSupervisor $newPort $CandidateSha){throw 'PREPARED_SUPERVISOR_EXISTS'}
    $oldSupervisor=Get-BackendSupervisor $oldPort $PreviousSha
    $newArguments=$old.Arguments.Replace($PreviousSha,$CandidateSha) -replace "-BoardPort $oldPort( |$)","-BoardPort $newPort`$1"
    if($canPrepare) {
        if($newArguments -notmatch '(?i)-DeploymentRoute\s'){$newArguments+=' -DeploymentRoute "'+$route+'"'}
    } else {
        # Recovery to a pre-gateway release: never start its unguarded workers
        # in parallel. Keep new client connections queued until it is ready.
        $newArguments=$newArguments -replace '(?i)\s-DeploymentRoute\s+(?:"[^"]+"|\S+)',''
    }
    $newAction=New-ScheduledTaskAction -Execute $old.Execute -Argument $newArguments
    $preparedAction=New-ScheduledTaskAction -Execute $old.Execute -Argument ($newArguments+' -DisableEntry')
    $evidence="$hostRoot\releases\continuous-switch-$CandidateSha.json"
    Export-ScheduledTask -TaskName WebLedger-Board | Set-Content "$evidence.task.xml" -Encoding UTF8
    if($canPrepare) {
        Register-ScheduledTask -TaskName WebLedger-Prepared -Action $preparedAction -Principal $task.Principal -Settings $task.Settings | Out-Null
        $registered=$true
        $candidateStarted=$true
        Start-ScheduledTask -TaskName WebLedger-Prepared
        $preparedSupervisor=Wait-PreparedSupervisor $newPort $CandidateSha
        Wait-Backend $newPort $CandidateSha
        $backendSupervisor=Get-BackendSupervisor $newPort $CandidateSha $true
        if($backendSupervisor.pid -ne $preparedSupervisor.pid){throw 'PREPARED_SUPERVISOR_MISMATCH'}
        if(-not (Get-VerifiedSupervisorProcess $preparedSupervisor)){throw 'PREPARED_SUPERVISOR_GONE'}
    }
    # No operating task has been stopped before the candidate passes readiness.
    $paused=$true
    Route-Control 'pause'
    Stop-ScheduledTask -TaskName WebLedger-Board
    $oldStopped=$true
    Stop-VerifiedSupervisor $oldSupervisor
    Stop-Backend $oldPort $PreviousSha
    # Keep the private entry port available to the new supervisor.
    foreach($entry in @(Get-NetTCPConnection -LocalPort 56069 -State Listen -ErrorAction SilentlyContinue)) {
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.OwningProcess)"
        if($entry.LocalAddress -ne '127.0.0.1' -or -not $process.CommandLine.Contains($PreviousSha) -or -not $process.CommandLine.Contains('serve_review_entry.py')){throw 'ENTRY_IDENTITY_FAILED'}
        Stop-Process -Id $process.ProcessId
    }
    Set-ScheduledTask -TaskName WebLedger-Board -Action $newAction | Out-Null
    if(-not $canPrepare) {
        $candidateStarted=$true
        Start-ScheduledTask -TaskName WebLedger-Board
        Wait-BoardTask
        Wait-Backend $newPort $CandidateSha
    }
    Route-Control 'activate' $newPort
    $paused=$false
    $switched=$true
    if($registered) {
        Stop-ScheduledTask -TaskName WebLedger-Prepared
        Stop-VerifiedSupervisor $preparedSupervisor
        Start-ScheduledTask -TaskName WebLedger-Board
    }
    Wait-BoardTask
    Wait-Backend $newPort $CandidateSha
    @{status='PASS';sha=$CandidateSha;previous_sha=$PreviousSha;backend_port=$newPort;gateway_port=8790;prepared_before_stop=[bool]$canPrepare;drained=$true;full_backup='NOT_REQUIRED_CODE_ONLY';at=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content $evidence -Encoding UTF8
} catch {
    $originalError=$_.FullyQualifiedErrorId
    $cleanupUnknown=$false
    if($switched){
        $paused=$true
        try {Route-Control 'pause'} catch {Route-Control 'resume'; throw 'ROLLBACK_DRAIN_FAILED_CANDIDATE_PRESERVED'}
    }
    if($registered){
        Stop-ScheduledTask -TaskName WebLedger-Prepared -ErrorAction SilentlyContinue
        if(-not $preparedSupervisor -and $candidateStarted){
            try {$preparedSupervisor=Get-PreparedSupervisor $newPort $CandidateSha} catch {$cleanupUnknown=$true}
            if(-not $preparedSupervisor){$cleanupUnknown=$true}
        }
        if($preparedSupervisor){try {Stop-VerifiedSupervisor $preparedSupervisor} catch {$cleanupUnknown=$true}}
    }
    if($candidateStarted) {
        if($switched -or -not $canPrepare){Stop-ScheduledTask -TaskName WebLedger-Board -ErrorAction SilentlyContinue}
        if(-not $cleanupUnknown){Stop-Backend $newPort $CandidateSha}
    }
    if($oldStopped) {
        Set-ScheduledTask -TaskName WebLedger-Board -Action $old | Out-Null
        Start-ScheduledTask -TaskName WebLedger-Board
        Wait-BoardTask
        Wait-Backend $oldPort $PreviousSha
        Route-Control 'activate' $oldPort
    } elseif($paused) {Route-Control 'resume'}
    if($cleanupUnknown){throw 'CONTINUOUS_SWITCH_FAILED_CANDIDATE_SUPERVISOR_UNVERIFIED'}
    throw "CONTINUOUS_SWITCH_FAILED_$originalError"
} finally {
    if($registered){Unregister-ScheduledTask -TaskName WebLedger-Prepared -Confirm:$false -ErrorAction SilentlyContinue}
    $lease.Dispose()
}
