"""Synthetic regression checks for the R4 CardFlow cache benchmark."""
from tools.benchmark_card_flow_cache import run


def test_card_flow_cache_benchmark_measures_real_compute_and_memo_hit():
    result = run(repeats=2, rows=12)
    assert result["scope"] == "synthetic_only_no_customer_source_access_snapshot_service_disabled"
    assert result["measurement_kind"].startswith("actual_card_flow_compute")
    assert result["optimization_status"] == "synthetic_duplicate_query_consolidation"
    assert result["cache_report_bytes"]["max"] > 0
    assert result["query_count_per_call"]["cold"] > 0
    assert result["query_count_per_call"]["warm"] == result["query_count_per_call"]["cold"]
    assert result["query_count_per_call"]["request_memo_hit"] == 0
    assert result["open_ids_equivalent_to_existing_helper"] is True
    assert result["expensive_stage_calls_per_call"]["request_memo_hit"]["snapshot_service"] == 0
    for stage in ("match_mail", "payment_events", "portal_extend", "reference_load"):
        assert result["expensive_stage_calls_per_call"]["cold"][stage] == 1
        assert result["expensive_stage_calls_per_call"]["warm"][stage] == 0
        assert result["expensive_stage_calls_per_call"]["request_memo_hit"][stage] == 0
    for distribution in result["latency_ms"].values():
        assert distribution["samples"] == 2
        assert distribution["p50"] is not None and distribution["p95"] is not None


def test_benchmark_restores_environment_and_process_mail_memo(monkeypatch):
    from app import ota_mail
    monkeypatch.setenv("WEBLEDGER_OTA_SOURCES", "sentinel-source-config")
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "sentinel-unified-config")
    ota_mail._MAIL_SIDE_MEMO.clear()
    ota_mail._MAIL_SIDE_MEMO["sentinel"] = ("preserved",)
    run(repeats=1, rows=2)
    assert __import__("os").environ["WEBLEDGER_OTA_SOURCES"] == "sentinel-source-config"
    assert __import__("os").environ["WEBLEDGER_UNIFIED_DB"] == "sentinel-unified-config"
    assert ota_mail._MAIL_SIDE_MEMO == {"sentinel": ("preserved",)}
