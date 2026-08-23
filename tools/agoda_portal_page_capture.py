#!/usr/bin/env python3
"""Capture Agoda completed-booking pages into an isolated staging database.

The browser is deliberately treated as the only source of truth for this run.
The tool re-reads the accessibility tree after every page transition, records
all visible cards (including non-2026 cards on the boundary page), and exposes
only aggregate output.  It never writes the candidate ledger database.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows uses msvcrt locking below
    fcntl = None  # type: ignore[assignment]
import functools
import hashlib
import json
import os
import re
import secrets
import signal
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt


ORCA = os.environ.get("ORCA_BIN") or shutil.which("orca") or "orca"
WINDOWS_UIA_FOREGROUND_OPERATIONS = frozenset({"hotkey", "type", "press"})
WINDOWS_UIA_MUTATING_OPERATIONS = frozenset(
    {"click", "select", "hotkey", "type", "press"}
)
WINDOWS_UIA_LOCK_DIRECTORY = Path(tempfile.gettempdir()) / "agoda-windows-uia-locks"
WINDOWS_UIA_FOREGROUND_LOCK_PATH = WINDOWS_UIA_LOCK_DIRECTORY / "foreground.lock"
WINDOWS_UIA_BRIDGE_SLOT_COUNT = 5
WINDOWS_UIA_BRIDGE_SLOT_PATHS = tuple(
    WINDOWS_UIA_LOCK_DIRECTORY / f"bridge-slot-{slot_no}.lock"
    for slot_no in range(WINDOWS_UIA_BRIDGE_SLOT_COUNT)
)
WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS = 300.0
WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS = 60.0
WINDOWS_UIA_FOREGROUND_LOCK_TIMEOUT_SECONDS = 30.0
WINDOWS_UIA_FOREGROUND_LOCK_POLL_SECONDS = 0.05
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
DATE_RE = re.compile(
    r"(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2})(?:,\s+(?P<year>\d{2,4}))?"
)
CARD_RE = re.compile(r"mmb-booking-card--([^\s]+)")
NODE_RE = re.compile(r"^\s*(\d+)\s+단추\s+(\d+)\s*$")
SPECIAL_NODE_RE = re.compile(
    r"^\s*(\d+)\s+단추\s+(Next(?: page)?|Previous(?: page)?)\s*$"
)
ACTIONABLE_NODE_RE = re.compile(
    r"^\s*(\d+)\s+(?:단추|탭 항목|링크|button|tab item|link)\s+(.+?)\s*$",
    re.IGNORECASE,
)
EXPECTED_PAGE_ORDER = (10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 11, 12, 13)


class WindowsUIABridgeError(RuntimeError):
    """A bridge error with safe, aggregate-only diagnostics when available."""

    def __init__(
        self,
        code: str,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.diagnostic = diagnostic or {}
        super().__init__(f"windows UIA browser command failed:{code}")


@functools.lru_cache(maxsize=1)
def _windows_uia_script_path(timeout: float = 10.0) -> str:
    script = Path(__file__).with_name("agoda_windows_uia_bridge.ps1").resolve()
    if not script.is_file():
        raise RuntimeError("windows UIA bridge script not found")
    return str(script)


_resolve_windows_uia_bridge_script = _windows_uia_script_path

CSC_PATH_DEFAULT = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
FRAMEWORK64_DIR_DEFAULT = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319"

_compiled_csharp_bridge: dict[str, Any] | None = None
_csharp_compile_lock = threading.Lock()
_atexit_registered = False


def _cleanup_compiled_bridge() -> None:
    global _compiled_csharp_bridge
    if _compiled_csharp_bridge is not None:
        bridge_path = _compiled_csharp_bridge.get("path")
        if bridge_path:
            try:
                if os.path.exists(bridge_path):
                    os.remove(bridge_path)
            except Exception:
                pass


def _resolve_csharp_source_windows_path(timeout: float = 10.0) -> str:
    source = Path(__file__).with_name("AgodaWindowsUiaBridge.cs").resolve()
    if not source.is_file():
        raise RuntimeError("windows UIA bridge source not found") from None
    return str(source)


def _resolve_temp_dir(timeout: float = 10.0) -> str:
    return tempfile.gettempdir()


def _verify_csharp_bridge_executable(exe_info: dict[str, Any]) -> None:
    bridge_path = exe_info.get("path")
    expected_sha = exe_info.get("sha256")
    if not bridge_path or not expected_sha or not os.path.isfile(bridge_path):
        raise RuntimeError("windows UIA bridge executable verification failed")
    verification_failed = False
    current_sha = ""
    try:
        with open(bridge_path, "rb") as f:
            content = f.read()
        current_sha = hashlib.sha256(content).hexdigest()
    except Exception:
        verification_failed = True
    if verification_failed or current_sha != expected_sha:
        raise RuntimeError("windows UIA bridge executable verification failed")


def _ensure_csharp_bridge(
    *,
    total_deadline: float,
    process_cap: float,
) -> dict[str, Any]:
    global _compiled_csharp_bridge, _atexit_registered
    if _compiled_csharp_bridge is not None:
        return _compiled_csharp_bridge

    with _csharp_compile_lock:
        if _compiled_csharp_bridge is not None:
            return _compiled_csharp_bridge

        remaining = total_deadline - time.monotonic()
        if remaining <= process_cap:
            raise RuntimeError("windows UIA bridge admission timed out")

        step_timeout = min(10.0, remaining - process_cap)
        if step_timeout <= 0:
            raise RuntimeError("windows UIA bridge admission timed out")

        win_src = _resolve_csharp_source_windows_path(timeout=step_timeout)

        remaining = total_deadline - time.monotonic()
        if remaining <= process_cap:
            raise RuntimeError("windows UIA bridge admission timed out")
        step_timeout = min(10.0, remaining - process_cap)
        if step_timeout <= 0:
            raise RuntimeError("windows UIA bridge admission timed out")

        temp_dir = _resolve_temp_dir(timeout=step_timeout)

        target_found = False
        bridge_path = ""
        for _ in range(10):
            token = secrets.token_hex(16)
            exe_filename = f"agoda_uia_{token}.exe"
            candidate_path = os.path.join(temp_dir, exe_filename)
            if not os.path.exists(candidate_path):
                bridge_path = candidate_path
                target_found = True
                break
        if not target_found:
            raise RuntimeError("windows UIA bridge compilation failed")

        remaining = total_deadline - time.monotonic()
        if remaining <= process_cap:
            raise RuntimeError("windows UIA bridge admission timed out")
        compile_timeout = min(30.0, remaining - process_cap)
        if compile_timeout <= 0:
            raise RuntimeError("windows UIA bridge admission timed out")

        framework_dir = FRAMEWORK64_DIR_DEFAULT
        wpf_dir = rf"{framework_dir}\WPF"
        csc_path = CSC_PATH_DEFAULT

        compile_cmd = [
            csc_path,
            "/noconfig",
            "/platform:x64",
            f"/r:{framework_dir}\\mscorlib.dll",
            f"/r:{framework_dir}\\System.dll",
            f"/r:{framework_dir}\\System.Core.dll",
            f"/r:{wpf_dir}\\UIAutomationClient.dll",
            f"/r:{wpf_dir}\\UIAutomationTypes.dll",
            f"/r:{wpf_dir}\\WindowsBase.dll",
            f"/r:{framework_dir}\\System.Windows.Forms.dll",
            f"/r:{framework_dir}\\System.Web.Extensions.dll",
            f"/out:{bridge_path}",
            win_src,
        ]

        timed_out = False
        failed = False
        compile_process: subprocess.CompletedProcess[str] | None = None
        try:
            compile_process = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=compile_timeout,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
        except Exception:
            failed = True

        if timed_out:
            raise RuntimeError("windows UIA bridge compilation timed out") from None
        if failed or compile_process is None or compile_process.returncode != 0:
            raise RuntimeError("windows UIA bridge compilation failed") from None

        if not os.path.isfile(bridge_path):
            raise RuntimeError("windows UIA bridge executable verification failed")
        try:
            with open(bridge_path, "rb") as f:
                content = f.read()
            file_sha256 = hashlib.sha256(content).hexdigest()
        except Exception:
            raise RuntimeError("windows UIA bridge executable verification failed") from None

        _compiled_csharp_bridge = {
            "path": bridge_path,
            "sha256": file_sha256,
        }

        if not _atexit_registered:
            atexit.register(_cleanup_compiled_bridge)
            _atexit_registered = True

        return _compiled_csharp_bridge



def _argument(args: tuple[str, ...], name: str) -> str:
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        raise RuntimeError(f"browser bridge argument missing:{name}") from None


@contextlib.contextmanager
def _windows_uia_foreground_lock() -> Any:
    deadline = time.monotonic() + WINDOWS_UIA_FOREGROUND_LOCK_TIMEOUT_SECONDS
    attempt = 0
    while True:
        descriptor = _try_private_file_lock(WINDOWS_UIA_FOREGROUND_LOCK_PATH)
        if descriptor is not None:
            break
        if not _bounded_lock_sleep(deadline, attempt):
            raise RuntimeError("windows UIA foreground lock timed out")
        attempt += 1
    try:
        yield
    finally:
        _release_private_file_lock(descriptor)


def _open_private_lock_directory(directory: Path) -> int:
    if os.name == "nt":
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return os.open(str(directory), os.O_RDONLY)
        except OSError:
            raise RuntimeError("windows UIA lock directory unavailable") from None
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    except OSError:
        raise RuntimeError("windows UIA lock directory unavailable") from None

    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        raise RuntimeError("windows UIA lock directory unavailable") from None
    metadata = os.fstat(descriptor)
    cloexec = fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or not cloexec
    ):
        os.close(descriptor)
        raise RuntimeError("windows UIA lock directory is not private")
    return descriptor


def _open_private_lock_file(path: Path) -> int:
    if os.name == "nt":
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                str(path), os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
            )
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            return descriptor
        except OSError:
            raise RuntimeError("windows UIA lock unavailable") from None
    directory_descriptor = _open_private_lock_directory(path.parent)
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            path.name,
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
    except OSError:
        os.close(directory_descriptor)
        raise RuntimeError("windows UIA lock unavailable") from None
    finally:
        if "descriptor" in locals():
            os.close(directory_descriptor)

    metadata = os.fstat(descriptor)
    cloexec = fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or not cloexec
    ):
        os.close(descriptor)
        raise RuntimeError("windows UIA lock is not private")
    return descriptor


def _try_private_file_lock(path: Path) -> int | None:
    descriptor = _open_private_lock_file(path)
    try:
        if os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError):
        os.close(descriptor)
        return None
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _release_private_file_lock(descriptor: int) -> None:
    try:
        if os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _bounded_lock_sleep(deadline: float, attempt: int) -> bool:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    jitter = 1.0 + ((os.getpid() + attempt) % 4) * 0.25
    time.sleep(min(remaining, WINDOWS_UIA_FOREGROUND_LOCK_POLL_SECONDS * jitter))
    return True


def _try_windows_uia_bridge_slot(attempt: int) -> int | None:
    slot_paths = WINDOWS_UIA_BRIDGE_SLOT_PATHS
    if not slot_paths:
        raise RuntimeError("windows UIA bridge slot configuration is empty")
    start = (os.getpid() + attempt) % len(slot_paths)
    for offset in range(len(slot_paths)):
        descriptor = _try_private_file_lock(
            slot_paths[(start + offset) % len(slot_paths)]
        )
        if descriptor is not None:
            return descriptor
    return None


def _windows_uia_window_lock_path(window_id: str) -> Path:
    if not re.fullmatch(r"[1-9]\d*", window_id):
        raise RuntimeError("windows UIA window id is invalid")
    return WINDOWS_UIA_LOCK_DIRECTORY / f"window-{window_id}.lock"


@contextlib.contextmanager
def _windows_uia_bridge_admission(
    operation: str,
    window_id: str,
    *,
    total_deadline: float | None = None,
) -> Any:
    process_cap = WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS
    total_budget = WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS
    if process_cap <= 0 or total_budget <= process_cap:
        raise RuntimeError("windows UIA bridge admission timed out")
    start = time.monotonic()
    if total_deadline is None:
        total_deadline = start + total_budget
    admission_deadline = total_deadline - process_cap
    if total_deadline - start < process_cap or admission_deadline < start:
        raise RuntimeError("windows UIA bridge admission timed out")
    needs_window = operation in WINDOWS_UIA_MUTATING_OPERATIONS
    needs_foreground = operation in WINDOWS_UIA_FOREGROUND_OPERATIONS
    attempt = 0
    while True:
        acquired: list[int] = []
        ready = False
        try:
            slot_descriptor = _try_windows_uia_bridge_slot(attempt)
            if slot_descriptor is not None:
                acquired.append(slot_descriptor)
                if needs_window:
                    window_descriptor = _try_private_file_lock(
                        _windows_uia_window_lock_path(window_id)
                    )
                    if window_descriptor is not None:
                        acquired.append(window_descriptor)
                    else:
                        window_descriptor = None
                else:
                    window_descriptor = -1
                if window_descriptor is not None and needs_foreground:
                    foreground_descriptor = _try_private_file_lock(
                        WINDOWS_UIA_FOREGROUND_LOCK_PATH
                    )
                    if foreground_descriptor is not None:
                        acquired.append(foreground_descriptor)
                    else:
                        foreground_descriptor = None
                else:
                    foreground_descriptor = -1
                ready = (
                    window_descriptor is not None
                    and foreground_descriptor is not None
                )
        except BaseException:
            for descriptor in reversed(acquired):
                _release_private_file_lock(descriptor)
            raise

        remaining = total_deadline - time.monotonic()
        if ready and remaining >= process_cap:
            try:
                yield min(process_cap, remaining)
            finally:
                for descriptor in reversed(acquired):
                    _release_private_file_lock(descriptor)
            return

        for descriptor in reversed(acquired):
            _release_private_file_lock(descriptor)
        if not _bounded_lock_sleep(admission_deadline, attempt):
            raise RuntimeError("windows UIA bridge admission timed out")
        attempt += 1


def _run_windows_uia(*args: str) -> dict[str, Any]:
    total_budget = WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS
    process_cap = WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS
    if process_cap <= 0 or total_budget <= process_cap:
        raise RuntimeError("windows UIA bridge admission timed out")

    total_deadline = time.monotonic() + total_budget

    if len(args) < 2 or args[0] != "computer":
        raise RuntimeError("windows UIA bridge command unsupported")
    operation_map = {
        "get-app-state": "state",
        "click": "click",
        "perform-secondary-action": "select",
        "hotkey": "hotkey",
        "type-text": "type",
        "press-key": "press",
    }
    operation = operation_map.get(args[1])
    if operation is None:
        raise RuntimeError("windows UIA bridge command unsupported")
    window_id = _argument(args, "--window-id")

    remaining_for_script = total_deadline - time.monotonic()
    if remaining_for_script <= process_cap:
        raise RuntimeError("windows UIA bridge admission timed out")

    implementation = os.environ.get(
        "AGODA_WINDOWS_UIA_IMPLEMENTATION", ""
    ).strip().lower()
    use_powershell = implementation == "powershell"

    if use_powershell:
        script_path = _windows_uia_script_path(
            timeout=min(10.0, remaining_for_script)
        )

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
            "-Operation",
            operation,
            "-WindowId",
            window_id,
        ]
    else:
        exe_info = _ensure_csharp_bridge(
            total_deadline=total_deadline,
            process_cap=process_cap,
        )
        _verify_csharp_bridge_executable(exe_info)
        command = [
            exe_info["path"],
            "-Operation",
            operation,
            "-WindowId",
            window_id,
        ]

    if operation == "select" and _argument(args, "--action").casefold() != "select":
        raise RuntimeError("windows UIA bridge action unsupported")
    if "--expected-name-sha256" in args:
        command.extend(
            [
                "-ExpectedNameSha256",
                _argument(args, "--expected-name-sha256"),
            ]
        )
    if operation in {"click", "select"}:
        command.extend(["-ElementIndex", _argument(args, "--element-index")])
    elif operation == "hotkey":
        command.extend(["-Key", _argument(args, "--key")])
    elif operation == "type":
        command.extend(["-Text", _argument(args, "--text")])
    elif operation == "press":
        command.extend(["-Key", _argument(args, "--key")])

    process: subprocess.CompletedProcess[str] | None = None
    subprocess_timed_out = False
    with _windows_uia_bridge_admission(
        operation, window_id, total_deadline=total_deadline
    ) as admission_remaining:
        remaining = total_deadline - time.monotonic()
        if isinstance(admission_remaining, (int, float)):
            remaining = min(remaining, admission_remaining)
        if remaining <= 0:
            raise RuntimeError("windows UIA bridge admission timed out")
        spawn_timeout = min(process_cap, remaining)
        if spawn_timeout <= 0:
            raise RuntimeError("windows UIA bridge admission timed out")
        if not use_powershell:
            _verify_csharp_bridge_executable(exe_info)
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=spawn_timeout,
            )
        except subprocess.TimeoutExpired:
            subprocess_timed_out = True

    if subprocess_timed_out:
        raise RuntimeError("windows UIA browser command timed out")
    if process is None:  # pragma: no cover - defensive state guard
        raise RuntimeError("windows UIA browser command failed")

    malformed_json = False
    result: Any = None
    try:
        result = json.loads(process.stdout)
    except Exception:
        malformed_json = True
    if malformed_json:
        if process.returncode != 0:
            raise RuntimeError("windows UIA browser command failed")
        raise RuntimeError("windows UIA browser response was not JSON")

    if process.returncode != 0:
        error_code = None
        if isinstance(result, dict):
            error = result.get("error")
            if isinstance(error, dict):
                candidate = error.get("code")
                if isinstance(candidate, str) and re.fullmatch(
                    r"[a-z0-9][a-z0-9_.:-]*", candidate
                ):
                    error_code = candidate
        if error_code is not None:
            diagnostic = None
            if isinstance(result, dict):
                error = result.get("error")
                if isinstance(error, dict) and isinstance(
                    error.get("diagnostic"), dict
                ):
                    diagnostic = error["diagnostic"]
            raise WindowsUIABridgeError(error_code, diagnostic)
        raise RuntimeError("windows UIA browser command failed")

    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("windows UIA browser command failed")
    return result


def _run_orca(*args: str) -> dict[str, Any]:
    if os.environ.get("AGODA_UI_BACKEND") == "windows_uia":
        return _run_windows_uia(*args)
    command = [ORCA, *args, "--json"]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, _stderr = process.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        timed_out = True
    if timed_out:
        raise RuntimeError("browser command timed out")
    if process.returncode != 0:
        raise RuntimeError("browser command failed")
    malformed_json = False
    result: Any = None
    try:
        result = json.loads(stdout)
    except Exception:  # pragma: no cover - defensive runtime guard
        malformed_json = True
    if malformed_json:
        raise RuntimeError("browser response was not JSON")
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("browser command failed")
    return result


def _tree(app: str, window_id: int) -> str:
    result = _run_orca(
        "computer",
        "get-app-state",
        "--app",
        app,
        "--window-id",
        str(window_id),
        "--restore-window",
    )
    return str(result["result"]["snapshot"]["treeText"])


def _element_name(tree: str, element_index: int) -> str:
    matches = [
        match.group(2)
        for line in tree.splitlines()
        if (match := ACTIONABLE_NODE_RE.match(line))
        and int(match.group(1)) == element_index
    ]
    unique = sorted(set(matches))
    if len(unique) != 1:
        raise RuntimeError("actionable_element_name_missing_or_ambiguous")
    return unique[0]


def _click(
    app: str,
    window_id: int,
    element_index: int,
    *,
    expected_name: str | None = None,
) -> None:
    arguments = [
        "computer",
        "click",
        "--app",
        app,
        "--window-id",
        str(window_id),
        "--element-index",
        str(element_index),
    ]
    if os.environ.get("AGODA_UI_BACKEND") == "windows_uia":
        if expected_name is None:
            raise RuntimeError("windows UIA click requires semantic name")
        arguments.extend(
            [
                "--expected-name-sha256",
                hashlib.sha256(expected_name.encode("utf-8")).hexdigest(),
            ]
        )
    _run_orca(*arguments)


def _page_buttons(tree: str) -> dict[int, int]:
    buttons: dict[int, int] = {}
    for line in tree.splitlines():
        match = NODE_RE.match(line)
        if not match:
            continue
        node, label = int(match.group(1)), int(match.group(2))
        if 1 <= label <= 13:
            buttons[label] = node
    return buttons


def _special_buttons(tree: str) -> dict[str, int]:
    buttons: dict[str, int] = {}
    for line in tree.splitlines():
        match = SPECIAL_NODE_RE.match(line)
        if match:
            label = match.group(2)
            if label == "Next":
                label = "Next page"
            elif label == "Previous":
                label = "Previous page"
            buttons[label] = int(match.group(1))
    return buttons


def _is_valid_page_range(pages: list[int]) -> bool:
    """Return whether a pagination snapshot is complete enough to trust.

    During an Agoda range transition Orca can briefly expose an empty or
    partial accessibility tree.  A changed list alone is therefore not
    evidence that the new range has finished rendering.  The current portal
    keeps page 1 and page 13 as sentinels and exposes a contiguous middle
    range between them.
    """
    if len(pages) < 3 or 1 not in pages or 13 not in pages:
        return False
    middle = [page for page in pages if page not in {1, 13}]
    return middle == list(range(min(middle), max(middle) + 1))


def _card_blocks(tree: str) -> list[str]:
    """Return only accessibility subtrees rooted at booking-card nodes.

    The last card is followed by pagination and footer nodes in the
    accessibility tree.  A boundary at the card root's indentation prevents
    those UI nodes from becoming part of the page-transition hash or the
    card's date search.
    """
    lines = tree.splitlines()
    starts = [i for i, line in enumerate(lines) if CARD_RE.search(line)]
    blocks: list[str] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        root_indent = len(lines[start]) - len(lines[start].lstrip())
        for candidate in range(start + 1, end):
            line = lines[candidate]
            if line.strip() and len(line) - len(line.lstrip()) <= root_indent:
                end = candidate
                break
        blocks.append("\n".join(lines[start:end]))
    return blocks


def _card_block_hash(tree: str) -> str:
    blocks = _card_blocks(tree)
    return hashlib.sha256("\n".join(blocks).encode()).hexdigest()


def _wait_loaded(
    app: str,
    window_id: int,
    *,
    previous_card_hash: str | None = None,
    timeout_seconds: float = 30.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    latest = ""
    candidate_hash: str | None = None
    while time.monotonic() < deadline:
        latest = _tree(app, window_id)
        card_hash = _card_block_hash(latest) if "mmb-booking-card--" in latest else None
        if (
            "Loading bookings" not in latest
            and card_hash
            and (previous_card_hash is None or card_hash != previous_card_hash)
        ):
            # Agoda can change the selected pagination control and expose a
            # partially replaced card tree before the final list arrives.
            # Require the same card hash in two consecutive observations so a
            # page worker cannot publish that intermediate list.
            if card_hash == candidate_hash:
                return latest
            candidate_hash = card_hash
        else:
            candidate_hash = None
        time.sleep(1.0)
    raise RuntimeError("Agoda booking page did not finish loading")


def _wait_stable_page_tree(
    app: str,
    window_id: int,
    timeout_seconds: float = 90.0,
) -> str:
    """Return a page tree only after two identical observations.

    Accessibility element indexes are ephemeral while Agoda rerenders its
    cards.  A single snapshot can therefore point a later click at a booking
    detail action instead of the numeric page control.  Requiring the page
    controls and card hash to repeat makes the index safe to use.
    """
    deadline = time.monotonic() + timeout_seconds
    previous_signature: tuple[
        tuple[tuple[int, int], ...],
        tuple[tuple[str, int], ...],
        str,
    ] | None = None
    while time.monotonic() < deadline:
        tree = _tree(app, window_id)
        page_buttons = _page_buttons(tree)
        special_buttons = _special_buttons(tree)
        pages = tuple(sorted(page_buttons))
        if "기본 Completed" not in tree or not _is_valid_page_range(list(pages)):
            previous_signature = None
            time.sleep(0.5)
            continue
        signature = (
            tuple(sorted(page_buttons.items())),
            tuple(sorted(special_buttons.items())),
            _card_block_hash(tree),
        )
        if page_buttons and signature == previous_signature:
            return tree
        previous_signature = signature
        time.sleep(0.5)
    raise RuntimeError("Agoda booking page did not stabilize")


def _wait_page_controls(
    app: str,
    window_id: int,
    previous_pages: list[int],
    previous_card_hash: str | None = None,
    timeout_seconds: float = 120.0,
) -> str:
    """Wait for the numeric page-range control to change.

    Agoda's ``Next page``/``Previous page`` buttons shift the visible number
    range; they do not load booking cards.  Waiting on a card hash here would
    therefore deadlock at the 6/7 and 8/9 range boundaries.
    """
    deadline = time.monotonic() + timeout_seconds
    stable_pages: list[int] | None = None
    while time.monotonic() < deadline:
        tree = _tree(app, window_id)
        pages = sorted(_page_buttons(tree))
        card_hash = _card_block_hash(tree) if "mmb-booking-card--" in tree else None
        if pages != previous_pages and _is_valid_page_range(pages):
            if pages == stable_pages:
                return tree
            stable_pages = pages
        else:
            stable_pages = None
            if (
                previous_card_hash
                and card_hash
                and card_hash != previous_card_hash
                and "Loading bookings" not in tree
            ):
                # Agoda can advance the card page while keeping the same
                # numeric range (notably 1..5 and 13).  Treat the changed,
                # non-loading card set as progress; the caller will re-read
                # stable controls before attempting another click.
                return tree
        time.sleep(0.5)
    raise RuntimeError("Agoda page-number controls did not change")


def _go_to_page(app: str, window_id: int, target: int) -> str:
    range_retry_count = 0
    for _ in range(20):
        tree = _wait_stable_page_tree(app, window_id)
        if "기본 Completed" not in tree:
            raise RuntimeError("completed-bookings tab is not active")
        buttons = _page_buttons(tree)
        if target in buttons:
            before_hash = _card_block_hash(tree)
            _click(
                app,
                window_id,
                buttons[target],
                expected_name=_element_name(tree, buttons[target]),
            )
            try:
                return _wait_loaded(app, window_id, previous_card_hash=before_hash)
            except RuntimeError:
                # If the browser was already on ``target``, clicking its
                # numeric control can be a no-op.  Force one known page
                # transition, then retry target; never accept the unchanged
                # card hash as a successful transition.
                retry_tree = _wait_stable_page_tree(app, window_id)
                retry_buttons = _page_buttons(retry_tree)
                alternatives = [page for page in sorted(retry_buttons) if page != target]
                if not alternatives:
                    raise
                alternative = alternatives[0]
                alternative_before_hash = _card_block_hash(retry_tree)
                _click(
                    app,
                    window_id,
                    retry_buttons[alternative],
                    expected_name=_element_name(
                        retry_tree, retry_buttons[alternative]
                    ),
                )
                _wait_loaded(
                    app,
                    window_id,
                    previous_card_hash=alternative_before_hash,
                )
                continue

        special = _special_buttons(tree)
        visible = sorted(buttons)
        if not visible:
            raise RuntimeError("booking page controls were not found")
        # Agoda exposes the first/last page as sentinels while hiding the
        # middle range (for example 1..5 and 13).  A target can therefore lie
        # numerically between min(visible) and max(visible) without being a
        # clickable button; use the contiguous middle range to choose the
        # range-shift control.
        middle = [page for page in visible if page not in {1, 13}]
        if middle:
            middle_min, middle_max = min(middle), max(middle)
        else:
            middle_min, middle_max = min(visible), max(visible)
        if target < middle_min and "Previous page" in special:
            before_pages = visible
            before_card_hash = _card_block_hash(tree)
            _click(
                app,
                window_id,
                special["Previous page"],
                expected_name=_element_name(
                    tree, special["Previous page"]
                ),
            )
        elif target > middle_max and "Next page" in special:
            before_pages = visible
            before_card_hash = _card_block_hash(tree)
            _click(
                app,
                window_id,
                special["Next page"],
                expected_name=_element_name(tree, special["Next page"]),
            )
        else:
            raise RuntimeError("target page is not reachable from visible controls")
        try:
            _wait_page_controls(
                app,
                window_id,
                before_pages,
                previous_card_hash=before_card_hash,
            )
        except RuntimeError:
            # Orca can race a slowly refreshed accessibility tree: the
            # numeric node that was clicked may be stale even though the
            # control is still present.  Re-read the tree and retry with a
            # fresh node a bounded number of times; never accept the old
            # range as a successful transition.
            range_retry_count += 1
            if range_retry_count > 3:
                raise
            _tree(app, window_id)
            continue
    raise RuntimeError("page navigation exceeded retry limit")


def _resolve_date(match: re.Match[str]) -> date | None:
    month = MONTHS[match.group("month")]
    day = int(match.group("day"))
    explicit_year = match.group("year")
    if explicit_year:
        year = int(explicit_year)
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None

    weekday = match.group("weekday")
    candidates: list[date] = []
    for year in (2025, 2026, 2027):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if WEEKDAYS[candidate.weekday()] == weekday:
            candidates.append(candidate)
    # An unambiguous weekday match is required.  Never silently prefer 2026
    # when more than one allowed year could represent the same token.
    return candidates[0] if len(candidates) == 1 else None


def _extract_cards(tree: str, page_no: int) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for block in _card_blocks(tree):
        block_lines = block.splitlines()
        match = CARD_RE.search(block_lines[0])
        if not match:
            continue
        booking_id = match.group(1)
        status_match = re.search(
            r"텍스트\s+(Confirmed|Completed|Cancelled|Pending|Refunded|Failed)",
            block,
        )
        status = status_match.group(1) if status_match else "unknown"

        service_dates: list[str] = []
        service_labels = {
            "Check in",
            "Check out",
            "Date",
            "Start date",
            "End date",
            "Activity date",
            "Event date",
        }
        for line_no, line in enumerate(block_lines):
            label_match = re.search(r"텍스트\s+(.+?)\s*$", line)
            if not label_match or label_match.group(1) not in service_labels:
                continue
            for candidate_line in block_lines[line_no + 1 : line_no + 4]:
                token = DATE_RE.search(candidate_line)
                if token:
                    resolved = _resolve_date(token)
                    if resolved is not None:
                        service_dates.append(resolved.isoformat())
                    break
        service_dates = sorted(set(service_dates))
        years = sorted({int(value[:4]) for value in service_dates})
        normalized = {
            "page_no": page_no,
            "booking_id_sha256": hashlib.sha256(booking_id.encode()).hexdigest(),
            "service_dates": service_dates,
            "status": status,
        }
        card_hash = hashlib.sha256(
            json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        cards.append(
            {
                "page_no": page_no,
                "booking_id": booking_id,
                "booking_id_sha256": normalized["booking_id_sha256"],
                "service_start_on": service_dates[0] if service_dates else None,
                "service_end_on": service_dates[-1] if service_dates else None,
                "service_dates_json": json.dumps(service_dates, ensure_ascii=False),
                "service_years_json": json.dumps(years),
                "is_2026": int(2026 in years),
                "status": status,
                "card_hash": card_hash,
            }
        )
    return cards


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE run_manifest (
            run_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            captured_pages INTEGER NOT NULL,
            target_year INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL
        );
        CREATE TABLE agoda_pages (
            page_no INTEGER PRIMARY KEY,
            card_count INTEGER NOT NULL,
            target_year_count INTEGER NOT NULL,
            no_service_date_count INTEGER NOT NULL,
            duplicate_booking_id_count INTEGER NOT NULL,
            min_service_on TEXT,
            max_service_on TEXT,
            page_sha256 TEXT NOT NULL
        );
        CREATE TABLE agoda_completed_bookings (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_no INTEGER NOT NULL,
            booking_id TEXT NOT NULL,
            booking_id_sha256 TEXT NOT NULL,
            service_start_on TEXT,
            service_end_on TEXT,
            service_dates_json TEXT NOT NULL,
            service_years_json TEXT NOT NULL,
            is_2026 INTEGER NOT NULL CHECK (is_2026 IN (0, 1)),
            status TEXT NOT NULL,
            card_sha256 TEXT NOT NULL
        );
        CREATE INDEX idx_agoda_completed_2026
            ON agoda_completed_bookings(is_2026, service_start_on);
        CREATE INDEX idx_agoda_completed_booking_hash
            ON agoda_completed_bookings(page_no, booking_id_sha256);
        """
    )


