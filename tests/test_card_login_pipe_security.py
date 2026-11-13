"""Card-login named-pipe security regression checks (synthetic, isolated temp store).

Covers the two REQUEST_CHANGES findings on the credential pipe:
  * the pipe DACL grants access only to the current-user SID (other accounts,
    Everyone, anonymous and a synthetic other-user SID are denied), and
  * the server delivers the secret only to the expected client PID — an
    unexpected client PID is rejected fail-closed (no bytes sent).

No real credential, card site, login session or production secret store is
touched: synthetic fixture values are registered into a temporary store root and
removed afterwards. A missing PowerShell toolchain fails the check instead of
skipping.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK_PS1 = ROOT / "tests" / "card_login" / "pipe_security_check.ps1"

EXP_ID = "synthetic-id-123"
EXP_PW = "synthetic-pw-456"
EXP_CERT = "synthetic-cert-789"
TIMEOUT = 180


def _powershell() -> str:
    exe = shutil.which("powershell.exe") or shutil.which("powershell")
    if exe is None:
        pytest.fail("powershell executable not found; toolchain must not be auto-installed")
    return exe


def test_pipe_acl_and_client_pid_enforcement() -> None:
    ps = _powershell()
    with tempfile.TemporaryDirectory(prefix="card-login-pipe-") as tmp:
        store = str(Path(tmp))
        check = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(CHECK_PS1), "-StoreRoot", store],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=TIMEOUT, check=False,
        )
        assert check.returncode == 0, f"pipe_security_check failed:\n{check.stdout}\n{check.stderr}"
        for secret in (EXP_ID, EXP_PW, EXP_CERT):
            assert secret not in check.stdout, "plaintext secret leaked into check stdout"
            assert secret not in check.stderr, "plaintext secret leaked into check stderr"

        result = json.loads(check.stdout.strip().splitlines()[-1])
        # (1) DACL: 현재 사용자 SID 만 허용, 그 외 계정/Everyone/익명 거부.
        assert result["aclOnlyCurrentUser"] is True, "pipe DACL grants access beyond current user"
        assert result["aclNoEveryone"] is True, "pipe DACL grants Everyone"
        assert result["aclNoAnonymous"] is True, "pipe DACL grants anonymous"
        assert result["aclOtherUserDenied"] is True, "pipe DACL grants a synthetic other-user SID"
        # (2) 기대 PID 클라이언트는 등록 값을 받는다.
        assert result["expectedPidAccepted"] is True, "expected client PID was not served"
        assert result["payloadMatchesRegistered"] is True, "served payload does not match registered credential"
        # (3) 예상 밖 PID 클라이언트는 값을 받지 못한다(fail closed).
        assert result["unexpectedClientRejected"] is True, "unexpected client PID received the secret"
