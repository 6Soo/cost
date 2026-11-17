import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path

from app.http_request_counts import RequestCounts, route_id_for_path


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
    assert state["possible_loss"]["window_count"] == 1
    assert state["possible_loss"]["latest_window"]["seconds"] == 3
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
