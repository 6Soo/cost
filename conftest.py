"""Temporary folders a test run creates live in one session folder that is removed when the run ends."""
import gc
import os
import stat
import shutil
import tempfile
import time
from pathlib import Path

PREFIX = "cost-pytest-"
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_session = {"dir": None, "root": None, "previous": None}


def _is_reparse_point(details) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & REPARSE_POINT
    )


def _is_safe_session_child(folder: str | Path, root: str | Path) -> bool:
    """Only remove the directory this pytest process created directly under temp root."""
    candidate = Path(folder)
    try:
        resolved_root = Path(root).resolve(strict=True)
        details = candidate.lstat()
        if not stat.S_ISDIR(details.st_mode) or _is_reparse_point(details):
            return False
        resolved_candidate = candidate.resolve(strict=True)
        return (
            resolved_candidate != resolved_root
            and resolved_candidate.parent == resolved_root
            and candidate.parent.resolve(strict=True) == resolved_root
        )
    except (OSError, RuntimeError):
        return False


def _remove_session_folder(folder: str | Path, root: str | Path, *, retries=10, delay=0.3) -> bool:
    """Retry deletion of this run's temp folder; never sweep another run's folder."""
    candidate = Path(folder)
    for attempt in range(retries):
        if not os.path.lexists(candidate):
            return True
        if not _is_safe_session_child(candidate, root):
            return False
        gc.collect()
        shutil.rmtree(candidate, ignore_errors=True)
        if not os.path.lexists(candidate):
            return True
        if attempt + 1 < retries:
            time.sleep(delay)
    return False


def pytest_configure(config):
    _session["previous"] = tempfile.tempdir
    _session["root"] = Path(tempfile.gettempdir()).resolve()
    _session["dir"] = tempfile.mkdtemp(prefix=PREFIX)
    tempfile.tempdir = _session["dir"]


def pytest_unconfigure(config):
    tempfile.tempdir = _session["previous"]
    folder = _session["dir"]
    if not folder:
        return
    # Other runs may still own old temp folders; each run cleans only its own direct child.
    _remove_session_folder(folder, _session["root"])
