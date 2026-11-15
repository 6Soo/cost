<#
.SYNOPSIS
    LOCAL-HOST-002 common host runner for the web ledger.

.DESCRIPTION
    One runner, started by the scheduled task, that supervises the whole local
    host: the board with its review config, the named Cloudflare tunnel, and
    optionally the loopback review entry page. It starts all three, then stays
    in the foreground and watches them.

    It stays in the foreground on purpose. A task that starts a process and
    exits reports success, so task restart cannot recover a child that died an
    hour later; the supervisor is what makes the restart real. The task is the
    supervisor's lifetime, not its children's.

    Every child is checked at runtime, in this process, on every start — an
    installer-time check cannot say anything about the state at the next login.
    The states are kept apart on purpose:

        Free     nothing of this kind is running
        Ours     our own is already there; reported, watched, not duplicated
        Legacy   the old serve_review.py is on the entry port
        Foreign  something else is there, or on a routable address
        Unknown  the process or port state could not be read

    Only Free and Ours lead to a start. Foreign, Legacy and Unknown refuse, and
    nothing here ever stops a process to make room. -MigrateLegacyEntry is the
    one exception, and it will stop only a serve_review.py whose command line
    names the exact script path and the exact --port, and only when the operator
    asked for it by name.

    A child that was found already running is still watched. The runner did not
    start it, so it has no process handle, and the only way to know it is still
    there is to look again: the port or the tunnel's identity is re-resolved on
    every tick, and a child that has since gone is started for real.

.PARAMETER Mode
    Plan prints what it would do and exits. Run starts and supervises. Plan is
    the default, so running this by hand cannot change the machine.

.NOTES
    Prepared, not installed. This worker is not authorised to run against the
    real deployment, so this file has never been executed against the parent
    account's paths. It reads no configuration file and no credential: the paths
    are configuration strings, passed in, and none of them is a secret.
