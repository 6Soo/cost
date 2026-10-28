"""Repeatable synthetic-only OTA queue benchmark; makes no operational DB reads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ota_queue_paging import build_queue_index, list_queue_page
from app.ota_queue_projection import summarize_queue
from app.ota_queue_telemetry import payload_bytes, safe_snapshot_metadata, summarize_samples, timed


KEY = b"synthetic-ota-queue-benchmark-signing-key"
READY = {"status": "ready", "stale": False, "refreshing": False,
         "fresh": True, "enabled": True, "generation": 1}


def synthetic_rows(size):
    rows, events = [], []
    for ordinal in range(size):
        event_id = f"synthetic-event-{ordinal:07d}"
        status = "MATCHED_AUTO" if ordinal % 3 else "HOLD_AMBIGUOUS"
        queue = "completed" if status == "MATCHED_AUTO" else "needs_action"
        event = {"ota_event_id": event_id, "provider": "synthetic", "booking_ref": f"SYN-{ordinal:07d}",
                 "event_type": "charge", "paid_on": "2026-10-01", "item": "synthetic stay",
                 "amount": 10000 + ordinal, "currency": "KRW", "status": status,
                 "payment_status": "paid", "evidence_status": "paid_verified",
                 "reason": "unique_exact_evidence", "transaction_id": f"synthetic-card-{ordinal:07d}",
                 "individual_payment_evidence": True}
        events.append(event)
        rows.append({"queue": queue, "reason_codes": [], "warning": False,
                     "event": {key: event[key] for key in (
                         "ota_event_id", "provider", "booking_ref", "event_type", "paid_on",
                         "item", "amount", "currency", "status")}})
    return events, rows


def query_plan_probe(size):
    """Create an ephemeral database from synthetic rows and explain a bounded lookup."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE synthetic_queue (event_key TEXT, queue TEXT, paid_on TEXT)")
        connection.executemany("INSERT INTO synthetic_queue VALUES (?, ?, ?)",
                               ((f"event-{n}", "needs_action" if n % 3 == 0 else "completed",
                                 "2026-10-01") for n in range(size)))
        connection.execute("CREATE INDEX synthetic_queue_order ON synthetic_queue(queue, paid_on, event_key)")
        started = time.perf_counter()
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT event_key FROM synthetic_queue "
            "WHERE queue=? ORDER BY paid_on, event_key LIMIT ?", ("needs_action", 20)).fetchall()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {"stage": "query_plan", "elapsed_ms": round(elapsed_ms, 3),
                "row_count": size, "plan_steps": len(plan),
                "uses_index": any("INDEX" in str(row[3]).upper() for row in plan)}
    finally:
        connection.close()


def run(size, repeats):
    events, rows = synthetic_rows(size)
    measurements = []
    summary = None
    for _ in range(repeats):
        tracemalloc.start()
        summary, projection_sample = timed(
            "projection", lambda: summarize_queue(events, READY, coverage="canonical"),
            row_count=size, byte_count_fn=payload_bytes)
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append(projection_sample)

        index, publish_sample = timed(
            "snapshot_publish",
            lambda: build_queue_index(rows, generation=1, snapshot_nonce="synthetic-run",
                                      signing_key=KEY),
            row_count=size, byte_count_fn=lambda _index: payload_bytes(rows))
        measurements.append(publish_sample)

        page, page_sample = timed("page_serialize", lambda: list_queue_page(index, limit=20),
                                  row_count=20, byte_count_fn=payload_bytes)
        measurements.append(page_sample)

    plan = query_plan_probe(size)
    metrics = summarize_samples(measurements + [plan])
    metrics["projection_memory"] = {"samples": repeats, "peak_memory_bytes": peak_bytes}
    output = {"measurement_scope": "synthetic_only_no_product_sla_claim",
              "fixture_events": size, "repeats": repeats,
              "snapshot_metadata": safe_snapshot_metadata(READY),
              "queue_counts": summary["counts_by_queue"],
              "page_items": len(page["items"]), "page_total": page["total_count"],
              "query_plan": {key: value for key, value in plan.items() if key != "elapsed_ms"},
              "metrics": metrics}
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000])
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args(argv)
    if args.repeats < 1 or args.repeats > 50 or any(size < 1 or size > 100_000 for size in args.sizes):
        parser.error("sizes must be 1..100000 and repeats 1..50")
    print(json.dumps([run(size, args.repeats) for size in args.sizes],
                     ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
