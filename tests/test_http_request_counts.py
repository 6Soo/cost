import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path

from app.http_request_counts import RequestCounts, _hour_bucket, route_id_for_path
from app import http_request_counts as _counts_module


class Clock:
    def __init__(self, wall=None, monotonic=10.0):
        self.wall = wall or datetime(2026, 11, 17, 3, 15, tzinfo=timezone.utc)
        self.monotonic = monotonic
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            return self.wall

    def tick(self, seconds=1):
        with self.lock:
            self.wall += timedelta(seconds=seconds)
            self.monotonic += seconds

    def monotonic_now(self):
        with self.lock:
            return self.monotonic


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def route_counts(state, route, method, bucket="2026-11-17T03:00:00Z"):
    return state["buckets"][bucket][route][method]


def test_routes_collapse_dynamic_paths_and_methods_to_fixed_ids():
    assert route_id_for_path("/cards/transaction-999?email=person@example.test") == "cards"
    assert route_id_for_path("/healthz?token=secret") == "health"
    assert route_id_for_path("/assets/photo-name.jpg") == "assets"
    assert route_id_for_path("/unknown/123?customer=customer-123") == "unknown"


def test_served_prefixes_and_api_suffixes_fall_into_fixed_ids_not_unknown():
    assert route_id_for_path("/readyz") == "health"
    assert route_id_for_path("/static/css/receipt_workflow.css") == "assets"
    assert route_id_for_path("/access/me") == "auth"
    assert route_id_for_path("/api/imports/upload-batch") != "unknown"
    assert route_id_for_path("/api/trips?limit=20") == "ledger"
    assert route_id_for_path("/api/receipts/image") == "receipts"
    for prefix in ("/board", "/review", "/rows", "/tsv", "/import", "/export",
                   "/rules", "/expense", "/reserve-links", "/download", "/ui"):
        assert route_id_for_path(prefix + "?trip=314") == "ledger", prefix
    assert route_id_for_path("/api/customer-314") == "api"
    assert route_id_for_path("/vendor-private/123") == "unknown"


def test_clean_shutdown_is_not_reported_as_possible_loss(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    first = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                          monotonic_clock=clock.monotonic_now)
    request = first.observe_begin("/api/synthetic", "GET")
    assert first.observe_finish(request, 200)
    assert first.close()
    assert load(path)["shutdown_utc"] == "2026-11-17T03:15:00Z"

    clock.tick(600)
    restarted = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                              monotonic_clock=clock.monotonic_now)
    assert restarted.flush()
    state = load(path)
    assert state["possible_loss"]["window_count"] == 0
    assert state["possible_loss"]["latest_window"] is None
    assert state["restart_count"] == 1
    assert route_counts(state, "api", "GET")["completed"]["2xx"] == 1
    restarted.close()


def test_abrupt_stop_still_reports_a_possible_loss_window(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    first = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                          monotonic_clock=clock.monotonic_now)
    request = first.observe_begin("/api/synthetic", "GET")
    assert first.observe_finish(request, 200)
    assert first.flush()  # flushed, but the process was never allowed to stop itself
    clock.tick(45)
    restarted = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                              monotonic_clock=clock.monotonic_now)
    assert restarted.flush()
    state = load(path)
    assert state["shutdown_utc"] is None
    assert state["possible_loss"]["window_count"] == 1
    window = state["possible_loss"]["latest_window"]
    assert window["seconds"] == 45 and window["reason"] == "unclean_stop"
    restarted.close()


def test_corrupt_snapshot_is_recorded_instead_of_reading_as_zero_requests(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    first = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                          monotonic_clock=clock.monotonic_now)
    request = first.observe_begin("/api/synthetic", "GET")
    assert first.observe_finish(request, 200)
    assert first.close()
    path.write_text('{"schema_version": "http-request-counts-v1", "buckets": {',
                    encoding="utf-8")

    restarted = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                              monotonic_clock=clock.monotonic_now)
    assert restarted.flush()
    state = load(path)
    assert state["counts_reset"]["count"] == 1
    assert state["counts_reset"]["reason"] == "corrupt"
    assert state["counts_reset"]["last_reset_utc"] == "2026-11-17T03:15:00Z"
    assert state["possible_loss"]["window_count"] == 1
    assert state["possible_loss"]["latest_window"]["seconds"] is None
    assert state["persistence_failure_count"] == 1
    restarted.close()


