"""Read-only summing of per-port request counters, including honesty markers."""
import json
from datetime import datetime, timedelta, timezone

from app.http_request_counts import RequestCounts
from tools.http_request_metrics_summary import main, summarize

STAMP = datetime(2026, 11, 17, 3, 15, tzinfo=timezone.utc)


def _clock():
    return STAMP


def _clean_snapshot(tmp_path, name):
    counter = RequestCounts(tmp_path / name, start_flusher=False, wall_clock=_clock)
    counter.observe_finish(counter.observe_begin("/api/customer-314", "GET"), 200)
    assert counter.flush()
    assert counter.close()
    return tmp_path / name


def test_two_ports_sum_totals_and_mark_the_live_one_as_not_final(tmp_path):
    live = RequestCounts(tmp_path / "http-8751.json", start_flusher=False, wall_clock=_clock)
    for _ in range(3):
        live.observe_finish(live.observe_begin("/api/customer-314", "GET"), 200)
    assert live.flush()  # still running: this is a live reading, not a final one

    stopped = RequestCounts(tmp_path / "http-8752.json", start_flusher=False, wall_clock=_clock)
    stopped.observe_finish(stopped.observe_begin("/receipts", "POST"), 201)
    assert stopped.close()

    report = summarize([tmp_path / "http-8751.json", tmp_path / "http-8752.json"])
    assert report["process_count"] == 2
    assert report["total_started"] == 4
    assert report["routes"]["api"]["GET"]["started"] == 3
    assert report["routes"]["receipts"]["POST"]["started"] == 1
    assert report["last_saved_utc"] == "2026-11-17T03:15:00Z"
    # The 8751 process never stopped, so its snapshot is not a final figure.
    assert report["live_process_snapshot_count"] == 1
    assert report["complete"] is False


def test_empty_input_is_not_a_zero_total(tmp_path):
    assert summarize([])["complete"] is False


def test_counts_saved_after_a_flush_are_reported_as_unrecorded(tmp_path):
    counter = RequestCounts(tmp_path / "http-8751.json", start_flusher=False, wall_clock=_clock)
    counter.observe_finish(counter.observe_begin("/api/customer-314", "GET"), 200)
    assert counter.flush()
    # This request finishes in memory only: it is not in the file.
    counter.observe_finish(counter.observe_begin("/api/customer-315", "GET"), 200)
    report = summarize([tmp_path / "http-8751.json"])
    assert report["total_started"] == 1
    assert report["in_flight_count"] == 0
    assert report["complete"] is False  # the process is still live
    counter.close()


def test_close_with_a_request_in_flight_is_not_a_clean_stop(tmp_path):
    path = tmp_path / "http-8751.json"
    counter = RequestCounts(path, start_flusher=False, wall_clock=_clock)
    observation = counter.observe_begin("/api/customer-314", "GET")
    counter.begin_shutdown()
    assert counter.close()
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["clean_shutdown"] is False
    assert state["shutdown_utc"] is None
    assert state["stopped_utc"] == "2026-11-17T03:15:00Z"
    assert state["in_flight_count"] == 1
    report = summarize([path])
    assert report["complete"] is False
    assert report["in_flight_count"] == 1
    # The response finishing after close is still persisted, not lost.
    assert counter.observe_finish(observation, 200)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["in_flight_count"] == 0
    # The file already said a request was open at the stop, so it stays honest
    # about that rather than retroactively calling the run clean.
    assert saved["clean_shutdown"] is False


def test_restart_after_stop_with_in_flight_records_a_window(tmp_path):
    path = tmp_path / "http-8751.json"
    counter = RequestCounts(path, start_flusher=False, wall_clock=_clock)
    counter.observe_begin("/api/customer-314", "GET")
    counter.begin_shutdown()
    assert counter.close()
    restarted = RequestCounts(path, start_flusher=False,
                             wall_clock=lambda: STAMP + timedelta(hours=1))
    assert restarted.flush()
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["possible_loss"]["window_count"] == 1
    assert state["possible_loss"]["latest_window"]["reason"] == (
        "shutdown_with_requests_in_flight")


def test_unreadable_and_corrupt_snapshots_are_named_and_block_completeness(tmp_path):
    good = _clean_snapshot(tmp_path, "http-8751.json")
    corrupt = tmp_path / "http-8790.json"
    corrupt.write_text("{not json", encoding="utf-8")
    missing = tmp_path / "http-9000.json"
    report = summarize([good, corrupt, missing])
    assert report["process_count"] == 1
    assert report["corrupt_snapshots"] == ["http-8790.json"]
    assert report["unreadable_snapshots"] == ["http-9000.json"]
    assert report["complete"] is False
    assert report["total_started"] == 1


