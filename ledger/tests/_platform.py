"""Platform capability gates for environment-bound regression families.

The operating premise of this repository is Windows-first development with
universal (cross-platform) execution where the underlying OS primitives allow
it.  Families that depend on staged evidence rounds or POSIX-only durability
machinery stay runnable through explicit capability flags instead of failing
with raw OS errors.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

STAGED_INPUT_DIR = Path(
    os.environ.get("COST_STAGED_INPUT_DIR") or tempfile.gettempdir()
)


def staged_input(*names: str) -> Path:
    return STAGED_INPUT_DIR.joinpath(*names)


def _symlink_privilege_ok() -> bool:
    try:
        directory = tempfile.mkdtemp(prefix="cap-probe-")
        target = os.path.join(directory, "target")
        link = os.path.join(directory, "link")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("probe")
        os.symlink(target, link)
        os.remove(link)
        os.remove(target)
        os.rmdir(directory)
        return True
    except OSError:
        return False


SYMLINK_OK = _symlink_privilege_ok()


def requires_staged_evidence(reason: str = "staged evidence round unavailable"):
    """Skip unless COST_STAGED_INPUT_DIR points at a usable staging root."""

    enabled = bool(os.environ.get("COST_STAGED_INPUT_DIR"))
    return unittest.skipUnless(enabled, f"environment-bound: {reason}")


def allow_pin_drift(
    reason: str = (
        "explicit regression check switch is off; "
        "run the original checks with COST_ALLOW_PIN_DRIFT"
    )
):
    """Skip while the explicit regression switch is off; COST_ALLOW_PIN_DRIFT runs the original checks."""

    enabled = bool(os.environ.get("COST_ALLOW_PIN_DRIFT"))
    return unittest.skipUnless(enabled, f"environment-bound: {reason}")


def requires_posix_durability():
    """Skip on Windows: renameat2/dir-fsync/nlink publication contracts."""

    return unittest.skipUnless(
        os.name == "posix",
        "environment-bound: POSIX durability machinery (renameat2, dir fsync)",
    )


def requires_symlinks():
    return unittest.skipUnless(
        SYMLINK_OK,
        "environment-bound: symlink privilege (enable Windows Developer Mode)",
    )
