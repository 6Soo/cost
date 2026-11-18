"""Read-only summing of per-port request counters, including honesty markers."""
import json
from datetime import datetime, timedelta, timezone

from app.http_request_counts import RequestCounts
from tools.http_request_metrics_summary import main, summarize

STAMP = datetime(2026, 11, 17, 3, 15, tzinfo=timezone.utc)


def _clock():
    return STAMP


def _clean_snapshot(tmp_path, name):
    """A snapshot that carries real evidence of a clean stop.

    `begin_shutdown()` is what the launcher calls after the socket is closed,
    so this fixture exercises the same contract the product uses. A close
    without it would produce an unclean snapshot, which is not what a test
    named "clean" should be handed.
    """
    counter = RequestCounts(tmp_path / name, start_flusher=False, wall_clock=_clock)
    counter.observe_finish(counter.observe_begin("/api/customer-314", "GET"), 200)
    counter.begin_shutdown()
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
    stopped.begin_shutdown()
    assert stopped.close()

    report = summarize([tmp_path / "http-8751.json", tmp_path / "http-8752.json"])
    assert report["process_count"] == 2
    assert report["total_started"] == 4
    assert report["routes"]["api"]["GET"]["started"] == 3
    assert report["routes"]["receipts"]["POST"]["started"] == 1
    assert report["last_saved_utc"] == "2026-11-17T03:15:00Z"
    # The 8751 process never stopped, so its snapshot is not a final figure;
    # 8752 stopped cleanly and contributes its counts to the sum regardless.
    assert report["live_process_snapshot_count"] == 1
    assert report["unclean_stop_snapshot_count"] == 1
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


def _state(**overrides):
    """A minimal, internally consistent snapshot for contract testing."""
    row = {
        "started": 2,
        "completed": {"1xx": 0, "2xx": 2, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0},
        "aborted": 0,
        "aborted_by_status_class": {k: 0 for k in
                                    ("1xx", "2xx", "3xx", "4xx", "5xx", "other")},
        "request_body_bytes": 0, "response_body_bytes": 0, "unfinished": 0,
    }
    state = {
        "schema_version": "http-request-counts-v1",
        "saved_at_utc": "2026-11-17T03:00:00Z",
        "process_started_at_utc": "2026-11-17T02:00:00Z",
        "retention_hours": 9600,
        "possible_loss": {"window_count": 0, "latest_window": None},
        "counts_reset": {"count": 0, "last_reset_utc": None, "reason": None},
        "persistence_failure_count": 0,
        "in_flight_count": 0,
        "unrecorded_open_requests": False,
        "is_open_process": False,
        "clean_shutdown": True,
        "stopped_utc": "2026-11-17T02:30:00Z",
        "shutdown_utc": "2026-11-17T02:30:00Z",
        "uptime_seconds": 3600,
        "buckets": {"2026-11-17T02:00:00Z": {"api": {"GET": row}}},
    }
    state.update(overrides)
    return state


def _write(tmp_path, name, state):
    path = tmp_path / name
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_a_clean_stop_needs_positive_evidence_before_anything_is_complete(tmp_path):
    report = summarize([_write(tmp_path, "http-8751.json", _state())])
    assert report["complete"] is True
    assert report["unclean_stop_snapshot_count"] == 0
    assert report["total_started"] == 2


def test_an_undeclared_stop_is_not_complete(tmp_path):
    """This is what a startup failure produces: no begin_shutdown, no stop time."""
    path = _write(tmp_path, "http-8751.json", _state(
        clean_shutdown=False, shutdown_utc=None, stopped_utc=None))
    report = summarize([path])
    assert report["complete"] is False
    assert report["unclean_stop_snapshot_count"] == 1


def test_a_false_clean_flag_with_a_stop_time_still_is_not_complete(tmp_path):
    path = _write(tmp_path, "http-8751.json", _state(
        clean_shutdown=False, stopped_utc="2026-11-17T02:30:00Z", shutdown_utc=None))
    report = summarize([path])
    assert report["complete"] is False
    assert report["rejected_snapshots"] == []


