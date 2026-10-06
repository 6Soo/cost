<#
.SYNOPSIS
    LOCAL-HOST-002 startup task installer for the web ledger host.

.DESCRIPTION
    Prepares one Windows scheduled task, and installs it only when asked:

      WebLedger-Board  starts tools\start_web_ledger_host.ps1, the common host
                       runner, which supervises the board with its review
                       config, the named Cloudflare tunnel, and the loopback
                       review entry page

    The task runs hidden, at logon, in the signed-in user's own account, with no
    stored password and no elevation. A task that needs a password typed in will
    prompt whoever logs on next, so the logon type is interactive and no secret
    is collected, printed or stored.

    The task's action is a single `powershell -File` line. It is not a command
    string built by joining paths and `&&`: a checkout under `C:\Program Files`
    would split into two arguments, and a path containing a metacharacter would
    turn into a second command. The runner receives structured parameters and
    quotes them itself, and the task's working directory is the checkout.

.SYNOPSIS NOTE
    Default is a plan. Nothing is created, changed or removed unless -Install is
    passed, and the plan prints what it would run rather than running it.

    Ownership is marked, not assumed. A task that merely shares the name
    WebLedger-Board is not this installer's: the description must carry the
    LOCAL-HOST-002 marker, and a name collision without it is refused rather than
    overwritten. Nothing else on the machine is read, written or removed, and no
    code path here deletes a task at all.

    No listener is checked at install time. A port checked now says nothing about
    the state at the next login, and the check that matters runs in the runner,
    where it happens again on every start.

.NOTES
    Prepared, not installed. This worker is not authorised to run against the
    real deployment, so this script has never been executed on the parent
    account. The paths below are configuration strings and are not read here: no
    file is opened, and no value from one is echoed. Secrets are named by where
    they live, never by what they contain.
