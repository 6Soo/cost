"""Read-only totals across every per-port request counter snapshot.

Each running process writes its own `metrics/http-<port>.json` (see
`webapp/http_counting.attach`). Provider sizing needs one number for all of
them, so this sums the files without touching a server, a database, or a
port: it only reads paths the caller names and prints aggregates.

The tool never prints a path, a header, a body, or a request identifier. It
reads exactly the fixed-ID fields the counter persists and reports the
bookkeeping (`possible_loss`, `counts_reset`, `persistence_failure_count`)
alongside the totals, because a sum that hides a reset or a loss window would
understate the real traffic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SUMMARY_SCHEMA = "http-request-counts-summary-v1"


class SnapshotError(Exception):
    """A snapshot that cannot be summed, named by the caller's own label."""


def _label(path: Path) -> str:
    """A stable way to name a file in output without echoing its absolute path."""
    return path.name


def read_snapshot(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"{_label(path)}: unreadable") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SnapshotError(f"{_label(path)}: corrupt") from exc
    if not isinstance(data, dict) or data.get("schema_version") != "http-request-counts-v1":
        raise SnapshotError(f"{_label(path)}: unexpected schema")
    return data


def summarize(snapshots) -> dict:
    """Sum route/method totals and surface every honesty marker.

    A snapshot that cannot be read is counted in `unreadable_snapshots` rather
    than skipped silently: the reader should see that a file was there and
    could not contribute.
    """
    totals: dict[tuple[str, str], dict] = {}
    problems: dict[str, list[str]] = {"unreadable": [], "corrupt": [],
                                      "unexpected_schema": []}
    loss_windows = 0
    reset_count = 0
    reset_reasons: dict[str, int] = {}
    persistence_failures = 0
    process_count = 0
    uptime_seconds = 0
    for path in snapshots:
        try:
            data = read_snapshot(path)
        except SnapshotError as exc:
            reason = str(exc).split(": ", 1)[-1]
            key = reason if reason in problems else "corrupt"
            problems[key].append(_label(path))
            continue
        process_count += 1
        loss = data.get("possible_loss") or {}
        loss_windows += int(loss.get("window_count") or 0)
        reset = data.get("counts_reset") or {}
        reset_count += int(reset.get("count") or 0)
        if reset.get("reason"):
            reset_reasons[str(reset["reason"])] = (
                reset_reasons.get(str(reset["reason"]), 0) + 1)
        persistence_failures += int(data.get("persistence_failure_count") or 0)
        uptime_seconds = max(uptime_seconds, int(data.get("uptime_seconds") or 0))
        for routes in (data.get("buckets") or {}).values():
            for route_id, methods in routes.items():
                for method, values in methods.items():
                    row = totals.setdefault((route_id, method), {
                        "started": 0,
                        "completed": {key: 0 for key in
                                      ("1xx", "2xx", "3xx", "4xx", "5xx", "other")},
                        "aborted": 0,
                        "aborted_by_status_class": {key: 0 for key in
                                                    ("1xx", "2xx", "3xx", "4xx", "5xx", "other")},
                        "request_body_bytes": 0,
                        "response_body_bytes": 0,
                        "unfinished": 0,
                    })
                    row["started"] += int(values.get("started") or 0)
                    row["aborted"] += int(values.get("aborted") or 0)
                    row["request_body_bytes"] += int(values.get("request_body_bytes") or 0)
                    row["response_body_bytes"] += int(values.get("response_body_bytes") or 0)
                    row["unfinished"] += int(values.get("unfinished") or 0)
                    for key, value in (values.get("completed") or {}).items():
                        if key in row["completed"]:
                            row["completed"][key] += int(value or 0)
                    for key, value in (values.get("aborted_by_status_class") or {}).items():
                        if key in row["aborted_by_status_class"]:
                            row["aborted_by_status_class"][key] += int(value or 0)
    routes = {
        route_id: {method: row for (rid, method), row in sorted(totals.items())
                   if rid == route_id}
        for route_id in sorted({rid for rid, _ in totals})
    }
    return {
        "schema": SUMMARY_SCHEMA,
        "source_count": len(list(snapshots)),
        "process_count": process_count,
        "max_uptime_seconds": uptime_seconds,
        "total_started": sum(row["started"] for row in totals.values()),
        "total_aborted": sum(row["aborted"] for row in totals.values()),
        "total_request_body_bytes": sum(row["request_body_bytes"] for row in totals.values()),
        "total_response_body_bytes": sum(row["response_body_bytes"] for row in totals.values()),
        # The markers below are the point of this tool: a total is only usable
        # for sizing when it says whether counts were ever reset or dropped.
        "possible_loss_window_count": loss_windows,
        "counts_reset_count": reset_count,
        "counts_reset_reasons": reset_reasons,
        "persistence_failure_count": persistence_failures,
        "unreadable_snapshots": problems["unreadable"],
        "corrupt_snapshots": problems["corrupt"],
        "unexpected_schema_snapshots": problems["unexpected_schema"],
        "complete": (not problems["unreadable"] and not problems["corrupt"]
                     and not problems["unexpected_schema"]
                     and not reset_count and not loss_windows),
        "routes": routes,
    }


def _candidate_paths(arguments) -> list[Path]:
    """Expand a directory to its counter snapshots; keep explicit files as-is."""
    resolved = []
    for value in arguments:
        path = Path(value)
        if path.is_dir():
            resolved.extend(sorted(path.glob("http-*.json")))
        else:
            resolved.append(path)
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Sum content-free HTTP request counters across ports (read-only).")
    parser.add_argument("paths", nargs="+",
                        help="counter snapshot files, or a metrics directory")
    parser.add_argument("--pretty", action="store_true",
                        help="indent the JSON instead of one line")
    args = parser.parse_args(argv)
    report = summarize(_candidate_paths(args.paths))
    print(json.dumps(report, ensure_ascii=True, sort_keys=True,
                     indent=2 if args.pretty else None))
    # A summary that cannot honestly represent traffic exits non-zero, so a
    # script reading it cannot mistake an incomplete total for a final one.
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