#>
[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Run')]
    [string]$Mode = 'Plan',

    [string]$Checkout = "",

    # Where the production launcher actually is. It defaults to the one in this
    # checkout, but a deployed board may run a launcher from elsewhere, and a
    # runner that silently used the checkout's copy would start the wrong program
    # while reporting the right one. It is also the identity the runner compares
    # against, so the two cannot drift apart.
    [string]$LauncherPath = "",

    [string]$DataRoot = "",
    [string]$ReviewConfig = "",
    [string]$DeploymentRoute = "",

    # A durable participant store shared with the roster receiver. Never derive
    # this from Checkout: each SHA release has a different directory.
    [string]$ParticipantDb = "",
    [string]$ParticipantSyncConfig = "",

    # The explicit reservation source configuration: a JSON file naming the
    # source path, the file's own SHA-256 and the roster's semantic digest.
    #
    # Optional on purpose. Without it the link screen shows the configuration-
    # required state and nothing else — no search for a roster, no collection, no
    # guessed file. With it, the same three values are read on every start, every
    # restart and every login, so the source a board is using cannot change
    # underneath it between runs.
    [string]$ReserveSourceConfig = "",
    [string]$OAuthFile = "",
    [string]$SessionSecretFile = "",

    [ValidateRange(1, 65535)]
    [int]$BoardPort = 8751,

    [ValidateSet('Board', 'Prepared')]
    [string]$LifecycleRole = 'Board',

    [string]$Python = "python",

    [string]$CloudflareExe = "cloudflared",
    [string]$CloudflareConfigPath = "",
    [string]$TunnelId = "",

    # The port the existing local review screen is already reached on. Defaulting
    # anywhere else would leave the URL people already have bookmarked answering
    # from the old server, and the new entry page would never be visited.
    [ValidateRange(1, 65535)]
    [int]$EntryPort = 56069,

    [switch]$DisableEntry,
    [switch]$MigrateLegacyEntry,

    # Seconds to watch. Zero watches until the process is stopped, which is the
    # mode the scheduled task uses.
    [ValidateRange(0, 86400)]
    [int]$SuperviseSeconds = 0,

    [ValidateRange(1, 3600)]
    [int]$WatchIntervalSeconds = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Hide-ScheduledTaskConsole {
    try {
        $self = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
        if (-not $self) { return }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($self.ParentProcessId)" -ErrorAction Stop
        if (-not $parent -or [string]$parent.Name -ne "svchost.exe") { return }

        if (-not ("WebLedgerConsoleWindow" -as [type])) {
            Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class WebLedgerConsoleWindow {
    [DllImport("kernel32.dll")]
    public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
        }
        $window = [WebLedgerConsoleWindow]::GetConsoleWindow()
        if ($window -ne [IntPtr]::Zero) {
            [WebLedgerConsoleWindow]::ShowWindow($window, 0) | Out-Null
        }
    } catch {
        # Hiding the console is presentation-only. Host startup must continue
        # even if Windows does not expose the parent process or window handle.
    }
}

if ($Mode -eq "Run") {
    Hide-ScheduledTaskConsole
}

#: The ownership marker, reported in every line so a log says which subsystem
#: answered, and matching the marker the installer writes into the task.
$script:Owner = "LOCAL-HOST-002"

# The role is part of the task identity. It lets the lifecycle wrapper use a
# port scoped mutex during an intentional blue/green overlap and makes an
# accidentally copied Prepared action fail identity checks instead of silently
# becoming the steady state board.
$env:WEBLEDGER_LIFECYCLE_ROLE = $LifecycleRole

$script:LegacyEntryName = "serve_review.py"

function Write-Note {
    <#
    .SYNOPSIS
        One line for the operator, on the host stream.

    .DESCRIPTION
        Write-Host, not Write-Output, and that is load-bearing. These functions
        return values — a list of refused children, a probe answer — and
        Write-Output inside a function becomes part of what the function
        returns. Every message printed this way would be collected into the
        caller's variable instead of being shown, so the operator would see a
        refusal count and no explanation of it.
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
        elements, so an element containing a space arrives as two arguments. A
        path with a space in it — `C:\Program Files\…` — is the ordinary case,
        not an edge one. Internal quotes are doubled and a trailing backslash run
        is doubled, because a lone backslash before the closing quote escapes it
        and the argument runs on into the next one.
    #>
    param([string]$Value)

    if ($null -eq $Value -or $Value -eq "") { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Test-TokenSequence {
    <#
    .SYNOPSIS
        Do these values appear as whole, consecutive arguments?

    .DESCRIPTION
        A substring is not an argument. `C:\a\run` contains `run`, and a config
        path of `config.yml.bak` contains `config.yml`, and either would make a
        probe report a match for something that is not this program. So each
        value is escaped and the sequence is required to sit between whitespace
        with an optional quote on the outside, which is what the command line
        actually looks like once Windows has parsed it.
    #>
    param(
        [string]$CommandLine,
        [string[]]$Tokens
    )

    # An optional quote on each token, not only on the ends: a command line with
    # a path in it reads `--config "C:\dir\config.yml"`, and a pattern that
    # only allowed a quote at the boundaries would miss every quoted argument.
    $escaped = @()
    foreach ($token in $Tokens) {
        $escaped += '"?' + [regex]::Escape($token) + '"?'
    }
    $pattern = '(^|\s)' + ($escaped -join '\s+') + '(\s|$)'
    return ($CommandLine -match $pattern)
}

function Get-ProcessCommandLine {
    <#
    .SYNOPSIS
        The command line of one process, or nothing.

    .DESCRIPTION
        Nothing rather than an empty string, because an empty command line and
        an unreadable one are the same thing here: there is no way to tell what
        the process is, and a child that cannot be identified is not replaced.
    #>
    param([int]$ProcessId)

    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" `
            -ErrorAction Stop
    } catch {
        return $null
    }
    if ($null -eq $process) { return $null }
    if (-not ($process.PSObject.Properties.Name -contains "CommandLine")) {
        return $null
    }
    $commandLine = [string]$process.CommandLine
    if ($commandLine -eq "") { return $null }
    return $commandLine
}

function Get-LoopbackListener {
    <#
    .SYNOPSIS
        What is listening on a loopback port, and is it one of ours.

    .DESCRIPTION
        Every listener is fetched and the port is filtered afterwards. Asking
        for one port and treating an empty answer as "free" is wrong on Windows:
        Get-NetTCPConnection -LocalPort raises NoMatchingObjectsFound when the
        port has no listener, so the missing-port case arrives as an error and a
        free port would be reported as unreadable — the opposite of the truth,
        and it would refuse to start on a port that is empty.

        Four answers, never one null: Free, Ours, Foreign, Unknown. Loopback
        only. A listener on a routable address is Foreign even when its command
        line looks familiar, because this host must never attach to, or
        displace, something the machine exposes to a network.
    #>
    param(
        [int]$LocalPort,
        [string]$Marker
    )

    $all = @()
    try {
        # A null in this list would make the filter below read a property off
        # nothing, so it is dropped rather than carried.
        $all = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $null -ne $_ })
    } catch {
        return @{ State = "Unknown"; Reason = "PROBE_FAILED" }
    }
    $listeners = @($all | Where-Object { $_.LocalPort -eq $LocalPort })
    if ($listeners.Count -eq 0) {
        return @{ State = "Free"; Reason = "" }
    }
    foreach ($listener in $listeners) {
        if ($listener.LocalAddress -notin @("127.0.0.1", "::1")) {
            return @{ State = "Foreign"; Reason = "ROUTABLE_ADDRESS" }
        }
    }

    $owners = @($listeners | ForEach-Object { $_.OwningProcess } |
        Where-Object { $_ } | Select-Object -Unique)
    if ($owners.Count -eq 0) {
        return @{ State = "Unknown"; Reason = "NO_OWNER" }
    }
    if ($owners.Count -gt 1) {
        # More than one process on one port: inherited sockets, or something
        # this runner does not understand. Either way it is not ours to judge,
        # and answering about the first one would be answering about half of it.
        return @{ State = "Unknown"; Reason = "MULTIPLE_OWNERS" }
    }
    $owner = $owners[0]
    $commandLine = Get-ProcessCommandLine -ProcessId $owner
    if ($null -eq $commandLine) {
        return @{ State = "Unknown"; Reason = "PROCESS_UNREADABLE"; Owner = $owner }
    }

    if ($Marker -and (Test-TokenSequence -CommandLine $commandLine -Tokens @($Marker))) {
        return @{
            State       = "Ours"
            Reason      = ""
            CommandLine = $commandLine
            Owner       = $owner
        }
    }
    # The old server is recognised by the exact path this checkout would use and
    # by the exact port, both as whole arguments. A relative path or a name that
    # merely appears in the line is not it: the migration below stops what this
    # classifies, so classifying loosely would stop the wrong thing.
    $legacyScript = Join-Path $Checkout "tools\$script:LegacyEntryName"
    if ((Test-TokenSequence -CommandLine $commandLine -Tokens @($legacyScript)) -and
        (Test-TokenSequence -CommandLine $commandLine -Tokens @("--port", "$EntryPort"))) {
        # The owning PID travels with the answer. The migration re-proves what
        # it is about to stop and re-reads the command line for that, which it
        # cannot do without knowing which process this was.
        return @{
            State       = "Legacy"
            Reason      = "LEGACY_ENTRY"
            CommandLine = $commandLine
            Owner       = $owner
        }
    }
    return @{
        State       = "Foreign"
        Reason      = "UNRECOGNISED"
        CommandLine = $commandLine
        Owner       = $owner
    }
}

function Get-TunnelState {
    <#
    .SYNOPSIS
        Is this exact tunnel already running?

    .DESCRIPTION
        A tunnel has no port, so it cannot be found by listening. It is found by
        process, and there are two steps to it.

        The query is by process Name, never by a pathname. A WQL string literal
        treats a backslash as an escape, so `ExecutablePath = 'D:\bin\cloudflared.exe'`
        is not the path it looks like and the query comes back terminating with
        "invalid query" — which arrives as an unreadable machine, and an
        unreadable machine must not be read as "no tunnel". The name is escaped
        and compared exactly, and the full path is compared here in PowerShell,
        where a backslash is only a backslash.

        Then the arguments, as three separate facts rather than one sequence: the
        `tunnel` keyword, the `--config <path>` pair, and the `run <id>` pair.
        One sequence would miss a valid command line in which the config option
        comes before the keyword, and that is a real ordering the CLI accepts.

        Anything unresolved is Unknown, and Unknown never starts a tunnel. A
        process of the same name at another path is Unknown rather than Free: it
        may be a second copy serving the same edge, and Free would add a third.
    #>
    param(
        [string]$Exe,
        [string]$ConfigPath,
        [string]$Id
    )

    $target = $Exe.Trim().TrimEnd('\').ToLowerInvariant()
    if ($target -eq "") {
        return @{ State = "Unknown"; Reason = "NO_EXECUTABLE" }
    }
    $leaf = Split-Path -Leaf $Exe
    if ([string]::IsNullOrEmpty($leaf)) {
        return @{ State = "Unknown"; Reason = "NO_EXECUTABLE" }
    }

    $candidates = @()
    try {
        $candidates = @(Get-CimInstance Win32_Process `
                -Filter "Name = '$($leaf.Replace("'", "''"))'" -ErrorAction Stop |
            Where-Object { $null -ne $_ })
    } catch {
        return @{ State = "Unknown"; Reason = "PROCESS_LIST_UNREADABLE" }
    }
    if ($candidates.Count -eq 0) {
        return @{ State = "Free"; Reason = "" }
    }

    foreach ($candidate in $candidates) {
        if (-not ($candidate.PSObject.Properties.Name -contains "ExecutablePath") -or
            [string]::IsNullOrWhiteSpace([string]$candidate.ExecutablePath)) {
            return @{ State = "Unknown"; Reason = "PATH_UNREADABLE" }
        }
        $path = ([string]$candidate.ExecutablePath).Trim().TrimEnd('\')
        if (-not ($candidate.PSObject.Properties.Name -contains "CommandLine")) {
            return @{ State = "Unknown"; Reason = "COMMAND_LINE_UNREADABLE" }
        }
        $commandLine = [string]$candidate.CommandLine
        if ($commandLine -eq "") {
            return @{ State = "Unknown"; Reason = "COMMAND_LINE_UNREADABLE" }
        }
        $isTunnel = Test-TokenSequence -CommandLine $commandLine -Tokens @("tunnel")
        $hasConfig = Test-TokenSequence -CommandLine $commandLine `
            -Tokens @("--config", $ConfigPath)
        $hasRun = Test-TokenSequence -CommandLine $commandLine -Tokens @("run", $Id)
        $isOurTunnel = $isTunnel -and $hasConfig -and $hasRun
        if ($path.ToLowerInvariant() -ne $target) {
            # The same program name at another path. It is refused only when it
            # runs this tunnel's config or id, because that is a second copy
            # serving the same edge. Any other tunnel (another project's) is left
            # alone and never stopped or reconfigured.
            $servesOurs = (Test-TokenSequence -CommandLine $commandLine -Tokens @("--config", $ConfigPath)) -or
                (Test-TokenSequence -CommandLine $commandLine -Tokens @("run", $Id))
            if ($servesOurs) {
                return @{ State = "Unknown"; Reason = "SAME_TUNNEL_OTHER_PATH" }
            }
            continue
        }
        if (-not $isOurTunnel) {
            # The right program, a different tunnel. Not ours, and not a reason to
            # refuse either.
            continue
        }
        return @{
            State       = "Ours"
            Reason      = "MATCHING_TUNNEL"
            CommandLine = $commandLine
            Owner       = $candidate.ProcessId
        }
    }
    return @{ State = "Free"; Reason = "" }
}

function Get-ChildProbe {
    <#
    .SYNOPSIS
        The probe a particular child is identified by.

    .DESCRIPTION
        A port for the two that listen, the process command line for the tunnel,
        which does not.
    #>
    param($Child)

    if ($Child.IdentityKind -eq "Tunnel") {
        return Get-TunnelState -Exe $Child.Exe -ConfigPath $Child.TunnelConfig `
            -Id $Child.TunnelId
    }
    return Get-LoopbackListener -LocalPort $Child.Port -Marker $Child.Marker
}

function New-HostChild {
    <#
    .SYNOPSIS
        One supervised child, as data.

    .DESCRIPTION
        Returned rather than started, so the same description drives the printed
        plan and the real start. A plan written separately from what runs is a
        plan that can be true while the run is not.
    #>
    param(
        [string]$Name,
        [string]$Exe,
        [string[]]$Arguments,
        [int]$Port,
        [string]$Marker,
        [string]$IdentityKind = "Port",
        [string]$TunnelConfig = "",
        [string]$TunnelName = ""
    )

    return [pscustomobject]@{
        Name          = $Name
        Exe           = $Exe
        Arguments     = $Arguments
        Port          = $Port
        Marker        = $Marker
        IdentityKind  = $IdentityKind
        TunnelConfig  = $TunnelConfig
        TunnelId      = $TunnelName
        Process       = $null
        Started       = $false
        StartedByUs   = $false
        EverStarted   = $false
    }
}

function Get-HostPlan {
    <#
    .SYNOPSIS
        The board, the tunnel, and the entry page if it was asked for.

    .DESCRIPTION
        The board is launched through the existing production launcher's own
        interface, with its own required arguments passed through unchanged:
        the checkout, the data root, the OAuth file and the session secret file.
        A data root is not invented here. The launcher requires all four, and a
        command line missing one of the credential files is not a board, it is a
        failure with a log line.

        The tunnel is a real invocation with a real config path and a real
        tunnel id. An environment value naming a tunnel config starts nothing:
        nothing reads it, so a host that "ran" one by setting a variable was
        relying on a cloudflared somebody else had already started, or on
        nothing at all.
    #>
    param([bool]$WithEntry)

    $launcher = if ($LauncherPath) {
        $LauncherPath
    } else {
        Join-Path $Checkout "tools\launch_web_ledger.py"
    }
    $entry = Join-Path $Checkout "tools\serve_review_entry.py"

    $children = @(
        New-HostChild -Name "board" -Exe $script:ChildPython -Marker $launcher `
            -Port $BoardPort `
            -Arguments @(
            $launcher,
            "--checkout", $Checkout,
            "--data-root", $DataRoot,
            "--oauth-file", $OAuthFile,
            "--session-secret-file", $SessionSecretFile,
            "--port", "$BoardPort")

        New-HostChild -Name "tunnel" -Exe $CloudflareExe `
            -Marker $TunnelId -Port 0 -IdentityKind "Tunnel" `
            -TunnelConfig $CloudflareConfigPath -TunnelName $TunnelId `
            -Arguments @(
            "tunnel",
            "--config", $CloudflareConfigPath,
            "run", $TunnelId)
    )

    if ($WithEntry) {
        $children += New-HostChild -Name "entry" -Exe $script:ChildPython `
            -Marker $entry -Port $EntryPort `
            -Arguments @($entry, "--port", "$EntryPort")
    }
    return $children
}

function Test-PlanRequirement {
    <#
    .SYNOPSIS
        Everything the launch needs, or the name of what is missing.

    .DESCRIPTION
        Checked before anything is planned, because a plan that omits a
        credential file prints a command that cannot run and then exits zero.
        That looks like success to whatever invoked it.
    #>
    $required = [ordered]@{
        CHECKOUT           = $Checkout
        DATA_ROOT          = $DataRoot
        REVIEW_CONFIG      = $ReviewConfig
        OAUTH_FILE         = $OAuthFile
        SESSION_SECRET_FILE = $SessionSecretFile
        CLOUDFLARE_CONFIG  = $CloudflareConfigPath
        TUNNEL_ID          = $TunnelId
    }
    foreach ($name in $required.Keys) {
        if (-not $required[$name]) { return $name }
    }
    return ""
}

function Write-ChildPlan {
    param($Child, $Probe)

    $quoted = @()
    foreach ($argument in $Child.Arguments) {
        $quoted += (Format-ProcessArgument $argument)
    }
    Write-Note ("  {0}: {1} {2}" -f $Child.Name, $Child.Exe, ($quoted -join " "))
    if ($Child.IdentityKind -eq "Tunnel") {
        Write-Note (("    identified by: executable, config path and run {0} " +
                "in the command line: {1}") -f $Child.TunnelId, $Probe.State)
    } elseif ($Child.Port -gt 0) {
        $reason = ""
        if ($Probe.Reason) { $reason = " ($($Probe.Reason))" }
        Write-Note (("    port {0}: {1}{2}") -f $Child.Port, $Probe.State, $reason)
    }
}

function Write-HostPlan {
    param($Children)

    Write-Note ("{0} plan: nothing is started in this mode." -f $script:Owner)
    foreach ($child in $Children) {
        Write-ChildPlan -Child $child -Probe (Get-ChildProbe -Child $child)
    }
    Write-Note "  supervision: the runner stays in the foreground and watches each"
    Write-Note "    child, including one it found already running. Task restart is"
    Write-Note "    not relied on for that."
}

function Start-HostChild {
    <#
    .SYNOPSIS
        Start one child, with a structured argument list.

    .DESCRIPTION
        Start-Process is given the executable and the arguments as separate
        values and is left to quote them through Format-ProcessArgument. No
        command string is built, so a path containing a space, an ampersand or a
        quote cannot turn into a second command.
    #>
    param($Child)

    $argumentList = @()
    foreach ($argument in $Child.Arguments) {
        $argumentList += (Format-ProcessArgument $argument)
    }
    $start = @{
        FilePath     = $Child.Exe
        ArgumentList = $argumentList
        WindowStyle  = "Hidden"
        PassThru     = $true
        ErrorAction  = "Stop"
    }
    if ($Child.Name -eq "board") {
        $stamp = Get-Date -Format "yyyyMMddTHHmmss"
        $start["RedirectStandardOutput"] = "D:\WebLedgerHost\logs\host-board-$stamp.out.log"
        $start["RedirectStandardError"] = "D:\WebLedgerHost\logs\host-board-$stamp.err.log"
    }
    if ($Checkout) { $start["WorkingDirectory"] = $Checkout }
    if ($script:VenvLauncher -and $Child.Exe -eq $script:ChildPython) {
        # The base interpreter runs as the venv for this one child; Python
        # removes the variable at startup, so nothing it starts inherits it.
        $env:__PYVENV_LAUNCHER__ = $script:VenvLauncher
    }
    try {
        $Child.Process = Start-Process @start
    } finally {
        Remove-Item Env:\__PYVENV_LAUNCHER__ -ErrorAction SilentlyContinue
    }
    $Child.Started = $true
    $Child.StartedByUs = $true
    $Child.EverStarted = $true
    return $Child
}

function Stop-LegacyEntry {
    <#
    .SYNOPSIS
        Stop the old entry server, and only after proving that is what it is.

    .DESCRIPTION
        The old serve_review.py is the one process on this port that a migration
        may clear, and only when the operator asked for the migration by name.
        The proof is exact: the command line must name the full script path this
        checkout would use, and must carry `--port` with this entry port as its
        own value. A relative path, a different port, or a port that merely
        appears somewhere in the line is not a match, and a port table read a
        moment ago can already be stale.
    #>
    param($Probe)

    if ($Probe.State -ne "Legacy") { return $false }
    $owner = $Probe.Owner
    if (-not $owner) { return $false }

    $commandLine = Get-ProcessCommandLine -ProcessId $owner
    if ($null -eq $commandLine) { return $false }

    $expectedScript = Join-Path $Checkout "tools\$script:LegacyEntryName"
    if ($commandLine -notlike "*$expectedScript*") { return $false }
    if ($commandLine -notmatch ("(^|\s)--port\s+" + $EntryPort + "(\s|$)")) {
        return $false
    }
    try {
        Stop-Process -Id $owner -Force -ErrorAction Stop
    } catch {
        return $false
    }
    return $true
}

function Start-HostChildWhenFree {
    <#
    .SYNOPSIS
        Decide one child, and start it only if the answer is Free.

    .DESCRIPTION
        Ours is a NOOP that is not forgotten: Started is set and StartedByUs is
        not, so the watch loop knows to re-resolve this child by probe instead of
        holding a process handle. Refusals are reported and the caller carries on
        with the others, so one busy port does not take the whole host down.
    #>
    param($Child)

    $probe = Get-ChildProbe -Child $Child
    $label = $Child.Name.ToUpperInvariant()

    if ($probe.State -eq "Ours") {
        Write-Note ("noop [{0}]: 이미 실행 중이라 그대로 둬요. 계속 지켜봐요." -f $label)
        $Child.Started = $true
        $Child.StartedByUs = $false
        return $true
    }
    if ($probe.State -eq "Legacy") {
        if ($Child.Name -eq "entry" -and $MigrateLegacyEntry) {
            if (Stop-LegacyEntry -Probe $probe) {
                Write-Note ("migrated [entry]: 기존 항목 서버를 그만뒀어요.")
            } else {
                Write-Note ("refused [ENTRY_LEGACY]: 기존 항목 서버를 그만둘 수 없어요.")
                return $false
            }
        } else {
            Write-Note (("operator [ENTRY_LEGACY]: 포트 {0}에 기존 항목 서버가 있어요. " +
                    "직접 옮겨 주세요. 이 스크립트는 그만두지 않아요.") -f $EntryPort)
            return $false
        }
    }
    if ($probe.State -eq "Foreign") {
        Write-Note (("refused [{0}]: 다른 프로그램이 사용 중이라 시작하지 않아요.") -f $label)
        return $false
    }
    if ($probe.State -eq "Unknown") {
        # Cannot prove it is ours, so nothing is started. For a tunnel that also
        # means no second cloudflared competing for the same edge.
        Write-Note (("refused [{0}]: 상태를 확인할 수 없어 시작하지 않아요.") -f $label)
        return $false
    }

    try {
        Start-HostChild -Child $Child | Out-Null
        Write-Note (("started [{0}]: pid {1}") -f $Child.Name, $Child.Process.Id)
        return $true
    } catch {
        Write-Note (("refused [{0}]: 시작하지 못했어요.") -f $label)
        return $false
    }
}

function Start-HostRunner {
    param($Children)

    $refused = @()
    foreach ($child in $Children) {
        if (Start-HostChildWhenFree -Child $child) { continue }
        $refused += $child.Name
    }
    return $refused
}

function Watch-HostChildren {
    <#
    .SYNOPSIS
        Stay in the foreground and keep every child running.

    .DESCRIPTION
        The reason this loop exists. Task restart fires when the task's own
        process fails; a task that launched three children and returned would
        look healthy forever while all three were gone. So the task's process is
        the supervisor, and a child that dies is started again here.

        Two kinds of child are watched. One this runner started has a process
        handle, and HasExited is the answer. One that was found already running
        has no handle, because it was not ours to launch, so the only way to
        know it is still there is to look again — the port, or the tunnel's own
        command line, is re-resolved on every tick. When that no longer finds it,
        the port is rechecked before anything is started, so a child that has
        since been taken over by something else is not started a second time.

        Nothing is ever killed to make room.
    #>
    param($Children)

    $deadline = if ($SuperviseSeconds -gt 0) {
        (Get-Date).AddSeconds($SuperviseSeconds)
    } else {
        [DateTime]::MaxValue
    }

    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds $WatchIntervalSeconds
        foreach ($child in $Children) {
            if ($child.Started -and $child.StartedByUs -and $child.Process) {
                if (-not $child.Process.HasExited) { continue }
                Write-Note (("exited [{0}]: 다시 시작합니다.") -f $child.Name)
            } else {
                $wasRunning = $child.Started
                # Either it was found already running, or it was refused at
                # startup. Both are re-probed here, every tick.
                #
                # A refusal is not a decision to give up. The port may have been
                # released by the time this runs, and a child abandoned on the
                # first tick would stay abandoned for the life of the process
                # while the thing that blocked it was gone after a minute. Only
                # Free leads to a start, so re-probing is safe: nothing foreign
                # is ever touched, and a port that is still held is refused
                # again with the reason.
                $probe = Get-ChildProbe -Child $child
                if ($probe.State -eq "Ours") {
                    $child.Started = $true
                    $child.StartedByUs = $false
                    continue
                }
                if ($wasRunning) {
                    Write-Note (("gone [{0}]: 없어져서 다시 시작합니다.") -f $child.Name)
                } else {
                    Write-Note (("retry [{0}]: 다시 확인합니다.") -f $child.Name)
                }
            }

            $child.Process = $null
            $child.Started = $false
            $child.StartedByUs = $false
            Start-HostChildWhenFree -Child $child | Out-Null
        }
    }
}

$missing = Test-PlanRequirement
if ($missing) {
    Write-Note (("refused [{0}]: 필요한 설정이 없어요.") -f $missing)
    exit 2
}

# Passed to the board process itself, so it inherits the review configuration.
# An environment value the launcher reads is a real setting; a variable nothing
# reads is not, which is why the tunnel is a command line and not one of these.
$env:WEBLEDGER_REVIEW_CONFIG = $ReviewConfig
if ($DeploymentRoute) {
    if (-not (Test-Path -LiteralPath $DeploymentRoute -PathType Leaf)) { throw 'DEPLOYMENT_ROUTE_MISSING' }
    $env:WEBLEDGER_DEPLOYMENT_ROUTE = $DeploymentRoute
    $env:WEBLEDGER_DEPLOYMENT_PORT = [string]$BoardPort
} else {
    Remove-Item Env:\WEBLEDGER_DEPLOYMENT_ROUTE -ErrorAction SilentlyContinue
    Remove-Item Env:\WEBLEDGER_DEPLOYMENT_PORT -ErrorAction SilentlyContinue
}
if (-not [string]::IsNullOrWhiteSpace($ParticipantSyncConfig)) {
    $participantSourceText = Get-Content -LiteralPath $ParticipantSyncConfig -Raw -Encoding UTF8
    $participantSettings = $participantSourceText | ConvertFrom-Json
    $sharedParticipantDb = [string]$participantSettings.db
    if (-not [IO.Path]::IsPathRooted($sharedParticipantDb) -or -not (Test-Path -LiteralPath $sharedParticipantDb -PathType Leaf)) {
        throw 'PARTICIPANT_DB_UNAVAILABLE'
    }
    if ($ParticipantDb -and $ParticipantDb -ne $sharedParticipantDb) { throw 'PARTICIPANT_DB_MISMATCH' }
    $ParticipantDb = $sharedParticipantDb
    $env:WEBLEDGER_PARTICIPANT_SYNC_CONFIG = $ParticipantSyncConfig
}
if (-not [string]::IsNullOrWhiteSpace($ParticipantDb)) {
    $env:WEBLEDGER_PARTICIPANT_DB = $ParticipantDb
}
# Receipt reading: subscription Claude opus (medium), tool-free, API keys stripped; Windows OCR when it fails.
$env:WEBLEDGER_RECEIPT_VISION = 'claude-opus'
# Owner-confirmed reading notes. The file is data, not release content, so it survives every release.
$env:WEBLEDGER_RECEIPT_LEARNING = 'D:/WebLedgerHost/data/receipt_learning.jsonl'
# Collections received from this moment on are classified and recorded automatically; older ones are left as they are.
$env:WEBLEDGER_AUTO_RECORD_SINCE = '2026-10-13T15:00:00+00:00'

# The reservation source configuration is passed the same way the review
# configuration is: read once here, handed to the board process, and therefore
# identical across a restart, a supervisor respawn and a fresh login.
#
# A missing or unreadable file is refused with its own note rather than being
# ignored, because a source that quietly stops being read looks exactly like a
# source that has not changed. Nothing here reads the roster itself and nothing
# searches for one — this hands over a path the owner named.
if ($ReserveSourceConfig) {
    if (-not (Test-Path -LiteralPath $ReserveSourceConfig -PathType Leaf)) {
        Write-Note (("refused [RESERVE_SOURCE_CONFIG]: 설정 파일이 없어요: {0}") -f $ReserveSourceConfig)
        exit 2
    }
    try {
        $reserveSourceText = Get-Content -LiteralPath $ReserveSourceConfig -Raw -Encoding UTF8
    } catch {
        Write-Note (("refused [RESERVE_SOURCE_CONFIG]: 설정 파일을 읽지 못했어요: {0} ({1})" -f $ReserveSourceConfig, $_.Exception.Message))
        exit 2
    }
    try {
        $reserveSourceJson = $reserveSourceText | ConvertFrom-Json
    } catch {
        Write-Note (("refused [RESERVE_SOURCE_CONFIG]: 설정 JSON이 손상됐어요: {0} ({1})" -f $ReserveSourceConfig, $_.Exception.Message))
        exit 2
    }
    foreach ($field in @('path', 'file_sha256', 'digest')) {
        # The property is asked for by name before it is read. Under
        # Set-StrictMode a missing property throws, and a throw here would leave
        # the operator with a PowerShell error instead of the refusal that names
        # the field: the same missing field, reported in a way nobody can grep.
        $present = $reserveSourceJson.PSObject.Properties.Name -contains $field
        if (-not $present) {
            Write-Note (("refused [RESERVE_SOURCE_CONFIG]: 설정에 {0} 이(가) 없어요: {1}" -f $field, $ReserveSourceConfig))
            exit 2
        }
        $value = $reserveSourceJson.$field
        if (-not $value -or ($value -isnot [string]) -or -not $value.Trim()) {
            Write-Note (("refused [RESERVE_SOURCE_CONFIG]: 설정의 {0} 이(가) 비어 있어요: {1}" -f $field, $ReserveSourceConfig))
            exit 2
        }
    }
    # Existence only. The roster itself is never opened here: the board reads it
    # under the same rules it already uses for a roster it was pointed at, and a
    # launcher that hashed a customer file would be a new place for that file to
    # be handled.
    if (-not (Test-Path -LiteralPath ([string]$reserveSourceJson.path) -PathType Leaf)) {
        Write-Note (("refused [RESERVE_SOURCE_CONFIG]: 설정이 가리키는 원천 파일이 없어요: {0}" -f $reserveSourceJson.path))
        exit 2
    }
    # Compact, so the value handed over is one line and cannot gain a stray newline
    # that the reader would then have to guess about.
    $env:WEBLEDGER_RESERVE_SOURCE = ($reserveSourceJson | ConvertTo-Json -Compress -Depth 4)
} else {
    Remove-Item Env:\WEBLEDGER_RESERVE_SOURCE -ErrorAction SilentlyContinue
}

# A venv's Scripts\python.exe is a launcher that starts the base interpreter as
# a second process. Starting the base interpreter as that venv keeps one
# process per child; anything that is not a readable venv is used as given.
# The interpreter is asked once which base it launches; no file is read here.
$script:ChildPython = $Python
$script:VenvLauncher = $null
if ([IO.Path]::IsPathRooted($Python) -and (Split-Path (Split-Path $Python -Parent) -Leaf) -eq "Scripts") {
    try {
        $venvBase = (& $Python -I -c "import sys; print(getattr(sys, '_base_executable', sys.executable))" 2>$null |
                Select-Object -First 1)
    } catch {
        $venvBase = $null
    }
    if ($venvBase -and $venvBase.Trim() -ne $Python -and (Test-Path -LiteralPath $venvBase.Trim() -PathType Leaf)) {
        $script:ChildPython = $venvBase.Trim()
        $script:VenvLauncher = $Python
    }
}

$plan = Get-HostPlan -WithEntry (-not $DisableEntry)

if ($Mode -eq "Plan") {
    Write-HostPlan -Children $plan
    exit 0
}

# One-shot operator restart request. The scheduled task runs this script with
# the token that owns the production child, while an ordinary shell may be able
# to see the loopback listener but not read or stop that child. The request does
# not weaken identity checking: the existing listener is stopped only after the
# normal probe proves that its command line contains this plan's exact launcher
# marker. The request file is removed only after the port is actually free.
$restartRequest = Join-Path $Checkout ".web-ledger-restart-request"
if (Test-Path -LiteralPath $restartRequest -PathType Leaf) {
    $board = @($plan | Where-Object { $_.Name -eq "board" })[0]
    $probe = Get-ChildProbe -Child $board
    if ($probe.State -eq "Ours" -and $probe.Owner) {
        Stop-Process -Id $probe.Owner -Force -ErrorAction Stop
    } elseif ($probe.State -eq "Free") {
        # A failed launcher can still be alive before it binds the port. Under
        # the scheduled task token its command line is readable, so clean up
        # only processes carrying both the exact launcher token and this port.
        $stale = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and
            (Test-TokenSequence -CommandLine ([string]$_.CommandLine) -Tokens @($board.Marker)) -and
            (Test-TokenSequence -CommandLine ([string]$_.CommandLine) -Tokens @("--port", "$BoardPort"))
        })
        foreach ($process in ($stale | Sort-Object ProcessId -Descending)) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
    } else {
        throw "LEDGER_PROCESS_IDENTITY_UNVERIFIED"
    }
    $freed = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        $after = Get-ChildProbe -Child $board
        if ($after.State -eq "Free") {
            $freed = $true
            break
        }
    }
    if (-not $freed) { throw "LEDGER_RESTART_PORT_NOT_FREE" }
    Remove-Item -LiteralPath $restartRequest -Force
    Write-Note "restart [BOARD]: 검증된 기존 board를 종료하고 다시 시작합니다."
}

$refused = Start-HostRunner -Children $plan
Watch-HostChildren -Children $plan
exit 0
