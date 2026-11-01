"""LOCAL-HOST-002 tests for the startup contract, against mocked PowerShell.

The two PowerShell files are the deliverable, so testing their text says very
little. These tests run them — in a child PowerShell in which every cmdlet they
would touch is replaced by a mock — and assert on what the operator would be
shown. No scheduled task is registered, no process is started, no port is
opened and no network call is made.

The mocks are deliberately faithful about the parts of Windows that bit this
code before:

* `Get-NetTCPConnection -State Listen -LocalPort <n>` raises
  NoMatchingObjectsFound when nothing is on that port. The mock raises too, so a
  probe written in that form reports "unknown" instead of "free" and the
  difference shows up here rather than on the operator's machine.
* `Get-CimInstance` answers per filter, and the whole process list can be made
  unreadable, which is the case where starting a second tunnel would be
  invisible and wrong.

Nothing here reads a real path. The checkout and config paths are strings under
`C:\\synthetic`, and one test uses a path with a space, because that is the case
a command-string construction breaks.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "tools" / "start_web_ledger_host.ps1"
INSTALLER = PROJECT_ROOT / "tools" / "install_web_ledger_startup.ps1"

CHECKOUT = "C:\\synthetic\\checkout"
DATA_ROOT = "D:\\ledger-data"
REVIEW_CONFIG = "C:\\synthetic\\review.json"
OAUTH_FILE = "C:\\synthetic\\oauth.json"
SESSION_SECRET_FILE = "C:\\synthetic\\session-secret.txt"
CLOUDFLARE_CONFIG = "C:\\synthetic\\cloudflared\\config.yml"
CLOUDFLARE_EXE = "C:\\Program Files\\cloudflared\\cloudflared.exe"
TUNNEL_ID = "0f1e2d3c-4b5a-6789-abcd-ef0123456789"
#: A checkout under Program Files is an ordinary location, not an edge case.
SPACED_CHECKOUT = "C:\\Program Files\\Forest Tour"

BOARD_PORT = 8751
ENTRY_PORT = 56069

#: A directory, as a distinct kind of thing from a file. The synthetic map holds
#: one, so `-PathType Leaf` has something to be wrong about.
SYNTHETIC_DIRECTORY = "C:\\synthetic\\reserve-source.json.d"

#: The reservation source configuration, and the roster file it names. Both are
#: paths under the synthetic tree and both exist only inside the harness's map.
RESERVE_SOURCE_CONFIG = "C:\\synthetic\\reserve-source.json"
SYNTHETIC_ROSTER = "C:\\synthetic\\roster.csv"

#: The one-shot operator restart marker, as the runner joins it. It is a control
#: file, not configuration: its existence is checked and it is never opened, so
#: it is the one existence probe a run without configuration may still make.
RESTART_REQUEST = CHECKOUT + "\\.web-ledger-restart-request"

POWERSHELL_TIMEOUT = 300

LAUNCHER = CHECKOUT + "\\tools\\launch_web_ledger.py"
ENTRY_SCRIPT = CHECKOUT + "\\tools\\serve_review_entry.py"
LEGACY_SCRIPT = CHECKOUT + "\\tools\\serve_review.py"
TUNNEL_COMMAND = (f'"{CLOUDFLARE_EXE}" tunnel --config "{CLOUDFLARE_CONFIG}" '
                  f"run {TUNNEL_ID}")


def tunnel_process(command=None, process_id=5555, executable=None):
    """A cloudflared process, identified by its full executable path."""
    return {"ProcessId": process_id, "ExecutablePath": executable or CLOUDFLARE_EXE,
            "CommandLine": command or TUNNEL_COMMAND}


def ps_list(items):
    """A PowerShell array literal: one dictionary per item, not one per key."""
    if not items:
        return "@()"
    # pscustomobject, not a hashtable: the runner asks whether a property exists
    # before reading it, which is the right way to treat a WMI object and the
    # wrong way to treat a hashtable, whose keys are not properties.
    parts = ["[pscustomobject]@{ " +
             "; ".join(f"{k} = '{v}'" for k, v in item.items()) + " }"
             for item in items]
    return "@(" + ", ".join(parts) + ")"


def executable_lines(path):
    """The file's lines with every comment removed, block comments included.

    Both files explain in their own prose why an earlier form went away, so a
    search over raw text matches its own explanation. A search over executable
    lines is the one that can mean something.
    """
    text = path.read_text(encoding="utf-8-sig")
    without_blocks = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    return [line.strip() for line in without_blocks.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def region(lines, opener, closer):
    """Index ranges of executable lines between two anchors, inclusive of opener.

    A region is a slice of the file, not a count. Anchoring on the text either
    side of a block is what lets a test say *which* block a statement is in, which
    is the difference between "there are three stops" and "these three stops are
    each inside a block that proved what it was stopping".
    """
    try:
        start = lines.index(opener)
        end = lines.index(closer, start + 1)
    except ValueError:
        return []
    return [(start, end + 1)]


def ps_map(items):
    """A PowerShell hashtable literal for a fixed set of synthetic values.

    Single-quoted PowerShell strings are literal, so only `'` has to be doubled.
    Backslashes must not be touched: the JSON value in here contains escaped
    backslashes on purpose, and doubling them again would hand the runner a path
    that is not the one the test meant.

    A value of `$null` is a directory: it exists, it is not a file, and it has no
    contents. That is the case `-PathType Leaf` exists to catch, and it cannot be
    expressed by a map of strings alone.
    """
    if not items:
        return "@{}"
    parts = []
    for key, value in items.items():
        name = "'" + str(key).replace("'", "''") + "'"
        if value is None:
            parts.append(f"{name} = $null")
        else:
            parts.append(name + " = '" + str(value).replace("'", "''") + "'")
    return "@{" + "; ".join(parts) + "}"


def harness(*, listeners=(), processes=(), port_table_fails=False,
            process_list_fails=False, task_description=None, task_present=False,
            exit_on_start=0, tunnel_answers=0, unreadable_command_line=0,
            files=None, stop_releases_port=True):
    """A PowerShell session in which nothing real can happen.

    `listeners` and `processes` are the machine's actual state, so every
    interesting situation is a list rather than a special case: a port held by
    ours, by a stranger, on a routable address, or by the legacy entry server,
    and a tunnel that is running, or running the wrong one.
    """
    return f"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$script:listeners = {ps_list(listeners)}
$script:processes = {ps_list(processes)}
$script:portTableFails = ${'true' if port_table_fails else 'false'}
$script:processListFails = ${'true' if process_list_fails else 'false'}
$script:taskPresent = ${'true' if task_present else 'false'}
$script:taskDescription = '{task_description or ''}'
$script:starts = 0
$script:exitOnStart = {exit_on_start}
$script:tunnelAnswers = {tunnel_answers}
$script:unreadableCommandLine = {unreadable_command_line}
$script:tunnelProbes = 0
$script:fakeNow = [datetime]'2026-01-01T00:00:00'
$script:tick = 0
# The only files that exist in this session. Everything outside this map is
# absent, so a path the runner invents cannot quietly resolve.
$script:files = {ps_map(files)}
$script:reads = @()
$script:stopReleasesPort = ${'true' if stop_releases_port else 'false'}

function Test-Path {{
    param([string]$LiteralPath, [string]$Path, $PathType, $ErrorAction)
    $target = if ($LiteralPath) {{ $LiteralPath }} else {{ $Path }}
    Write-Host ("MOCK-EXISTS " + $target)
    if (-not $script:files.ContainsKey($target)) {{ return $false }}
    # A `$null` entry is a directory. `-PathType Leaf` on it is false, which is
    # exactly what the runner relies on to refuse a directory passed as a file.
    $isDirectory = ($null -eq $script:files[$target])
    if ($PathType -eq 'Leaf') {{ return -not $isDirectory }}
    if ($PathType -eq 'Container') {{ return $isDirectory }}
    return $true
}}
function Get-Content {{
    param([string]$LiteralPath, [string]$Path, [switch]$Raw, $Encoding, $ErrorAction)
    $target = if ($LiteralPath) {{ $LiteralPath }} else {{ $Path }}
    $script:reads += $target
    Write-Host ("MOCK-READ " + $target)
    if (-not $script:files.ContainsKey($target)) {{
        throw ("cannot find path '" + $target + "'")
    }}
    return $script:files[$target]
}}
function Remove-Item {{
    # Two removals are allowed, and nothing else can be reached.
    #
    # The environment provider clears a variable this session set. `Env:NAME`
    # carries the provider separator and its backslash in the name itself, so the
    # name is trimmed of leading separators before it is handed to the .NET call.
    # Substring(4) alone would leave the backslash attached, which silently
    # clears nothing and makes the runner's else-branch look tested when it is not.
    #
    # A path is removable only when it is the restart marker named here. The
    # synthetic map is not a whitelist: any key in it would do, and the map
    # exists to make files *readable*, so allowing removal by membership would
    # turn the map into a delete permission over anything a test put in it. One
    # exact path, compared exactly, keeps the protection that was here before:
    # nothing outside the environment provider is reachable.
    param([string]$LiteralPath, [string]$Path, [switch]$Recurse,
          [switch]$Force, [switch]$Confirm, $ErrorAction)
    $target = if ($LiteralPath) {{ $LiteralPath }} else {{ $Path }}
    Write-Host ("MOCK-REMOVE " + $target)
    if ($target -notlike 'Env:*') {{
        if ($target -cne '{RESTART_REQUEST}') {{
            throw 'MOCK-REFUSE-FILE-REMOVAL ' + $target
        }}
        if (-not $script:files.ContainsKey($target)) {{
            throw 'MOCK-REFUSE-UNKNOWN-FILE-REMOVAL ' + $target
        }}
        $script:files.Remove($target)
        Write-Host ("MOCK-REMOVED-FILE " + $target)
        return
    }}
    $name = $target.Substring(4).TrimStart([char]92)
    if ([string]::IsNullOrWhiteSpace($name)) {{
        throw 'MOCK-REFUSE-EMPTY-ENV-NAME ' + $target
    }}
    [System.Environment]::SetEnvironmentVariable($name, $null, 'Process')
    Write-Host ("MOCK-REMOVED " + $name)
}}

function Get-Date {{
    $script:tick++
    # Two seconds a call: the deadline is eight seconds out, so the watch loop
    # iterates a few times deterministically instead of never, and never in a
    # busy spin.
    return $script:fakeNow.AddSeconds(2 * $script:tick)
}}
function Start-Sleep {{ param([int]$Seconds, [int]$Milliseconds) }}

function Get-NetTCPConnection {{
    param($State, $LocalPort, $ErrorAction)
    if ($script:portTableFails) {{ throw 'the port table is not available' }}
    if ($PSBoundParameters.ContainsKey('LocalPort')) {{
        # The form this task must not use. Real Windows raises
        # NoMatchingObjectsFound for a port with no listener, so a probe written
        # this way cannot tell "free" from "could not ask".
        $hit = @($script:listeners | Where-Object {{ $_.LocalPort -eq $LocalPort }})
        if ($hit.Count -eq 0) {{
            throw 'No matching objects found'
        }}
        return $hit
    }}
    return $script:listeners
}}
function Get-CimInstance {{
    # $ClassName is first because the runner calls this positionally, exactly as
    # the real cmdlet takes `Get-CimInstance Win32_Process`. With a mock whose
    # first parameter was $Filter, the class name would bind to it and every
    # lookup would quietly take the filtered path.
    param($ClassName, $Filter, $ErrorAction)
    # A CIM failure fails the filtered form as well as the unfiltered one, so
    # this is checked before the filter is looked at.
    if ($script:processListFails) {{ throw 'the process list is not available' }}
    if (-not [string]::IsNullOrEmpty($Filter)) {{
        if ($Filter -like 'Name =*') {{
            # The tunnel this runner did not start goes away partway through, so
            # the watch loop has something to recover from.
            $script:tunnelProbes++
            if ($script:tunnelAnswers -gt 0 -and
                $script:tunnelProbes -gt $script:tunnelAnswers) {{
                return @()
            }}
            $wantName = ($Filter -split "'")[1]
            $hit = @()
            foreach ($p in $script:processes) {{
                if (-not ($p.PSObject.Properties.Name -contains 'ExecutablePath')) {{
                    continue
                }}
                if ((Split-Path -Leaf $p.ExecutablePath) -ne $wantName) {{
                    continue
                }}
                if ($script:unreadableCommandLine -gt 0 -and
                    [string]$p.ProcessId -eq "$script:unreadableCommandLine") {{
                    # The real cmdlet can return a process whose command line it
                    # cannot read, and that is a case of its own.
                    return @([pscustomobject]@{{
                        ProcessId = $p.ProcessId
                        ExecutablePath = $p.ExecutablePath
                    }})
                }}
                $hit += $p
            }}
            return $hit
        }}
        if ($Filter -like 'ExecutablePath*') {{
            $want = ($Filter -split "'")[1]
            $hit = @()
            foreach ($p in $script:processes) {{
                if (-not ($p.PSObject.Properties.Name -contains 'ExecutablePath')) {{
                    continue
                }}
                if ($p.ExecutablePath -ne $want) {{ continue }}
                if ($script:unreadableCommandLine -and
                    [string]$p.ProcessId -eq "$script:unreadableCommandLine") {{
                    # The real cmdlet returns a process object with no readable
                    # command line, and that is a case of its own.
                    return @([pscustomobject]@{{ ProcessId = $p.ProcessId }})
                }}
                $hit += $p
            }}
            return $hit
        }}
        $id = ($Filter -replace '[^0-9]', '')
        foreach ($p in $script:processes) {{
            if ([string]$p.ProcessId -eq $id) {{ return $p }}
        }}
        # Nothing, not $null: a $null here would be collected into a one-element
        # array by the caller, which is a different thing from no processes.
        return
    }}
    $script:tunnelProbes++
    if ($script:tunnelAnswers -gt 0 -and $script:tunnelProbes -gt $script:tunnelAnswers) {{
        # The tunnel this runner did not start goes away partway through.
        return @($script:processes | Where-Object {{ $_.CommandLine -notlike '*cloudflared*' }})
    }}
    return $script:processes
}}
function Start-Process {{
    param($FilePath, $ArgumentList, $WindowStyle, $PassThru, $ErrorAction, $WorkingDirectory)
    $script:starts++
    Write-Host ("MOCK-START file=" + $FilePath + " wd=" + $WorkingDirectory +
        " args=" + ($ArgumentList -join ' '))
    # What the child would have inherited, reported at the moment it would have
    # been started. A configuration that is set but not inherited is the case
    # this exists for: the board would find no source and say so, while the
    # shell that set it looks correct.
    Write-Host ("MOCK-CHILD-ENV reserve=[" + [string]$env:WEBLEDGER_RESERVE_SOURCE +
        "] review=[" + [string]$env:WEBLEDGER_REVIEW_CONFIG + "]")
    Write-Host ("MOCK-PARTICIPANT-DB [" + [string]$env:WEBLEDGER_PARTICIPANT_DB + "]")
    $exited = ($script:exitOnStart -gt 0 -and $script:starts -eq $script:exitOnStart)
    return [pscustomobject]@{{ Id = (9000 + $script:starts); HasExited = $exited }}
}}
function Add-Type {{
    param($TypeDefinition)
}}
function Stop-Process {{
    # A stopped process releases its port, so the listener goes with it. Without
    # that, any code that stops something and then waits for the port would wait
    # out its whole deadline here and fail for a reason that exists only in the
    # mock. The process is dropped from the process list for the same reason: the
    # next probe has to be able to see that it is gone.
    param($Id, [switch]$Force, $ErrorAction)
    Write-Host ("MOCK-STOP id=" + $Id)
    if ($script:stopReleasesPort) {{
        $script:listeners = @($script:listeners | Where-Object {{
            [string]$_.OwningProcess -ne "$Id"
        }})
    }}
    $script:processes = @($script:processes | Where-Object {{
        [string]$_.ProcessId -ne "$Id"
    }})
}}
function Get-ScheduledTask {{
    param($TaskName, $ErrorAction)
    if (-not $script:taskPresent) {{ throw 'no such task' }}
    return [pscustomobject]@{{ TaskName = $TaskName; Description = $script:taskDescription }}
}}
function Register-ScheduledTask {{
    param($TaskName, $Description, $Action, $Trigger, $Principal, $Settings, [switch]$Force, $ErrorAction)
    Write-Host ("MOCK-REGISTER name=" + $TaskName + " description=" + $Description)
    Write-Host ("MOCK-REGISTER action=" + $Action.Execute + ' ' + $Action.Arguments)
    Write-Host ("MOCK-REGISTER wd=" + $Action.WorkingDirectory)
    return [pscustomobject]@{{ TaskName = $TaskName }}
}}
function New-ScheduledTaskAction {{
    param($Execute, $Argument, $WorkingDirectory)
    return [pscustomobject]@{{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory }}
}}
function New-ScheduledTaskTrigger {{ param([switch]$AtLogOn, $User) return 'trigger' }}
function New-ScheduledTaskPrincipal {{
    param($UserId, $LogonType, $RunLevel)
    return [pscustomobject]@{{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel }}
}}
function New-ScheduledTaskSettingsSet {{
    param([switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries,
          [switch]$StartWhenAvailable, $MultipleInstances, $ExecutionTimeLimit,
          $RestartCount, $RestartInterval)
    return 'settings'
}}
function New-TimeSpan {{ param($Hours, $Minutes, $Seconds, $Days) return 'timespan' }}
"""


