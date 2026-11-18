"""Read-only totals across every per-port request counter snapshot.

Each running process writes its own `metrics/http-<port>.json` (see
`webapp/http_counting.attach`). Provider sizing needs one number for all of
them, so this sums the files without touching a server, a database, or a
port: it only reads paths the caller names and prints aggregates.

Two things this tool refuses to blur:

- The sum is the *saved* state. Requests that had started but not finished when
  a snapshot was written are reported separately as `in_flight_count`, and the
  time of the newest save is reported as `last_saved_utc`, so a reader can see
  how far behind the files are instead of assuming they are current.
- A total is only `complete` when every snapshot was readable, every count was
  reset-free, no loss window was ever opened, nothing was left in flight, and
  at least one snapshot was actually read. An empty input is not a zero.

Validation is strict and silent about contents: a bucket key, route ID, method
or counter that is not one of the fixed values the counter can write makes the
whole snapshot `rejected`, and only the file's own name is reported -- never
the offending value. A corrupted or hostile file therefore cannot inject text
into the report.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SUMMARY_SCHEMA = "http-request-counts-summary-v1"

SNAPSHOT_SCHEMA = "http-request-counts-v1"
ROUTE_IDS = frozenset({"ledger", "cards", "ota", "receipts", "upload",
                       "auth", "health", "assets", "api", "unknown"})
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE",
                          "OPTIONS", "TRACE", "CONNECT", "other"})
STATUS_CLASSES = frozenset({"1xx", "2xx", "3xx", "4xx", "5xx", "other"})
LOSS_REASONS = frozenset({"unclean_stop", "shutdown_with_requests_in_flight",
                          "corrupt", "unreadable", "symlink"})
RESET_REASONS = frozenset({"corrupt", "unreadable", "symlink"})
# Bounds that a real counter can never exceed. A value outside them means the
# file was not written by this counter, whatever it claims.
MAX_RETENTION_HOURS = 24 * 400
MAX_VALUE = 2 ** 63 - 1


class SnapshotError(Exception):
    """A snapshot that cannot be summed. The message is a fixed category.

    The message never carries a value read from the file: only `file`, `status`
    and, for a rejected snapshot, the fixed name of the rule that failed.
    """

    def __init__(self, label: str, status: str, rule: str = ""):
        super().__init__(f"{status}:{rule}" if rule else status)
        self.label = label
        self.status = status
        self.rule = rule


def _label(path: Path) -> str:
    """A stable way to name a file in output without echoing its absolute path."""
    return path.name


def _count(value: object, rule: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotError("", "rejected", rule)
    if value < 0 or value > MAX_VALUE or (not allow_zero and value == 0):
        raise SnapshotError("", "rejected", rule)
    return value


def _stamp(value: object, rule: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SnapshotError("", "rejected", rule)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise SnapshotError("", "rejected", rule) from None
    if parsed.tzinfo is None:
        raise SnapshotError("", "rejected", rule)
    return value


def validate(data: object, label: str) -> dict:
    """Validate one snapshot strictly, or raise with a fixed reason.

    Only values the counter itself can write are accepted, so a hostile file
    cannot smuggle unknown route IDs, unknown methods or negative counters into
    the totals.
    """
    if not isinstance(data, dict):
        raise SnapshotError(label, "rejected", "not_object")
    if data.get("schema_version") != SNAPSHOT_SCHEMA:
        raise SnapshotError(label, "rejected", "schema")

    saved_at = data.get("saved_at_utc")
    if _stamp(saved_at, "saved_at") is None:
        raise SnapshotError(label, "rejected", "saved_at")

    retention = data.get("retention_hours")
    if (isinstance(retention, bool) or not isinstance(retention, int)
            or not 1 <= retention <= MAX_RETENTION_HOURS):
        raise SnapshotError(label, "rejected", "retention")

    loss = data.get("possible_loss")
    if not isinstance(loss, dict):
        raise SnapshotError(label, "rejected", "possible_loss")
    loss_windows = _count(loss.get("window_count"), "loss_windows")
    latest_window = loss.get("latest_window")
    if latest_window is not None:
        if not isinstance(latest_window, dict):
            raise SnapshotError(label, "rejected", "latest_window")
        window_reason = latest_window.get("reason")
        if window_reason is not None:
            # Type first: an unhashable value must reject, not raise.
            if not isinstance(window_reason, str) or window_reason not in LOSS_REASONS:
                raise SnapshotError(label, "rejected", "latest_window_reason")
        _stamp(latest_window.get("from_utc"), "latest_window_from")
        _stamp(latest_window.get("to_utc"), "latest_window_to")
        seconds = latest_window.get("seconds")
        if seconds is not None:
            _count(seconds, "latest_window_seconds")

    reset = data.get("counts_reset")
    if not isinstance(reset, dict):
        raise SnapshotError(label, "rejected", "counts_reset")
    reset_count = _count(reset.get("count"), "counts_reset")
    reset_reason = reset.get("reason")
    # Type first, then membership. A list or dict here used to reach the set
    # test and raise TypeError out of the tool instead of rejecting the file.
    if reset_reason is not None:
        if not isinstance(reset_reason, str) or reset_reason not in RESET_REASONS:
            raise SnapshotError(label, "rejected", "counts_reset_reason")
    _stamp(reset.get("last_reset_utc"), "last_reset")
    persistence_failures = _count(data.get("persistence_failure_count"),
                                  "persistence_failure_count")
    in_flight = _count(data.get("in_flight_count"), "in_flight_count")
    unrecorded_open = data.get("unrecorded_open_requests")
    if unrecorded_open is not None and not isinstance(unrecorded_open, bool):
        raise SnapshotError(label, "rejected", "unrecorded_open_requests")
    is_open_process = data.get("is_open_process")
    if is_open_process is not None and not isinstance(is_open_process, bool):
        raise SnapshotError(label, "rejected", "is_open_process")
    _stamp(data.get("shutdown_utc"), "shutdown")
    _stamp(data.get("stopped_utc"), "stopped")
    if data.get("clean_shutdown") is not None and not isinstance(
            data.get("clean_shutdown"), bool):
        raise SnapshotError(label, "rejected", "clean_shutdown")
    uptime = _count(data.get("uptime_seconds"), "uptime_seconds")

    buckets = data.get("buckets")
    if not isinstance(buckets, dict):
        raise SnapshotError(label, "rejected", "buckets")
    rows: list[tuple[str, str, dict]] = []
    totals_balance = {"outcomes": 0, "started": 0}
    for bucket, routes in buckets.items():
        if not isinstance(bucket, str):
            raise SnapshotError(label, "rejected", "bucket_key")
        _stamp(bucket, "bucket_key")
        if not bucket.endswith(":00:00Z"):
            raise SnapshotError(label, "rejected", "bucket_key")
        if not isinstance(routes, dict):
            raise SnapshotError(label, "rejected", "bucket_routes")
        for route_id, methods in routes.items():
            # Type first: an unhashable key must reject, not raise.
            if not isinstance(route_id, str) or route_id not in ROUTE_IDS:
                raise SnapshotError(label, "rejected", "route_id")
            if not isinstance(methods, dict):
                raise SnapshotError(label, "rejected", "route_methods")
            for method, values in methods.items():
                if not isinstance(method, str) or method not in HTTP_METHODS:
                    raise SnapshotError(label, "rejected", "method")
                if not isinstance(values, dict):
                    raise SnapshotError(label, "rejected", "method_values")
                for key in ("completed", "aborted_by_status_class"):
                    block = values.get(key)
                    if not isinstance(block, dict) or set(block) != STATUS_CLASSES:
                        raise SnapshotError(label, "rejected", f"{key}_classes")
                    for status, count in block.items():
                        _count(count, f"{key}_count")
                row = {
                    "started": _count(values.get("started"), "started"),
                    "aborted": _count(values.get("aborted"), "aborted"),
                    "request_body_bytes": _count(values.get("request_body_bytes"),
                                                 "request_body_bytes"),
                    "response_body_bytes": _count(values.get("response_body_bytes"),
                                                  "response_body_bytes"),
                    "unfinished": _count(values.get("unfinished"), "unfinished"),
                    "completed": {status: int(values["completed"][status])
                                  for status in STATUS_CLASSES},
                    "aborted_by_status_class": {
                        status: int(values["aborted_by_status_class"][status])
                        for status in STATUS_CLASSES},
                }
                # The counter writes one row per finished request, so these
                # three numbers have to agree. A row claiming more outcomes
                # than starts (or a different unfinished count than the
                # remainder) was not written by this counter, and summing it
                # would produce a total that cannot be true.
                outcomes = (sum(row["completed"].values()) + row["aborted"]
                            + row["unfinished"])
                if outcomes != row["started"]:
                    raise SnapshotError(label, "rejected", "row_balance")
                if row["aborted"] != sum(row["aborted_by_status_class"].values()):
                    raise SnapshotError(label, "rejected", "aborted_balance")
                rows.append((route_id, method, row))
                totals_balance["outcomes"] += outcomes
                totals_balance["started"] += row["started"]
    # The snapshot's own in-flight figure has to match what the rows say is
    # unfinished, or the two descriptions of the same file disagree.
    unfinished_total = sum(row["unfinished"] for _, _, row in rows)
    if totals_balance["outcomes"] != totals_balance["started"]:
        raise SnapshotError(label, "rejected", "snapshot_balance")
    if in_flight != unfinished_total:
        raise SnapshotError(label, "rejected", "snapshot_in_flight")
    return {
        "saved_at_utc": saved_at,
        "uptime_seconds": uptime,
        "loss_windows": loss_windows,
        "lost_in_flight_at_window": in_flight,
        "reset_count": reset_count,
        "reset_reason": reset.get("reason"),
        "persistence_failures": persistence_failures,
        "in_flight": in_flight,
        # A snapshot from a process that had not stopped is a live reading, not
        # a final one. An older file without the flag is treated as possibly
        # live: missing information is never read as "finished".
        "is_open_process": is_open_process is not False,
        "unrecorded_open_requests": bool(unrecorded_open),
        "shutdown_utc": data.get("shutdown_utc"),
        "rows": rows,
    }


def read_snapshot(path: Path) -> dict:
    label = _label(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raise SnapshotError(label, "unreadable") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise SnapshotError(label, "corrupt") from None
    try:
        return validate(data, label)
    except SnapshotError as exc:
        if exc.label is None or exc.label == "":
            raise SnapshotError(label, "rejected", exc.rule) from None
        raise


def summarize(snapshots) -> dict:
    """Sum validated snapshots and separate saved state from what is missing."""
    totals: dict[tuple[str, str], dict] = {}
    unreadable: list[str] = []
    corrupt: list[str] = []
    rejected: list[dict] = []
    loss_windows = 0
    reset_count = 0
    reset_reasons: dict[str, int] = {}
    persistence_failures = 0
    in_flight = 0
    open_processes = 0
    unrecorded_open = 0
    process_count = 0
    uptime_seconds = 0
    last_saved_at: str | None = None
    older_than_newest: list[str] = []
    for path in snapshots:
        try:
            snap = read_snapshot(path)
        except SnapshotError as exc:
            if exc.status == "unreadable":
                unreadable.append(exc.label)
            elif exc.status == "corrupt":
                corrupt.append(exc.label)
            else:
                rejected.append({"file": exc.label, "rule": exc.rule})
            continue
        process_count += 1
        loss_windows += snap["loss_windows"]
        reset_count += snap["reset_count"]
        if snap["reset_reason"]:
            reset_reasons[str(snap["reset_reason"])] = (
                reset_reasons.get(str(snap["reset_reason"]), 0) + 1)
        persistence_failures += snap["persistence_failures"]
        in_flight += snap["in_flight"]
        if snap["is_open_process"]:
            open_processes += 1
        if snap["unrecorded_open_requests"]:
            unrecorded_open += 1
        uptime_seconds = max(uptime_seconds, snap["uptime_seconds"])
        if last_saved_at is None or snap["saved_at_utc"] > last_saved_at:
            last_saved_at = snap["saved_at_utc"]
        elif snap["saved_at_utc"] != last_saved_at:
            older_than_newest.append(_label(path))
        for route_id, method, values in snap["rows"]:
            row = totals.setdefault((route_id, method), {
                "started": 0,
                "completed": {status: 0 for status in STATUS_CLASSES},
                "aborted": 0,
                "aborted_by_status_class": {status: 0 for status in STATUS_CLASSES},
                "request_body_bytes": 0,
                "response_body_bytes": 0,
                "unfinished": 0,
            })
            for key in ("started", "aborted", "request_body_bytes",
                        "response_body_bytes", "unfinished"):
                row[key] += values[key]
            for status, count in values["completed"].items():
                row["completed"][status] += count
            for status, count in values["aborted_by_status_class"].items():
                row["aborted_by_status_class"][status] += count
    routes = {
        route_id: {method: row for (rid, method), row in sorted(totals.items())
                   if rid == route_id}
        for route_id in sorted({rid for rid, _ in totals})
    }
    problems = {
        "unreadable_snapshots": unreadable,
        "corrupt_snapshots": corrupt,
        "rejected_snapshots": rejected,
        "stale_snapshots": older_than_newest,
    }
    # `complete` is the narrow claim "this sum is the whole, final story".
    # Everything that can make it short is listed above as its own reason.
    complete = (
        process_count > 0
        and not unreadable and not corrupt and not rejected
        and loss_windows == 0 and reset_count == 0
        and persistence_failures == 0 and in_flight == 0
        and open_processes == 0 and unrecorded_open == 0
    )
    return {
        "schema": SUMMARY_SCHEMA,
        "source_count": len(list(snapshots)),
        "process_count": process_count,
        "max_uptime_seconds": uptime_seconds,
        # When the newest snapshot was written, and how far behind the others
        # are. Never implied to be "now".
        "last_saved_utc": last_saved_at,
        "total_started": sum(row["started"] for row in totals.values()),
        "total_aborted": sum(row["aborted"] for row in totals.values()),
        "total_request_body_bytes": sum(row["request_body_bytes"] for row in totals.values()),
        "total_response_body_bytes": sum(row["response_body_bytes"] for row in totals.values()),
        # Requests that had begun and not closed when their snapshot was
        # written: their outcome is not in any total above.
        "in_flight_count": in_flight,
        # Snapshots still owned by a running process, and snapshots whose
        # writer admitted a request was open after the last save.
        "live_process_snapshot_count": open_processes,
        "unrecorded_open_snapshot_count": unrecorded_open,
        "possible_loss_window_count": loss_windows,
        "counts_reset_count": reset_count,
        "counts_reset_reasons": reset_reasons,
        "persistence_failure_count": persistence_failures,
        **problems,
        "complete": complete,
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
