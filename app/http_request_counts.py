"""Content-free, process-local HTTP request totals.

The caller assigns one fixed storage path to each concurrently running process and
reuses that path when the process restarts. The module retains only bounded UTC
hour buckets and safe enum values; request paths, headers, bodies, and identifiers
are never written to disk.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit


SCHEMA_VERSION = "http-request-counts-v1"
ROUTE_IDS = frozenset({"ledger", "cards", "ota", "receipts", "upload",
                       "auth", "health", "assets", "api", "unknown"})
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE",
                          "OPTIONS", "TRACE", "CONNECT", "other"})
STATUS_CLASSES = ("1xx", "2xx", "3xx", "4xx", "5xx", "other")
# Every first path segment the web board actually serves maps into one of the
# fixed route IDs above. A served path that fell through to "unknown" made the
# per-provider request figures look smaller than they are, so the table follows
# the real dispatch prefixes: ledger pages (board, trips, review, rows, import,
# export, rules, income, evidence, ...), the login/access layer (auth, login,
# logout, access), the platform probes (healthz, readyz, readiness, livez) and
# the static asset prefixes.
_ROUTE_BY_PREFIX = {
    "ledger": "ledger", "board": "ledger", "trips": "ledger", "trip": "ledger",
    "review": "ledger", "row": "ledger", "rows": "ledger", "import": "ledger",
    "export": "ledger", "share": "ledger", "rules": "ledger", "income": "ledger",
    "expense": "ledger", "evidence": "ledger", "lineage": "ledger",
    "draft": "ledger", "preview": "ledger", "revise": "ledger", "scope": "ledger",
    "split": "ledger", "supersede": "ledger", "versions": "ledger",
    "tsv": "ledger", "download": "ledger", "conversation": "ledger",
    "dialog": "ledger", "my-actions": "ledger", "reserve-links": "ledger",
    "participants": "ledger", "google-ledger": "ledger", "ui": "ledger",
    "demo": "ledger", "cards": "cards", "card": "cards", "ota": "ota",
    "receipts": "receipts", "receipt": "receipts",
    "upload": "upload", "uploads": "upload",
    "auth": "auth", "login": "auth", "logout": "auth", "session": "auth",
    "access": "auth", "health": "health", "healthz": "health", "ready": "health",
    "readyz": "health", "readiness": "health", "livez": "health",
    "assets": "assets", "static": "assets", "favicon.ico": "assets",
    "robots.txt": "assets", "api": "api",
}
# Byte-transfer and page endpoints that live under /api keep the same fixed IDs
# as their non-API counterparts; everything else under /api stays "api".
_API_BY_SEGMENT = {
    "imports": "upload", "bank-imports": "upload", "upload": "upload",
    "uploads": "upload", "receipts": "receipts", "cards": "cards", "ota": "ota",
    "ota-refresh-state": "ota", "rows": "ledger", "trips": "ledger",
    "income": "ledger", "google-ledger": "ledger", "expenses": "ledger",
    "participants": "ledger", "flight-passengers": "ledger",
    "access": "auth", "auth": "auth", "session": "auth", "user-actions": "auth",
    "health": "health", "healthz": "health", "readyz": "health",
}
_METHODS = frozenset(HTTP_METHODS - {"other"})


def route_id_for_path(path: object) -> str:
    """Map an incoming URL to a fixed route ID without retaining its raw value."""
    if not isinstance(path, str):
        return "unknown"
    try:
        # urlsplit discards query and fragment from the value used below.
        path_only = urlsplit(path).path
    except (TypeError, ValueError):
        return "unknown"
    segments = path_only.lstrip("/").split("/")
    first = segments[0].lower()
    if not first:
        return "ledger"
    route_id = _ROUTE_BY_PREFIX.get(first)
    if route_id is None:
        return "unknown"
    if route_id == "api" and len(segments) > 1:
        return _API_BY_SEGMENT.get(segments[1].lower(), "api")
    return route_id


def _method_id(method: object) -> str:
    if not isinstance(method, str):
        return "other"
    value = method.upper()
    return value if value in _METHODS else "other"


def _status_class(status: object) -> str:
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        return "other"
    return f"{status // 100}xx"


def _as_utc(value: datetime | None = None) -> datetime:
    if value is None:
        value = datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("clock must return a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_window(value: object) -> dict | None:
    """Accept the previously saved loss window without trusting measured values."""
    if not isinstance(value, dict):
        return None
    result = {"from_utc": None, "to_utc": None, "seconds": None}
    if isinstance(value.get("from_utc"), str):
        result["from_utc"] = _stamp(_parse_stamp(value["from_utc"]))
    if isinstance(value.get("to_utc"), str):
        result["to_utc"] = _stamp(_parse_stamp(value["to_utc"]))
    seconds = value.get("seconds")
    if type(seconds) is int and seconds >= 0:
        result["seconds"] = seconds
    reason = value.get("reason")
    if reason in ("unclean_stop", "corrupt", "unreadable", "symlink"):
        result["reason"] = reason
    return result


def _hour_bucket(value: datetime) -> str:
    value = value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return _stamp(value)


def _new_route_counts() -> dict:
    return {
        "started": 0,
        "completed": {status: 0 for status in STATUS_CLASSES},
        "aborted": 0,
        "aborted_by_status_class": {status: 0 for status in STATUS_CLASSES},
        "request_body_bytes": 0,
        "response_body_bytes": 0,
    }


class RequestObservation:
    """Short-lived hook token. It contains only normalized labels and byte totals."""

    __slots__ = ("_owner", "route_id", "method", "bucket", "request_body_bytes",
                 "response_body_bytes", "_finished", "_lock")

    def __init__(self, owner: "RequestCounts", route_id: str, method: str, bucket: str):
        self._owner = owner
        self.route_id = route_id
        self.method = method
        self.bucket = bucket
        self.request_body_bytes = 0
        self.response_body_bytes = 0
        self._finished = False
        self._lock = threading.Lock()


class RequestCounts:
    """Bounded HTTP totals with a 60-second atomic snapshot by default."""

    def __init__(self, storage_path: str | os.PathLike, *, flush_interval_seconds: float = 60,
                 retention_hours: int = 24 * 400, start_flusher: bool = True,
                 wall_clock=None, monotonic_clock=None):
        if type(flush_interval_seconds) not in (int, float) or flush_interval_seconds <= 0:
            raise ValueError("flush interval must be positive")
        if type(retention_hours) is not int or not 1 <= retention_hours <= 24 * 400:
            raise ValueError("retention must be between 1 and 9600 hours")
        self._path = Path(storage_path)
        self._interval = float(flush_interval_seconds)
        self._retention_hours = retention_hours
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._buckets: dict[str, dict[str, dict[str, dict]]] = {}
        # Each hour bucket keeps the JSON text it last had and a revision that
        # every counted request bumps. A snapshot then re-encodes only the
        # buckets that changed instead of all 9,600 retained hours, which is
        # what used to hold the interpreter for over a second per flush.
        self._bucket_rev: dict[str, int] = {}
        self._bucket_cache: dict[str, tuple[int, str]] = {}
        self._base_uptime_seconds = 0.0
        self._persistence_failure_count = 0
        self._restart_count = 0
        self._possible_loss_window_count = 0
        self._latest_possible_loss_window = None
        self._corrupt_snapshot_count = 0
        self._counts_reset_at = None
        self._counts_reset_reason = None
        self._clean_shutdown_at = None
        self._unfinished_at_shutdown = 0
        self._unrecorded_after_save = False
        self._closing = False
        self._process_started_at = _as_utc(self._wall_clock())
        self._process_started_monotonic = self._monotonic_clock()
        self._last_saved_at = None
        self._load_existing()
        self._stop_event = threading.Event()
        self._flusher = None
        if start_flusher:
            self._flusher = threading.Thread(target=self._flush_loop,
                                             name="http-request-counts-flusher", daemon=True)
            self._flusher.start()

    def observe_begin(self, path: object, method: object) -> RequestObservation:
        """Start one request using only its fixed route and method labels."""
        route_id = route_id_for_path(path)
        method_id = _method_id(method)
        bucket = _hour_bucket(_as_utc(self._wall_clock()))
        observation = RequestObservation(self, route_id, method_id, bucket)
        with self._lock:
            counts = self._counts_for_locked(bucket, route_id, method_id)
            counts["started"] += 1
            self._touch_locked(bucket)
            self._trim_locked(_as_utc(self._wall_clock()))
        return observation

    def observe_request_read(self, observation: RequestObservation, byte_count: int) -> bool:
        """Add bytes returned by the real request-body read boundary."""
        return self._add_bytes(observation, "request_body_bytes", byte_count)

    def observe_response_write(self, observation: RequestObservation, byte_count: int) -> bool:
        """Add bytes accepted by the real response-body write boundary."""
        return self._add_bytes(observation, "response_body_bytes", byte_count)

    def observe_finish(self, observation: RequestObservation, status: object) -> bool:
        """Finish a request once, classifying its final HTTP status."""
        return self._close(observation, aborted=False, status=status)

    def observe_abort(self, observation: RequestObservation, status: object = None) -> bool:
        """Finish a request once after a handler or connection abort."""
        return self._close(observation, aborted=True, status=status)

    def _add_bytes(self, observation: RequestObservation, key: str, byte_count: int) -> bool:
        if not self._owns(observation) or key not in ("request_body_bytes", "response_body_bytes"):
            return False
        if type(byte_count) is not int or byte_count < 0:
            return False
        with observation._lock:
            if observation._finished:
                return False
            observation.__setattr__(key, observation.__getattribute__(key) + byte_count)
        return True

    def _close(self, observation: RequestObservation, *, aborted: bool, status: object) -> bool:
        if not self._owns(observation):
            return False
        status_class = _status_class(status)
        with observation._lock:
            if observation._finished:
                return False
            observation._finished = True
            request_bytes = observation.request_body_bytes
            response_bytes = observation.response_body_bytes
        with self._lock:
            counts = self._counts_for_locked(observation.bucket, observation.route_id,
                                             observation.method)
            if aborted:
                counts["aborted"] += 1
                counts["aborted_by_status_class"][status_class] += 1
            else:
                counts["completed"][status_class] += 1
            counts["request_body_bytes"] += request_bytes
            counts["response_body_bytes"] += response_bytes
            self._touch_locked(observation.bucket)
            self._trim_locked(_as_utc(self._wall_clock()))
        # A request that finishes after the counter was closed would otherwise
        # stay in memory and never reach disk. Re-check the point of the stop:
        # this only happens during shutdown, so the extra flush costs nothing.
        if self._closing:
            self.flush()
        return True

    def _owns(self, observation: object) -> bool:
        return isinstance(observation, RequestObservation) and observation._owner is self

    def _touch_locked(self, bucket: str) -> None:
        """Mark the one hour bucket whose counters changed."""
        self._bucket_rev[bucket] = self._bucket_rev.get(bucket, 0) + 1

    def _counts_for_locked(self, bucket: str, route_id: str, method: str) -> dict:
        return self._buckets.setdefault(bucket, {}).setdefault(route_id, {}).setdefault(
            method, _new_route_counts())

    def _trim_locked(self, now: datetime) -> None:
        cutoff = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=self._retention_hours - 1)
        cutoff_key = _hour_bucket(cutoff)
        for bucket in tuple(self._buckets):
            if bucket < cutoff_key:
                del self._buckets[bucket]

    def _load_existing(self) -> None:
        if self._path.is_symlink():
            self._reset_after_unreadable_snapshot("symlink")
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            self._reset_after_unreadable_snapshot("unreadable")
            return
        try:
            data = json.loads(raw)
            self._load_valid_state(data)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            # Corrupt or unexpected persisted data never gets copied into a new
            # snapshot. The totals go back to zero, so the snapshot has to say
            # that they were reset -- otherwise a truncated file reads as
            # "no requests were ever served, nothing was lost".
            self._reset_after_unreadable_snapshot("corrupt")

    def _reset_after_unreadable_snapshot(self, reason: str) -> None:
        """Record that an earlier snapshot existed but could not be used."""
        self._buckets = {}
        self._persistence_failure_count = max(self._persistence_failure_count, 1)
        self._corrupt_snapshot_count += 1
        self._counts_reset_at = self._process_started_at
        self._counts_reset_reason = reason
        self._possible_loss_window_count += 1
        # The prior saved time is unknowable, so the window stays open-ended
        # rather than claiming a measured duration.
        self._latest_possible_loss_window = {
            "from_utc": None, "to_utc": _stamp(self._process_started_at),
            "seconds": None, "reason": reason,
        }

    def _load_valid_state(self, data: object) -> None:
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("invalid state")
        saved_at = _parse_stamp(data.get("saved_at_utc"))
        self._base_uptime_seconds = _nonnegative_number(data.get("uptime_seconds"))
        self._restart_count = _nonnegative_int(data.get("restart_count")) + 1
        self._persistence_failure_count = _nonnegative_int(data.get("persistence_failure_count"))
        loss = data.get("possible_loss")
        if not isinstance(loss, dict):
            raise ValueError("invalid loss state")
        self._possible_loss_window_count = _nonnegative_int(loss.get("window_count"))
        previous_window = _optional_window(loss.get("latest_window"))
        reset = data.get("counts_reset")
        if reset is not None:
            if not isinstance(reset, dict):
                raise ValueError("invalid reset state")
            self._corrupt_snapshot_count = _nonnegative_int(reset.get("count"))
            last_reset = reset.get("last_reset_utc")
            self._counts_reset_at = (None if last_reset is None
                                     else _parse_stamp(last_reset))
            self._counts_reset_reason = reset.get("reason") if reset.get("reason") in (
                "corrupt", "unreadable", "symlink") else None
        self._last_saved_at = saved_at
        self._buckets = _validated_buckets(data.get("buckets"))
        stored_in_flight = _nonnegative_int(data.get("in_flight_count"))
        stopped = data.get("stopped_utc")
        if data.get("shutdown_utc") is not None and stored_in_flight == 0:
            # The earlier process stopped itself after a successful final
            # snapshot taken with nothing in flight: the idle window that
            # follows is not evidence of loss.
            self._clean_shutdown_at = _parse_stamp(data.get("shutdown_utc"))
            self._latest_possible_loss_window = previous_window
            self._unfinished_at_shutdown = 0
        elif stopped is not None:
            # It stopped on purpose, but a final snapshot was taken while
            # requests were still open. Their outcomes were never written, so
            # this is a loss window like any other -- just with a known cause.
            self._possible_loss_window_count += 1
            self._latest_possible_loss_window = {
                "from_utc": _stamp(saved_at), "to_utc": _stamp(self._process_started_at),
                "seconds": max(0, int((self._process_started_at - saved_at).total_seconds())),
                "reason": "shutdown_with_requests_in_flight",
            }
            self._unfinished_at_shutdown = stored_in_flight
        else:
            # An abrupt stop can drop up to one whole flush interval of counts.
            self._possible_loss_window_count += 1
            self._latest_possible_loss_window = {
                "from_utc": _stamp(saved_at), "to_utc": _stamp(self._process_started_at),
                "seconds": max(0, int((self._process_started_at - saved_at).total_seconds())),
                "reason": "unclean_stop",
            }
        self._trim_locked(self._process_started_at)

    def _flush_loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            self.flush()

    def flush(self) -> bool:
        """Persist the cumulative snapshot atomically; failures stay out of requests."""
        try:
            with self._flush_lock:
                saved_at = _as_utc(self._wall_clock())
                with self._lock:
                    self._trim_locked(saved_at)
                    header = self._header_locked(saved_at)
                    segments = self._encode_dirty_buckets_locked(known=self._known_buckets_locked())
                    # Read under the same lock as the snapshot it describes, so
                    # the clean marker and the in-flight count cannot disagree.
                    clean = header.get("shutdown_utc") is not None if self._closing else None
                self._atomic_replace(header, segments)
            with self._lock:
                self._last_saved_at = saved_at
                # Only a flush taken while nothing was in flight may claim a
                # clean stop; a snapshot that skipped live requests cannot.
                self._clean_shutdown_at = saved_at if clean else None
                # `clean` is None unless this flush is taking the final
                # snapshot of a deliberate stop. Anything else that leaves a
                # request open means its outcome is not on disk.
                self._unrecorded_after_save = (clean is not None
                                               and self._in_flight_locked() > 0)
            return True
        except Exception:
            with self._lock:
                self._persistence_failure_count += 1
            return False

    def _known_buckets_locked(self) -> set:
        """The retained buckets this flush must write, after trimming."""
        return set(self._buckets)

    def _in_flight_locked(self) -> int:
        started = sum(values["started"] for routes in self._buckets.values()
                      for methods in routes.values() for values in methods.values())
        closed = sum(sum(values["completed"].values()) + values["aborted"]
                     for routes in self._buckets.values()
                     for methods in routes.values() for values in methods.values())
        return max(0, started - closed)

    def _header_locked(self, saved_at: datetime) -> dict:
        elapsed = max(0.0, self._monotonic_clock() - self._process_started_monotonic)
        in_flight = self._in_flight_locked()
        return {
            "schema_version": SCHEMA_VERSION,
            "saved_at_utc": _stamp(saved_at),
            "process_started_at_utc": _stamp(self._process_started_at),
            "uptime_seconds": int(self._base_uptime_seconds + elapsed),
            "restart_count": self._restart_count,
            "persistence_failure_count": self._persistence_failure_count,
            # Requests that began and never closed. A later process reads this
            # to know that the snapshot does not include their outcome.
            "in_flight_count": in_flight,
            # A deliberate stop is recorded whenever it happens; whether it was
            # clean is a separate fact, because a stop can happen while a
            # request is still open and its outcome is then not saved.
            "stopped_utc": _stamp(self._clean_shutdown_at or saved_at)
                            if self._closing else None,
            "clean_shutdown": bool(self._closing and in_flight == 0),
            # Kept as the single "this file may be treated as final" marker.
            "shutdown_utc": (_stamp(self._clean_shutdown_at or saved_at)
                             if self._closing and in_flight == 0 else None),
            # True when a request was still open after the last save: its
            # outcome is not in the totals above.
            "unrecorded_open_requests": bool(self._unrecorded_after_save
                                             or (in_flight > 0)),
            "is_open_process": not self._closing,
            "possible_loss": {
                "window_count": self._possible_loss_window_count,
                "latest_window": self._latest_possible_loss_window,
                "unflushed_since_utc": _stamp(self._last_saved_at or self._process_started_at),
            },
            "counts_reset": {
                "count": self._corrupt_snapshot_count,
                "last_reset_utc": (None if self._counts_reset_at is None
                                   else _stamp(self._counts_reset_at)),
                "reason": self._counts_reset_reason,
            },
            "retention_hours": self._retention_hours,
        }

    def _encode_dirty_buckets_locked(self, *, known=None) -> list:
        """JSON text per retained bucket, re-encoding only the changed ones.

        `known` lets a flush hand in the exact retained set, so a bucket another
        thread added between the trim and this call is still written rather than
        silently dropped from the snapshot. The cache itself stays bounded by
        the retained buckets.
        """
        buckets = self._buckets if known is None else known
        segments = []
        live = set()
        for bucket, routes in sorted(self._buckets.items()):
            if bucket not in buckets:
                continue
            live.add(bucket)
            revision = self._bucket_rev.get(bucket, 0)
            cached = self._bucket_cache.get(bucket)
            if cached is not None and cached[0] == revision:
                text = cached[1]
            else:
                text = json.dumps(_bucket_payload(routes), ensure_ascii=True,
                                  sort_keys=True, separators=(",", ":"))
                self._bucket_cache[bucket] = (revision, text)
            segments.append((bucket, text))
        if len(self._bucket_cache) > len(live) * 2:
            for bucket in tuple(self._bucket_cache):
                if bucket not in live:
                    del self._bucket_cache[bucket]
                    self._bucket_rev.pop(bucket, None)
        return segments

    def _atomic_replace(self, header: dict, segments: list | None = None) -> None:
        path = self._path
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if segments is None:  # a caller passing a finished dict still gets a file
            payload = json.dumps(header, ensure_ascii=True, sort_keys=True,
                                 separators=(",", ":")) + "\n"
        else:
            payload = _compose_payload(header, segments)
        temporary = parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(temporary, flags, stat.S_IRUSR | stat.S_IWUSR)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def close(self) -> bool:
        """Stop the periodic writer and persist whatever is still unsaved.

        The snapshot is marked clean only when no request was in flight when it
        was written. The launcher closes this before the socket stops serving,
        so an in-flight request can still finish afterwards; in that case the
        snapshot honestly says a stop happened with requests open, and the next
        start counts it as a loss window instead of a clean stop.
        """
        self._closing = True
        self._stop_event.set()
        joiner_alive = False
        if self._flusher is not None and self._flusher is not threading.current_thread():
            self._flusher.join(timeout=max(1.0, self._interval * 2))
            # A daemon writer that ignored the stop signal can still be running
            # and may write after this returns. That snapshot must not be
            # labelled a clean stop.
            joiner_alive = self._flusher.is_alive()
        if joiner_alive:
            self._closing = False
            with self._lock:
                self._persistence_failure_count += 1
            return False
        return self.flush()

    @property
    def persistence_failure_count(self) -> int:
        with self._lock:
            return self._persistence_failure_count


def _bucket_payload(routes: dict) -> dict:
    """The persisted form of one hour bucket, with unfinished derived."""
    out = {}
    for route_id, methods in routes.items():
        out[route_id] = {}
        for method, values in methods.items():
            copied = {
                "started": values["started"],
                "completed": dict(values["completed"]),
                "aborted": values["aborted"],
                "aborted_by_status_class": dict(values["aborted_by_status_class"]),
                "request_body_bytes": values["request_body_bytes"],
                "response_body_bytes": values["response_body_bytes"],
            }
            copied["unfinished"] = max(
                0, copied["started"] - sum(copied["completed"].values()) - copied["aborted"])
            out[route_id][method] = copied
    return out


def _compose_payload(header: dict, segments: list) -> str:
    """Write the snapshot as header fields plus one already-encoded bucket each.

    The result is byte-identical to `json.dumps` of the whole document with
    `sort_keys=True`: each header field is emitted on its own and "buckets"
    takes its normal sorted place among them, so readers and the loader need
    no change.
    """
    keys = sorted(set(header) | {"buckets"})
    parts = []
    for key in keys:
        if key == "buckets":
            body = ",".join(
                f"{json.dumps(bucket, ensure_ascii=True, sort_keys=True, separators=(',', ':'))}:{text}"
                for bucket, text in segments)
            parts.append('"buckets":{' + body + "}")
        else:
            parts.append(json.dumps(key, ensure_ascii=True) + ":" + json.dumps(
                header[key], ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return "{" + ",".join(parts) + "}\n"


def _parse_stamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    return parsed.astimezone(timezone.utc)


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid integer")
    return value


def _nonnegative_number(value: object) -> float:
    if type(value) not in (int, float) or value < 0:
        raise ValueError("invalid number")
    return float(value)


def _validated_buckets(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("invalid buckets")
    result = {}
    for bucket, routes in value.items():
        if _hour_bucket(_parse_stamp(bucket)) != bucket or not isinstance(routes, dict):
            raise ValueError("invalid bucket key")
        result[bucket] = {}
        for route_id, methods in routes.items():
            if route_id not in ROUTE_IDS or not isinstance(methods, dict):
                raise ValueError("invalid route")
            result[bucket][route_id] = {}
            for method, row in methods.items():
                if method not in HTTP_METHODS or not isinstance(row, dict):
                    raise ValueError("invalid method")
                completed = row.get("completed")
                aborted_by = row.get("aborted_by_status_class")
                if (not isinstance(completed, dict) or set(completed) != set(STATUS_CLASSES) or
                        not isinstance(aborted_by, dict) or set(aborted_by) != set(STATUS_CLASSES)):
                    raise ValueError("invalid status counts")
                result[bucket][route_id][method] = {
                    "started": _nonnegative_int(row.get("started")),
                    "completed": {key: _nonnegative_int(completed[key]) for key in STATUS_CLASSES},
                    "aborted": _nonnegative_int(row.get("aborted")),
                    "aborted_by_status_class": {
                        key: _nonnegative_int(aborted_by[key]) for key in STATUS_CLASSES
                    },
                    "request_body_bytes": _nonnegative_int(row.get("request_body_bytes")),
                    "response_body_bytes": _nonnegative_int(row.get("response_body_bytes")),
                }
    return result