def runner_arguments(mode="Run", extra="", checkout=CHECKOUT, data_root=DATA_ROOT,
                     oauth=OAUTH_FILE, secret=SESSION_SECRET_FILE,
                     cloudflare_config=CLOUDFLARE_CONFIG, tunnel=TUNNEL_ID,
                     cloudflare_exe=CLOUDFLARE_EXE, entry_port=ENTRY_PORT,
                     watch=8, interval=1, reserve_config=None):
    parts = [
        f"-Mode {mode}",
        f"-Checkout '{checkout}'",
        f"-DataRoot '{data_root}'",
        f"-ReviewConfig '{REVIEW_CONFIG}'",
        f"-OAuthFile '{oauth}'",
        f"-SessionSecretFile '{secret}'",
        f"-BoardPort {BOARD_PORT}",
        "-Python python",
        f"-CloudflareExe '{cloudflare_exe}'",
        f"-CloudflareConfigPath '{cloudflare_config}'",
        f"-TunnelId '{tunnel}'",
        f"-EntryPort {entry_port}",
    ]
    if reserve_config is not None:
        parts.append(f"-ReserveSourceConfig '{reserve_config}'")
    if watch:
        parts += [f"-SuperviseSeconds {watch}", f"-WatchIntervalSeconds {interval}"]
    if extra:
        parts.append(extra)
    return " ".join(parts)


