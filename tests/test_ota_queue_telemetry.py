"""Synthetic-only tests for queue telemetry and benchmark safety boundaries."""
import json

import pytest

from app.ota_queue_telemetry import (
    build_read_trace, payload_bytes, percentile, safe_snapshot_metadata,
    stage_sample, summarize_samples, timed,
)
from tools.benchmark_ota_queue import query_plan_probe, run


def test_snapshot_memory_profiling_is_explicit_and_does_not_toggle_another_profiler():
    from unittest.mock import patch
    from webapp.ota_snapshot import OtaSnapshotService
    service = OtaSnapshotService(key_fn=lambda: 'synthetic-key',
        reconcile_fn=lambda: {'public': {}, 'data': {}, 'rule_fingerprint': 'a' * 64}, start=False)
    with patch('webapp.ota_snapshot.tracemalloc.start') as start, patch(
            'webapp.ota_snapshot.tracemalloc.stop') as stop:
        service.check_now()
    start.assert_not_called()
    stop.assert_not_called()
    assert service.view()['telemetry']['memory_peak_bytes'] is None
    assert service.view()['telemetry']['memory_scope'] == 'not_measured'


def test_opt_in_memory_probe_preserves_an_existing_process_profiler():
    from unittest.mock import patch
    from webapp.ota_snapshot import OtaSnapshotService
    service = OtaSnapshotService(key_fn=lambda: 'synthetic-key',
        reconcile_fn=lambda: {'public': {}, 'data': {}, 'rule_fingerprint': 'a' * 64},
        start=False, profile_memory=True)
    with patch('webapp.ota_snapshot.tracemalloc.is_tracing', return_value=True), patch(
            'webapp.ota_snapshot.tracemalloc.get_traced_memory', return_value=(100, 200)), patch(
            'webapp.ota_snapshot.tracemalloc.start') as start, patch(
            'webapp.ota_snapshot.tracemalloc.stop') as stop:
        service.check_now()
    start.assert_not_called()
    stop.assert_not_called()
    assert service.view()['telemetry']['memory_peak_bytes'] == 200
    assert service.view()['telemetry']['memory_scope'] == 'process_tracemalloc'


