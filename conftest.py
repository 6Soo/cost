"""Temporary folders a test run creates live in one session folder that is removed when the run ends."""
import gc
import shutil
import tempfile
import time
from pathlib import Path

PREFIX = "cost-pytest-"
STALE_SECONDS = 6 * 3600
_session = {"dir": None, "previous": None}


def _remove_stale_sessions(root: str) -> None:
    # A server fixture can keep a SQLite file open until the process exits, so the
    # session folder of that run is swept by a later run once it is clearly finished.
    for old in Path(root).glob(PREFIX + "*"):
        try:
            if old.is_dir() and time.time() - old.stat().st_mtime > STALE_SECONDS:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


def pytest_configure(config):
    _session["previous"] = tempfile.tempdir
    _remove_stale_sessions(tempfile.gettempdir())
    _session["dir"] = tempfile.mkdtemp(prefix=PREFIX)
    tempfile.tempdir = _session["dir"]


def pytest_unconfigure(config):
    tempfile.tempdir = _session["previous"]
    folder = _session["dir"]
    if not folder:
        return
    # Windows can hold a just-closed SQLite file until its object is collected, so collect and retry.
    for _ in range(10):
        gc.collect()
        shutil.rmtree(folder, ignore_errors=True)
        if not Path(folder).exists():
            return
        time.sleep(0.3)