def run_runner(**kwargs):
    mocks = {key: kwargs.pop(key) for key in list(kwargs)
             if key in ("listeners", "processes", "port_table_fails",
                        "process_list_fails", "exit_on_start", "tunnel_answers",
                        "unreadable_command_line", "files", "stop_releases_port")}
    # The runner ends in `exit`, which takes the whole session with it, so nothing
    # is printed after the invocation. Everything a test needs is reported by the
    # mocks while the run is still going.
    body = (harness(**mocks)
            + f"\n$text = [System.IO.File]::ReadAllText('{RUNNER}')\n"
              "$sb = [scriptblock]::Create($text)\n"
              f"& $sb {runner_arguments(**kwargs)}\n")
    return _invoke(body)


def run_installer(*, install=True, task_present=False, task_description=None,
                  checkout=CHECKOUT, run_level=None, launcher_path="",
                  reserve_source_config=None, files=None):
    flag = "-Install" if install else ""
    level = f"-RunLevel {run_level}" if run_level else ""
    source = ""
    if reserve_source_config is not None:
        source = f"-ReserveSourceConfig '{reserve_source_config}' "
    body = (harness(task_present=task_present, task_description=task_description,
                    files=files)
            + f"\n$text = [System.IO.File]::ReadAllText('{INSTALLER}')\n"
              "$sb = [scriptblock]::Create($text)\n"
              f"& $sb {flag} -Checkout '{checkout}' -LauncherPath '{launcher_path}' "
              f"-DataRoot '{DATA_ROOT}' "
              f"-ReviewConfig '{REVIEW_CONFIG}' -OAuthFile '{OAUTH_FILE}' "
              f"-SessionSecretFile '{SESSION_SECRET_FILE}' "
              f"-CloudflareConfigPath '{CLOUDFLARE_CONFIG}' -TunnelId '{TUNNEL_ID}' "
              f"{source}{level}\n")
    return _invoke(body)


def _invoke(body):
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", body],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=POWERSHELL_TIMEOUT)
    return result.returncode, result.stdout + result.stderr


def board_command(output):
    """The launcher's command line, from whichever line reported it."""
    for line in output.splitlines():
        if "launch_web_ledger.py" in line and "MOCK-START" in line:
            return line
    for line in output.splitlines():
        if "launch_web_ledger.py" in line:
            return line
    return ""


class BoardLaunchTests(unittest.TestCase):
    """The board is the existing launcher's, with its own arguments intact."""

    def test_the_board_command_carries_the_launchers_own_required_arguments(self):
        """A missing credential file is a failure, not a board.

        The launcher requires a checkout, a data root, an OAuth file and a
        session secret file. A command line with three of them starts nothing,
        and if the plan exits zero the caller reads that as success.
        """
        _code, output = run_runner(mode="Plan")
        command = board_command(output)
        self.assertIn(f"--checkout {CHECKOUT}", command)
        self.assertIn(f"--data-root {DATA_ROOT}", command)
        self.assertIn(f"--oauth-file {OAUTH_FILE}", command)
        self.assertIn(f"--session-secret-file {SESSION_SECRET_FILE}", command)
        self.assertIn(f"--port {BOARD_PORT}", command)

    def test_participant_store_survives_checkout_changes_and_child_restart(self):
        shared = "C:\\synthetic\\shared rosters\\participant.sqlite"
        for checkout in (CHECKOUT, SPACED_CHECKOUT):
            code, output = run_runner(checkout=checkout, exit_on_start=1,
                                      extra=f"-ParticipantDb '{shared}'")
            self.assertEqual(code, 0, output)
            # A dead board child is restarted by the supervisor, inheriting the
            # same receiver database both times, regardless of release path.
            self.assertGreaterEqual(output.count(f"MOCK-PARTICIPANT-DB [{shared}]"), 2, output)

    def test_no_data_root_is_invented(self):
        """A `checkout/data` beside the real one would be a second, empty ledger."""
        _code, output = run_runner(mode="Plan")
        self.assertNotIn(CHECKOUT + "\\data", output)
        _code, plan_output = run_installer(install=False)
        self.assertNotIn(CHECKOUT + "\\data", plan_output)

    def test_each_missing_argument_is_named_rather_than_launched(self):
        for missing, code in (("data_root", "DATA_ROOT"),
                              ("oauth", "OAUTH_FILE"),
                              ("secret", "SESSION_SECRET_FILE")):
            with self.subTest(missing=missing):
                _code, output = run_runner(mode="Plan", **{missing: ""})
                self.assertIn(f"refused [{code}]", output)
                self.assertNotIn("MOCK-START", output)

    def test_the_task_passes_every_argument_to_the_runner(self):
        _code, output = run_installer()
        self.assertIn("MOCK-REGISTER action=powershell", output)
        self.assertIn("-WindowStyle Hidden", output)
        self.assertIn("start_web_ledger_host.ps1", output)
        for value in (CHECKOUT, DATA_ROOT, OAUTH_FILE, SESSION_SECRET_FILE,
                      CLOUDFLARE_CONFIG, TUNNEL_ID):
            self.assertIn(value, output, value)