def test_stage_adapter_accepts_only_finite_allowlisted_metadata():
    sample = stage_sample("projection", 2.12345, row_count=7, byte_count=91)
    assert sample == {"stage": "projection", "elapsed_ms": 2.123,
                      "row_count": 7, "byte_count": 91}
    for stage in ("merchant: SECRET", "customer_id", "sql", "unknown"):
        with pytest.raises(ValueError):
            stage_sample(stage, 1)
    for value in (-1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            stage_sample("projection", value)


def test_timed_operation_returns_result_and_never_serializes_result_content():
    ticks = iter((1.0, 1.005))
    value, sample = timed("page_serialize", lambda: {"booking_ref": "SENTINEL_BOOKING"},
                          row_count=1, byte_count_fn=payload_bytes,
                          clock=lambda: next(ticks))
    assert value["booking_ref"] == "SENTINEL_BOOKING"
    assert sample == {"stage": "page_serialize", "elapsed_ms": 5.0,
                      "row_count": 1, "byte_count": payload_bytes(value)}
    assert "SENTINEL" not in json.dumps(sample)


def test_aggregate_is_content_free_and_percentiles_use_nearest_rank():
    records = [stage_sample("solver", n, row_count=1, byte_count=5) for n in range(1, 6)]
    summary = summarize_samples(records)
    assert summary["solver"] == {"samples": 5, "p50_ms": 3.0,
                                 "p95_ms": 5.0, "rows": 5, "bytes": 25}
    assert percentile([], 95) is None
    assert percentile(["SENTINEL", 4, 2], 50) == 2.0
    assert "SENTINEL" not in json.dumps(summary)


def test_snapshot_metadata_drops_keys_timestamps_payload_and_arbitrary_text():
    metadata = safe_snapshot_metadata({"status": "ready", "generation": 3,
                                       "stale": False, "refreshing": False, "fresh": True,
                                       "snapshot_key": "SENTINEL_KEY", "generated_at": "SENTINEL_TIME",
                                       "events": ["SENTINEL_EVENT"]})
    assert metadata == {"status": "ready", "generation": 3,
                        "stale": False, "refreshing": False, "fresh": True,
                        "input_fingerprint": None, "rule_fingerprint": None}
    assert "SENTINEL" not in json.dumps(metadata)


def test_trace_marks_same_generation_summary_page_detail_complete_without_identity_fields():
    envelope = {"status": "ready", "generation": 7, "fresh": True,
                "stale": False, "refreshing": False,
                "input_fingerprint": "a" * 64, "rule_fingerprint": "b" * 64}
    trace = build_read_trace(summary={**envelope, "snapshot_key": "SENTINEL_KEY"},
                             page={**envelope, "event_id": "SENTINEL_EVENT",
                                   "reason_codes": ["MATCHING_REVIEW_RESOLVED"]},
                             detail={**envelope, "transaction_id": "SENTINEL_CARD"},
                             sample={"stage": "detail_read", "elapsed_ms": 4.5,
                                     "row_count": 1, "byte_count": 64})
    assert trace["trace_status"] == "complete"
    encoded = json.dumps(trace)
    for secret in ("SENTINEL", "event_id", "transaction_id", "snapshot_key"):
        assert secret not in encoded


@pytest.mark.parametrize("page_changes", [
    {"generation": 8}, {"stale": True}, {"fresh": False},
    {"status": "refreshing"}, {"refreshing": True},
])
def test_trace_downgrades_mixed_or_stale_summary_page_lineage(page_changes):
    envelope = {"status": "ready", "generation": 7, "fresh": True,
                "stale": False, "refreshing": False,
                "input_fingerprint": "a" * 64, "rule_fingerprint": "b" * 64}
    trace = build_read_trace(summary=envelope,
                             page={**envelope, **page_changes,
                                   "reason_codes": ["MATCHING_REVIEW_RESOLVED"]})
    assert trace["trace_status"] == "incomplete"
    assert "SNAPSHOT_LINEAGE_INCOMPLETE" in trace["reason_codes"]


def test_trace_sanitizes_malformed_reason_codes_and_rejects_private_sample_fields():
    envelope = {"status": "ready", "generation": 1, "fresh": True,
                "stale": False, "refreshing": False,
                "input_fingerprint": "a" * 64, "rule_fingerprint": "b" * 64}
    trace = build_read_trace(summary=envelope,
                             page={**envelope, "reason_codes": ["SENTINEL_PRIVATE_REASON", "valid"]})
    assert trace["trace_status"] == "complete"
    assert trace["reason_codes"] == ["TRACE_REASON_CODES_INVALID"]
    assert "SENTINEL" not in json.dumps(trace)
    sanitized = build_read_trace(summary=envelope,
                                 page={**envelope, "reason_codes": []},
                                 sample={"stage": "detail_read", "elapsed_ms": 1,
                                         "customer_name": "SENTINEL"})
    assert "customer_name" not in json.dumps(sanitized)
    assert "SENTINEL" not in json.dumps(sanitized)


def test_synthetic_query_plan_uses_fixture_index_without_product_database():
    result = query_plan_probe(200)
    assert result["row_count"] == 200
    assert result["plan_steps"] > 0
    assert result["uses_index"] is True
    assert result["stage"] == "query_plan"


def test_benchmark_reports_synthetic_scope_bounded_page_and_memory():
    result = run(120, 2)
    assert result["measurement_scope"] == "synthetic_only_no_product_sla_claim"
    assert result["page_items"] == 20 and result["page_total"] == 120
    assert result["query_plan"]["uses_index"] is True
    assert result["metrics"]["projection"]["samples"] == 2
    assert result["metrics"]["page_serialize"]["p95_ms"] is not None
    assert result["metrics"]["projection_memory"]["peak_memory_bytes"] > 0
    serialized = json.dumps(result)
    assert "synthetic-event-" not in serialized
    assert "synthetic-card-" not in serialized
    assert "SYN-" not in serialized
