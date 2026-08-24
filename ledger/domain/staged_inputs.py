"""Shared root for staged evidence rounds.

Historical admission families read sealed evidence packages that were staged
under ``/tmp`` on the original Linux sessions.  The location is now resolved
from ``COST_STAGED_INPUT_DIR`` when set, falling back to the platform standard
temporary directory so the same code runs universally.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

STAGED_INPUT_DIR = Path(
    os.environ.get("COST_STAGED_INPUT_DIR") or tempfile.gettempdir()
)


def staged(*names: str) -> Path:
    return STAGED_INPUT_DIR.joinpath(*names)


def is_strict_static_pins() -> bool:
    """Strict pin mode for historical reproduction. Default non-strict (warn)."""
    return os.getenv("COST_STRICT_STATIC_PINS") == "1"
