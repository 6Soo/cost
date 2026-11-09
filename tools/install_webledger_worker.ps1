param(
    [string]$HostRoot = 'D:\WebLedgerHost',
    [string]$Evidence = '',
    [switch]$Apply,
    [switch]$Rollback
)
# Moves the host's background jobs into one WebLedger-Worker task on the board's release and starts
# the gateway as one process. Preview by default. Every task it changes is exported first, and the
# old tasks are disabled rather than deleted, so -Rollback restores exactly what was there.
$ErrorActionPreference = 'Stop'
$legacy = @('COST-InsuranceRosterSync', 'WebLedger-SourceRefresh', 'WebLedger-MailCollect', 'WebLedger-GoogleAuthority')
$configPath = "$HostRoot\config\worker.json"
if (-not $Evidence) { $Evidence = "$HostRoot\logs\worker-install" }

if ($Rollback) {
    foreach ($name in @('WebLedger-Gateway') + $legacy) {
        $xml = Join-Path $Evidence "$name.xml"
        if (-not (Test-Path -LiteralPath $xml -PathType Leaf)) { throw "ROLLBACK_EVIDENCE_MISSING_$name" }
    }
    Stop-ScheduledTask -TaskName WebLedger-Worker -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName WebLedger-Worker -Confirm:$false -ErrorAction SilentlyContinue
    Stop-ScheduledTask -TaskName WebLedger-Gateway -ErrorAction SilentlyContinue
    foreach ($name in @('WebLedger-Gateway') + $legacy) {
        Register-ScheduledTask -TaskName $name -Xml (Get-Content -LiteralPath (Join-Path $Evidence "$name.xml") -Raw) -Force | Out-Null
    }
    foreach ($name in @('WebLedger-Gateway', 'COST-InsuranceRosterSync', 'WebLedger-SourceRefresh')) { Start-ScheduledTask -TaskName $name }
    @{ status = 'ROLLED_BACK'; at = (Get-Date).ToUniversalTime().ToString('o') } | ConvertTo-Json -Compress
    return
}

function Get-Action([string]$Name) {
    $task = Get-ScheduledTask -TaskName $Name
    if ($task.Actions.Count -ne 1) { throw "TASK_ACTION_COUNT_$Name" }
    return $task.Actions[0]
}
function Split-Arguments([string]$Text) {
    # Task Scheduler stores one command line; it is split the way the C runtime splits it.
    $parsed = [Management.Automation.Language.Parser]::ParseInput("& x $Text", [ref]$null, [ref]$null)
    $command = $parsed.Find({ param($node) $node -is [Management.Automation.Language.CommandAst] }, $true)
    return @($command.CommandElements | Select-Object -Skip 1 | ForEach-Object {
            if ($_ -is [Management.Automation.Language.StringConstantExpressionAst]) { $_.Value } else { $_.Extent.Text }
        })
}
function Get-BaseInterpreter([string]$Executable) {
    $config = Join-Path (Split-Path (Split-Path $Executable -Parent) -Parent) 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { return $Executable }
    $venvHome = ((Get-Content -LiteralPath $config | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1) -replace '^\s*home\s*=\s*', '').Trim()
    $base = Join-Path $venvHome (Split-Path $Executable -Leaf)
    if (-not (Test-Path -LiteralPath $base -PathType Leaf)) { throw 'BASE_INTERPRETER_MISSING' }
    return $base
}

# The board's release is where the worker runs.
$board = Get-Action 'WebLedger-Board'
if ($board.Arguments -notmatch 'releases\\(?<sha>[0-9a-f]{40})\\tools\\start_web_ledger_host\.ps1') { throw 'BOARD_RELEASE_UNKNOWN' }
$sha = $Matches.sha
$release = "$HostRoot\releases\$sha"
$venvPython = "$HostRoot\venv\Scripts\python.exe"
$venvPythonw = "$HostRoot\venv\Scripts\pythonw.exe"
$basePythonw = Get-BaseInterpreter $venvPythonw

$roster = Get-Action 'COST-InsuranceRosterSync'
$rosterArgs = Split-Arguments $roster.Arguments
if ($rosterArgs[0] -ne '-u' -or $rosterArgs[1] -notlike '*\tools\ingest_participant_roster.py') { throw 'ROSTER_ACTION_UNEXPECTED' }
$mail = Get-Action 'WebLedger-MailCollect'
$mailArgs = Split-Arguments $mail.Arguments
if ($mailArgs[0] -ne '-m' -or $mailArgs[1] -ne 'app.mail_collect') { throw 'MAIL_ACTION_UNEXPECTED' }
$google = Get-Action 'WebLedger-GoogleAuthority'
$googleArgs = Split-Arguments $google.Arguments
if ($googleArgs[0] -notlike '*\tools\google_authority_sync.py') { throw 'GOOGLE_ACTION_UNEXPECTED' }
$source = Get-Action 'WebLedger-SourceRefresh'
if ($source.Arguments -notlike '*watch_review_source.ps1*') { throw 'SOURCE_ACTION_UNEXPECTED' }

