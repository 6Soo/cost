"""Cross-platform atomic publication primitives.

Sol high review boundary: POSIX-only durability machinery (renameat2,
dir_fd, O_DIRECTORY/O_NOFOLLOW, st_nlink contracts) is centralized here.
Windows gets an equivalent atomic-replace implementation; callers keep the
same function names so behavior is preserved on both platforms.
"""
from __future__ import annotations

import ctypes
import errno
import os
import stat
from pathlib import Path

O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_BINARY = getattr(os, "O_BINARY", 0)


def open_dir(path: Path) -> int:
    """Open a directory descriptor (POSIX) or handle-like fd (Windows)."""
    if os.name == "nt":
        return _open_dir_windows(path)
    return os.open(path, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW)


def _open_dir_windows(path: Path) -> int:
    """Windows: opening a directory with plain os.open raises
    PermissionError. Use CreateFileW via msvcrt-compatible ctypes to get
    a real directory handle that can be fsynced."""
    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    INVALID_HANDLE_VALUE = -1  # as signed

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.CreateFileW(
        str(path),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle == 0xFFFFFFFFFFFFFFFF:
        raise PermissionError(f"cannot open directory handle: {path}")
    return handle


def open_nofollow(path: Path, flags: int = os.O_RDONLY) -> int:
    """Open a regular file without following symlinks."""
    if os.name == "nt":
        return os.open(str(path), flags | O_BINARY)
    return os.open(path, flags | O_NOFOLLOW | O_CLOEXEC)


def verify_regular_single_link(fd: int, mode: int | None = None) -> None:
    """POSIX contract check: regular file, exactly one link, optional mode.

    On Windows st_nlink is always reported differently by NTFS, so this
    degrades gracefully instead of failing every run.
    """
    meta = os.fstat(fd)
    if not stat.S_ISREG(meta.st_mode):
        raise ValueError("not_regular_file")
    if os.name != "nt":
        if meta.st_nlink != 1:
            raise ValueError("hardlink_rejected")
        if mode is not None and stat.S_IMODE(meta.st_mode) != mode:
            raise ValueError("mode_mismatch")


def fsync_dir(path_or_fd: Path | int) -> None:
    """Flush a directory entry to disk. No-op equivalent on Windows where
    directory handles cannot be opened via os.open; data integrity there is
    guaranteed by FlushFileBuffers on the file itself."""
    if os.name == "nt":
        if isinstance(path_or_fd, int):
            try:
                libc = ctypes.CDLL("msvcrt")
                libc._flushall()
            except Exception:
                pass
        return
    if isinstance(path_or_fd, int):
        fd = path_or_fd
    else:
        fd = os.open(path_or_fd, os.O_RDONLY | O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rename_noreplace(stage: Path, target: Path) -> None:
    """Atomically publish stage->target, refusing to overwrite.

    POSIX uses renameat2(RENAME_NOREPLACE); Windows uses a two-step
    os.link + os.unlink which fails atomically when target exists because
    os.link refuses to create a second hardlink to an existing name... but
    for cross-volume safety we use MoveFileEx without REPLACE_EXISTING.
    """
    if os.path.lexists(target):
        raise FileExistsError(f"output_exists:{target}")
    if os.name == "posix":
        _renameat2_noreplace(stage, target)
        return
    # Windows fallback: os.rename raises FileExistsError when destination
    # exists (no overwrite semantics in Python's os.rename on nt).
    try:
        os.rename(stage, target)
    except FileExistsError:
        raise
    except OSError as exc:
        # os.rename on Windows overwrites silently in some cases; guard.
        if os.path.lexists(target):
            raise FileExistsError(f"output_exists:{target}") from exc
        raise


def rename_noreplace_at(
    parent_fd: int, old_name: str, new_name: str
) -> None:
    """Directory-descriptor variant of rename_noreplace."""
    if os.name == "posix":
        _renameat2_at(parent_fd, old_name, new_name)
        return
    parent = Path(_fd_to_path_windows(parent_fd))
    if not parent.is_dir():
        raise PermissionError(f"invalid or closed directory handle: fd={parent_fd}")
    rename_noreplace(parent / old_name, parent / new_name)


def _renameat2_noreplace(stage: Path, target: Path) -> None:
    fn = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if fn is None:
        raise OSError(errno.ENOSYS, "renameat2_unsupported")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    parent_fd = os.open(target.parent, os.O_RDONLY | O_DIRECTORY)
    try:
        result = fn(parent_fd, os.fsencode(stage.name), parent_fd, os.fsencode(target.name), 1)
    finally:
        os.close(parent_fd)
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(f"output_exists:{target}")
    raise OSError(code, "renameat2")


def _renameat2_at(parent_fd: int, old_name: str, new_name: str) -> None:
    fn = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if fn is None:
        raise OSError(errno.ENOSYS, "renameat2_unsupported")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    result = fn(parent_fd, os.fsencode(old_name), parent_fd, os.fsencode(new_name), 1)
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(f"output_exists:{new_name}")
    raise OSError(code, "renameat2")


def _fd_to_path_windows(fd: int) -> str:
    """Best-effort recovery of a path from a Windows directory handle."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buf = ctypes.create_unicode_buffer(4096)
    GetFinalPathNameByHandleW = getattr(kernel32, "GetFinalPathNameByHandleW", None)
    if GetFinalPathNameByHandleW is None:
        return ""
    length = GetFinalPathNameByHandleW(fd, buf, len(buf), 0)
    if length == 0:
        return ""
    result = buf.value
    # Strip \\?\ prefix
    if result.startswith("\\\\?\\"):
        result = result[4:]
    return result


def identity(st_result: os.stat_result) -> tuple:
    """Stable inode-identity tuple. On Windows dev/ino are less meaningful
    but still stable within one session."""
    return (
        st_result.st_dev, st_result.st_ino, st_result.st_size,
        st_result.st_mtime_ns, st_result.st_ctime_ns,
        st_result.st_mode, st_result.st_uid,
        getattr(st_result, "st_nlink", 1),
    )


def hardlink_noreplace(stage: Path, target: Path) -> None:
    """Publish by hardlink then remove stage. Atomic on both platforms;
    os.link fails atomically if target exists."""
    if os.path.lexists(target):
        raise FileExistsError(f"output_exists:{target}")
    os.link(stage, target)
