"""Read the Google trip ledgers once, read-only, into an explicit snapshot file.

    python tools/google_authority_sync.py --snapshot C:\\cost-dev-data\\google-authority\\snapshot.json

There is no default snapshot path and no scheduler registration here. The hourly
schedule is set up separately once the operator approves it. Output is status codes
and counts only, so the task log holds no customer data.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import google_authority


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True, type=pathlib.Path)
    parser.add_argument("--rows", required=True, type=pathlib.Path)
    parser.add_argument("--timeout", type=float, default=google_authority.DEFAULT_TIMEOUT)
    parser.add_argument("--max-bytes", type=int, default=google_authority.DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    try:
        snapshot = google_authority.sync(args.snapshot, args.rows, timeout=args.timeout, max_bytes=args.max_bytes)
    except google_authority.SnapshotError as error:
        print(json.dumps({"code": error.code}))
        return 2
    sources = {
        role: {"status": source["status"], "error_code": source["error_code"], "stale": source["stale"],
               "unchanged": source.get("unchanged", False), "trip_tabs": len(source["trips"])}
        for role, source in snapshot["sources"].items()
    }
    print(json.dumps({"sources": sources, "trips": len(snapshot["trips"])}, ensure_ascii=False))
    failed = any(source["status"] != "ok" for source in snapshot["sources"].values())
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