def test_a_missing_clean_flag_is_not_read_as_clean(tmp_path):
    """An older or foreign file with a stop time but no flag is not trusted."""
    state = _state()
    del state["clean_shutdown"]
    path = _write(tmp_path, "http-8751.json", state)
    report = summarize([path])
    assert report["complete"] is False
    assert report["rejected_snapshots"] == [
        {"file": "http-8751.json", "rule": "stop_time_without_clean"}]


def test_clean_without_a_stop_time_is_rejected(tmp_path):
    path = _write(tmp_path, "http-8751.json", _state(
        clean_shutdown=True, shutdown_utc=None, stopped_utc=None))
    assert summarize([path])["rejected_snapshots"] == [
        {"file": "http-8751.json", "rule": "clean_without_stop_time"}]


def test_a_stop_time_after_the_snapshot_is_rejected(tmp_path):
    path = _write(tmp_path, "http-8751.json", _state(
        stopped_utc="2026-11-17T04:00:00Z", shutdown_utc="2026-11-17T04:00:00Z"))
    assert summarize([path])["rejected_snapshots"] == [
        {"file": "http-8751.json", "rule": "stop_after_save"}]


def test_a_stop_time_before_the_process_start_is_rejected(tmp_path):
    path = _write(tmp_path, "http-8751.json", _state(
        stopped_utc="2026-11-17T01:00:00Z", shutdown_utc="2026-11-17T01:00:00Z"))
    assert summarize([path])["rejected_snapshots"] == [
        {"file": "http-8751.json", "rule": "stop_before_start"}]


def test_a_stop_time_without_the_clean_flag_is_rejected(tmp_path):
    state = _state(clean_shutdown=None, stopped_utc="2026-11-17T02:30:00Z")
    path = _write(tmp_path, "http-8751.json", state)
    assert summarize([path])["rejected_snapshots"] == [
        {"file": "http-8751.json", "rule": "stop_time_without_clean"}]


def test_clean_is_revoked_when_a_request_begins_after_close(tmp_path):
    counter = RequestCounts(tmp_path / "http-8751.json", start_flusher=False, wall_clock=_clock)
    counter.observe_finish(counter.observe_begin("/api/customer-314", "GET"), 200)
    counter.begin_shutdown()
    assert counter.close()
    assert summarize([tmp_path / "http-8751.json"])["complete"] is True
    # A connection kept alive delivers one more request in the stop gap.
    counter.observe_begin("/api/customer-315", "GET")
    report = summarize([tmp_path / "http-8751.json"])
    assert report["complete"] is False
    assert report["unclean_stop_snapshot_count"] == 1
    assert report["total_started"] == 2


def test_every_port_must_stop_cleanly_for_the_sum_to_be_complete(tmp_path):
    one = _clean_snapshot(tmp_path, "http-8751.json")
    two = _write(tmp_path, "http-8752.json", _state(
        clean_shutdown=False, shutdown_utc=None, stopped_utc=None))
    report = summarize([one, two])
    assert report["process_count"] == 2
    assert report["complete"] is False
    assert report["unclean_stop_snapshot_count"] == 1


def test_a_restart_keeps_the_earlier_abrupt_stop_visible(tmp_path):
    """The clean second generation does not erase the first one's loss window."""
    path = tmp_path / "http-8751.json"
    first = RequestCounts(path, start_flusher=False, wall_clock=_clock)
    first.observe_finish(first.observe_begin("/api/customer-314", "GET"), 200)
    assert first.flush()  # abrupt: never closed
    second = RequestCounts(path, start_flusher=False,
                           wall_clock=lambda: STAMP + timedelta(minutes=5))
    second.begin_shutdown()
    assert second.close()
    report = summarize([path])
    assert report["complete"] is False
    assert report["possible_loss_window_count"] == 1