def _insert_page(
    connection: sqlite3.Connection,
    page_no: int,
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    booking_ids = [card["booking_id_sha256"] for card in cards]
    duplicate_count = len(booking_ids) - len(set(booking_ids))
    dates = [card["service_start_on"] for card in cards if card["service_start_on"]]
    page_sha256 = hashlib.sha256(
        "".join(sorted(card["card_hash"] for card in cards)).encode()
    ).hexdigest()
    for card in cards:
        connection.execute(
            """
            INSERT INTO agoda_completed_bookings(
                page_no, booking_id, booking_id_sha256, service_start_on,
                service_end_on, service_dates_json, service_years_json,
                is_2026, status, card_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card["page_no"],
                card["booking_id"],
                card["booking_id_sha256"],
                card["service_start_on"],
                card["service_end_on"],
                card["service_dates_json"],
                card["service_years_json"],
                card["is_2026"],
                card["status"],
                card["card_hash"],
            ),
        )
    connection.execute(
        """
        INSERT INTO agoda_pages(
            page_no, card_count, target_year_count, no_service_date_count,
            duplicate_booking_id_count, min_service_on, max_service_on,
            page_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            page_no,
            len(cards),
            sum(card["is_2026"] for card in cards),
            sum(not card["service_start_on"] for card in cards),
            duplicate_count,
            min(dates) if dates else None,
            max(dates) if dates else None,
            page_sha256,
        ),
    )
    return {
        "page": page_no,
        "card_count": len(cards),
        "target_year_count": sum(card["is_2026"] for card in cards),
        "no_service_date_count": sum(not card["service_start_on"] for card in cards),
        "duplicate_booking_id_count": duplicate_count,
        "min_service_on": min(dates) if dates else None,
        "max_service_on": max(dates) if dates else None,
        "page_sha256": page_sha256,
    }


def capture_pages(
    *,
    app: str,
    window_id: int,
    pages: list[int],
    db_path: Path,
    run_id: str,
) -> dict[str, Any]:
    db_path = db_path.expanduser().resolve()
    allowed_roots = [Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve()]
    if not any(root in db_path.parents for root in allowed_roots):
        raise RuntimeError("staging database must be under /tmp")
    if db_path.exists():
        raise RuntimeError("refusing to overwrite an existing staging database")
    if tuple(pages) != EXPECTED_PAGE_ORDER:
        raise RuntimeError(
            "complete Agoda capture requires page order "
            + ",".join(str(page) for page in EXPECTED_PAGE_ORDER)
        )
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(":memory:")
    _schema(connection)
    page_summaries: list[dict[str, Any]] = []
    lock_path = db_path.with_name(f".{db_path.name}.lock")
    try:
        lock_fd = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        connection.close()
        raise RuntimeError("staging database destination is locked") from None
    os.close(lock_fd)
    try:
        connection.execute(
            "INSERT INTO run_manifest VALUES (?, ?, ?, ?, datetime('now'))",
            (run_id, "agoda_account_completed_pages", len(pages), 2026),
        )
        for page_no in pages:
            tree = _go_to_page(app, window_id, page_no)
            cards = _extract_cards(tree, page_no)
            if not cards:
                raise RuntimeError(f"page {page_no} contained no booking cards")
            page_summaries.append(_insert_page(connection, page_no, cards))
        connection.commit()
        total_cards = sum(summary["card_count"] for summary in page_summaries)
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{db_path.name}.",
            suffix=".tmp",
            dir=str(db_path.parent),
        )
        os.close(temp_fd)
        temporary_path = Path(temp_name)
        published_here = False
        try:
            destination = sqlite3.connect(str(temporary_path))
            try:
                connection.backup(destination)
                destination.commit()
            finally:
                destination.close()
            os.chmod(temporary_path, 0o600)
            with temporary_path.open("r+b") as sync_file:
                os.fsync(sync_file.fileno())
            # Hard-link publication is atomic and no-replace on the same
            # filesystem: if another process created db_path during capture,
            # this fails instead of overwriting it.
            os.link(temporary_path, db_path)
            published_here = True
            temporary_path.unlink()
            os.chmod(db_path, 0o600)
            verified = sqlite3.connect(
                f"file:{db_path}?mode=ro&immutable=1",
                uri=True,
            )
            try:
                verified_pages = verified.execute(
                    "SELECT COUNT(*) FROM agoda_pages"
                ).fetchone()[0]
                verified_rows = verified.execute(
                    "SELECT COUNT(*) FROM agoda_completed_bookings"
                ).fetchone()[0]
            finally:
                verified.close()
            if verified_pages != len(pages) or verified_rows != total_cards:
                raise RuntimeError("staging database immutable verification failed")
        except Exception:
            if published_here and db_path.exists():
                db_path.unlink()
            raise
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        total_target_rows = sum(summary["target_year_count"] for summary in page_summaries)
        total_distinct_rows = int(
            connection.execute("SELECT COUNT(DISTINCT booking_id_sha256) FROM agoda_completed_bookings").fetchone()[0]
        )
        target_distinct_rows = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) FROM agoda_completed_bookings WHERE is_2026 = 1"
            ).fetchone()[0]
        )
        target_duplicate_rows = total_target_rows - target_distinct_rows
        all_duplicate_rows = total_cards - total_distinct_rows
        page_counts = sorted({summary["card_count"] for summary in page_summaries})
        return {
            "run_id": run_id,
            "db": str(db_path),
            "captured_pages": pages,
            "page_summaries": page_summaries,
            "total_cards": total_cards,
            "target_year_rows": total_target_rows,
            "distinct_total_bookings": total_distinct_rows,
            "distinct_target_year_bookings": target_distinct_rows,
            "duplicate_total_rows": all_duplicate_rows,
            "duplicate_target_year_rows": target_duplicate_rows,
            "page_card_count_values": page_counts,
            "page_card_count_is_constant": len(page_counts) == 1,
        }
    finally:
        connection.close()
        if lock_path.exists():
            lock_path.unlink()


