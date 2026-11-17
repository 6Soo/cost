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
_ROUTE_BY_PREFIX = {
    "ledger": "ledger", "board": "ledger", "cards": "cards", "card": "cards",
    "ota": "ota", "receipts": "receipts", "receipt": "receipts",
    "upload": "upload", "uploads": "upload", "auth": "auth", "login": "auth",
    "logout": "auth", "session": "auth", "health": "health", "healthz": "health",
    "ready": "health", "readiness": "health", "assets": "assets", "static": "assets",
    "api": "api",
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
    first = path_only.lstrip("/").split("/", 1)[0].lower()
    if not first:
        return "ledger"
    return _ROUTE_BY_PREFIX.get(first, "unknown")


def _method_id(method: object) -> str:
    if not isinstance(method, str):
        return "other"
    value = method.upper()
    return value if value in _METHODS else "other"


def _status_class(status: object) -> str:
    if type(status) is not int or not 100 <= status <= 599:
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
        self._base_uptime_seconds = 0.0
        self._persistence_failure_count = 0
        self._restart_count = 0
        self._possible_loss_window_count = 0
        self._latest_possible_loss_window = None
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
            self._trim_locked(_as_utc(self._wall_clock()))
        return True

    def _owns(self, observation: object) -> bool:
        return isinstance(observation, RequestObservation) and observation._owner is self

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
            self._persistence_failure_count = 1
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            self._persistence_failure_count = 1
            return
        try:
            data = json.loads(raw)
            self._load_valid_state(data)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            # Corrupt or unexpected persisted data never gets copied into a new snapshot.
            self._buckets = {}
            self._persistence_failure_count = max(self._persistence_failure_count, 1)

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
        self._possible_loss_window_count = _nonnegative_int(loss.get("window_count")) + 1
        start = saved_at
        end = self._process_started_at
        self._latest_possible_loss_window = {
            "from_utc": _stamp(start), "to_utc": _stamp(end),
            "seconds": max(0, int((end - start).total_seconds())),
        }
        self._last_saved_at = saved_at
        self._buckets = _validated_buckets(data.get("buckets"))
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
                    snapshot = self._snapshot_locked(saved_at)
                self._atomic_replace(snapshot)
            with self._lock:
                self._last_saved_at = saved_at
            return True
        except Exception:
            with self._lock:
                self._persistence_failure_count += 1
            return False

    def _snapshot_locked(self, saved_at: datetime) -> dict:
        buckets = {}
        for bucket, routes in sorted(self._buckets.items()):
            buckets[bucket] = {}
            for route_id, methods in sorted(routes.items()):
                buckets[bucket][route_id] = {}
                for method, values in sorted(methods.items()):
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
                    buckets[bucket][route_id][method] = copied
        elapsed = max(0.0, self._monotonic_clock() - self._process_started_monotonic)
        return {
            "schema_version": SCHEMA_VERSION,
            "saved_at_utc": _stamp(saved_at),
            "process_started_at_utc": _stamp(self._process_started_at),
            "uptime_seconds": int(self._base_uptime_seconds + elapsed),
            "restart_count": self._restart_count,
            "persistence_failure_count": self._persistence_failure_count,
            "possible_loss": {
                "window_count": self._possible_loss_window_count,
                "latest_window": self._latest_possible_loss_window,
                "unflushed_since_utc": _stamp(self._last_saved_at or self._process_started_at),
            },
            "retention_hours": self._retention_hours,
            "buckets": buckets,
        }

    def _atomic_replace(self, snapshot: dict) -> None:
        path = self._path
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
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
        """Stop the periodic writer and make one final best-effort snapshot."""
        self._stop_event.set()
        if self._flusher is not None and self._flusher is not threading.current_thread():
            self._flusher.join(timeout=max(1.0, self._interval * 2))
        return self.flush()

    @property
    def persistence_failure_count(self) -> int:
        with self._lock:
            return self._persistence_failure_count


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