class PortProbeTests(unittest.TestCase):
    def test_a_free_port_is_free_and_not_a_failed_query(self):
        """The mock raises for `Get-NetTCPConnection -LocalPort`.

        That is what real Windows does for a port with no listener, so a probe
        written that way cannot tell an empty port from an unreadable one and
        would refuse to start on a port that is free.
        """
        _code, output = run_runner(mode="Plan")
        self.assertIn(f"port {BOARD_PORT}: Free", output)
        _code, run_output = run_runner()
        self.assertIn("started [board]", run_output)

    def test_an_unreadable_port_table_refuses_rather_than_attempting(self):
        _code, output = run_runner(port_table_fails=True)
        self.assertIn("refused [BOARD]", output)
        self.assertIn("refused [ENTRY]", output)
        self.assertNotIn("started [board]", output)
        self.assertNotIn("started [entry]", output)
        # The tunnel is identified by its command line, not by a port.
        self.assertIn("started [tunnel]", output)

    def test_a_routable_listener_is_foreign_even_when_it_looks_familiar(self):
        _code, output = run_runner(
            listeners=[{"LocalAddress": "0.0.0.0", "LocalPort": BOARD_PORT,
                        "OwningProcess": 4242}],
            processes=[{"ProcessId": 4242, "CommandLine": LAUNCHER}])
        self.assertIn("refused [BOARD]", output)
        self.assertNotIn("started [board]", output)

    def test_a_working_board_on_the_port_is_a_noop(self):
        _code, output = run_runner(
            listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": BOARD_PORT,
                        "OwningProcess": 4242}],
            processes=[{"ProcessId": 4242, "CommandLine": LAUNCHER}])
        self.assertIn("noop [BOARD]", output)
        # The board is not started again. The entry page is a different program
        # on a different port and is expected to start.
        self.assertEqual(board_command(output), "", output)
        self.assertIn("started [tunnel]", output)

    def test_a_stranger_on_the_board_port_refuses_that_child_only(self):
        _code, output = run_runner(
            listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": BOARD_PORT,
                        "OwningProcess": 4242}],
            processes=[{"ProcessId": 4242,
                        "CommandLine": r"python C:\other\thing.py"}])
        self.assertIn("refused [BOARD]", output)
        self.assertIn("started [tunnel]", output)

    def test_nothing_is_ever_stopped_to_make_room(self):
        for kwargs in (
                {"port_table_fails": True},
                {"listeners": [{"LocalAddress": "127.0.0.1",
                                "LocalPort": BOARD_PORT,
                                "OwningProcess": 4242}],
                 "processes": [{"ProcessId": 4242,
                                "CommandLine": r"python C:\other\thing.py"}]}):
            with self.subTest(**kwargs):
                _code, output = run_runner(**kwargs)
                self.assertNotIn("MOCK-STOP", output)


class RestartRequestTests(unittest.TestCase):
    def test_a_live_board_is_restarted_only_with_a_request(self):
        for requested in (False, True):
            with self.subTest(requested=requested):
                code, output = run_runner(
                    watch=1, files={RESTART_REQUEST: ""} if requested else {},
                    listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": BOARD_PORT,
                                "OwningProcess": 4242}],
                    processes=[{"ProcessId": 4242, "CommandLine": LAUNCHER}])
                self.assertEqual(code, 0, output)
                if requested:
                    self.assertEqual(re.findall(r"MOCK-STOP id=(\d+)", output), ["4242"])
                    removed = "MOCK-REMOVED-FILE " + RESTART_REQUEST
                    self.assertIn(removed, output)
                    self.assertIn("restart [BOARD]", output)
                    self.assertIn("started [board]", output)
                    self.assertLess(output.index("MOCK-STOP"), output.index(removed))
                    self.assertLess(output.index(removed), output.index("MOCK-START"))
                else:
                    self.assertIn("noop [BOARD]", output)
                    self.assertNotIn("MOCK-STOP", output)
                    self.assertNotIn("MOCK-REMOVED-FILE", output)
                    self.assertEqual(board_command(output), "", output)

    def test_a_free_port_stops_only_the_exact_stale_launcher_and_port(self):
        for command in (f"python {LAUNCHER} --port {BOARD_PORT}",
                        f'python "{LAUNCHER}" --port "{BOARD_PORT}"'):
            with self.subTest(command=command):
                code, output = run_runner(
                    watch=1, files={RESTART_REQUEST: ""},
                    processes=[
                        {"ProcessId": 4242, "CommandLine": command},
                        {"ProcessId": 4243, "CommandLine": command},
                        {"ProcessId": 5001, "CommandLine": f"python {LAUNCHER}.other --port {BOARD_PORT}"},
                        {"ProcessId": 5002, "CommandLine": f"python {LAUNCHER} --port {BOARD_PORT}0"},
                        {"ProcessId": 5003, "CommandLine": f"python {LAUNCHER}"},
                        {"ProcessId": 5004, "CommandLine": ""},
                        {"ProcessId": 5005, "CommandLine": f"python C:\\other\\launch_web_ledger.py --port {BOARD_PORT}"},
                    ])
                self.assertEqual(code, 0, output)
                self.assertEqual(re.findall(r"MOCK-STOP id=(\d+)", output), ["4243", "4242"])
                self.assertIn("MOCK-REMOVED-FILE " + RESTART_REQUEST, output)
                self.assertIn("started [board]", output)

    def test_foreign_and_unknown_ownership_preserve_the_request(self):
        cases = (
            {"processes": [{"ProcessId": 4242, "CommandLine": r"python C:\other\thing.py"}]},
            {"processes": [{"ProcessId": 4242}]},
            {"port_table_fails": True},
            {"process_list_fails": True},
        )
        for case in cases:
            with self.subTest(case=case):
                code, output = run_runner(
                    watch=1, files={RESTART_REQUEST: ""},
                    listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": BOARD_PORT,
                                "OwningProcess": 4242}], **case)
                self.assertNotEqual(code, 0, output)
                self.assertIn("LEDGER_PROCESS_IDENTITY_UNVERIFIED", output)
                self.assertNotIn("MOCK-STOP", output)
                self.assertNotIn("MOCK-REMOVED-FILE", output)
                self.assertNotIn("MOCK-START", output)

    def test_a_port_that_does_not_release_preserves_the_request_and_starts_nothing(self):
        code, output = run_runner(
            watch=1, files={RESTART_REQUEST: ""}, stop_releases_port=False,
            listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": BOARD_PORT,
                        "OwningProcess": 4242}],
            processes=[{"ProcessId": 4242, "CommandLine": LAUNCHER}])
        self.assertNotEqual(code, 0, output)
        self.assertEqual(re.findall(r"MOCK-STOP id=(\d+)", output), ["4242"])
        self.assertIn("LEDGER_RESTART_PORT_NOT_FREE", output)
        self.assertNotIn("MOCK-REMOVED-FILE", output)
        self.assertNotIn("MOCK-START", output)

    def test_file_removal_allows_only_the_exact_request_and_consumes_the_map_entry(self):
        for target, allowed in ((RESTART_REQUEST, True), (REVIEW_CONFIG, False),
                                (RESTART_REQUEST + ".other", False)):
            with self.subTest(target=target):
                body = harness(files={RESTART_REQUEST: "", target: "synthetic"})
                body += f"""
try {{ Remove-Item -LiteralPath '{target}' -Force }}
catch {{ Write-Host ('MOCK-DENIED ' + $_.Exception.Message) }}
Write-Host ('MOCK-MAP-PRESENT ' + $script:files.ContainsKey('{target}'))
"""
                code, output = _invoke(body)
                self.assertEqual(code, 0, output)
                self.assertIn("MOCK-MAP-PRESENT " + ("False" if allowed else "True"), output)
                if allowed:
                    self.assertIn("MOCK-REMOVED-FILE " + target, output)
                    self.assertNotIn("MOCK-DENIED", output)
                else:
                    self.assertIn("MOCK-REFUSE-FILE-REMOVAL " + target, output)
                    self.assertNotIn("MOCK-REMOVED-FILE", output)


