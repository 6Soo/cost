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


def test_sweep_removes_only_old_exact_child_exchanges(tmp_path):
    import os
    import time
    from app.python_launch import sweep_stale_child_files
    stale = time.time() - 3 * 3600
    old_in = tmp_path / ('ota-reconcile-' + 'a' * 32 + '.in')
    old_out = tmp_path / ('ota-reconcile-' + 'b' * 32 + '.out')
    fresh = tmp_path / ('ota-reconcile-' + 'c' * 32 + '.in')
    audit = tmp_path / 'ota-reconcile-audit.json'
    snapshot = tmp_path / 'ota-snapshot.json'
    exchange = tmp_path / 'ota-catalog-worker-ab12cd_3'
    data_dir = tmp_path / 'ota-catalog-worker-ab12cd_4'
    named = tmp_path / 'ota-catalog-worker-keep'
    for path in (old_in, old_out, fresh, audit, snapshot):
        path.write_text('x', encoding='utf-8')
    for folder, files in ((exchange, ('request', 'result')), (data_dir, ('request', 'notes.txt')), (named, ('request',))):
        folder.mkdir()
        for name in files:
            (folder / name).write_text('x', encoding='utf-8')
            os.utime(folder / name, (stale, stale))
    for path in (old_in, old_out, audit, snapshot, exchange, data_dir, named):
        os.utime(path, (stale, stale))
    assert sweep_stale_child_files(tmp_path) == 3
    assert not old_in.exists() and not old_out.exists() and not exchange.exists()
    assert fresh.exists() and audit.exists() and snapshot.exists() and data_dir.exists() and named.exists()
