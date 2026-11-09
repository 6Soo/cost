"""OTA 검토 대사 결과를 요청 경로에서 분리해 보관한다.

요청은 계산하지 않고 마지막으로 성공한 결과를 돌려준다. 워커 한 개가 입력 지문을 주기적으로
확인하고, 지문이 바뀌었을 때만 대사를 다시 한다. 워커가 하나이므로 같은 계산이 겹치지 않는다.

디스크에는 화면에 필요한 공개 결과와 지문만 저장한다. 미리보기·기록에 필요한 전체 데이터는
메모리에만 있고, 재시작 뒤에는 워커가 한 번 다시 대사해 채운다. 그 전까지는 행동을 받지 않는다.
"""
import hashlib
import base64
import hmac
import json
import os
import re
import secrets
import threading
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from app.ota_queue_paging import build_queue_index
from app.ota_queue_telemetry import append_sample, fingerprint, payload_bytes, stage_sample, summarize_samples
from app.request_metrics import measurement as request_measurement, new_request_id

SCHEMA = "ota-snapshot-v1"
CHECK_SECONDS = 60
FRESH_SECONDS = 150
RETRY_SECONDS = 60
RETRY_CAP_SECONDS = 900
# Inputs that keep changing during a multi-minute reconciliation throw its result away. After the
# second such loss in a row, a new run waits until the inputs have held still this long.
SETTLE_SECONDS = 30
SETTLE_CAP_SECONDS = 300
FIRST_WAIT_SECONDS = 3
LOG_HEARTBEAT_SECONDS = 3600
MAX_DIAGNOSTIC_LOG_BYTES = 5 * 1024 * 1024
WORKER_NAME = "ota-snapshot"
_CURSOR_CHARS = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_RESERVATION_PRIVATE_FIELDS = frozenset((
    "reservation_identity_attestation", "_portal_reservation_provenance", "_mail_reservation_provenance"))


def _public_results(results):
    """Copy solver result rows while hiding only the new reservation-private fields."""
    if type(results) is not list:
        return results
    return [{key: value for key, value in row.items() if key not in _RESERVATION_PRIVATE_FIELDS}
            if type(row) is dict else row for row in results]


class SnapshotReadError(ValueError):
    """Finite read-only snapshot error safe to translate to an HTTP response."""

    def __init__(self, code, status_code):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _proposal_cursor_encode(key, generation, offset, limit):
    payload = json.dumps({"v": 1, "g": generation, "o": offset, "l": limit},
                         separators=(",", ":"), sort_keys=True).encode("ascii")
    left = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = hmac.new(key, left.encode("ascii"), hashlib.sha256).digest()
    right = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return left + "." + right


def _proposal_cursor_decode(key, token, generation, limit):
    if type(token) is not str or len(token) > 512 or token.count(".") != 1:
        raise SnapshotReadError("BAD_CURSOR", 400)
    left, right = token.split(".")
    try:
        if not _CURSOR_CHARS.fullmatch(left) or not _CURSOR_CHARS.fullmatch(right):
            raise ValueError
        payload_bytes = base64.b64decode(left + "=" * (-len(left) % 4), altchars=b"-_", validate=True)
        signature = base64.b64decode(right + "=" * (-len(right) % 4), altchars=b"-_", validate=True)
        if (base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii") != left or
                base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii") != right or
                not hmac.compare_digest(signature, hmac.new(key, left.encode("ascii"), hashlib.sha256).digest())):
            raise ValueError
        payload = json.loads(payload_bytes.decode("ascii"))
        if (type(payload) is not dict or set(payload) != {"v", "g", "o", "l"} or
                type(payload["v"]) is not int or payload["v"] != 1 or
                type(payload["g"]) is not int or payload["g"] < 0 or
                type(payload["o"]) is not int or payload["o"] < 0 or
                type(payload["l"]) is not int or not 1 <= payload["l"] <= 20):
            raise ValueError
    except Exception:
        raise SnapshotReadError("BAD_CURSOR", 400) from None
    if payload["g"] != generation or payload["l"] != limit:
        raise SnapshotReadError("SNAPSHOT_CHANGED", 409)
    return payload["o"]


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_STARTED = []


