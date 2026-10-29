"""Synthetic regression checks for the R4 CardFlow cache benchmark."""
from tools.benchmark_card_flow_cache import run


def test_card_flow_cache_benchmark_measures_real_compute_and_memo_hit():
    result = run(repeats=2, rows=12)
    assert result["scope"] == "synthetic_only_no_customer_source_access"
    assert result["measurement_kind"].startswith("actual_card_flow_compute")
    assert result["optimization_status"] == "baseline_only_no_code_change"
    assert result["cache_report_bytes"]["max"] > 0
    assert result["query_count_per_call"]["cold"] > 0
    assert result["query_count_per_call"]["warm"] == result["query_count_per_call"]["cold"]
    assert result["query_count_per_call"]["request_memo_hit"] == 0
    for stage in ("match_mail", "payment_events", "portal_extend", "reference_load"):
        assert result["expensive_stage_calls_per_call"]["cold"][stage] == 1
        assert result["expensive_stage_calls_per_call"]["warm"][stage] == 0
        assert result["expensive_stage_calls_per_call"]["request_memo_hit"][stage] == 0
    for distribution in result["latency_ms"].values():
        assert distribution["samples"] == 2
        assert distribution["p50"] is not None and distribution["p95"] is not None
