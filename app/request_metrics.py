"""Bounded, content-free request and performance measurements.

Only allowlisted operation/stage names, opaque request tokens, integer lineage
metadata, fingerprints, and numeric measurements are retained. Callers must
never pass source rows, SQL, paths, user-provided labels, or exception text.
"""
from __future__ import annotations

import secrets
import time
import functools
from contextlib import contextmanager
from collections import defaultdict
from threading import Lock
from contextvars import ContextVar

from app.ota_queue_telemetry import percentile, stage_sample


OPERATIONS = frozenset({"ota_snapshot", "first_render", "card_search",
                        "google_canonical_read", "db_lock_wait", "payload_serialize"})
STAGES = frozenset({"snapshot_compute", "first_render", "card_search",
                    "google_read", "db_lock_wait", "payload_serialize",
                    "db_connect", "card_query", "trip_labels", "card_render"})
_CARD_OPERATION = ContextVar("cost_card_metrics_operation", default=None)
_REQUEST_ID = ContextVar("cost_request_metrics_id", default=None)
_LOCK_WAIT_STARTED = ContextVar("cost_request_metrics_lock_started", default=None)
_REGISTRY = None


def new_request_id() -> str:
    """Create a random correlation token that carries no user or transaction ID."""
    return secrets.token_hex(16)


def current_request_id() -> str:
    """Return this request's ID or create one for a standalone measured seam."""
    return _REQUEST_ID.get() or new_request_id()


def mark_lock_wait_started():
    return _LOCK_WAIT_STARTED.set(time.perf_counter())


def lock_wait_started():
    return _LOCK_WAIT_STARTED.get()


def bind_request_id(value=None):
    """Bind an opaque request ID and lock timer; return reset tokens."""
    request_token = _REQUEST_ID.set(value or new_request_id())
    lock_token = _LOCK_WAIT_STARTED.set(None)
    return request_token, lock_token


def reset_request_id(token) -> None:
    request_token, lock_token = token
    _REQUEST_ID.reset(request_token)
    _LOCK_WAIT_STARTED.reset(lock_token)


def measurement(operation: str, stage: str, elapsed_ms, *, row_count=None,
                byte_count=None, generation=None, rule_version=None,
                data_fingerprint=None, request_id=None, peak_memory_bytes=None) -> dict:
    """Build one validated, PII-free measurement envelope."""
    if operation not in OPERATIONS or stage not in STAGES:
        raise ValueError("unknown metric operation or stage")
    sample = stage_sample(stage, elapsed_ms, row_count=row_count, byte_count=byte_count)
    if generation is not None and (type(generation) is not int or generation < 0):
        raise ValueError("generation must be a non-negative integer")
    if rule_version is not None and (type(rule_version) is not str or len(rule_version) > 64 or
                                     not all(char.isalnum() or char in "_.-" for char in rule_version)):
        raise ValueError("invalid rule version")
    if data_fingerprint is not None and (type(data_fingerprint) is not str or len(data_fingerprint) != 64 or
                                         any(c not in "0123456789abcdef" for c in data_fingerprint)):
        raise ValueError("invalid data fingerprint")
    if request_id is None:
        request_id = current_request_id()
    if type(request_id) is not str or len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id):
        raise ValueError("invalid request id")
    if peak_memory_bytes is not None and (type(peak_memory_bytes) is not int or peak_memory_bytes < 0):
        raise ValueError("peak memory must be a non-negative integer")
    result = {"operation": operation, "request_id": request_id,
            "snapshot_generation": generation, "rule_version": rule_version,
            "data_fingerprint": data_fingerprint, **sample}
    if peak_memory_bytes is not None:
        result["peak_memory_bytes"] = peak_memory_bytes
    return result


class MetricsWindow:
    """Thread-safe bounded in-memory aggregator; exports aggregates only."""

    def __init__(self, *, limit=2048):
        if type(limit) is not int or not 1 <= limit <= 100_000:
            raise ValueError("invalid metrics window limit")
        self._limit = limit
        self._records = []
        self._lock = Lock()

    def record(self, item: dict) -> None:
        # Revalidate by rebuilding from allowlisted fields; unknown values vanish.
        clean = measurement(item.get("operation"), item.get("stage"), item.get("elapsed_ms"),
                            row_count=item.get("row_count"), byte_count=item.get("byte_count"),
                            generation=item.get("snapshot_generation"),
                            rule_version=item.get("rule_version"),
                            data_fingerprint=item.get("data_fingerprint"),
                            request_id=item.get("request_id"),
                            peak_memory_bytes=item.get("peak_memory_bytes"))
        with self._lock:
            self._records = (self._records + [clean])[-self._limit:]

    def summary(self) -> dict:
        with self._lock:
            records = list(self._records)
        grouped = defaultdict(list)
        for record in records:
            grouped[(record["operation"], record["stage"])].append(record)
        return {f"{operation}.{stage}": {
            "samples": len(rows),
            "p50_ms": percentile([r["elapsed_ms"] for r in rows], 50),
            "p95_ms": percentile([r["elapsed_ms"] for r in rows], 95),
            "rows": sum(r.get("row_count", 0) for r in rows),
            "bytes": sum(r.get("byte_count", 0) for r in rows),
            "peak_memory_bytes": max((r["peak_memory_bytes"] for r in rows
                                       if "peak_memory_bytes" in r), default=None),
        } for (operation, stage), rows in sorted(grouped.items())}


def timed(operation: str, stage: str, callback, *, row_count=None,
          byte_count_fn=None, generation=None, rule_version=None,
          data_fingerprint=None, clock=time.perf_counter, metrics: MetricsWindow | None = None):
    """Measure a call without retaining or logging its result contents."""
    request_id = current_request_id()
    started = clock()
    result = callback()
    elapsed = (clock() - started) * 1000
    size = byte_count_fn(result) if byte_count_fn is not None else None
    item = measurement(operation, stage, elapsed, row_count=row_count,
                       byte_count=size, generation=generation,
                       rule_version=rule_version, data_fingerprint=data_fingerprint,
                       request_id=request_id)
    if metrics is not None:
        metrics.record(item)
    return result, item


_REGISTRY = MetricsWindow(limit=4096)


def record(item: dict) -> None:
    """Record one safe event in the process-local bounded metrics window."""
    _REGISTRY.record(item)


def summary() -> dict:
    return _REGISTRY.summary()


@contextmanager
def card_scope(operation):
    """Select a fixed operation for nested card reads; retain no query values."""
    if operation not in ('first_render', 'card_search'):
        raise ValueError('invalid card operation')
    token = _CARD_OPERATION.set(operation)
    try:
        yield
    finally:
        _CARD_OPERATION.reset(token)


@contextmanager
def card_phase(stage):
    if stage not in ('db_connect', 'card_query', 'trip_labels', 'card_render'):
        raise ValueError('invalid card stage')
    operation = _CARD_OPERATION.get()
    if operation is None:
        yield
        return
    started = time.perf_counter()
    yield
    record(measurement(operation, stage, (time.perf_counter() - started) * 1000))


def card_stage(stage):
    """Time a card read boundary only inside a card page scope.

    card_query includes connection setup and result materialization; db_connect
    is its nested subset. These are inclusive wall times, not SQLite CPU time.
    Exceptions propagate unchanged and do not become successful samples.
    """
    if stage not in ('db_connect', 'card_query', 'trip_labels', 'card_render'):
        raise ValueError('invalid card stage')
    def decorate(callback):
        @functools.wraps(callback)
        def measured(*args, **kwargs):
            with card_phase(stage):
                return callback(*args, **kwargs)
        return measured
    return decorate
