"""Python children start as one process and see the same environment as their parent."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.python_launch import LAUNCHER_VARIABLE, child_environment, python_command


def _fake_venv(tmp_path: Path, base_exists: bool = True) -> Path:
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    if base_exists:
        (base_dir / "python.exe").write_bytes(b"")
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"")
    (tmp_path / "venv" / "pyvenv.cfg").write_text(f"home = {base_dir}\nversion = 3.14.0\n", encoding="utf-8")
    return scripts / "python.exe"


def test_a_plain_interpreter_is_used_as_it_is(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"")
    assert python_command(exe) == ([str(exe)], {})


@pytest.mark.skipif(os.name != "nt", reason="venv launchers are a Windows detail")
def test_a_venv_launcher_is_replaced_by_its_base_interpreter(tmp_path):
    launcher = _fake_venv(tmp_path)
    argv, env = python_command(launcher)
    assert argv == [str(tmp_path / "base" / "python.exe")]
    assert env == {LAUNCHER_VARIABLE: str(launcher)}


@pytest.mark.skipif(os.name != "nt", reason="venv launchers are a Windows detail")
def test_a_venv_whose_base_is_missing_keeps_the_launcher(tmp_path):
    launcher = _fake_venv(tmp_path, base_exists=False)
    assert python_command(launcher) == ([str(launcher)], {})


def test_nothing_added_means_the_child_inherits_the_environment():
    assert child_environment({}) is None
    assert child_environment({"A": "1"}, base={"B": "2"}) == {"A": "1", "B": "2"}


def test_the_child_is_a_direct_child_with_the_same_environment():
    argv, extra = python_command()
    probe = "import os, sys; print(sys.prefix); print(os.getppid())"
    output = subprocess.run([*argv, "-I", "-c", probe], capture_output=True, text=True, check=True,
                            env=child_environment(extra)).stdout.split()
    assert output[0] == sys.prefix
    assert int(output[1]) == os.getpid()
