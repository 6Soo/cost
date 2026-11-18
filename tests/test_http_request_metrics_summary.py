"""Read-only summing of per-port request counters, including honesty markers."""
import json

from app.http_request_counts import RequestCounts
from tools.http_request_metrics_summary import main, summarize


def _clock():
    from datetime import datetime, timezone
    return datetime(2026, 11, 17, 3, 15, tzinfo=timezone.utc)


def _clean_snapshot(tmp_path, name):
    counter = RequestCounts(tmp_path / name, start_flusher=False, wall_clock=_clock)
    counter.observe_finish(counter.observe_begin("/api/customer-314", "GET"), 200)
    assert counter.flush()
    assert counter.close()
    return tmp_path / name


def test_two_ports_sum_and_preserve_markers(tmp_path):
    first = RequestCounts(tmp_path / "http-8751.json", start_flusher=False,
                          wall_clock=_clock)
    for _ in range(3):
        first.observe_finish(first.observe_begin("/api/customer-314", "GET"), 200)
    # An abrupt stop: flushed, never closed. The next start is what records
    # the window, so it is reopened and left alone before the snapshot is read.
    assert first.flush()
    resumed = RequestCounts(tmp_path / "http-8751.json", start_flusher=False,
                            wall_clock=_clock)
    assert resumed.flush()
    assert resumed.close()

    second = RequestCounts(tmp_path / "http-8752.json", start_flusher=False,
                           wall_clock=_clock)
    second.observe_finish(second.observe_begin("/receipts", "POST"), 201)
    assert second.close()

    report = summarize([tmp_path / "http-8751.json", tmp_path / "http-8752.json"])
    assert report["process_count"] == 2
    assert report["source_count"] == 2
    assert report["total_started"] == 4
    assert report["routes"]["api"]["GET"]["started"] == 3
    assert report["routes"]["receipts"]["POST"]["started"] == 1
    assert report["possible_loss_window_count"] == 1
    assert report["complete"] is False  # a loss window means "not final yet"


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


def test_directory_argument_expands_counter_files_only(tmp_path):
    _clean_snapshot(tmp_path, "http-8751.json")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    from tools.http_request_metrics_summary import _candidate_paths
    assert [path.name for path in _candidate_paths([tmp_path])] == ["http-8751.json"]


def test_cli_exits_nonzero_when_the_total_is_not_final(tmp_path, capsys):
    path = tmp_path / "http-8751.json"
    path.write_text(json.dumps({"schema_version": "http-request-counts-v1",
                                "possible_loss": {"window_count": 2},
                                "buckets": {}}), encoding="utf-8")
    assert main([str(path)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["possible_loss_window_count"] == 2
    assert printed["complete"] is False


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