class TunnelIdentityTests(unittest.TestCase):
    """A tunnel has no port, so it is found by its own command line."""

    def test_the_tunnel_is_really_invoked_with_its_config_and_id(self):
        _code, output = run_runner()
        self.assertIn("MOCK-START file=" + CLOUDFLARE_EXE, output)
        self.assertIn(f"tunnel --config {CLOUDFLARE_CONFIG} run {TUNNEL_ID}",
                      output)
        self.assertIn("started [tunnel]", output)

    def test_a_matching_live_tunnel_is_a_noop(self):
        """The one that is already serving is the one that must not be doubled."""
        _code, output = run_runner(
            processes=[tunnel_process()])
        self.assertIn("noop [TUNNEL]", output)
        self.assertNotIn("MOCK-START file=" + CLOUDFLARE_EXE, output)

    def test_a_tunnel_id_that_only_appears_inside_another_one_is_not_a_match(self):
        """A substring is not an identity.

        Tunnel ids turn up in log paths and in the arguments of unrelated
        tooling. Treating that as our tunnel would report a NOOP while the
        tunnel actually serving the edge is somebody else's.
        """
        other = (f'"{CLOUDFLARE_EXE}" tunnel --config "{CLOUDFLARE_CONFIG}" '
                 f"run {TUNNEL_ID}-canary")
        _code, output = run_runner(processes=[tunnel_process(other)])
        self.assertNotIn("noop [TUNNEL]", output)
        self.assertIn("started [tunnel]", output)

    def test_a_tunnel_with_another_config_path_is_not_a_match(self):
        other = (f'"{CLOUDFLARE_EXE}" tunnel --config "C:\\other\\config.yml" '
                 f"run {TUNNEL_ID}")
        _code, output = run_runner(processes=[tunnel_process(other)])
        self.assertNotIn("noop [TUNNEL]", output)
        self.assertIn("started [tunnel]", output)

    def test_the_same_program_at_another_path_is_unknown_rather_than_free(self):
        """A name match is not an identity, and neither is a second copy.

        `cloudflared` is on the PATH of every machine that has it and a copy
        lives in several tool directories. One at another path may be serving the
        same edge, so the answer is Unknown — and Unknown does not start a third.
        """
        elsewhere = "C:\\other\\bin\\cloudflared.exe"
        _code, output = run_runner(
            processes=[tunnel_process(executable=elsewhere)])
        self.assertIn("refused [TUNNEL]", output)
        self.assertNotIn("MOCK-START file=" + CLOUDFLARE_EXE, output)

    def test_another_projects_tunnel_at_another_path_does_not_block_the_ledger(self):
        """A different tunnel of the same program name is not ours to wait for.

        Another project runs its own tunnel from its own directory. It serves a
        different tunnel id and config, so the ledger tunnel starts beside it,
        and the other process is neither stopped nor reconfigured.
        """
        other = (f'"C:\\other\\bin\\cloudflared.exe" tunnel --no-autoupdate run '
                 f"--token-file C:\\other\\tunnel.token")
        _code, output = run_runner(
            processes=[tunnel_process(other, executable="C:\\other\\bin\\cloudflared.exe")])
        self.assertIn("started [tunnel]", output)
        self.assertNotIn("refused [TUNNEL]", output)
        self.assertNotIn("MOCK-STOP", output)

    def test_the_same_tunnel_at_another_path_is_refused_even_with_another_name(self):
        """A second copy of this tunnel, by config path or by id, blocks a start."""
        same_id_other_config = (f'"C:\\other\\bin\\cloudflared.exe" tunnel --config '
                                f'"C:\\other\\config.yml" run {TUNNEL_ID}')
        _code, output = run_runner(processes=[tunnel_process(
            same_id_other_config, executable="C:\\other\\bin\\cloudflared.exe")])
        self.assertIn("refused [TUNNEL]", output)
        self.assertNotIn("MOCK-START file=" + CLOUDFLARE_EXE, output)

    def test_another_path_process_without_a_readable_path_is_unknown(self):
        """A process whose executable cannot be read may be ours: refuse."""
        unreadable = {"ProcessId": 5555, "ExecutablePath": "",
                      "CommandLine": '"C:\\x\\cloudflared.exe" tunnel --token-file t.tok'}
        _code, output = run_runner(processes=[unreadable])
        self.assertIn("refused [TUNNEL]", output)
        self.assertNotIn("MOCK-START file=" + CLOUDFLARE_EXE, output)

    def test_a_target_process_whose_command_line_is_unreadable_is_unknown(self):
        """It cannot be ruled out, so it is not treated as absent.

        Free would start a second cloudflared for the same tunnel, and two of
        them do not share the load politely.
        """
        _code, output = run_runner(
            unreadable_command_line=5555, processes=[tunnel_process()])
        self.assertIn("refused [TUNNEL]", output)
        self.assertNotIn("MOCK-START file=" + CLOUDFLARE_EXE, output)

    def test_an_unreadable_process_list_does_not_spawn_a_second_tunnel(self):
        """Cannot prove one is not running, so do not add a competitor.

        Two cloudflared processes for one tunnel do not share the load
        politely; they race for the same edge and the same connections.
        """
        _code, output = run_runner(process_list_fails=True)
        self.assertIn("refused [TUNNEL]", output)
        self.assertNotIn("MOCK-START file=" + CLOUDFLARE_EXE, output)
        self.assertIn("started [board]", output)

    def test_an_already_running_tunnel_is_watched_and_recovered(self):
        """Found running, so not ours to launch — and not ours to forget.

        The runner has no process handle for a tunnel it did not start, so the
        only way to know it is still there is to look again. When it goes, the
        runner starts it for real.
        """
        _code, output = run_runner(
            tunnel_answers=1,
            processes=[tunnel_process()])
        self.assertIn("noop [TUNNEL]", output)
        self.assertIn("gone [tunnel]", output)
        self.assertIn("MOCK-START file=" + CLOUDFLARE_EXE, output)
        # And the board, which this runner did start itself, is not started
        # twice while it is running.
        self.assertEqual(output.count("MOCK-START file=python"), 2)


class SupervisionTests(unittest.TestCase):
    def test_a_child_that_dies_is_started_again(self):
        """Claimed by what was started, not by a word in a message.

        The report and the second launch are the evidence: a restart that only
        announced itself would pass a test that read the wrong string.
        """
        _code, output = run_runner(exit_on_start=1)
        self.assertIn("exited [board]", output)
        launcher_starts = [line for line in output.splitlines()
                           if "MOCK-START" in line and "launch_web_ledger.py" in line]
        self.assertEqual(len(launcher_starts), 2, output)

    def test_a_child_refused_at_startup_is_retried_once_the_port_is_free(self):
        """A refusal is not a decision to give up.

        The port may be released a minute later, and a child abandoned on the
        first tick stays abandoned for the life of the process.
        """
        _code, output = run_runner(
            listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": ENTRY_PORT,
                        "OwningProcess": 4242}],
            processes=[{"ProcessId": 4242,
                        "CommandLine": r"python C:\other\thing.py"}])
        self.assertIn("refused [ENTRY]", output)
        # The stranger is still there, so every retry refuses again and nothing
        # is ever stopped for it.
        self.assertIn("retry [entry]", output)
        self.assertNotIn("MOCK-STOP", output)
        self.assertNotIn("started [entry]", output)

    def test_plan_mode_starts_nothing(self):
        _code, output = run_runner(mode="Plan", watch=0)
        self.assertNotIn("MOCK-START", output)
        self.assertIn("nothing is started", output)

    def test_the_entry_page_is_optional(self):
        _code, output = run_runner(extra="-DisableEntry")
        self.assertIn("started [board]", output)
        self.assertNotIn("serve_review_entry.py", output)


class QuotingTests(unittest.TestCase):
    def test_a_checkout_with_a_space_stays_one_argument(self):
        spaced_launcher = SPACED_CHECKOUT + "\\tools\\launch_web_ledger.py"
        spaced_root = "D:\\Ledger Data"
        _code, output = run_runner(mode="Plan", checkout=SPACED_CHECKOUT,
                                   data_root=spaced_root)
        self.assertIn(f'"{spaced_launcher}"', output)
        self.assertIn(f'"{spaced_root}"', output)
        # A path with no space in it is left plain, which is the other half of
        # the rule: quoting everything would be safe but unreadable.
        _code, plain = run_runner(mode="Plan")
        self.assertIn(f"--data-root {DATA_ROOT}", plain)
        _code, run_output = run_runner(checkout=SPACED_CHECKOUT)
        self.assertIn(f"wd={SPACED_CHECKOUT}", run_output)
        self.assertIn(f'"{spaced_launcher}"', run_output)

    def test_no_command_string_is_built_anywhere(self):
        for path in (RUNNER, INSTALLER):
            for number, line in enumerate(executable_lines(path), 1):
                for forbidden in ("cmd.exe", "cmd /c", "&&", "Invoke-Expression"):
                    self.assertNotIn(forbidden, line,
                                     f"{path.name}:{number}: {line}")

    def test_the_task_working_directory_is_the_checkout(self):
        _code, output = run_installer()
        self.assertIn(f"MOCK-REGISTER wd={CHECKOUT}", output)


