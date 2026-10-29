"""Read-only evidence that CLI and web use the same participant store."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import participant_roster


def _identity(path: Path) -> dict:
    resolved = path.resolve()
    if not resolved.exists():
        return {"exists": False, "path": str(resolved)}
    stat = resolved.stat()
    return {"exists": True, "path": str(resolved),
            "file_id": [stat.st_dev, stat.st_ino], "size": stat.st_size}


def verify_paths(cli_db: Path, web_db: Path | None = None) -> dict:
    """Compare configured paths and inspect only SQLite metadata, never data."""
    web_db = web_db or participant_roster.default_db_path()
    cli = _identity(cli_db)
    web = _identity(web_db)
    same_path = Path(cli["path"]).resolve() == Path(web["path"]).resolve()
    same_file = bool(cli.get("exists") and web.get("exists") and
                     cli.get("file_id") == web.get("file_id"))
    result = {"status": "ok" if same_path and same_file else "blocked",
              "checks": {"same_resolved_path": same_path,
                         "same_file_identity": same_file},
              "cli": cli, "web": web,
              "write_performed": False}
    if same_file:
        try:
            store = participant_roster.ParticipantStore.open_readonly(Path(cli["path"]))
            try:
                tables = {row[0] for row in store.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                result["schema_present"] = "roster_batches" in tables and "trip_participants" in tables
            finally:
                store.close()
        except (OSError, sqlite3.Error):
            result["schema_present"] = False
    else:
        result["schema_present"] = False
    return result


def runtime_paths(cli_db: Path) -> tuple[Path, Path]:
    return cli_db.resolve(), participant_roster.default_db_path().resolve()