def capture_page(
    *,
    app: str,
    window_id: int,
    page_no: int,
    db_path: Path,
    run_id: str,
    assume_current: bool = False,
) -> dict[str, Any]:
    """Capture exactly one Agoda page into its own private staging DB.

    This is intentionally separate from ``capture_pages``: a page worker may
    publish only its own page, while the final merge remains responsible for
    proving that all 13 page DBs exist and are mutually complete.
    """
    if page_no not in range(1, 14):
        raise RuntimeError("page number must be between 1 and 13")
    db_path = db_path.expanduser().resolve()
    allowed_roots = [Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve()]
    if not any(root in db_path.parents for root in allowed_roots):
        raise RuntimeError("staging database must be under /tmp")
    if db_path.exists():
        raise RuntimeError("refusing to overwrite an existing staging database")
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(":memory:")
    _schema(connection)
    page_summaries: list[dict[str, Any]] = []
    lock_path = db_path.with_name(f".{db_path.name}.lock")
    try:
        lock_fd = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        connection.close()
        raise RuntimeError("staging database destination is locked") from None
    os.close(lock_fd)
    try:
        connection.execute(
            "INSERT INTO run_manifest VALUES (?, ?, ?, ?, datetime('now'))",
            (run_id, "agoda_account_completed_page", 1, 2026),
        )
        tree = (
            _wait_stable_page_tree(app, window_id)
            if assume_current
            else _go_to_page(app, window_id, page_no)
        )
        cards = _extract_cards(tree, page_no)
        if not cards:
            raise RuntimeError(f"page {page_no} contained no booking cards")
        page_summaries.append(_insert_page(connection, page_no, cards))
        connection.commit()
        total_cards = len(cards)
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{db_path.name}.",
            suffix=".tmp",
            dir=str(db_path.parent),
        )
        os.close(temp_fd)
        temporary_path = Path(temp_name)
        published_here = False
        try:
            destination = sqlite3.connect(str(temporary_path))
            try:
                connection.backup(destination)
                destination.commit()
            finally:
                destination.close()
            os.chmod(temporary_path, 0o600)
            with temporary_path.open("r+b") as sync_file:
                os.fsync(sync_file.fileno())
            os.link(temporary_path, db_path)
            published_here = True
            temporary_path.unlink()
            os.chmod(db_path, 0o600)
            verified = sqlite3.connect(
                f"file:{db_path}?mode=ro&immutable=1",
                uri=True,
            )
            try:
                verified_pages = verified.execute(
                    "SELECT COUNT(*) FROM agoda_pages"
                ).fetchone()[0]
                verified_rows = verified.execute(
                    "SELECT COUNT(*) FROM agoda_completed_bookings"
                ).fetchone()[0]
            finally:
                verified.close()
            if verified_pages != 1 or verified_rows != total_cards:
                raise RuntimeError("single-page immutable verification failed")
        except Exception:
            if published_here and db_path.exists():
                db_path.unlink()
            raise
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        total_target_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM agoda_completed_bookings WHERE is_2026 = 1"
            ).fetchone()[0]
        )
        total_distinct_rows = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) FROM agoda_completed_bookings"
            ).fetchone()[0]
        )
        target_distinct_rows = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) FROM agoda_completed_bookings WHERE is_2026 = 1"
            ).fetchone()[0]
        )
        return {
            "run_id": run_id,
            "db": str(db_path),
            "captured_pages": [page_no],
            "page_summaries": page_summaries,
            "total_cards": total_cards,
            "target_year_rows": total_target_rows,
            "distinct_total_bookings": total_distinct_rows,
            "distinct_target_year_bookings": target_distinct_rows,
            "duplicate_total_rows": total_cards - total_distinct_rows,
            "duplicate_target_year_rows": total_target_rows - target_distinct_rows,
            "page_card_count_values": [total_cards],
            "page_card_count_is_constant": True,
        }
    finally:
        connection.close()
        if lock_path.exists():
            lock_path.unlink()


