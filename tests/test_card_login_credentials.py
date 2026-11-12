"""Card-login credential storage checks (synthetic values, isolated temp store).

Covers the DPAPI round-trip, the ciphertext file holding no plaintext, the
one-shot named-pipe delivery to the Node client, and the not-registered path.
No real credential, card site, login session or production secret store is
 touched: every run registers synthetic fixture values into a temporary store
root and removes it afterwards. A missing PowerShell/Node toolchain fails the
check instead of skipping.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK_PS1 = ROOT / "tests" / "card_login" / "credential_check.ps1"
PROBE_MJS = ROOT / "tests" / "card_login" / "read_probe.mjs"

EXP_ID = "synthetic-id-123"
EXP_PW = "synthetic-pw-456"
EXP_CERT = "synthetic-cert-789"
TIMEOUT = 120


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _powershell() -> str:
    exe = shutil.which("powershell.exe") or shutil.which("powershell")
    if exe is None:
        pytest.fail("powershell executable not found; toolchain must not be auto-installed")
    return exe


def _node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.fail("node executable not found; toolchain must not be auto-installed")
    return exe


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=TIMEOUT, check=False)


def test_credential_dpapi_roundtrip_and_pipe_delivery() -> None:
    ps = _powershell()
    node = _node()
    with tempfile.TemporaryDirectory(prefix="card-login-store-") as tmp:
        store = str(Path(tmp))

        # 1) DPAPI 등록·왕복·평문 유출 (PowerShell, 불리언만 출력).
        check = _run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                      "-File", str(CHECK_PS1), "-StoreRoot", store])
        assert check.returncode == 0, f"credential_check failed:\n{check.stdout}\n{check.stderr}"
        for secret in (EXP_ID, EXP_PW, EXP_CERT):
            assert secret not in check.stdout, "plaintext secret leaked into check stdout"
            assert secret not in check.stderr, "plaintext secret leaked into check stderr"
        result = json.loads(check.stdout.strip().splitlines()[-1])
        assert result["registered"] is True
        assert result["idMatch"] is True
        assert result["pwMatch"] is True
        assert result["certMatch"] is True
        assert result["fileHasPlaintext"] is False, "ciphertext file contains plaintext"
        assert result["schemaOk"] is True
        assert result["hanaRegistered"] is False

        # 암호화 파일이 실제로 존재하고 평문이 없는지 직접 확인.
        cred_file = Path(store) / "kb.json"
        assert cred_file.is_file()
        raw = cred_file.read_text(encoding="utf-8")
        for secret in (EXP_ID, EXP_PW, EXP_CERT):
            assert secret not in raw

        # 2) named pipe 전달 → Node 클라이언트 (해시만 출력, 평문 없음).
        probe = _run([node, str(PROBE_MJS), "kb", store])
        assert probe.returncode == 0, f"read_probe failed:\n{probe.stdout}\n{probe.stderr}"
        for secret in (EXP_ID, EXP_PW, EXP_CERT):
            assert secret not in probe.stdout, "plaintext secret leaked into probe stdout"
            assert secret not in probe.stderr, "plaintext secret leaked into probe stderr"
        delivered = json.loads(probe.stdout.strip().splitlines()[-1])
        assert delivered["status"] == "ok"
        assert delivered["idSha256"] == _sha(EXP_ID)
        assert delivered["passwordSha256"] == _sha(EXP_PW)
        assert delivered["certSha256"] == _sha(EXP_CERT)
        assert delivered["idLen"] == len(EXP_ID)
        assert delivered["passwordLen"] == len(EXP_PW)

        # 3) 미등록 발급사 → not_registered (로그인 시도 없음).
        missing = _run([node, str(PROBE_MJS), "hana", store])
        assert missing.returncode == 0, f"read_probe(hana) failed:\n{missing.stdout}\n{missing.stderr}"
        assert json.loads(missing.stdout.strip().splitlines()[-1])["status"] == "not_registered"
