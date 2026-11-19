"""Windows-only parse check for the incremental P2 registration script.

The script is a PowerShell file, so only Windows PowerShell can decide whether
it parses. A Linux run of the same call fails on a missing `powershell`
executable rather than on the script, which is not evidence of anything. The
portable half of the old test (file location and the dry-run contract) stays in
tests/test_p2_incremental.py and still runs on Linux.
"""
import subprocess
from pathlib import Path

from tools.p2_batch import run_incremental as inc


def test_registration_script_parses():
    script = Path(inc.__file__).with_name('register_incremental_task.ps1')
    assert script.is_file(), 'The registration script must ship next to the module'
    result = subprocess.run(['powershell', '-NoProfile', '-Command',
        '$tokens=$null; $parseErrors=$null; [System.Management.Automation.Language.Parser]::ParseFile(\''
        + str(script) + "', [ref]$tokens, [ref]$parseErrors) | Out-Null; if ($parseErrors.Count) { exit 1 }"],
        capture_output=True)
    assert result.returncode == 0, result.stdout.decode('utf-8', 'replace') + result.stderr.decode('utf-8', 'replace')