class OwnershipMarkerTests(unittest.TestCase):
    def test_no_task_exists_so_install_creates_one(self):
        _code, output = run_installer(task_present=False)
        self.assertIn("create [MANAGED]: WebLedger-Board", output)
        self.assertIn("MOCK-REGISTER name=WebLedger-Board", output)

    def test_a_task_carrying_the_marker_is_replaced(self):
        _code, output = run_installer(
            task_present=True,
            task_description="LOCAL-HOST-002 managed task: web ledger host runner.")
        self.assertIn("replace [MANAGED]: WebLedger-Board", output)
        self.assertIn("MOCK-REGISTER name=WebLedger-Board", output)

    def test_a_same_named_task_without_the_marker_is_refused(self):
        """A name is not identity, and overwriting is not this installer's call."""
        _code, output = run_installer(
            task_present=True,
            task_description="a task belonging to another installer")
        self.assertIn("refused [TASK_NOT_OWNED]", output)
        self.assertNotIn("MOCK-REGISTER", output)

    def test_an_empty_description_is_not_ownership(self):
        _code, output = run_installer(task_present=True, task_description="")
        self.assertIn("refused [TASK_NOT_OWNED]", output)
        self.assertNotIn("MOCK-REGISTER", output)

    def test_the_run_level_is_chosen_and_printed(self):
        """Limited by default; Highest only when the installer is told.

        A Limited task cannot inspect a child running elevated, and cannot read
        the operating secrets it holds, so the runner's identity checks would come
        back unreadable and refuse every start. The operator decides, and the
        level used is printed rather than assumed.
        """
        _code, output = run_installer(install=False)
        self.assertIn("run level: Limited", output)
        _code, high = run_installer(install=False, run_level="Highest")
        self.assertIn("run level: Highest", high)
        # The level is a parameter with Limited as its default, and the two
        # choices are the only ones offered. A hard-coded `-RunLevel Limited`
        # would be the opposite of configurable.
        installer = INSTALLER.read_text(encoding="utf-8-sig")
        self.assertIn("[ValidateSet('Limited', 'Highest')]", installer)
        self.assertIn("[string]$RunLevel = 'Limited'", installer)
        self.assertIn("-RunLevel $Task.RunLevel", installer)

    def test_plan_mode_registers_nothing(self):
        _code, output = run_installer(install=False)
        self.assertNotIn("MOCK-REGISTER", output)
        self.assertIn("plan only", output)

    def test_missing_configuration_is_refused_before_anything_else(self):
        body = (harness() + f"\n$text = [System.IO.File]::ReadAllText('{INSTALLER}')\n"
                "$sb = [scriptblock]::Create($text)\n& $sb -Install\n")
        _code, output = _invoke(body)
        self.assertIn("refused [CHECKOUT]", output)
        self.assertNotIn("MOCK-REGISTER", output)


class LegacyEntryTests(unittest.TestCase):
    """The old server may hold 56069. Migration is exact or it does not happen."""

    def legacy(self, command_line):
        return run_runner(
            extra="-MigrateLegacyEntry",
            listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": ENTRY_PORT,
                        "OwningProcess": 4242}],
            processes=[{"ProcessId": 4242, "CommandLine": command_line}])

    def test_a_verified_legacy_server_is_migrated(self):
        _code, output = self.legacy(f'python "{LEGACY_SCRIPT}" --port {ENTRY_PORT}')
        self.assertIn("MOCK-STOP id=4242", output)
        self.assertIn("migrated [entry]", output)

    def test_migration_needs_the_exact_script_path(self):
        """A relative path is not proof, and the port table can already be stale."""
        _code, output = self.legacy(
            f"python tools\\serve_review.py --port {ENTRY_PORT}")
        self.assertNotIn("MOCK-STOP", output)
        # Not even classified as the legacy server: a relative path is somebody
        # else's command line, and the migration stops what it classified.
        self.assertIn("refused [ENTRY]", output)

    def test_migration_needs_the_explicit_port_value(self):
        _code, output = self.legacy(
            f'python "{LEGACY_SCRIPT}" --port {ENTRY_PORT + 1}')
        self.assertNotIn("MOCK-STOP", output)
        _code, embedded = self.legacy(
            f'python "{LEGACY_SCRIPT}" --log-port {ENTRY_PORT}')
        self.assertNotIn("MOCK-STOP", embedded)

    def test_a_legacy_server_is_reported_rather_than_stopped_by_default(self):
        _code, output = run_runner(
            listeners=[{"LocalAddress": "127.0.0.1", "LocalPort": ENTRY_PORT,
                        "OwningProcess": 4242}],
            processes=[{"ProcessId": 4242,
                        "CommandLine": f'python "{LEGACY_SCRIPT}" --port {ENTRY_PORT}'}])
        self.assertIn("operator [ENTRY_LEGACY]", output)
        self.assertNotIn("MOCK-STOP", output)
        self.assertNotIn("started [entry]", output)


