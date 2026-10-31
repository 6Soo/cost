"""PII-free timing and size helpers for OTA queue stages.

The adapter accepts only finite stage names and numeric measurements. It never
records row contents, identifiers, SQL parameters, paths, exception text, or
arbitrary labels. Callers own the clock and can use it with synthetic inputs.
"""
from __future__ import annotations

import json
import hashlib
import math
import time
from collections.abc import Mapping


STAGES = frozenset({"source_parse", "card_read", "solver", "projection",
                    "snapshot_publish", "page_serialize", "summary_read",
                    "detail_read", "query_plan", "memory_peak", "trace_validate",
                    "reconcile", "snapshot_read", "queue_index_build",
                    "snapshot_compute", "first_render", "card_search", "google_read",
                    "db_lock_wait", "payload_serialize", "db_connect",
                    "card_query", "trip_labels", "card_render"})


def payload_bytes(value) -> int:
    """Return compact UTF-8 JSON size; caller must pass an already-safe payload."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8"))


def stage_sample(stage: str, elapsed_ms, *, row_count=None, byte_count=None) -> dict:
    """Build a strictly bounded, content-free measurement record."""
    if type(stage) is not str or stage not in STAGES:
        raise ValueError("unknown telemetry stage")
    if type(elapsed_ms) not in (int, float) or not math.isfinite(elapsed_ms) or elapsed_ms < 0:
        raise ValueError("elapsed_ms must be a finite non-negative number")
    sample = {"stage": stage, "elapsed_ms": round(float(elapsed_ms), 3)}
    for name, value in (("row_count", row_count), ("byte_count", byte_count)):
        if value is not None:
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            sample[name] = value
    return sample


def timed(stage: str, operation, *, row_count=None, byte_count_fn=None,
          clock=time.perf_counter):
    """Run one operation and return (result, content-free sample); exceptions pass through."""
    started = clock()
    value = operation()
    elapsed_ms = (clock() - started) * 1000
    size = byte_count_fn(value) if byte_count_fn is not None else None
    return value, stage_sample(stage, elapsed_ms, row_count=row_count, byte_count=size)


def percentile(samples, percentile_value):
    """Nearest-rank percentile over finite non-negative samples."""
    if type(percentile_value) not in (int, float) or not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    values = sorted(float(value) for value in samples
                    if type(value) in (int, float) and math.isfinite(value) and value >= 0)
    if not values:
        return None
    index = max(0, math.ceil(float(percentile_value) / 100 * len(values)) - 1)
    return round(values[index], 3)


def summarize_samples(records) -> dict:
    """Aggregate approved stage samples without preserving any source record."""
    grouped = {}
    for record in records:
        if type(record) is not dict:
            raise ValueError("sample must be a dictionary")
        clean = stage_sample(record.get("stage"), record.get("elapsed_ms"),
                             row_count=record.get("row_count"),
                             byte_count=record.get("byte_count"))
        grouped.setdefault(clean["stage"], []).append(clean)
    result = {}
    for stage, rows in sorted(grouped.items()):
        latency = [row["elapsed_ms"] for row in rows]
        result[stage] = {"samples": len(rows), "p50_ms": percentile(latency, 50),
                         "p95_ms": percentile(latency, 95),
                         "rows": sum(row.get("row_count", 0) for row in rows),
                         "bytes": sum(row.get("byte_count", 0) for row in rows)}
    return result


def append_sample(window, sample, *, limit=128):
    """Return a bounded copy of an approved sample window."""
    if type(window) not in (list, tuple) or type(limit) is not int or not 1 <= limit <= 1024:
        raise ValueError("invalid sample window")
    clean = stage_sample(sample.get("stage"), sample.get("elapsed_ms"),
                         row_count=sample.get("row_count"), byte_count=sample.get("byte_count"))
    return (list(window) + [clean])[-limit:]


def fingerprint(value) -> str:
    """Stable content fingerprint for internal version-consistency metadata."""
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str).encode("utf-8")).hexdigest()


def safe_snapshot_metadata(metadata: Mapping) -> dict:
    """Keep only finite lifecycle metadata; omit keys, timestamps, paths and payloads."""
    if not isinstance(metadata, Mapping):
        return {"status": "unknown", "generation": None, "stale": None,
                "refreshing": None, "fresh": None}
    status = metadata.get("status")
    generation = metadata.get("generation")
    clean = {"status": status if type(status) is str and status in
            ("loading", "ready", "refreshing", "error") else "unknown",
            "generation": generation if type(generation) is int and generation >= 0 else None,
            "stale": metadata.get("stale") if type(metadata.get("stale")) is bool else None,
            "refreshing": metadata.get("refreshing") if type(metadata.get("refreshing")) is bool else None,
            "fresh": metadata.get("fresh") if type(metadata.get("fresh")) is bool else None}
    for key in ("input_fingerprint", "rule_fingerprint"):
        value = metadata.get(key)
        clean[key] = value if type(value) is str and len(value) == 64 and all(
            char in "0123456789abcdef" for char in value) else None
    return clean


def _finite_codes(value):
    if type(value) not in (list, tuple) or len(value) > 32:
        return None
    if any(type(code) is not str or not code or len(code) > 64 or
           not code.replace("_", "").isalnum() or code.upper() != code for code in value):
        return None
    return list(dict.fromkeys(value))


def build_read_trace(*, summary, page, detail=None, sample=None):
    """Validate summary/page/detail lineage and emit a PII-free diagnostic trace.

    Inputs are metadata envelopes and allowlisted reason codes only. Event,
    group, card, reservation, and source identifiers are neither accepted nor
    returned. ``page`` and optional ``detail`` must declare their snapshot
    envelope and reason codes explicitly.
    """
    if type(summary) is not dict or type(page) is not dict or (detail is not None and type(detail) is not dict):
        raise ValueError("trace inputs must be dictionaries")
    summary_meta = {key: summary.get(key) for key in
                    ("status", "generation", "fresh", "stale", "refreshing",
                     "input_fingerprint", "rule_fingerprint")}
    page_meta = {key: page.get(key) for key in
                 ("status", "generation", "fresh", "stale", "refreshing",
                  "input_fingerprint", "rule_fingerprint")}
    detail_meta = ({key: detail.get(key) for key in
                    ("status", "generation", "fresh", "stale", "refreshing",
                     "input_fingerprint", "rule_fingerprint")}
                   if detail is not None else None)
    clean_summary = safe_snapshot_metadata(summary_meta)
    clean_page = safe_snapshot_metadata(page_meta)
    clean_detail = safe_snapshot_metadata(detail_meta) if detail_meta is not None else None
    reasons = _finite_codes(page.get("reason_codes", ()))
    if reasons is None:
        reasons = ["TRACE_REASON_CODES_INVALID"]
    complete = (clean_summary["generation"] is not None and
                clean_summary["generation"] == clean_page["generation"] and
                clean_summary["status"] == "ready" and clean_page["status"] == "ready" and
                clean_summary["fresh"] is True and clean_page["fresh"] is True and
                clean_summary["stale"] is False and clean_page["stale"] is False and
                clean_summary["refreshing"] is False and clean_page["refreshing"] is False)
    if clean_detail is not None:
        complete = bool(complete and clean_detail["generation"] == clean_summary["generation"] and
                        clean_detail["status"] == "ready" and clean_detail["fresh"] is True and
                        clean_detail["stale"] is False and clean_detail["refreshing"] is False)
    fingerprints = (clean_summary["input_fingerprint"], clean_page["input_fingerprint"],
                    clean_summary["rule_fingerprint"], clean_page["rule_fingerprint"])
    complete = bool(complete and all(type(value) is str for value in fingerprints) and
                    fingerprints[0] == fingerprints[1] and fingerprints[2] == fingerprints[3])
    if clean_detail is not None:
        complete = bool(complete and clean_detail["input_fingerprint"] == fingerprints[0] and
                        clean_detail["rule_fingerprint"] == fingerprints[2])
    clean_sample = None
    if sample is not None:
        if type(sample) is not dict:
            raise ValueError("sample must be a dictionary")
        clean_sample = stage_sample(sample.get("stage"), sample.get("elapsed_ms"),
                                    row_count=sample.get("row_count"),
                                    byte_count=sample.get("byte_count"))
    if not complete:
        reasons.append("SNAPSHOT_LINEAGE_INCOMPLETE")
    return {"trace_status": "complete" if complete else "incomplete",
            "reason_codes": list(dict.fromkeys(reasons)),
            "summary": clean_summary, "page": clean_page, "detail": clean_detail,
            "sample": clean_sample}
