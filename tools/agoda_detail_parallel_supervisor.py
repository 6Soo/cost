#!/usr/bin/env python3
"""Keep independent Agoda detail workers alive until their page lanes resolve."""

from __future__ import annotations

import argparse
try:
    import fcntl
except ImportError:
    fcntl = None
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Worker:
    label: str
    window_id: int
    work_db: Path
    run_id: str
    tab: str
    pages: tuple[int, ...]
    expected: int


def _worker(value: str) -> Worker:
    parts = value.split(",")
    if len(parts) != 7:
        raise argparse.ArgumentTypeError("worker_requires_7_comma_fields")
    label, window_id, work_db, run_id, tab, pages, expected = parts
    parsed_pages = tuple(int(page) for page in pages.split("+") if page)
    if not parsed_pages or tab not in {"Upcoming", "Completed", "Cancelled"}:
        raise argparse.ArgumentTypeError("worker_tab_or_pages_invalid")
    return Worker(
        label=label,
        window_id=int(window_id),
        work_db=Path(work_db),
        run_id=run_id,
        tab=tab,
        pages=parsed_pages,
        expected=int(expected),
    )


def _active_work_dbs() -> set[Path]:
    active: set[Path] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = [
                item.decode(errors="replace")
                for item in (entry / "cmdline").read_bytes().split(b"\0")
                if item
            ]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if "tools/agoda_portal_detail_capture.py" not in argv or "--work-db" not in argv:
            continue
        index = argv.index("--work-db")
        if index + 1 < len(argv):
            active.add(Path(argv[index + 1]))
    return active


def _resolved_count(path: Path) -> int:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        priced = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) "
                "FROM booking_detail_snapshots"
            ).fetchone()[0]
        )
        observed = (
            int(
                connection.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_observations"
                ).fetchone()[0]
            )
            if "booking_detail_observations" in tables
            else 0
        )
        connection.close()
        return priced + observed
    except (OSError, sqlite3.Error):
        return -1


def _start(
    worker: Worker,
    *,
    project_root: Path,
    source_db: Path,
    hmac_key_file: Path,
    log_dir: Path,
) -> None:
    raise RuntimeError(
        "PASEO_IAB_REQUIRED: the legacy Windows UIA/msedge supervisor is disabled; "
        "run Agoda collection through the Paseo IAB browser tools"
    )
    browser_lock = Path("/tmp") / f".{worker.run_id}.agoda-browser.lock"
    browser_lock.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["AGODA_UI_BACKEND"] = "windows_uia"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("AGODA_WINDOWS_UIA_IMPLEMENTATION", None)
    command = [
        "python3",
        "tools/agoda_portal_detail_capture.py",
        "capture",
        "--app",
        "msedge",
        "--window-id",
        str(worker.window_id),
        "--source-db",
        str(source_db),
        "--hmac-key-file",
        str(hmac_key_file),
        "--work-db",
        str(worker.work_db),
        "--run-id",
        worker.run_id,
        "--pages",
        *(str(page) for page in worker.pages),
        "--tabs",
        worker.tab,
    ]
    if worker.work_db.exists():
        command.append("--resume")
    output = (log_dir / f"agoda-detail-supervisor-{worker.label}.log").open(
        "ab", buffering=0
    )
    subprocess.Popen(
        command,
        cwd=project_root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--worker", action="append", type=_worker, required=True)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--status-seconds", type=int, default=300)
    parser.add_argument("--lock-file", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    lock = args.lock_file.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            assert fcntl is not None
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return 0
    log = args.log_file.open("a", encoding="utf-8", buffering=1)

    def emit(message: str) -> None:
        log.write(time.strftime("%Y-%m-%dT%H:%M:%S%z") + " " + message + "\n")

    emit("supervisor-v8-terminal-observation-aware-start")
    next_status_at = 0.0
    while True:
        active = _active_work_dbs()
        incomplete = 0
        total_resolved = 0
        total_expected = 0
        lane_status: list[str] = []
        for worker in args.worker:
            resolved = _resolved_count(worker.work_db)
            total_resolved += max(0, resolved)
            total_expected += worker.expected
            lane_status.append(f"{worker.label}:{resolved}/{worker.expected}")
            if resolved >= worker.expected:
                continue
            incomplete += 1
            if worker.work_db not in active:
                _start(
                    worker,
                    project_root=args.project_root,
                    source_db=args.source_db,
                    hmac_key_file=args.hmac_key_file,
                    log_dir=args.log_file.parent,
                )
                emit(
                    f"restart {worker.label} resolved={resolved} "
                    f"expected={worker.expected}"
                )
        now = time.monotonic()
        if now >= next_status_at:
            active_workers = sum(
                worker.work_db in active for worker in args.worker
            )
            emit(
                f"status resolved={total_resolved}/{total_expected} "
                f"active_workers={active_workers}/{len(args.worker)} "
                f"lanes={','.join(lane_status)}"
            )
            next_status_at = now + max(1, args.status_seconds)
        if incomplete == 0:
            emit("all-workers-resolved")
            return 0
        time.sleep(max(1, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