$config = [ordered]@{
    venv = "$HostRoot\venv"
    log  = "$HostRoot\logs\webledger-worker.log"
    jobs = @(
        [ordered]@{ name = 'participant-roster'; kind = 'watch'; module = 'tools.ingest_participant_roster'
            argv = @($rosterArgs | Select-Object -Skip 2) },
        [ordered]@{ name = 'review-source'; kind = 'watch'; module = 'tools.refresh_review_source'
            argv = @('--config', "$HostRoot\config\real-review.json", '--master', 'release:ledger/master_ledger.csv',
                '--bundle-root', "$HostRoot\review\refreshed", '--source-config', 'release:config/review_source.json',
                '--timeout', '30', '--attempts', '2', '--max-bytes', '20971520', '--watch', '--interval', '300') },
        [ordered]@{ name = 'mail-collect'; kind = 'process'; python = $mail.Execute; argv = $mailArgs
            every_seconds = 3600; timeout_seconds = 1800; log = "$HostRoot\logs\worker-mail-collect.log" },
        [ordered]@{ name = 'google-authority'; kind = 'process'; python = $venvPythonw
            argv = @('release:tools/google_authority_sync.py') + @($googleArgs | Select-Object -Skip 1)
            every_seconds = 3600; timeout_seconds = 900; log = "$HostRoot\logs\worker-google-authority.log" }
    )
}
$gateway = Get-Action 'WebLedger-Gateway'
$plan = [ordered]@{
    status       = if ($Apply) { 'APPLY' } else { 'PREVIEW' }
    release      = $sha
    worker       = "`"$basePythonw`" `"$release\tools\webledger_worker.py`" --config `"$configPath`""
    disable      = $legacy
    gateway_from = $gateway.Execute
    gateway_to   = $basePythonw
    config       = $config
}
if (-not $Apply) { $plan | ConvertTo-Json -Depth 6; return }
if (-not (Test-Path -LiteralPath "$release\tools\webledger_worker.py" -PathType Leaf)) { throw 'RELEASE_HAS_NO_WORKER' }

New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
foreach ($name in @('WebLedger-Gateway', 'WebLedger-Board') + $legacy) {
    Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $Evidence "$name.xml") -Encoding Unicode
}
[IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))

$boardTask = Get-ScheduledTask -TaskName 'WebLedger-Board'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $boardTask.Principal.UserId
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$action = New-ScheduledTaskAction -Execute $basePythonw -Argument "`"$release\tools\webledger_worker.py`" --config `"$configPath`""
foreach ($name in $legacy) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $name | Out-Null
}
Register-ScheduledTask -TaskName 'WebLedger-Worker' -Action $action -Trigger $trigger -Principal $boardTask.Principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'WebLedger-Worker'

# The gateway uses only the standard library, so the base interpreter runs it as one process.
Stop-ScheduledTask -TaskName 'WebLedger-Gateway'
Set-ScheduledTask -TaskName 'WebLedger-Gateway' -Action (New-ScheduledTaskAction -Execute $basePythonw -Argument $gateway.Arguments) | Out-Null
Start-ScheduledTask -TaskName 'WebLedger-Gateway'

$ready = $false
for ($attempt = 0; $attempt -lt 60 -and -not $ready; $attempt++) {
    Start-Sleep -Milliseconds 500
    try { $ready = (Invoke-WebRequest 'http://127.0.0.1:8790/readyz' -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch {}
}
if (-not $ready) { throw 'GATEWAY_NOT_READY_RUN_WITH_ROLLBACK' }
$workerLog = $config.log
$started = $false
for ($attempt = 0; $attempt -lt 60 -and -not $started; $attempt++) {
    Start-Sleep -Milliseconds 500
    $started = (Test-Path -LiteralPath $workerLog) -and ((Get-Content -LiteralPath $workerLog -Tail 20) -match '"event": "ready"')
}
if (-not $started) { throw 'WORKER_NOT_READY_RUN_WITH_ROLLBACK' }
@{ status = 'APPLIED'; release = $sha; evidence = $Evidence; at = (Get-Date).ToUniversalTime().ToString('o') } | ConvertTo-Json -Compress