def stop_all(timeout=5):
    """Stop every worker this process started. Used when a test ends so nothing outlives its store."""
    for service in list(_STARTED):
        service.stop(timeout=timeout)
    _STARTED.clear()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


class OtaSnapshotService:
    def __init__(self, *, key_fn, reconcile_fn, persist_path=None, log_path=None, clock=time.monotonic,
                 check_seconds=CHECK_SECONDS, fresh_seconds=FRESH_SECONDS, retry_seconds=RETRY_SECONDS,
                 first_wait_seconds=FIRST_WAIT_SECONDS, start=True, on_published=None,
                 profile_memory=False, verify_key_fn=None):
        self._key_fn = key_fn
        self._verify_key_fn = verify_key_fn
        self._reconcile_fn = reconcile_fn
        self._profile_memory = profile_memory is True
        self._persist_path = Path(persist_path) if persist_path else None
        self._log_path = Path(log_path) if log_path else None
        self._clock = clock
        self._check_seconds = check_seconds
        self._fresh_seconds = fresh_seconds
        self._retry_seconds = retry_seconds
        self._first_wait = first_wait_seconds
        self._on_published = on_published
        self._queue_page_signing_key = secrets.token_bytes(32)
        self._first_ready = threading.Event()
        self._lock = threading.Lock()
        self._publish_lock = threading.Lock()
        self._pending_publish = None
        self._published_role_token = None
        self._role_inactive = True
        self._wake = threading.Event()
        self._stopping = False
        self._current = None
        self._checked_key = None
        self._checked_at = None
        self._refreshing = False
        self._checks = 0
        self._error = None
        self._telemetry_samples = []
        self._failed_key = None
        self._failed_at = None
        self._failures = 0
        self._source_changed_retry = False
        self._source_changes = 0
        self._seen_key = None
        self._seen_since = None
        self._thread = None
        self._last_check_sig = None
        self._last_check_log_at = 0.0
        self._load_persisted()
        self._autostart = start
        if start:
            self.ensure_started()

    # lifecycle

    def ensure_started(self):
        if not self._autostart:
            return
        with self._lock:
            if self._stopping:
                return
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name=WORKER_NAME, daemon=True)
            self._thread.start()
            _STARTED.append(self)

    def stop(self, timeout=10):
        """Stop the worker and wait for it. Safe to call repeatedly; after it returns nothing runs here."""
        with self._lock:
            self._stopping = True
            thread = self._thread
        self._wake.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive():
                raise RuntimeError("OTA snapshot worker did not stop in time")
        with self._lock:
            self._thread = None

    def worker_alive(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _run(self):
        while not self._stopping:
            self.check_now()
            if self._stopping:
                break
            with self._lock:
                retry_changed = self._source_changed_retry
                self._source_changed_retry = False
            self._wake.wait(min(self._check_seconds, 1) if retry_changed else self._check_seconds)
            self._wake.clear()

    # worker

    def request_check(self, wait_seconds=0):
        """Ask the worker to re-read the input digest soon. Never computes on the caller's thread.

        A caller may wait a bounded time for the worker to publish a newer result; the wait is bounded by
        `wait_seconds`, so a slow reconciliation only means the answer is still the last good one.
        """
        with self._lock:
            checks_before = self._checks
        self._wake.set()
        deadline = time.monotonic() + wait_seconds
        while wait_seconds > 0 and time.monotonic() < deadline:
            with self._lock:
                if self._checks > checks_before and not self._refreshing:
                    return
            time.sleep(0.05)

    def _log(self, event, **fields):
        """One JSON line per worker decision, for operators. Never raises."""
        if self._log_path is None:
            return
        try:
            if self._log_path.stat().st_size >= MAX_DIAGNOSTIC_LOG_BYTES:
                try:
                    os.replace(self._log_path, self._log_path.with_name(self._log_path.name + ".1"))
                except OSError:
                    pass
        except OSError:
            pass
        try:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": _now_iso(), "event": event, **fields}, ensure_ascii=False, default=str) + "\n")
        except OSError:
            return

    def _log_check(self, key, held, failed, generation):
        """Log a held/failed check only on state change, at most once an hour otherwise."""
        signature = (bool(held), bool(failed), bool(self._refreshing), generation)
        now = self._clock()
        if signature != self._last_check_sig or now - self._last_check_log_at >= LOG_HEARTBEAT_SECONDS:
            self._log("check", key=key[:12], held=held, failed=failed, refreshing=self._refreshing,
                      generation=generation)
            self._last_check_sig = signature
            self._last_check_log_at = now

    def _retry_window(self):
        """The wait before retrying the same failed input: doubles per repeat, capped.

        A new input key is never held back by this; only an identical input that keeps failing waits longer.
        """
        return min(self._retry_seconds * 2 ** max(self._failures - 1, 0), RETRY_CAP_SECONDS)

    def _settle_window(self):
        """How long the inputs must hold still before another run, once runs keep being outdated.

        The first change during a run is retried at once; only a burst of changes waits.
        """
        if self._source_changes < 2:
            return 0
        return min(SETTLE_SECONDS * 2 ** (self._source_changes - 2), SETTLE_CAP_SECONDS)

    def check_now(self):
        """One pass: read the input digest, and reconcile only if it differs from the held result."""
        if self._stopping:
            return
        try:
            key = self._key_fn()
        except Exception as exc:
            with self._lock:
                self._checks += 1
                self._error = {"code": type(exc).__name__, "message": str(exc)[:200], "at": _now_iso()}
            return
        with self._lock:
            self._checks += 1
            self._checked_key = key
            self._checked_at = self._clock()
            current = self._current
            if key != self._seen_key:
                self._seen_key = key
                self._seen_since = self._clock()
            failed = self._failed_key == key and self._clock() - (self._failed_at or 0) < self._retry_window()
            held = current is not None and current["key"] == key and current.get("data") is not None
            settling = (current is not None and not held
                        and self._clock() - self._seen_since < self._settle_window())
            if held and not self._refreshing:
                # A successful key check revalidates this already-held snapshot.
                self._error = None
            skip = held or failed or settling or self._refreshing or self._stopping
            publish_held = held and not self._refreshing and not self._stopping
            if skip:
                self._log_check(key, held, failed, (current or {}).get("generation", 0))
            else:
                self._refreshing = True
        if skip:
            if publish_held:
                self._publish_if_active()
            return
        self._log("refresh_start", key=key[:12], generation=(current or {}).get("generation", 0))
        started = self._clock()
        owns_tracing = self._profile_memory and not tracemalloc.is_tracing()
        if owns_tracing:
            tracemalloc.start()
        try:
            request_id = new_request_id()
            input_fingerprint = fingerprint(key)
            reconcile_started = time.perf_counter()
            reconciled = self._reconcile_fn()
            reconcile_elapsed = (time.perf_counter() - reconcile_started) * 1000
            telemetry_samples = list(reconciled.get("telemetry_samples", ())) if type(reconciled) is dict else []
            telemetry_samples = append_sample(telemetry_samples, stage_sample(
                "reconcile", reconcile_elapsed,
                row_count=len(reconciled.get("queue_page_rows", ())) if type(reconciled) is dict else 0))
            memory_peak_bytes = (tracemalloc.get_traced_memory()[1]
                                 if self._profile_memory and tracemalloc.is_tracing() else None)
            with self._lock:
                next_generation = (self._current or {}).get("generation", 0) + 1
            page_rows = reconciled.get("queue_page_rows") if type(reconciled) is dict else None
            page_index = None
            if type(page_rows) is list:
                index_started = time.perf_counter()
                page_index = build_queue_index(
                    page_rows, generation=next_generation,
                    snapshot_nonce=secrets.token_urlsafe(24),
                    signing_key=self._queue_page_signing_key)
                index_elapsed = (time.perf_counter() - index_started) * 1000
                telemetry_samples = append_sample(telemetry_samples, stage_sample(
                    "queue_index_build", index_elapsed, row_count=len(page_rows)))
            group_rows = reconciled.get("queue_group_rows") if type(reconciled) is dict else None
            group_index = (build_queue_index(
                group_rows, generation=next_generation,
                snapshot_nonce=secrets.token_urlsafe(24),
                signing_key=self._queue_page_signing_key) if type(group_rows) is list else None)
            member_rows = reconciled.get("queue_group_member_rows") if type(reconciled) is dict else None
            member_indexes = {}
            if type(member_rows) is dict:
                for group_id, rows in member_rows.items():
                    if (type(group_id) is str and re.fullmatch(r"[a-f0-9]{64}", group_id, re.ASCII)
                            and type(rows) is list):
                        member_indexes[group_id] = build_queue_index(
                            rows, generation=next_generation,
                            snapshot_nonce=secrets.token_urlsafe(24),
                            signing_key=self._queue_page_signing_key)
            detail_map = reconciled.get("queue_detail_rows") if type(reconciled) is dict else None
            if type(detail_map) is not dict:
                detail_map = {}
            else:
                detail_map = dict(detail_map)
            ambiguous_ids = reconciled.get("queue_ambiguous_ids", ()) if type(reconciled) is dict else ()
            if type(ambiguous_ids) not in (list, tuple, set, frozenset):
                ambiguous_ids = ()
            else:
                ambiguous_ids = frozenset(value for value in ambiguous_ids
                                          if type(value) is str and value.strip())
            changed_to = self._verify_key_fn() if self._verify_key_fn is not None else key
            source_changed = changed_to != key
            with self._lock:
                holds_complete = self._has_data_locked()
            if source_changed and holds_complete:
                raise ValueError('SOURCE_CHANGED_DURING_RECONCILIATION')
            # With no complete generation held (a fresh start), a result one input behind is shown
            # rather than nothing; it is published as not fresh and reconciled again at once.
        except Exception as exc:
            with self._lock:
                self._refreshing = False
                self._failures = self._failures + 1 if self._failed_key == key else 1
                self._failed_key = key
                self._failed_at = self._clock()
                self._error = {"code": type(exc).__name__, "message": str(exc)[:200], "at": _now_iso()}
                if isinstance(exc, ValueError) and str(exc) == 'SOURCE_CHANGED_DURING_RECONCILIATION':
                    self._source_changes += 1
                    self._source_changed_retry = self._source_changes < 2
                    # The settle window counts from when the change was seen, not the next check.
                    self._seen_key = changed_to
                    self._seen_since = self._clock()
            self._log("refresh_failed", key=key[:12], code=type(exc).__name__, message=str(exc)[:200])
            if owns_tracing:
                tracemalloc.stop()
            return
        if owns_tracing:
            tracemalloc.stop()
        self._log("refresh_done", key=key[:12], seconds=round(self._clock() - started, 2),
                  **({"outdated_by": changed_to[:12]} if source_changed else {}))
        with self._lock:
            generation = (current or {}).get("generation", 0) + 1
            generated_at = _now_iso()
            published = {"key": key, "generation": generation, "generated_at": generated_at,
                         **{name: value for name, value in reconciled.items()
                            if name not in ("queue_page_rows", "queue_group_rows", "queue_group_member_rows",
                                            "queue_detail_rows", "queue_ambiguous_ids")}}
            if page_index is not None:
                published["_queue_page_index"] = page_index
            if group_index is not None:
                published["_queue_group_index"] = group_index
                published["_queue_group_rows_internal"] = reconciled.get("queue_group_rows", [])
            if page_index is not None:
                published["_queue_page_rows_internal"] = reconciled.get("queue_page_rows", [])
            published["_queue_group_member_indexes"] = member_indexes
            published["_queue_detail_map"] = detail_map
            published["_queue_ambiguous_ids"] = ambiguous_ids
            queue_summary = reconciled.get("queue_summary") if isinstance(reconciled, dict) else None
            if isinstance(queue_summary, dict):
                published["queue_summary"] = {**queue_summary, "generation": generation,
                                               "generated_at": generated_at}
            self._telemetry_samples = (self._telemetry_samples + telemetry_samples)[-128:]
            metrics = summarize_samples(self._telemetry_samples)
            metrics["query_plan"] = {"kind": "read_only_explain",
                                     "samples": metrics.get("query_plan", {}).get("samples", 0)}
            rule_version = reconciled.get("rule_version")
            if (type(rule_version) is not str or len(rule_version) > 64 or
                    not re.fullmatch(r"[A-Za-z0-9_.-]+", rule_version, re.ASCII)):
                rule_version = None
            published["telemetry"] = {
                "request_id": request_id,
                "snapshot_generation": generation,
                "rule_version": rule_version,
                "stages": metrics,
                "input_fingerprint": input_fingerprint,
                "rule_fingerprint": (reconciled.get("rule_fingerprint")
                                     if type(reconciled.get("rule_fingerprint")) is str and
                                     len(reconciled.get("rule_fingerprint")) == 64 else None),
                "memory_peak_bytes": memory_peak_bytes,
                "memory_scope": "process_tracemalloc" if memory_peak_bytes is not None else "not_measured",
                "requests": [request_measurement(
                    "ota_snapshot", "snapshot_compute", reconcile_elapsed,
                    row_count=len(reconciled.get("queue_page_rows", ()))
                    if type(reconciled) is dict else 0,
                    generation=generation,
                    rule_version=rule_version,
                    data_fingerprint=input_fingerprint, request_id=request_id,
                    peak_memory_bytes=memory_peak_bytes)]
            }
            published["telemetry"]["snapshot_bytes"] = payload_bytes({
                "generation": generation, "queue_summary": published.get("queue_summary"),
                "public": published.get("public")})
            self._current = published
            self._refreshing = False
            self._error = None
            self._failed_key = None
            self._source_changes = 0
            self._checked_at = self._clock()
            if source_changed:
                self._checked_key = changed_to
                self._seen_key = changed_to
                self._seen_since = self._clock()
                self._source_changed_retry = True
            published = self._current
            if not source_changed:
                self._pending_publish = published
        self._first_ready.set()
        if not source_changed:
            # A result one input behind stays in memory for display only and is never written out.
            self._publish_if_active()

    def _publish_if_active(self):
        """Publish shared files only while this release owns the writer role."""
        from .deployment_role import writer
        with self._publish_lock:
            with self._lock:
                current = self._pending_publish or self._current
            if current is None or current.get('data') is None:
                return
            try:
                with writer() as active:
                    if not active:
                        self._role_inactive = True
                        return
                    route = os.environ.get('WEBLEDGER_DEPLOYMENT_ROUTE')
                    role_token = (route, json.loads(Path(route).read_text(encoding='utf-8-sig')).get('generation')) if route else ('unmanaged',)
                    with self._lock:
                        if current is not self._current:
                            return
                        if (self._pending_publish is None and not self._role_inactive
                                and role_token == self._published_role_token):
                            return
                    self._persist(current)
                    if self._on_published is not None:
                        try:
                            self._on_published(current)
                        except Exception:
                            pass
                    with self._lock:
                        if current is self._pending_publish:
                            self._pending_publish = None
                    self._published_role_token = role_token
                    self._role_inactive = False
            except (OSError, ValueError, TypeError):
                # Keep the in-memory snapshot available; retry publication on the next check.
                self._role_inactive = True
                return

    # reads

    def _fresh_locked(self):
        return (not self._refreshing and self._error is None and self._current is not None
                and self._checked_key == self._current["key"]
                and self._checked_at is not None and self._clock() - self._checked_at < self._fresh_seconds)

    def _has_data_locked(self):
        return self._current is not None and self._current.get("data") is not None

    def view(self):
        """What a request sees now. Never computes; `status` tells the screen what it is looking at."""
        self.ensure_started()
        with self._lock:
            check_due = (not self._refreshing and
                         (self._checked_at is None or
                          self._clock() - self._checked_at >= self._check_seconds))
        if self._autostart and check_due:
            # Reads share the worker's normal check interval. Waking it for
            # every summary/page/detail GET repeatedly hashes all source files
            # and reads the ledger while the request also needs the store lock.
            # Explicit request_check() and action-time key validation stay eager.
            self.request_check(wait_seconds=0)
        with self._lock:
            current, fresh, refreshing, error = self._current, self._fresh_locked(), self._refreshing, self._error
            has_data = self._has_data_locked()
        if current is None:
            status = "error" if error and not refreshing else "loading"
        elif error:
            status = "error"
        elif refreshing or not fresh or not has_data:
            status = "refreshing"
        else:
            status = "ready"
        public = {key: value for key, value in (current or {}).items()
                  if key not in ("data", "_queue_page_index", "_queue_group_index", "_queue_group_rows_internal",
                                 "_queue_page_rows_internal",
                                 "_queue_group_member_indexes", "_queue_detail_map",
                                 "_queue_ambiguous_ids", "queue_page_rows", "queue_detail_rows",
                                 "queue_ambiguous_ids")}
        if "results" in public:
            public["results"] = _public_results(public["results"])
        return {"status": status, "stale": not fresh, "refreshing": refreshing,
                "generation": current["generation"] if current else 0,
                "generated_at": current["generated_at"] if current else None,
                "snapshot_key": current["key"][:12] if current else None,
                "last_error": error, "fresh": fresh, "current": public or None,
                "telemetry": current.get("telemetry") if current else None}

    def queue_page_context(self):
        """Return the private in-memory index with a freshness envelope for the read-only route."""
        view = self.view()
        with self._lock:
            current = self._current
            index = current.get("_queue_page_index") if current else None
            matches_view = (current is not None and
                            current.get("generation") == view.get("generation"))
        return {
            "index": index if matches_view else None,
            "rows": current.get("_queue_page_rows_internal") if current and matches_view else None,
            "status": view.get("status"), "generation": view.get("generation"),
            "generated_at": view.get("generated_at"), "fresh": view.get("fresh"),
            "stale": view.get("stale"), "refreshing": view.get("refreshing"),
            "telemetry": view.get("telemetry"),
            "summary": ({**current.get("queue_summary"),
                         "snapshot_status": view.get("status"),
                         "fresh": view.get("fresh"), "stale": view.get("stale"),
                         "refreshing": view.get("refreshing"),
                         "input_fingerprint": (current.get("telemetry") or {}).get("input_fingerprint"),
                         "rule_fingerprint": (current.get("telemetry") or {}).get("rule_fingerprint")}
                        if current and matches_view and type(current.get("queue_summary")) is dict else None),
        }

    def queue_group_context(self):
        """Return the worker-prepared reservation group index for this generation."""
        view = self.view()
        with self._lock:
            current = self._current
            index = current.get("_queue_group_index") if current else None
            matches_view = current is not None and current.get("generation") == view.get("generation")
        return {"index": index if matches_view else None,
                "rows": current.get("_queue_group_rows_internal") if current and matches_view else None,
                "status": view.get("status"), "generation": view.get("generation"),
                "generated_at": view.get("generated_at"), "fresh": view.get("fresh"),
                "stale": view.get("stale"), "refreshing": view.get("refreshing"),
                "summary": ({**current.get("queue_summary"),
                             "snapshot_status": view.get("status"),
                             "fresh": view.get("fresh"), "stale": view.get("stale"),
                             "refreshing": view.get("refreshing"),
                             "input_fingerprint": (current.get("telemetry") or {}).get("input_fingerprint"),
                             "rule_fingerprint": (current.get("telemetry") or {}).get("rule_fingerprint")}
                            if current and matches_view and type(current.get("queue_summary")) is dict else None),
                "telemetry": current.get("telemetry") if current and matches_view else None}

    def queue_group_members_context(self, group_id, expected_generation):
        """Return a generation-bound private member index, without scanning members."""
        view = self.view()
        with self._lock:
            current = self._current
            if (current is None or not self._fresh_locked() or self._refreshing or self._error or
                    current.get("data") is None):
                raise SnapshotReadError("SNAPSHOT_NOT_READY", 409)
            generation = current.get("generation")
            if generation != expected_generation or generation != view.get("generation"):
                raise SnapshotReadError("SNAPSHOT_CHANGED", 409)
            index = current.get("_queue_group_member_indexes", {}).get(group_id)
            if index is None:
                raise SnapshotReadError("GROUP_NOT_FOUND", 404)
            return {"index": index, "generation": generation,
                    "status":"ready", "fresh":True, "stale":False, "refreshing":False,
                    "generated_at":current.get("generated_at")}

    def queue_detail_context(self, event_id, expected_generation):
        """O(1) detail lookup from the current private map, guarded by exact freshness/generation."""
        view = self.view()
        with self._lock:
            current = self._current
            fresh = self._fresh_locked()
            if (current is None or not fresh or self._refreshing or self._error or
                    current.get("data") is None or current.get("_queue_page_index") is None):
                raise SnapshotReadError("SNAPSHOT_NOT_READY", 409)
            if current.get("generation") != expected_generation:
                raise SnapshotReadError("SNAPSHOT_CHANGED", 409)
            if current.get("generation") != view.get("generation"):
                raise SnapshotReadError("SNAPSHOT_CHANGED", 409)
            ambiguous = event_id in current.get("_queue_ambiguous_ids", ())
            detail = current.get("_queue_detail_map", {}).get(event_id)
            return {"generation": current["generation"], "event": detail,
                    "ambiguous": ambiguous,
                    "summary": ({**current.get("queue_summary"),
                                 "snapshot_status": view.get("status"),
                                 "fresh": view.get("fresh"), "stale": view.get("stale"),
                                 "refreshing": view.get("refreshing"),
                                 "input_fingerprint": (current.get("telemetry") or {}).get("input_fingerprint"),
                                 "rule_fingerprint": (current.get("telemetry") or {}).get("rule_fingerprint")}
                                if type(current.get("queue_summary")) is dict else None),
                    "telemetry": current.get("telemetry"),
                    "generated_at": current.get("generated_at")}

    def proposal_page_context(self, expected_generation, *, limit=20, cursor=None):
        """Read one bounded slice from the already-sanitized public proposal snapshot."""
        view = self.view()
        with self._lock:
            current = self._current
            fresh = self._fresh_locked()
            if (current is None or not fresh or self._refreshing or self._error or
                    current.get("data") is None or current.get("_queue_page_index") is None):
                raise SnapshotReadError("SNAPSHOT_NOT_READY", 409)
            generation = current.get("generation")
            if generation != expected_generation or generation != view.get("generation"):
                raise SnapshotReadError("SNAPSHOT_CHANGED", 409)
            if type(limit) is not int or not 1 <= limit <= 20:
                raise SnapshotReadError("INVALID_QUERY", 400)
            offset = 0 if cursor is None else _proposal_cursor_decode(
                self._queue_page_signing_key, cursor, generation, limit)
            public = current.get("public")
            proposals = public.get("proposals") if type(public) is dict else None
            if type(proposals) is not list:
                proposals = []
            items = proposals[offset:offset + limit]
            next_offset = offset + len(items)
            next_cursor = (_proposal_cursor_encode(self._queue_page_signing_key,
                                                    generation, next_offset, limit)
                           if next_offset < len(proposals) else None)
            return {"generation": generation, "items": items,
                    "next_cursor": next_cursor, "total_count": len(proposals)}

    def checked_key(self):
        """The input fingerprint the worker last read. Read only; never computes anything."""
        with self._lock:
            return self._checked_key

    def held(self):
        """(current result or None, is_fresh) for holds that must not grant new authority on stale data."""
        self.ensure_started()
        with self._lock:
            current = self._current
            if current is not None and current.get("data") is None:
                # Holds need the in-memory result; before it exists, the caller treats every card as unresolved.
                return None, False
            return current, self._fresh_locked()

    def display_context(self):
        """한 화면에서 같은 세대의 결과와 신선도·오류 상태를 함께 읽는다.

        대사를 요청하거나 실행하지 않는다. 디스크 복구 결과는 표시할 수 있지만,
        전체 근거가 메모리에 없는 동안 최신 판단으로 표시하지 않는다.
        """
        with self._lock:
            current = self._current
            complete = self._has_data_locked()
            fresh = bool(self._fresh_locked() and complete and not self._refreshing and not self._error)
            status = ('error' if self._error else 'loading' if current is None else
                      'ready' if fresh else 'refreshing')
            state = {'enabled': True, 'status': status, 'fresh': fresh, 'stale': not fresh,
                     'generation': current.get('generation') if current else None,
                     'error_code': str(self._error.get('code') or 'INPUT_UNAVAILABLE') if self._error else None}
            return current, state

    def action_context(self):
        """The full in-memory result for a preview or confirm, only while it is fresh and complete.

        Anything else returns (None, reason). A non-fresh state asks the worker to look again, and the
        caller answers with a refreshing status instead of computing.
        """
        self.ensure_started()
        with self._lock:
            current, fresh, has_data = self._current, self._fresh_locked(), self._has_data_locked()
            refreshing = self._refreshing
        if current is None:
            reason = "loading"
        elif not has_data or refreshing:
            reason = "refreshing"
        elif not fresh:
            reason = "stale"
        else:
            return current, "ready"
        self.request_check()
        return None, reason

    # persistence

    def _persist(self, current):
        if self._persist_path is None:
            return
        document = {"schema": SCHEMA, "key": current["key"], "generation": current["generation"],
                    "generated_at": current["generated_at"], "public": current["public"],
                    "authority": current.get("authority"),
                    "results": _public_results(current["results"]), "links": current["links"]}
        if isinstance(current.get("queue_summary"), dict):
            document["queue_summary"] = current["queue_summary"]
        if isinstance(current.get("telemetry"), dict):
            document["telemetry"] = current["telemetry"]
        if isinstance(document.get("public"), dict) and isinstance(document["public"].get("results"), list):
            document["public"] = {**document["public"],
                                  "results": _public_results(document["public"]["results"])}
        try:
            text = json.dumps(document, ensure_ascii=False, default=str)
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._persist_path.with_suffix(self._persist_path.suffix + ".tmp")
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, self._persist_path)
        except OSError:
            return

    def _load_persisted(self):
        if self._persist_path is None or not self._persist_path.is_file():
            return
        try:
            document = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(document, dict) or document.get("schema") != SCHEMA or not document.get("key"):
            return
        public = document.get("public") or {}
        if isinstance(public, dict) and isinstance(public.get("results"), list):
            public = {**public, "results": _public_results(public["results"])}
        self._current = {"key": str(document["key"]), "generation": int(document.get("generation") or 1),
                         "generated_at": document.get("generated_at"), "public": public,
                         "results": document.get("results") or [], "links": document.get("links") or {},
                         "authority": document.get("authority"),
                         "queue_summary": document.get("queue_summary")
                         if isinstance(document.get("queue_summary"), dict) else None,
                         "telemetry": document.get("telemetry")
                         if isinstance(document.get("telemetry"), dict) else None,
                         "data": None}
        self._first_ready.set()