#>
[CmdletBinding()]
param(
    # Plan unless this is set. There is no default-on path in this script.
    [switch]$Install,

    [string]$Checkout = "",

    # Where the production launcher really is. Empty means this checkout's copy.
    # A deployed board may run a launcher from elsewhere, and the runner needs
    # that exact path both to start it and to recognise it later.
    [string]$LauncherPath = "",

    # The data root and the two credential files are the production launcher's
    # own required arguments. They are passed to it unchanged and never
    # invented: a data root invented here would be a second, empty ledger
    # beside the real one, which is worse than not starting.
    [string]$DataRoot = "",
    [string]$ReviewConfig = "",

    # The explicit reservation source configuration, carried into the scheduled
    # task's arguments unchanged. The task is what restarts the board after a
    # reboot or a crash, so a setting that lived only on the launcher's own command
    # line would be lost at exactly the moment the source mattered most.
    [string]$ReserveSourceConfig = "",
    [string]$OAuthFile = "",
    [string]$SessionSecretFile = "",

    [ValidateRange(1, 65535)]
    [int]$BoardPort = 8751,

    [string]$Python = "python",
    [string]$CloudflareExe = "cloudflared",
    [string]$CloudflareConfigPath = "",
    [string]$TunnelId = "",

    [ValidateRange(1, 65535)]
    [int]$EntryPort = 56069,

    [switch]$DisableEntry,
    [switch]$MigrateLegacyEntry,

    [string]$TaskName = "WebLedger-Board",

    # Limited by default. Highest is here for an installer that is itself already
    # authorised to run elevated: a Limited task cannot inspect a child that is
    # running elevated, and cannot read the operating secrets such a child holds,
    # so the runner's identity checks would come back unreadable and it would
    # refuse every start. The choice is the operator's, made here rather than
    # guessed, and the level actually used is printed.
    [ValidateSet('Limited', 'Highest')]
    [string]$RunLevel = 'Limited'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

#: The ownership marker, written into the description of the task this script
#: manages and required in the description of any task it is about to replace.
$script:Owner = "LOCAL-HOST-002"
$script:Description = "$script:Owner managed task: web ledger host runner."

function Write-Note {
    <#
    .SYNOPSIS
        One line for the operator, on the host stream.

    .DESCRIPTION
        Write-Host, not Write-Output: these functions return values, and
        Write-Output inside a function becomes part of what the function
        returns, so every message printed this way would be swallowed into the
        caller's variable instead of being shown.
    #>
    param([string]$Text)
    Write-Host $Text
}

function Format-ProcessArgument {
    <#
    .SYNOPSIS
        One command-line argument, quoted the way Windows will read it back.

    .DESCRIPTION
        Start-Process joins -ArgumentList with spaces and does not quote the
        elements, so an argument containing a space arrives as two of them.
        `C:\Program Files\…` is an ordinary checkout path, not an edge case.
    #>
    param([string]$Value)

    if ($null -eq $Value -or $Value -eq "") { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Test-InstallRequirement {
    $required = [ordered]@{
        CHECKOUT            = $Checkout
        DATA_ROOT           = $DataRoot
        REVIEW_CONFIG       = $ReviewConfig
        OAUTH_FILE          = $OAuthFile
        SESSION_SECRET_FILE = $SessionSecretFile
    }
    foreach ($name in $required.Keys) {
        if (-not $required[$name]) { return $name }
    }
    # `RESERVE_SOURCE_CONFIG` is deliberately not required. A host with no
    # reservation source is a valid host: the link screen shows the
    # configuration-required state and nothing else. Making it mandatory would
    # force every existing installation to invent a source file, and a file
    # invented to satisfy an installer is a file nobody chose.
    if (-not $CloudflareConfigPath) { return "CLOUDFLARE_CONFIG" }
    if (-not $TunnelId) { return "TUNNEL_ID" }
    return ""
}

function Get-TaskDescription {
    try {
        return Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-TaskIsOurs {
    <#
    .SYNOPSIS
        Is the task of this name one this installer created?

    .DESCRIPTION
        Decided by the ownership marker in its own description, and by nothing
        else. A name is not identity: Windows lets any user or installer create
        a task called WebLedger-Board, and overwriting one because it shares a
        name would replace a stranger's work with a runner that serves a
        different application. So the marker decides, and its absence refuses.
    #>
    param($Task)

    if ($null -eq $Task) { return $true }
    $description = ""
    try {
        if ($Task.PSObject.Properties.Name -contains "Description") {
            $description = [string]$Task.Description
        }
    } catch {
        return $false
    }
    if ($description -eq "") { return $false }
    return ($description -like "*$script:Owner*")
}

function Get-TaskPlan {
    <#
    .SYNOPSIS
        The one task definition, as data.

    .DESCRIPTION
        Returned rather than registered, so the same values drive the printed
        plan and the installed task.
    #>
    param()

    $runner = Join-Path $Checkout "tools\start_web_ledger_host.ps1"
    $arguments = @(
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass",
        "-File", $runner,
        "-Mode", "Run",
        "-Checkout", $Checkout,
        "-LauncherPath", $LauncherPath,
        "-DataRoot", $DataRoot,
        "-ReviewConfig", $ReviewConfig,
        "-ReserveSourceConfig", $ReserveSourceConfig,
        "-OAuthFile", $OAuthFile,
        "-SessionSecretFile", $SessionSecretFile,
        "-BoardPort", "$BoardPort",
        "-Python", $Python,
        "-CloudflareExe", $CloudflareExe,
        "-CloudflareConfigPath", $CloudflareConfigPath,
        "-TunnelId", $TunnelId,
        "-EntryPort", "$EntryPort"
    )
    if ($DisableEntry) { $arguments += "-DisableEntry" }
    if ($MigrateLegacyEntry) { $arguments += "-MigrateLegacyEntry" }

    return [pscustomobject]@{
        Name        = $TaskName
        Description = $script:Description
        Owner       = $script:Owner
        Executable  = "powershell"
        Arguments   = $arguments
        WorkingDir  = $Checkout
        RunLevel    = $RunLevel
    }
}

function Write-Plan {
    param($Task)

    Write-Note "plan: nothing is created unless -Install is passed."
    Write-Note ""
    Write-Note ("task {0}" -f $Task.Name)
    Write-Note ("  description: {0}" -f $Task.Description)
    Write-Note ("  working directory: {0}" -f $Task.WorkingDir)
    Write-Note ("  run level: {0} (account: the signed-in user, logon type: interactive)" -f
        $Task.RunLevel)

    $argumentLine = ($Task.Arguments | ForEach-Object {
            Format-ProcessArgument $_
        }) -join " "
    Write-Note ("  runs: {0} {1}" -f $Task.Executable, $argumentLine)
    Write-Note ("  ports: board {0}, entry {1} (the existing local review port)" -f
        $BoardPort, $EntryPort)
    Write-Note "  board: the production launcher's own required arguments, passed"
    Write-Note "    through unchanged, including the data root and both credential"
    Write-Note "    files. A data root is never invented here."
    Write-Note ("  launcher: {0}" -f $(if ($LauncherPath) { $LauncherPath }
        else { "this checkout's tools\launch_web_ledger.py" }))
    Write-Note "  tunnel: the configured cloudflared, with its config path and"
    Write-Note "    tunnel id passed as arguments, so it is really started."
    Write-Note "    The runner finds an already-running tunnel by its own command"
    Write-Note "    line and leaves it alone."
    Write-Note "  as: the signed-in user, hidden, at logon, no password stored, no"
    Write-Note "      elevation, and no listener stopped to make room."
    Write-Note "  listener checks happen in the runner, at every start, because a"
    Write-Note "    port checked now says nothing about the next login."

    $existing = Get-TaskDescription
    if ($null -eq $existing) {
        Write-Note "  existing task: none, so -Install would create it."
    } elseif (Test-TaskIsOurs -Task $existing) {
        Write-Note "  existing task: carries the $script:Owner marker, so -Install would replace it."
    } else {
        Write-Note ("  existing task: same name, no $script:Owner marker, so -Install " +
            "would refuse and change nothing.")
    }
}

function Install-Task {
    <#
    .SYNOPSIS
        Register the managed task.

    .DESCRIPTION
        Working directory is the checkout, so the runner starts in the tree it
        belongs to instead of wherever the task scheduler happens to launch it.
    #>
    param($Task)

    $argumentList = @()
    foreach ($argument in $Task.Arguments) {
        $argumentList += (Format-ProcessArgument $argument)
    }

    $action = New-ScheduledTaskAction -Execute $Task.Executable `
        -Argument ($argumentList -join " ") `
        -WorkingDirectory $Task.WorkingDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
        -LogonType Interactive -RunLevel $Task.RunLevel
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    Register-ScheduledTask -TaskName $Task.Name `
        -Description $Task.Description `
        -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Force -ErrorAction Stop | Out-Null
}

$missing = Test-InstallRequirement
if ($missing) {
    Write-Note (("refused [{0}]: 필요한 설정이 없어요.") -f $missing)
    exit 2
}

$task = Get-TaskPlan

if (-not $Install) {
    Write-Plan -Task $task
    Write-Note ""
    Write-Note "plan only. Re-run with -Install to register this task."
    exit 0
}

$existing = Get-TaskDescription
if (-not (Test-TaskIsOurs -Task $existing)) {
    # A same-named task that is not ours is left exactly as it is. Replacing it
    # would mean overwriting somebody else's work because of a coincidence of
    # naming, on a machine where the operator may not even know it exists.
    Write-Note (("refused [TASK_NOT_OWNED]: {0} 이름의 작업이 있지만 {1} 표시가 " +
            "없어요. 건드리지 않았어요.") -f $TaskName, $script:Owner)
    exit 2
}

if ($null -eq $existing) {
    Write-Note ("create [MANAGED]: {0}" -f $Task.Name)
} else {
    Write-Note ("replace [MANAGED]: {0}" -f $Task.Name)
}

try {
    Install-Task -Task $task
} catch {
    Write-Note (("refused [REGISTER]: {0} 을(를) 등록하지 못했어요.") -f $Task.Name)
    exit 2
}

Write-Note ("done: {0} registered. No other task was touched." -f $Task.Name)
exit 0