class ReserveSourceConfigHandoverTests(unittest.TestCase):
    """The one file the launcher is allowed to read, and what it does with it.

    The reservation source configuration is read from a path the owner named on
    the command line and handed to the board as one environment value. Everything
    here is synthetic: the configuration and the roster file it names live in the
    harness's map and nowhere else, so the runner cannot reach a real roster even
    if the code asked for one.
    """

    VALID_CONFIG = ('{"path":"C:\\\\synthetic\\\\roster.csv","file_sha256":"'
                    + "a" * 64 + '","digest":"' + "b" * 64 + '"}')
    ROSTER = "reservation:SYNTHETIC-KEY,2026-01-01,1,100\n"

    def files(self, config=None, roster=True):
        table = {}
        if roster:
            table[SYNTHETIC_ROSTER] = self.ROSTER
        if config is not None:
            table[RESERVE_SOURCE_CONFIG] = config
        return table

    def reserve_env(self, output):
        """The value the board process would have been handed.

        `None` means no child was started at all, which is a different fact from
        a child started with nothing to inherit. The empty string is therefore a
        real answer here and is not collapsed into `None`.
        """
        for line in output.splitlines():
            if line.startswith("MOCK-CHILD-ENV"):
                return line.split("reserve=[", 1)[1].split("] review=[", 1)[0]
        return None

    def review_env(self, output):
        for line in output.splitlines():
            if line.startswith("MOCK-CHILD-ENV"):
                return line.split("] review=[", 1)[1].rstrip("]")
        return None

    def test_the_named_configuration_is_read_and_the_board_inherits_it(self):
        """A good configuration has to reach the child, not just this shell.

        Setting an environment value in the parent is not enough: the board is a
        separate process started by this launcher, so what matters is the value at
        the moment it is started. That is what the mock reports.
        """
        _code, output = run_runner(
            mode="Run", reserve_config=RESERVE_SOURCE_CONFIG,
            files=self.files(self.VALID_CONFIG), exit_on_start=1)
        self.assertIn(f"MOCK-READ {RESERVE_SOURCE_CONFIG}", output)
        handed = self.reserve_env(output)
        self.assertIsNotNone(handed, "no child was started")
        # One line, so the value cannot gain a stray newline the reader would
        # have to guess about.
        self.assertNotIn("\n", handed)
        # The handover is JSON text, so its backslashes are escaped and reading it
        # as a string would say nothing about the path it carries. It is parsed
        # here instead: the roster path has to survive the round trip as one
        # backslash, because a doubled one is a path that does not exist and the
        # board would refuse the configuration later.
        parsed = json.loads(handed)
        self.assertEqual(parsed["path"], SYNTHETIC_ROSTER)
        self.assertEqual(parsed["file_sha256"], "a" * 64)
        self.assertEqual(parsed["digest"], "b" * 64)
        self.assertEqual(sorted(parsed), ["digest", "file_sha256", "path"])
        # The review configuration is still passed the same way, so adding this
        # did not move the other one.
        self.assertEqual(self.review_env(output), REVIEW_CONFIG)

    def test_a_configuration_that_is_not_there_is_a_refusal_and_nothing_starts(self):
        _code, output = run_runner(
            mode="Run", reserve_config=RESERVE_SOURCE_CONFIG, files=self.files())
        self.assertIn("refused [RESERVE_SOURCE_CONFIG]", output)
        self.assertNotIn("MOCK-START", output)

    def test_a_directory_in_the_configurations_place_is_a_refusal(self):
        """`Test-Path -PathType Leaf` is what makes a directory a refusal.

        Without the leaf test, a directory at the same path would pass the
        existence check and the failure would arrive later as something else.
        """
        _code, output = run_runner(
            mode="Run", reserve_config=SYNTHETIC_DIRECTORY,
            files=dict(self.files(self.VALID_CONFIG),
                       **{SYNTHETIC_DIRECTORY: None}))
        self.assertIn("refused [RESERVE_SOURCE_CONFIG]", output)
        self.assertNotIn("MOCK-START", output)

    def test_a_configuration_naming_a_roster_that_is_not_there_is_a_refusal(self):
        """The file the configuration points at is checked too.

        A configuration that survives the launcher and fails inside the board
        would leave a running host whose link screen says the configuration is
        required, which reads the same as a source that has not changed.
        """
        _code, output = run_runner(
            mode="Run", reserve_config=RESERVE_SOURCE_CONFIG,
            files=self.files(self.VALID_CONFIG, roster=False))
        self.assertIn("refused [RESERVE_SOURCE_CONFIG]", output)
        self.assertNotIn("MOCK-START", output)

    def test_each_missing_field_is_named_rather_than_started_with(self):
        """A field that is absent is refused by name, not by a raw error.

        This is the case that is easy to get wrong: the runner reads
        `Set-StrictMode`, where touching a property that is not there throws.
        A throw would still stop the board from starting, but the operator would
        be reading a PowerShell stack instead of `refused
        [RESERVE_SOURCE_CONFIG]`, and the field that is missing would not be
        named anywhere.
        """
        for field in ("path", "file_sha256", "digest"):
            config = json.loads(self.VALID_CONFIG)
            del config[field]
            with self.subTest(field):
                _code, output = run_runner(
                    mode="Run", reserve_config=RESERVE_SOURCE_CONFIG,
                    files=self.files(json.dumps(config)))
                self.assertIn("refused [RESERVE_SOURCE_CONFIG]", output)
                self.assertIn(field, output)
                self.assertNotIn("PropertyNotFound", output)
                self.assertNotIn("MOCK-START", output)

    def test_a_field_that_is_empty_or_not_a_string_is_a_refusal(self):
        """`-not $value` alone would accept the number 0 and an empty array.

        So the type is checked too: a SHA is a string or it is not a SHA, and a
        blank one is not a SHA either.
        """
        for value in ('""', "0", "[]", "  "):
            config = json.loads(self.VALID_CONFIG)
            config["digest"] = json.loads(value) if value != "  " else "  "
            with self.subTest(value=value):
                _code, output = run_runner(
                    mode="Run", reserve_config=RESERVE_SOURCE_CONFIG,
                    files=self.files(json.dumps(config)))
                self.assertIn("refused [RESERVE_SOURCE_CONFIG]", output)
                self.assertNotIn("MOCK-START", output)

    def test_a_damaged_configuration_is_refused_without_starting_the_board(self):
        _code, output = run_runner(
            mode="Run", reserve_config=RESERVE_SOURCE_CONFIG,
            files=self.files('{"path": "C:\\\\synthetic\\\\roster.csv",'))
        self.assertIn("refused [RESERVE_SOURCE_CONFIG]", output)
        self.assertNotIn("MOCK-START", output)

    def test_no_configuration_clears_a_stale_one_rather_than_starting_with_it(self):
        """Absent stays absent.

        A supervisor respawn, a re-login or a restart inherits whatever this shell
        happened to carry. If the owner has withdrawn the setting, the next start
        must not quietly keep using the previous one, and it must not hand over an
        empty value either: an empty value reads as a configuration with nothing
        in it, which is a different state from no configuration at all.
        """
        body = (harness(exit_on_start=1)
                + "$env:WEBLEDGER_RESERVE_SOURCE = '{\"path\":\"stale\"}'\n"
                + f"\n$text = [System.IO.File]::ReadAllText('{RUNNER}')\n"
                  "$sb = [scriptblock]::Create($text)\n"
                  f"& $sb {runner_arguments(mode='Run')}\n")
        _code, output = _invoke(body)
        self.assertIn("MOCK-REMOVE Env:\\WEBLEDGER_RESERVE_SOURCE", output)
        # The mock reports the name it cleared, and the value is gone from this
        # session too: a mock that printed the removal but left the variable in
        # place would let the runner's else-branch pass for the wrong reason.
        self.assertIn("MOCK-REMOVED WEBLEDGER_RESERVE_SOURCE", output)
        # A child was started, and it inherited nothing. `assertFalse` would also
        # pass on `None`, which would mean no child started at all.
        self.assertEqual(self.reserve_env(output), "",
                         "the child was handed the stale configuration")
        self.assertNotIn("refused [RESERVE_SOURCE_CONFIG]", output)

    def test_no_configuration_reads_no_file_at_all(self):
        """Without the setting the launcher reads nothing and searches for nothing.

        The link screen shows configuration-required, so the launcher must not go
        looking for a roster to fill it in. The mock answers from a fixed map, so
        a path the launcher invented would have printed as an existence check.

        The one existence check that does happen is the restart-request marker,
        and this used to be `assertNotIn("MOCK-EXISTS", output)`, which was a
        blanket ban written before the marker existed. It did not say which path
        must not be probed, so it would equally have hidden a new file search. The
        check is now on the paths: nothing is read, and the only existence probe
        is the marker, which names no roster and opens nothing.
        """
        _code, output = run_runner(mode="Run", files=self.files(self.VALID_CONFIG))
        self.assertNotIn("MOCK-READ", output)
        probed = [line for line in output.splitlines()
                  if line.startswith("MOCK-EXISTS ")]
        self.assertEqual([line[len("MOCK-EXISTS "):] for line in probed],
                         [RESTART_REQUEST], output)
        # And the configuration that is sitting in the map is still not consulted.
        for value in (RESERVE_SOURCE_CONFIG, SYNTHETIC_ROSTER):
            self.assertNotIn(value, output)
        self.assertIn("MOCK-START", output)
        self.assertEqual(self.reserve_env(output), "")

    def test_no_credential_file_is_opened_and_nothing_the_runner_read_is_printed(self):
        """The boundary, checked by what the run actually did.

        The synthetic OAuth file and session secret hold canary text. If either
        were opened, this fails. The configuration's hashes and the roster's
        contents must not reach the output either — but the mock's own
        `MOCK-CHILD-ENV` line reports the handover on purpose, because that is
        how the test above knows the child was handed it. So the check is on the
        lines the runner itself wrote.
        """
        canary = "CANARY-SHOULD-NEVER-APPEAR"
        _code, output = run_runner(
            mode="Run", reserve_config=RESERVE_SOURCE_CONFIG,
            files=dict(self.files(self.VALID_CONFIG),
                       **{OAUTH_FILE: f"{{\"client_secret\":\"{canary}\"}}",
                          SESSION_SECRET_FILE: canary}))
        for opened in (OAUTH_FILE, SESSION_SECRET_FILE):
            self.assertNotIn(f"MOCK-READ {opened}", output, opened)
            self.assertNotIn(f"MOCK-EXISTS {opened}", output, opened)
        # The roster's existence was checked, which is all the launcher needs.
        self.assertIn(f"MOCK-EXISTS {SYNTHETIC_ROSTER}", output)
        self.assertNotIn(f"MOCK-READ {SYNTHETIC_ROSTER}", output)
        spoken = "\n".join(line for line in output.splitlines()
                           if not line.startswith("MOCK-"))
        self.assertNotIn(canary, spoken)
        self.assertNotIn(self.ROSTER.strip(), spoken)
        for value in ("a" * 64, "b" * 64):
            self.assertNotIn(value, spoken)

    def test_the_installer_passes_the_configuration_path_through_unchanged(self):
        """The installer hands the runner a path, not the configuration.

        It never opens the file. That is the point: the supervisor re-reads the
        configuration at every start, so a value frozen into the task at install
        time would go stale the moment the owner moved it.
        """
        _code, output = run_installer(
            reserve_source_config=RESERVE_SOURCE_CONFIG,
            files=self.files(self.VALID_CONFIG))
        self.assertIn(RESERVE_SOURCE_CONFIG, output)
        self.assertNotIn("MOCK-READ", output)
        self.assertNotIn("MOCK-EXISTS", output)

    def test_the_installer_without_the_setting_registers_no_configuration(self):
        _code, output = run_installer(files=self.files(self.VALID_CONFIG))
        self.assertNotIn(RESERVE_SOURCE_CONFIG, output)
        self.assertNotIn("MOCK-READ", output)


