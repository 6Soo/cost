"""Import a complete Reservation access snapshot into an explicit COST DB.

Both paths are mandatory so this command cannot silently select a production
database or another default state file.  The same parsed snapshot is applied a
second time to prove the whole-directory revision guard is idempotent.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.reservation_access_snapshot import parse_reservation_access_snapshot
from webapp.access_control import AccessStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()

    snapshot = parse_reservation_access_snapshot(args.input.read_bytes())
    db_path = args.db.resolve()
    conn = sqlite3.connect(db_path)
    try:
        store = AccessStore(conn)
        first = store.sync_reservation_access_snapshot(snapshot=snapshot)
        second = store.sync_reservation_access_snapshot(snapshot=snapshot)
    finally:
        conn.close()

    print(json.dumps({
        "database": str(db_path),
        "digest": snapshot["digest"],
        "snapshot_revision": snapshot["snapshot_revision"],
        "persons_seen": first["persons_seen"],
        "persons_deactivated": first["persons_deactivated"],
        "connections_revoked": first["connections_revoked"],
        "sessions_bumped": first["sessions_bumped"],
        "connected_persons_synced": first["connected_persons_synced"],
        "assignments_applied": first["assignments_applied"],
        "assignments_ignored_older": first["assignments_ignored_older"],
        "idempotent": bool(second["ignored_stale_or_equal"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
