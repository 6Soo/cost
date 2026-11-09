"""Start Python children as one process each.

On Windows a virtual environment's ``Scripts\\python.exe`` is a small launcher that starts the
base interpreter as a second process. The base interpreter given ``__PYVENV_LAUNCHER__`` behaves
exactly like that launcher's child (same ``sys.prefix``, site-packages and ``sys.executable``), so
starting it directly halves the processes without changing what runs. Anywhere this does not apply
the current interpreter is used unchanged.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LAUNCHER_VARIABLE = "__PYVENV_LAUNCHER__"


def _venv_base(executable: Path) -> Path | None:
    """The base interpreter behind a Windows venv launcher, or None when it is not one."""
    if os.name != "nt":
        return None
    config = executable.parent.parent / "pyvenv.cfg"
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    home = None
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip().lower() == "home":
            home = value.strip()
    if not home:
        return None
    base = Path(home) / executable.name
    return base if base.is_file() else None


def python_command(executable: str | os.PathLike | None = None) -> tuple[list[str], dict[str, str]]:
    """The argv prefix and extra environment that start `executable` as a single process."""
    target = Path(executable or sys.executable)
    base = _venv_base(target)
    if base is None:
        return [str(target)], {}
    return [str(base)], {LAUNCHER_VARIABLE: str(target)}


def child_environment(extra: dict[str, str], base: dict[str, str] | None = None) -> dict[str, str] | None:
    """The environment for a child: None (inherit) when nothing is added."""
    if not extra:
        return None
    env = dict(os.environ if base is None else base)
    env.update(extra)
    return env