def _generation(path, moment, requests, *, clean=True):
    """Run one process lifetime against `path` and return the saved state."""
    counter = RequestCounts(path, start_flusher=False, wall_clock=lambda: moment)
    for _ in range(requests):
        counter.observe_finish(counter.observe_begin("/api/customer-314", "GET"), 200)
    if clean:
        counter.begin_shutdown()
        assert counter.close()
    else:
        assert counter.flush()  # abrupt: flushed but never stopped deliberately
    return json.loads(path.read_text(encoding="utf-8"))


def _started(state):
    return sum(values["started"] for routes in state["buckets"].values()
               for methods in routes.values() for values in methods.values())


def test_each_generation_reports_its_own_stop_time(tmp_path):
    """A previous clean stop must not be reused as this generation's stop."""
    path = tmp_path / "http-8751.json"
    first_at = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
    second_at = datetime(2026, 11, 18, 1, 5, tzinfo=timezone.utc)
    first = _generation(path, first_at, 1)
    assert first["stopped_utc"] == "2026-11-18T01:00:00Z"

    second = _generation(path, second_at, 1)
    assert second["restart_count"] == 1
    assert second["clean_shutdown"] is True
    assert second["stopped_utc"] == "2026-11-18T01:05:00Z"
    assert second["shutdown_utc"] == "2026-11-18T01:05:00Z"
    assert second["saved_at_utc"] == "2026-11-18T01:05:00Z"


def test_clean_a_then_b_then_c_accumulates_without_undercounting(tmp_path):
    path = tmp_path / "http-8751.json"
    base = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
    for generation in range(3):
        state = _generation(path, base + timedelta(minutes=5 * generation), 1)
        assert _started(state) == generation + 1
        assert state["stopped_utc"] == (
            base + timedelta(minutes=5 * generation)).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = summarize([path])
    assert report["rejected_snapshots"] == []
    assert report["complete"] is True
    assert report["total_started"] == 3


def test_an_abrupt_generation_then_a_clean_one_still_reports_loss(tmp_path):
    path = tmp_path / "http-8751.json"
    base = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
    _generation(path, base, 1, clean=False)
    state = _generation(path, base + timedelta(minutes=5), 1)
    assert state["clean_shutdown"] is True
    assert state["stopped_utc"] == "2026-11-18T01:05:00Z"
    assert state["possible_loss"]["window_count"] == 1
    assert state["possible_loss"]["latest_window"]["reason"] == "unclean_stop"
    report = summarize([path])
    assert report["complete"] is False   # the earlier loss is still visible
    assert report["total_started"] == 2  # and the counts are still summed


def test_a_stop_timestamp_is_the_form_the_reader_accepts(tmp_path):
    """Producer -> reader: the stored stop time must parse and pass the checks."""
    path = tmp_path / "http-8751.json"
    state = _generation(path, STAMP, 1)
    assert state["stopped_utc"].endswith("Z")
    assert len(state["stopped_utc"]) == len("2026-11-18T01:00:00Z")
    report = summarize([path])
    assert report["rejected_snapshots"] == []
    assert report["complete"] is True


def test_a_second_clean_port_adds_to_a_clean_first_port(tmp_path):
    base = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
    one = _generation(tmp_path / "http-8751.json", base, 2)
    report_one = summarize([tmp_path / "http-8751.json"])
    assert report_one["complete"] is True and report_one["total_started"] == 2

    other = RequestCounts(tmp_path / "http-8752.json", start_flusher=False,
                          wall_clock=lambda: base)
    other.observe_finish(other.observe_begin("/receipts", "POST"), 201)
    other.begin_shutdown()
    assert other.close()
    report = summarize([tmp_path / "http-8751.json", tmp_path / "http-8752.json"])
    assert report["process_count"] == 2
    assert report["complete"] is True
    assert report["total_started"] == 3
