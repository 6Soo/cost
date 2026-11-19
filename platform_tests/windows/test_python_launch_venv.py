"""Windows-only venv launcher contract.

`app/python_launch.py::_venv_base` returns None off-Windows because a `.exe`
launcher plus `pyvenv.cfg` is a Windows virtual-environment detail. Running these
assertions on Linux would test the early-return, not the launcher contract.
They execute here in the windows-p2-descendant-boundary job.

The portable launcher assertions stay in webapp/tests/test_python_launch.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.python_launch import LAUNCHER_VARIABLE, python_command  # noqa: E402


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


def test_a_venv_launcher_is_replaced_by_its_base_interpreter(tmp_path):
    launcher = _fake_venv(tmp_path)
    argv, env = python_command(launcher)
    assert argv == [str(tmp_path / "base" / "python.exe")]
    assert env == {LAUNCHER_VARIABLE: str(launcher)}


def test_a_venv_whose_base_is_missing_keeps_the_launcher(tmp_path):
    launcher = _fake_venv(tmp_path, base_exists=False)
    assert python_command(launcher) == ([str(launcher)], {})
