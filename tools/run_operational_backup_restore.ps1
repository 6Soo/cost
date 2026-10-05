param([switch]$PopulateSelectedTrips, [switch]$DeployReserveCandidate, [switch]$DeployReserveNavigation, [switch]$DeployGoogleCookieJar, [switch]$DeployReserveMobile, [switch]$DeployOwnerMetadata, [switch]$DeployExportAssigneeGuidance, [switch]$DeployLightweight, [switch]$RefreshCardCategories, [switch]$ApplyHistoryRules, [switch]$InferAssignments, [switch]$DeployReserveTrips, [switch]$RefineOtaOnly, [switch]$ApplyOtaAnswers)
$ErrorActionPreference = 'Stop'
if ($InferAssignments -and -not $ApplyHistoryRules) { throw 'INFERENCE_REQUIRES_HISTORY_RULES_MODE' }
if ($RefineOtaOnly -and -not ($ApplyHistoryRules -and $InferAssignments)) { throw 'OTA_REFINEMENT_REQUIRES_INFERENCE_MODE' }
if (@($PopulateSelectedTrips,$DeployReserveCandidate,$DeployReserveNavigation,$DeployGoogleCookieJar,$DeployReserveMobile,$DeployOwnerMetadata,$DeployExportAssigneeGuidance,$DeployLightweight,$RefreshCardCategories,$ApplyHistoryRules,$DeployReserveTrips,$ApplyOtaAnswers | Where-Object { $_ }).Count -gt 1) { throw 'MAINTENANCE_MODES_EXCLUSIVE' }
$resume = @()
try {
    $definitions = @{
        'WebLedger-Board' = 'LOCAL-HOST-002 managed task: web ledger host runner.'
        'WebLedger-SourceRefresh' = 'SOURCE-REFRESH-001 managed task: explicit selected source collector.'
    }
    foreach ($name in $definitions.Keys) {
        $task = Get-ScheduledTask -TaskName $name
        if ($task.Description -ne $definitions[$name]) { throw 'BACKUP_TASK_IDENTITY_UNVERIFIED' }
        if ($task.State -eq 'Running') {
            $resume += $task
            Stop-ScheduledTask -InputObject $task
        }
    }
    foreach ($task in $resume) {
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if ((Get-ScheduledTask -TaskName $task.TaskName).State -ne 'Running') { break }
            Start-Sleep -Milliseconds 250
        }
        if ((Get-ScheduledTask -TaskName $task.TaskName).State -eq 'Running') { throw 'BACKUP_WRITER_PAUSE_FAILED' }
    }
    $collectors = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*C:\AX\cost\tools\refresh_review_source.py*' })
    if ($collectors.Count -gt 0) { throw 'BACKUP_COLLECTOR_STILL_RUNNING' }
    $listeners = @(Get-NetTCPConnection -LocalPort 8751 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1) { throw 'BACKUP_LEDGER_LISTENER_UNVERIFIED' }
    $child = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if ($child.CommandLine -notlike '*D:\WebLedgerHost\bin\launch_web_ledger.py*') { throw 'BACKUP_LEDGER_PROCESS_UNVERIFIED' }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ParentProcessId)"
    Stop-Process -Id $child.ProcessId
    if ($parent.CommandLine -like '*D:\WebLedgerHost\bin\launch_web_ledger.py*') {
        Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue
    }
    $probe = Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @('C:\AX\cost\tools\verify_operational_backup_restore.py') -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -PassThru -Wait
    if ($probe.ExitCode -ne 0) { throw 'OPERATIONAL_BACKUP_RESTORE_FAILED' }
    if ($ApplyOtaAnswers) {
        $answerPreference=$ErrorActionPreference
        try {
            $ErrorActionPreference='Continue'
            $env:PYTHONIOENCODING='utf-8'
            $answerArguments=@()
            if ($env:WEBLEDGER_OTA_FOLLOWUP -eq '1') { $answerArguments+='--followup-answers' }
            elseif ($env:WEBLEDGER_OTA_HOLD_REFUND -eq '1') { $answerArguments+='--hold-refunded-flight' }
            $answerScript='C:\AX\cost\tools\apply_ota_owner_answers.py'
            if ($env:WEBLEDGER_OTA_REVIEW_HOLDS -eq '1') { $answerScript='C:\AX\cost\tools\prepare_ota_review_holds.py'; $answerArguments=@() }
            & 'D:\WebLedgerHost\venv\Scripts\python.exe' $answerScript @answerArguments
            $answerExit=$LASTEXITCODE
        } finally { $ErrorActionPreference=$answerPreference }
        if ($answerExit -ne 0) { throw 'OTA_OWNER_ANSWERS_APPLICATION_FAILED' }
    }
    if ($DeployReserveTrips) {
        & 'D:\WebLedgerHost\venv\Scripts\python.exe' 'C:\AX\cost\tools\deploy_reserve_trips.py'
        if ($LASTEXITCODE -ne 0) { throw 'RESERVE_TRIPS_DEPLOYMENT_FAILED' }
    }
    if ($RefreshCardCategories) {
        & 'D:\WebLedgerHost\venv\Scripts\python.exe' 'C:\AX\cost\tools\refresh_card_categories.py'
        if ($LASTEXITCODE -ne 0) { throw 'CARD_CATEGORIES_REFRESH_FAILED' }
    }
    if ($ApplyHistoryRules) {
        $previousMaintenance=$env:WEBLEDGER_MAINTENANCE
        try {
            $env:WEBLEDGER_MAINTENANCE='HISTORY_RULES'
            $env:PYTHONIOENCODING='utf-8'
            $ruleArguments=@('--apply')
            if ($InferAssignments) { $ruleArguments+='--infer' }
            if ($RefineOtaOnly) { $ruleArguments+='--ota-only' }
            & 'D:\WebLedgerHost\venv\Scripts\python.exe' 'C:\AX\cost\tools\recover_history_rules.py' @ruleArguments
            if ($LASTEXITCODE -ne 0) { throw 'HISTORY_RULES_APPLICATION_FAILED' }
        } finally {
            $env:WEBLEDGER_MAINTENANCE=$previousMaintenance
        }
    }
    if ($DeployLightweight) {
        $previousMaintenance=$env:WEBLEDGER_MAINTENANCE
        try {
            $env:WEBLEDGER_MAINTENANCE='LIGHTWEIGHT'
            $deploy=Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @('C:\AX\cost\tools\deploy_lightweight.py') -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -PassThru -Wait
            if ($deploy.ExitCode -ne 0) { throw 'LIGHTWEIGHT_DEPLOYMENT_FAILED' }
        } finally {
            $env:WEBLEDGER_MAINTENANCE=$previousMaintenance
        }
    }
    if ($DeployReserveNavigation -or $DeployGoogleCookieJar -or $DeployReserveMobile -or $DeployOwnerMetadata -or $DeployExportAssigneeGuidance) {
        $previousMaintenance=$env:WEBLEDGER_MAINTENANCE
        try {
            $candidatePrefix='reserve-navigation'
            $env:WEBLEDGER_MAINTENANCE='RESERVE_NAVIGATION'
            if ($DeployGoogleCookieJar) {
                $candidatePrefix='google-cookie-jar'
                $env:WEBLEDGER_MAINTENANCE='GOOGLE_COOKIE_JAR'
            }
            if ($DeployReserveMobile) {
                $candidatePrefix='reserve-mobile'
                $env:WEBLEDGER_MAINTENANCE='RESERVE_MOBILE'
            }
            if ($DeployOwnerMetadata) {
                $candidatePrefix='owner-metadata'
                $env:WEBLEDGER_MAINTENANCE='OWNER_METADATA'
            }
            if ($DeployExportAssigneeGuidance) {
                $candidatePrefix='export-assignee-guidance'
                $env:WEBLEDGER_MAINTENANCE='EXPORT_ASSIGNEE_GUIDANCE'
            }
            $deploy=Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @('C:\AX\cost\tools\deploy_reserve_navigation.py',$candidatePrefix) -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -PassThru -Wait
            if ($deploy.ExitCode -ne 0) { throw 'RESERVE_NAVIGATION_INTEGRATION_FAILED' }
        } finally {
            $env:WEBLEDGER_MAINTENANCE=$previousMaintenance
        }
    }
    if ($DeployReserveCandidate) {
        $boardTask=Get-ScheduledTask -TaskName 'WebLedger-Board'
        if (@($boardTask.Actions).Count -ne 1 -or $boardTask.Actions[0].Arguments -notmatch '(?i)C:\\AX\\cost\\tools\\start_web_ledger_host\.ps1') { throw 'DEPLOY_TASK_ACTION_UNVERIFIED' }
        if ($boardTask.Actions[0].Arguments -match '-ReserveSourceConfig') { throw 'DEPLOY_CONFIG_ARGUMENT_ALREADY_EXISTS' }
        $originalXml=Export-ScheduledTask -TaskName 'WebLedger-Board'
        $originalXml | Set-Content -LiteralPath 'D:\WebLedgerHost\config\board-task-before-reserve.xml' -Encoding UTF8
        $previousMaintenance=$env:WEBLEDGER_MAINTENANCE
        $integrationStarted=$false
        try {
            $env:WEBLEDGER_MAINTENANCE='RESERVE_CANDIDATE'
            $integrationStarted=$true
            $deploy=Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @('C:\AX\cost\tools\deploy_reserve_candidate.py') -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -PassThru -Wait
            if ($deploy.ExitCode -ne 0) { throw 'RESERVE_CANDIDATE_INTEGRATION_FAILED' }
            [xml]$newXml=$originalXml
            $ns=New-Object System.Xml.XmlNamespaceManager($newXml.NameTable)
            $ns.AddNamespace('t',$newXml.DocumentElement.NamespaceURI)
            $arguments=$newXml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Arguments',$ns)
            if ($null -eq $arguments) { throw 'TASK_ARGUMENT_NODE_MISSING' }
            $arguments.InnerText += ' -ReserveSourceConfig "D:\WebLedgerHost\config\reserve-source.json"'
            Register-ScheduledTask -TaskName 'WebLedger-Board' -Xml $newXml.OuterXml -Force | Out-Null
            $updated=Get-ScheduledTask -TaskName 'WebLedger-Board'
            if ($updated.Description -ne $boardTask.Description -or $updated.Actions[0].Arguments -notmatch '-ReserveSourceConfig\s+"D:\\WebLedgerHost\\config\\reserve-source\.json"') { throw 'TASK_CONFIG_REGISTRATION_FAILED' }
        } catch {
            Register-ScheduledTask -TaskName 'WebLedger-Board' -Xml $originalXml -Force | Out-Null
            if ($integrationStarted -and (Test-Path -LiteralPath 'C:\AX\cost\docs\handoff\2026-10-01\reserve-operational-integration.json')) {
                $rollback=Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @('C:\AX\cost\tools\deploy_reserve_candidate.py','--rollback') -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -PassThru -Wait
                if ($rollback.ExitCode -ne 0) { throw 'RESERVE_ROLLBACK_FAILED' }
            }
            throw
        } finally {
            $env:WEBLEDGER_MAINTENANCE=$previousMaintenance
        }
    }
    if ($PopulateSelectedTrips) {
        $previousMaintenance=$env:WEBLEDGER_MAINTENANCE
        try {
            $env:WEBLEDGER_MAINTENANCE='SELECTED_TRIP_DIRECTORY'
            $populate=Start-Process 'D:\WebLedgerHost\venv\Scripts\python.exe' -ArgumentList @('C:\AX\cost\tools\prepare_selected_trip_directory.py','--apply') -WorkingDirectory 'C:\AX\cost' -WindowStyle Hidden -PassThru -Wait
            if ($populate.ExitCode -ne 0) { throw 'SELECTED_TRIP_DIRECTORY_POPULATE_FAILED' }
        } finally {
            $env:WEBLEDGER_MAINTENANCE=$previousMaintenance
        }
    }
} finally {
    try {
        & 'C:\AX\cost\tools\restart_real_review_host.ps1'
    } finally {
        foreach ($task in $resume) { Start-ScheduledTask -TaskName $task.TaskName }
    }
}
