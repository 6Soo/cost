"""Read the Google trip ledgers once, read-only, into an explicit snapshot file.

    python tools/google_authority_sync.py --snapshot C:\\cost-dev-data\\google-authority\\snapshot.json

There is no default snapshot path and no scheduler registration here. The hourly
schedule is set up separately once the operator approves it. Output is status codes
and counts only, so the task log holds no customer data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import google_authority, sync_schedule


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True, type=pathlib.Path)
    parser.add_argument("--rows", required=True, type=pathlib.Path)
    parser.add_argument("--timeout", type=float, default=google_authority.DEFAULT_TIMEOUT)
    parser.add_argument("--max-bytes", type=int, default=google_authority.DEFAULT_MAX_BYTES)
    parser.add_argument("--google-auth", choices=("public", "adc"), default="public",
                        help="Use authenticated Google Drive read-only export with ADC when selected")
    args = parser.parse_args(argv)
    now = dt.datetime.now(google_authority.KST)
    state_path = args.snapshot.with_name("sync-state.json")
    try:
        with sync_schedule.SyncLock(args.snapshot.with_name("sync.lock"), now=now):
            return _run_locked(args, now, state_path)
    except sync_schedule.LockHeld as error:
        print(json.dumps({"code": str(error)}))
        return 4
    except sync_schedule.StateError:
        print(json.dumps({"code": "SYNC_STATE_UNAVAILABLE"}))
        return 6
    except OSError:
        print(json.dumps({"code": "SYNC_IO_UNAVAILABLE"}))
        return 7


def _run_locked(args, now, state_path) -> int:
    # The retry state belongs to the same writer as snapshot publication.
    state = sync_schedule.read_state(state_path)
    if not sync_schedule.may_attempt(state, now):
        print(json.dumps({"code": "BACKOFF_WAIT", "next_attempt_at": state["next_attempt_at"]}))
        return 3
    fetcher = None
    auth_unavailable = False
    if getattr(args, "google_auth", "public") == "adc":
        try:
            from app.google_adc_export import authorized_export_fetcher
            fetcher = authorized_export_fetcher(timeout=args.timeout, max_bytes=args.max_bytes)
        except Exception:
            auth_unavailable = True

            def fetcher(_url):
                # Publish the same last-good/stale transition as a fetch error.
                # Never fall back to anonymous access when ADC was selected.
                raise google_authority.SourceError('GOOGLE_AUTH_UNAVAILABLE')
    try:
        snapshot = google_authority.sync(args.snapshot, args.rows, timeout=args.timeout,
                                         max_bytes=args.max_bytes, fetcher=fetcher, now=now)
    except google_authority.SnapshotError as error:
        sync_schedule.record_result(state_path, ok=False, now=now, error_code=error.code)
        print(json.dumps({"code": error.code}))
        return 2
    sources = {
        role: {"status": source["status"], "error_code": source["error_code"], "stale": source["stale"],
               "unchanged": source.get("unchanged", False), "trip_tabs": len(source["trips"])}
        for role, source in snapshot["sources"].items()
    }
    failed = [role for role, source in snapshot["sources"].items() if source["status"] != "ok"]
    sync_schedule.record_result(state_path, ok=not failed, now=now,
                                error_code=snapshot["sources"][failed[0]]["error_code"] if failed else None)
    result = {"sources": sources, "trips": len(snapshot["trips"])}
    if auth_unavailable:
        result['code'] = 'GOOGLE_AUTH_UNAVAILABLE'
    print(json.dumps(result, ensure_ascii=False))
    if auth_unavailable:
        return 5
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