class IsolationTests(unittest.TestCase):
    #: Every cmdlet these two files are allowed to call. All of them are defined
    #: as functions in the harness, so a test that reaches a new code path still
    #: cannot touch a task, a process, a port or a network. The three file
    #: cmdlets are here for the one file the runner is allowed to read: the
    #: reservation source configuration the owner named on the command line.
    #: They answer from a fixed synthetic map and nothing else.
    MOCKED_CMDLETS = {
        "Get-NetTCPConnection", "Get-CimInstance", "Start-Process", "Add-Type",
        "Stop-Process", "Get-ScheduledTask", "Register-ScheduledTask",
        "New-ScheduledTaskAction", "New-ScheduledTaskTrigger",
        "New-ScheduledTaskPrincipal", "New-ScheduledTaskSettingsSet",
        "New-TimeSpan", "Test-Path", "Get-Content", "Remove-Item",
    }

    #: Built-ins that cannot touch the machine, so a file may use them without
    #: this harness replacing them. Anything outside this list and outside the
    #: file's own functions has to be mocked, or it would really run.
    SAFE_BUILTINS = {
        "Get-Date", "Join-Path", "Split-Path", "Set-StrictMode",
        "Where-Object", "Select-Object", "Sort-Object", "Write-Host", "Out-Null",
        "Start-Sleep", "Exit",
    }

    def external_cmdlets(self, path):
        """Every Verb-Noun token that is neither the file's own nor a safe built-in."""
        own = set(re.findall(r"^function ([A-Za-z]+-[A-Za-z]+)",
                             path.read_text(encoding="utf-8-sig"), re.M))
        called = set()
        for line in executable_lines(path):
            called |= set(re.findall(r"\b[A-Z][a-z]+-[A-Z][a-zA-Z]+\b", line))
        return called - own - self.SAFE_BUILTINS

    def test_the_scripts_call_nothing_this_harness_has_not_mocked(self):
        body = harness()
        for cmdlet in self.MOCKED_CMDLETS:
            self.assertIn(f"function {cmdlet} ", body, cmdlet)

        for path in (RUNNER, INSTALLER):
            external = self.external_cmdlets(path)
            unexpected = external - self.MOCKED_CMDLETS
            self.assertEqual(
                unexpected, set(),
                f"{path.name} would really call: {sorted(unexpected)}")
            # And it does call real-shaped cmdlets, so the check is not vacuous.
            self.assertTrue(external, f"{path.name} calls nothing at all")

    def test_the_probe_never_asks_for_a_single_port(self):
        """`Get-NetTCPConnection -LocalPort` raises when nothing is listening.

        So the port is filtered here, from every listener, and the code says so
        where the next person would otherwise reach for the shorter form.
        """
        for path in (RUNNER,):
            for line in executable_lines(path):
                self.assertNotIn("Get-NetTCPConnection -State Listen -LocalPort",
                                 line, f"{path.name}: {line}")

    def test_no_credential_is_read_or_echoed(self):
        """The launcher may open exactly one file, and it is not a credential.

        The reservation source configuration is the only file either file reads,
        and it is opened by the path the owner named on the command line. So the
        read is checked rather than forbidden: it must name that one parameter,
        and it must never name the OAuth file or the session secret file, which
        are handed to the board by path and never opened here.

        Everything that used to be forbidden outright still is, because none of
        it is needed to read a JSON file: the credential-shaped cmdlets, and a
        raw .NET read that would bypass the harness's synthetic map.
        """
        for path in (RUNNER, INSTALLER):
            for line in executable_lines(path):
                for forbidden in ("ReadAllText", "ReadAllLines", "-Password",
                                  "Read-Host", "RunAs", "HighestAvailable",
                                  "Unregister-ScheduledTask", "ConvertFrom-SecureString",
                                  "Get-Credential", "-Credential"):
                    self.assertNotIn(forbidden, line, f"{path.name}: {line}")
                if "Get-Content" in line:
                    self.assertIn("$ReserveSourceConfig", line,
                                  f"{path.name} reads a file nobody named: {line}")
                if "ConvertFrom-Json" in line:
                    # Only the source configuration is ever parsed, so the parse
                    # can only be fed the text that came out of that file.
                    self.assertIn("$reserveSourceText", line,
                                  f"{path.name} parses something else: {line}")
                for secret in ("$OAuthFile", "$SessionSecretFile"):
                    if "Get-Content" in line or "ConvertFrom-Json" in line:
                        self.assertNotIn(secret, line, f"{path.name}: {line}")
        installer = INSTALLER.read_text(encoding="utf-8-sig")
        self.assertIn("-LogonType Interactive", installer)

    def test_the_source_configuration_is_never_written_out(self):
        """Handing a value to the board is not the same as printing it.

        The configuration names a roster file and two hashes of it. A note that
        echoed either hash would put the roster's fingerprint into the installer's
        output log, so no line may write the parsed configuration's hashes, or the
        text read from the file, or the value handed to the child.

        Naming the roster *path* is allowed and intended: a refusal that says only
        "the configuration is wrong" tells the operator nothing they can act on,
        and the path is already on the command line they typed.
        """
        for path in (RUNNER, INSTALLER):
            for line in executable_lines(path):
                if not any(writer in line for writer in
                           ("Write-Host", "Write-Note", "Write-Output",
                            "Write-Warning", "Write-Verbose")):
                    continue
                for value in ("$reserveSourceText", "$reserveSourceJson.digest",
                              "$reserveSourceJson.file_sha256",
                              "$env:WEBLEDGER_RESERVE_SOURCE"):
                    self.assertNotIn(value, line, f"{path.name} echoes {value}: {line}")

    def test_the_legacy_server_is_named_in_one_place_and_stopped_in_one_place(self):
        """One name, and every stop accounted for by name rather than by count.

        The count this replaced was `exactly one Stop-Process in the runner`. It
        held while there was one place to stop anything, and it did not say which
        place that was, so the moment a second guarded stop was added the test had
        to be either loosened to a number or deleted. A number says nothing about
        safety: three unguarded stops would pass it exactly as one guarded stop
        did.

        So the stops are located instead. Every `Stop-Process` in the runner has
        to sit inside one of two named regions — the legacy migration function, or
        the explicit restart-request block — and both regions have to carry the
        identity proof that makes stopping safe. A stop anywhere else is a stop
        with nothing proved about its target, which is what this asserts against.
        """
        for path in (RUNNER, INSTALLER):
            for line in executable_lines(path):
                if "serve_review.py" in line:
                    self.assertIn("LegacyEntryName", line, f"{path.name}: {line}")
        self.assertEqual([line for line in executable_lines(INSTALLER)
                          if "Stop-Process" in line], [])

        lines = executable_lines(RUNNER)
        legacy = region(lines, "function Stop-LegacyEntry {",
                        "function Start-HostChildWhenFree {")
        restart = region(lines,
                         '$restartRequest = Join-Path $Checkout ".web-ledger-restart-request"',
                         "$refused = Start-HostRunner -Children $plan")
        self.assertTrue(legacy, "Stop-LegacyEntry was not found")
        self.assertTrue(restart, "the restart-request block was not found")

        stops = [(index, line) for index, line in enumerate(lines)
                 if "Stop-Process" in line]
        self.assertEqual(len(stops), 3, stops)
        for index, line in stops:
            in_legacy = any(a <= index < b for a, b in legacy)
            in_restart = any(a <= index < b for a, b in restart)
            self.assertTrue(
                in_legacy or in_restart,
                f"Stop-Process outside both guarded regions: {line}")

        # The legacy stop is reached only after the exact script path and the
        # exact port have been re-read from the command line, so what is stopped
        # is proved rather than assumed.
        legacy_lines = [lines[index] for a, b in legacy for index in range(a, b)]
        self.assertIn("Stop-Process", "\n".join(legacy_lines))
        self.assertIn("Get-ProcessCommandLine", "\n".join(legacy_lines))
        self.assertIn("-notlike", "\n".join(legacy_lines))
        self.assertIn("--port", "\n".join(legacy_lines))

        # The restart block stops in two shapes and both are proved: the listener
        # whose probe said Ours, and otherwise only processes carrying this plan's
        # exact launcher marker together with this exact port.
        restart_lines = [lines[index] for a, b in restart for index in range(a, b)]
        joined = "\n".join(restart_lines)
        self.assertIn('$probe.State -eq "Ours"', joined)
        self.assertIn("LEDGER_PROCESS_IDENTITY_UNVERIFIED", joined)
        self.assertIn("$board.Marker", joined)
        self.assertIn('"--port", "$BoardPort"', joined)

    def test_the_accepted_entry_page_and_the_legacy_server_are_untouched(self):
        self.assertIn("ledger.foresttour.kr/review",
                      (PROJECT_ROOT / "tools" / "serve_review_entry.py")
                      .read_text(encoding="utf-8"))
        self.assertNotIn("56069", (PROJECT_ROOT / "tools" / "serve_review_entry.py")
                         .read_text(encoding="utf-8"))
        self.assertTrue((PROJECT_ROOT / "tools" / "serve_review.py").exists())


if __name__ == "__main__":
    unittest.main()
