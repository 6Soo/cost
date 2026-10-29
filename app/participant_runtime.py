"""Read-only evidence that CLI and web use the same participant store."""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path

from . import participant_roster


def _identity(path: Path) -> dict:
    resolved = path.resolve()
    if not resolved.exists():
        return {"exists": False, "path": str(resolved)}
    stat = resolved.stat()
    return {"exists": True, "path": str(resolved),
            "file_id": [stat.st_dev, stat.st_ino], "size": stat.st_size}


def verify_paths(cli_db: Path, web_db: Path | None = None, *, receipt: dict | None = None) -> dict:
    """Compare paths and schema; optionally compare a saved registration receipt."""
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
                if result['schema_present']:
                    batch_columns = {row[1] for row in store.conn.execute('PRAGMA table_info(roster_batches)')}
                    person_columns = {row[1] for row in store.conn.execute('PRAGMA table_info(trip_participants)')}
                    result['schema_present'] = ({'batch_id','roster_id','status','result_json'} <= batch_columns
                        and {'participant_id','trip_id','state','active'} <= person_columns)
                if receipt is not None:
                    batch_id = receipt.get('batch_id') if isinstance(receipt, dict) else None
                    recorded = store.conn.execute(
                        'SELECT status,result_json FROM roster_batches WHERE batch_id=?',
                        (batch_id,)).fetchone() if isinstance(batch_id, str) and result['schema_present'] else None
                    stored = json.loads(recorded[1]) if recorded else {}
                    fields = ('batch_id','trip_id','google_trip_key','new_participants','reused_participants')
                    result['receipt_matches_recorded_batch'] = bool(
                        recorded and isinstance(stored, dict)
                        and recorded[0] == 'registered' and receipt.get('status') == 'registered'
                        and all(type(receipt.get(key)) is int and receipt[key] >= 0
                                for key in ('new_participants','reused_participants'))
                        and all(key in receipt and receipt[key] == stored.get(key) for key in fields))
            finally:
                store.close()
        except (OSError, ValueError, sqlite3.Error, participant_roster.RosterError):
            result["schema_present"] = False
    else:
        result["schema_present"] = False
    if not result['schema_present'] or (receipt is not None and not result.get('receipt_matches_recorded_batch')):
        result['status'] = 'blocked'
    result['scope'] = 'configured_paths_only; active web process configuration must be verified separately'
    result['insurer_completion_verified'] = False
    return result


def runtime_paths(cli_db: Path) -> tuple[Path, Path]:
    return cli_db.resolve(), participant_roster.default_db_path().resolve()
