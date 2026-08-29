"""Import a reservation schedule export into an explicitly selected ledger DB.

The database path is mandatory to prevent an accidental write to the default
ledger.  The command imports the same document twice and reports whether the
second import inserted zero rows, but it does not publish allocations or
journal entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.ledger_db import connect, initialize
from ledger.domain.reservation_schedule_export import import_reservation_schedule_export


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()

    raw = args.input.read_bytes()
    db = connect(args.db.resolve())
    try:
        initialize(db)
        first = import_reservation_schedule_export(db, raw)
        db.commit()
        second = import_reservation_schedule_export(db, raw)
        db.commit()
    finally:
        db.close()

    print(json.dumps({
        "database": str(args.db.resolve()),
        "first": first,
        "second": second,
        "idempotent": second["inserted"] == 0
        and first["export_sha256"] == second["export_sha256"],
        "posting_created": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