def test_reset_marker_survives_a_later_snapshot(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    path.write_text("not json at all", encoding="utf-8")
    first = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                          monotonic_clock=clock.monotonic_now)
    assert first.flush()
    first.close()
    # A second normal-looking restart must keep saying counts were reset once.
    second = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    assert second.flush()
    assert load(path)["counts_reset"]["count"] == 1
    assert load(path)["counts_reset"]["reason"] == "corrupt"
    second.close()


def test_standard_library_error_statuses_are_counted_as_http_errors(tmp_path):
    clock = Clock()
    path = tmp_path / "counts.json"
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    for status in (HTTPStatus.NOT_FOUND, HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE,
                   HTTPStatus.NOT_IMPLEMENTED, True):
        counts.observe_finish(counts.observe_begin("/api/synthetic", "GET"), status)
    assert counts.flush()
    completed = route_counts(load(path), "api", "GET")["completed"]
    assert completed["4xx"] == 2 and completed["5xx"] == 1 and completed["other"] == 1
    counts.close()


def test_start_finish_and_abort_are_counted_once_with_actual_byte_totals(tmp_path):
    path = tmp_path / "request-counts.json"
    clock = Clock()
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    request = counts.observe_begin("/api/invoice-314?auth=credential", "get")
    assert counts.observe_request_read(request, 7)
    assert counts.observe_response_write(request, 3)
    assert counts.observe_finish(request, 404)
    assert not counts.observe_finish(request, 200)
    assert not counts.observe_abort(request)

    denied = counts.observe_begin("/login?user=person@example.test", "POST")
    assert counts.observe_finish(denied, 401)
    failed = counts.observe_begin("/private/secret-row", "M-SEARCH")
    assert counts.observe_abort(failed, 500)
    assert counts.flush()

    state = load(path)
    api = route_counts(state, "api", "GET")
    assert api["started"] == 1
    assert api["completed"]["4xx"] == 1
    assert api["request_body_bytes"] == 7
    assert api["response_body_bytes"] == 3
    assert api["unfinished"] == 0
    auth = route_counts(state, "auth", "POST")
    assert auth["started"] == 1 and auth["completed"]["4xx"] == 1
    unknown = route_counts(state, "unknown", "other")
    assert unknown["started"] == 1 and unknown["aborted"] == 1
    assert unknown["aborted_by_status_class"]["5xx"] == 1
    payload = path.read_text(encoding="utf-8")
    for private in ("invoice-314", "credential", "person@example.test", "secret-row", "M-SEARCH"):
        assert private not in payload
    counts.close()