def test_hostile_snapshot_is_rejected_without_echoing_any_of_its_values(tmp_path):
    hostile = tmp_path / "hostile.json"
    hostile.write_text(json.dumps({
        "schema_version": "http-request-counts-v1",
        "possible_loss": {"window_count": "PROMPT_INJECT_SECRET"},
        "counts_reset": {"count": -9, "reason": "/home/private/path"},
        "persistence_failure_count": True,
        "buckets": {"2026-11-17T03:00:00Z": {
            "CUSTOMER_ID_12345": {"GET": {"started": -5}},
        }},
    }), encoding="utf-8")
    report = summarize([hostile])
    rendered = json.dumps(report, ensure_ascii=False)
    for value in ("PROMPT_INJECT_SECRET", "/home/private/path",
                  "CUSTOMER_ID_12345", "-9", "-5"):
        assert value not in rendered
    assert report["complete"] is False
    assert report["rejected_snapshots"] == [{"file": "hostile.json", "rule": "saved_at"}]
    assert report["total_started"] == 0


def test_unknown_route_or_negative_counter_rejects_the_whole_snapshot(tmp_path):
    real = _clean_snapshot(tmp_path, "http-8751.json")
    state = json.loads(real.read_text(encoding="utf-8"))
    route = next(iter(state["buckets"]["2026-11-17T03:00:00Z"]))
    row = state["buckets"]["2026-11-17T03:00:00Z"][route]["GET"]
    row["started"] = -1
    real.write_text(json.dumps(state), encoding="utf-8")
    report = summarize([real])
    assert report["total_started"] == 0
    assert report["rejected_snapshots"] == [{"file": "http-8751.json", "rule": "started"}]
    assert report["complete"] is False


def test_directory_argument_expands_counter_files_only(tmp_path):
    _clean_snapshot(tmp_path, "http-8751.json")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    from tools.http_request_metrics_summary import _candidate_paths
    assert [path.name for path in _candidate_paths([tmp_path])] == ["http-8751.json"]


def test_cli_exits_nonzero_when_the_total_is_not_final(tmp_path, capsys):
    live = RequestCounts(tmp_path / "http-8751.json", start_flusher=False, wall_clock=_clock)
    live.observe_finish(live.observe_begin("/api/customer-314", "GET"), 200)
    assert live.flush()
    assert main([str(tmp_path / "http-8751.json")]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["complete"] is False
    assert printed["live_process_snapshot_count"] == 1
    live.close()


def test_cli_exits_zero_for_a_clean_total_and_echoes_no_request_contents(tmp_path, capsys):
    clean = _clean_snapshot(tmp_path, "http-8751.json")
    assert main([str(clean), "--pretty"]) == 0
    out = capsys.readouterr().out
    printed = json.loads(out)
    assert printed["complete"] is True
    assert printed["total_started"] == 1
    # Nothing identifying the caller's path or the request is echoed.
    assert "/api/customer-314" not in out
    assert "customer-314" not in out

def test_inconsistent_row_balances_reject_the_snapshot(tmp_path):
    """A row claiming more outcomes than starts cannot be summed honestly."""
    state = {
        "schema_version": "http-request-counts-v1",
        "saved_at_utc": "2026-11-17T03:00:00Z",
        "retention_hours": 10,
        "possible_loss": {"window_count": 0, "latest_window": None},
        "counts_reset": {"count": 0, "last_reset_utc": None, "reason": None},
        "persistence_failure_count": 0,
        "in_flight_count": 0,
        "stopped_utc": "2026-11-17T03:00:00Z",
        "clean_shutdown": True,
        "shutdown_utc": "2026-11-17T03:00:00Z",
        "unrecorded_open_requests": False,
        "is_open_process": False,
        "uptime_seconds": 5,
        "buckets": {"2026-11-17T03:00:00Z": {"api": {"GET": {
            "started": 2,
            "completed": {"1xx": 0, "2xx": 99, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0},
            "aborted": 0,
            "aborted_by_status_class": {k: 0 for k in
                                       ("1xx", "2xx", "3xx", "4xx", "5xx", "other")},
            "request_body_bytes": 0, "response_body_bytes": 0, "unfinished": 0,
        }}}},
    }
    path = tmp_path / "http-8751.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    report = summarize([path])
    assert report["rejected_snapshots"] == [{"file": "http-8751.json", "rule": "row_balance"}]
    assert report["complete"] is False
    assert report["total_started"] == 0


def test_unhashable_reset_reason_is_rejected_not_raised(tmp_path):
    """A list where a reason string belongs used to raise TypeError."""
    state = {
        "schema_version": "http-request-counts-v1",
        "saved_at_utc": "2026-11-17T03:00:00Z",
        "retention_hours": 10,
        "possible_loss": {"window_count": 0, "latest_window": None},
        "counts_reset": {"count": 0, "last_reset_utc": None, "reason": ["corrupt"]},
        "persistence_failure_count": 0,
        "in_flight_count": 0,
        "uptime_seconds": 5,
        "buckets": {},
    }
    path = tmp_path / "http-8790.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    report = summarize([path])
    assert report["rejected_snapshots"] == [
        {"file": "http-8790.json", "rule": "counts_reset_reason"}]
    assert report["complete"] is False