def main() -> int:
    try:
        from tools.agoda_browser_policy import legacy_browser_block
    except ImportError:  # pragma: no cover - direct script execution
        from agoda_browser_policy import legacy_browser_block

    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="msedge")
    parser.add_argument("--window-id", type=int, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--page", type=int)
    parser.add_argument(
        "--assume-current",
        action="store_true",
        help="capture --page from the already displayed completed-bookings page",
    )
    parser.add_argument("--pages", default=",".join(str(page) for page in EXPECTED_PAGE_ORDER))
    args = parser.parse_args()

    # This module still contains the historical Windows UIA implementation,
    # but it must never be used as a browser entry point.  Paseo IAB owns the
    # browser session and is driven by the coordinator's browser tools.
    return legacy_browser_block("agoda_portal_page_capture")

    if "-" in args.pages:
        start, end = (int(part) for part in args.pages.split("-", 1))
        pages = list(range(start, end + 1))
    else:
        pages = [int(part) for part in args.pages.split(",") if part]
    if args.page is not None:
        result = capture_page(
            app=args.app,
            window_id=args.window_id,
            page_no=args.page,
            db_path=args.db,
            run_id=args.run_id,
            assume_current=args.assume_current,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if tuple(pages) != EXPECTED_PAGE_ORDER:
        parser.error(
            "pages must be the complete ordered capture: "
            + ",".join(str(page) for page in EXPECTED_PAGE_ORDER)
        )
    result = capture_pages(
        app=args.app,
        window_id=args.window_id,
        pages=pages,
        db_path=args.db,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