def test_head_204_stream_abort_and_exception_status_keep_real_bytes_only(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    head = counts.observe_begin("/cards", "HEAD")
    assert counts.observe_finish(head, 204)
    stream = counts.observe_begin("/upload/session-88", "POST")
    assert counts.observe_request_read(stream, 4)
    assert counts.observe_response_write(stream, 11)
    assert counts.observe_abort(stream, 200)
    exception_response = counts.observe_begin("/ota", "GET")
    assert counts.observe_finish(exception_response, 500)
    assert counts.flush()
    state = load(path)
    assert route_counts(state, "cards", "HEAD")["response_body_bytes"] == 0
    upload = route_counts(state, "upload", "POST")
    assert upload["aborted"] == 1 and upload["aborted_by_status_class"]["2xx"] == 1
    assert upload["request_body_bytes"] == 4 and upload["response_body_bytes"] == 11
    assert route_counts(state, "ota", "GET")["completed"]["5xx"] == 1
    counts.close()


def test_concurrent_requests_keep_bounded_aggregate_dimensions(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)

    def worker():
        for index in range(40):
            request = counts.observe_begin(f"/unknown/customer-{index}?id={index}", "GET")
            counts.observe_finish(request, 200)

    workers = [threading.Thread(target=worker) for _ in range(12)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join()

    assert counts.flush()
    state = load(path)
    unknown = route_counts(state, "unknown", "GET")
    assert unknown["started"] == 480
    assert unknown["completed"]["2xx"] == 480
    assert unknown["unfinished"] == 0
    assert len(state["buckets"]) == 1
    assert set(state["buckets"][next(iter(state["buckets"]))]) == {"unknown"}
    contents = path.read_text(encoding="utf-8")
    assert "customer-" not in contents and '"id"' not in contents
    counts.close()


def test_restart_resumes_cumulative_buckets_without_double_adding(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    first = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                          monotonic_clock=clock.monotonic_now)
    request = first.observe_begin("/receipts", "POST")
    assert first.observe_finish(request, 201)
    clock.tick(9)
    assert first.flush()
    first.close()

    clock.tick(3)
    restarted = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                              monotonic_clock=clock.monotonic_now)
    next_request = restarted.observe_begin("/receipts", "POST")
    assert restarted.observe_finish(next_request, 201)
    assert restarted.flush()
    state = load(path)
    receipts = route_counts(state, "receipts", "POST")
    assert receipts["started"] == 2
    assert receipts["completed"]["2xx"] == 2
    assert state["restart_count"] == 1
    # The earlier process stopped itself, so the 3 s it stayed down is idle
    # time, not a window in which counts could have been dropped.
    assert state["possible_loss"]["window_count"] == 0
    assert state["possible_loss"]["latest_window"] is None
    assert state["uptime_seconds"] >= 9
    restarted.close()


def test_periodic_flush_and_storage_failure_never_raise_into_request(tmp_path):
    path = tmp_path / "periodic.json"
    clock = Clock()
    counts = RequestCounts(path, flush_interval_seconds=0.02, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    request = counts.observe_begin("/health", "GET")
    assert counts.observe_finish(request, 200)
    deadline = time.monotonic() + 2
    while not path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.is_file()
    assert route_counts(load(path), "health", "GET")["completed"]["2xx"] == 1
    counts.close()

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    broken = RequestCounts(blocker / "counts.json", start_flusher=False)
    request = broken.observe_begin("/api", "GET")
    assert broken.observe_finish(request, 200)
    assert not broken.flush()
    assert broken.persistence_failure_count == 1
    assert not broken.close()


def test_flush_swallows_clock_failures(tmp_path):
    path = tmp_path / "clock-failure.json"
    calls = 0

    def flaky_wall_clock():
        nonlocal calls
        calls += 1
        if calls <= 4:
            return datetime(2026, 11, 17, 3, 15, tzinfo=timezone.utc)
        raise OSError("synthetic clock failure")

    counts = RequestCounts(path, start_flusher=False, wall_clock=flaky_wall_clock)
    request = counts.observe_begin("/health", "GET")
    assert counts.observe_finish(request, 200)
    assert not counts.flush()
    assert counts.persistence_failure_count == 1


def _payload_pairs(counts):
    from app.http_request_counts import _bucket_payload
    return [(bucket, _bucket_payload(routes))
            for bucket, routes in sorted(counts._buckets.items())]


def test_snapshot_stays_byte_identical_to_a_whole_document_dump(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    for route, method, status in [
            ("/api/synthetic", "GET", 200), ("/board", "GET", 401),
            ("/receipts", "POST", 201), ("/healthz", "HEAD", 200)]:
        counts.observe_finish(counts.observe_begin(route, method), status)
    clock.tick(3600)
    counts.observe_finish(counts.observe_begin("/unknown/1", "M-SEARCH"), 503)
    saved_at = clock.now().replace(microsecond=0)
    with counts._lock:
        reference = counts._header_locked(saved_at)
    reference["buckets"] = {bucket: payload for bucket, payload in _payload_pairs(counts)}
    assert counts.flush()
    raw = path.read_text(encoding="utf-8")
    assert raw == json.dumps(reference, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":")) + "\n"
    counts.close()


def test_repeated_flush_only_rewrites_the_hours_that_changed(tmp_path, monkeypatch):
    """Flushing the same 400-day footprint again must not re-encode all of it."""
    path = tmp_path / "tall.json"
    clock = Clock()
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    base = datetime(2026, 11, 17, 3, 0, tzinfo=timezone.utc)
    for hours in range(24 * 400):
        bucket = _hour_bucket(base - timedelta(hours=hours))
        for route in ("api", "ledger", "assets"):
            counts._counts_for_locked(bucket, route, "GET")["started"] += 250
    assert counts.flush()
    encoded = []
    real_dumps = _counts_module.json.dumps

    def counting_dumps(value, *args, **kwargs):
        # A per-hour bucket encodes routes -> methods; anything else is header.
        if (kwargs.get("sort_keys") and isinstance(value, dict)
                and set(value) <= {"api", "ledger", "assets"}):
            encoded.append(1)
        return real_dumps(value, *args, **kwargs)

    monkeypatch.setattr(_counts_module.json, "dumps", counting_dumps)
    assert counts.flush()
    assert counts.flush()
    assert encoded == []
    # A new request in the current hour re-encodes that one hour only.
    counts.observe_finish(counts.observe_begin("/api/synthetic", "GET"), 200)
    assert counts.flush()
    assert len(encoded) == 1
    monkeypatch.setattr(_counts_module.json, "dumps", real_dumps)
    assert json.loads(path.read_text(encoding="utf-8"))["buckets"][
        "2026-11-17T03:00:00Z"]["api"]["GET"]["started"] == 251
    counts.close()


def test_stop_with_a_request_in_flight_is_not_a_clean_shutdown(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    observation = counts.observe_begin("/api/synthetic", "GET")
    assert counts.close()
    state = load(path)
    assert state["clean_shutdown"] is False
    assert state["shutdown_utc"] is None
    assert state["stopped_utc"] == "2026-11-17T03:15:00Z"
    assert state["in_flight_count"] == 1
    assert state["unrecorded_open_requests"] is True

    # The outcome that arrives after the stop is still persisted.
    assert counts.observe_finish(observation, 200)
    saved = load(path)
    assert saved["in_flight_count"] == 0
    assert saved["clean_shutdown"] is True


def test_stop_with_in_flight_records_a_named_window_on_restart(tmp_path):
    path = tmp_path / "counts.json"
    clock = Clock()
    counts = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                           monotonic_clock=clock.monotonic_now)
    counts.observe_begin("/api/synthetic", "GET")
    assert counts.close()
    clock.tick(60)
    restarted = RequestCounts(path, start_flusher=False, wall_clock=clock.now,
                              monotonic_clock=clock.monotonic_now)
    assert restarted.flush()
    state = load(path)
    assert state["possible_loss"]["window_count"] == 1
    assert state["possible_loss"]["latest_window"]["reason"] == (
        "shutdown_with_requests_in_flight")


def test_a_flusher_that_ignores_the_stop_never_reports_a_clean_close(tmp_path, monkeypatch):
    """A daemon writer that outlives the join timeout must not fake a clean stop."""
    import threading
    path = tmp_path / "counts.json"
    clock = Clock()
    counts = RequestCounts(path, flush_interval_seconds=0.02, start_flusher=False,
                           wall_clock=clock.now, monotonic_clock=clock.monotonic_now)
    counts.observe_finish(counts.observe_begin("/api/synthetic", "GET"), 200)
    blocker = threading.Event()
    entered = threading.Event()
    real_flush = counts.flush

    def stuck_flush():
        entered.set()
        blocker.wait(10)
        return real_flush()

    def stuck_loop():
        while not counts._stop_event.wait(counts._interval):
            stuck_flush()

    flusher = threading.Thread(target=stuck_loop, daemon=True)
    monkeypatch.setattr(counts, "_flusher", flusher)
    flusher.start()
    assert entered.wait(2)  # the flusher really is inside a write that will not finish
    assert not counts.close()
    assert flusher.is_alive()
    assert counts.persistence_failure_count >= 1
    blocker.set()
    flusher.join(timeout=5)
