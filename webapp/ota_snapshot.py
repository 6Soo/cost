"""OTA 검토 대사 결과를 요청 경로에서 분리해 보관한다.

요청은 계산하지 않고 마지막으로 성공한 결과를 돌려준다. 워커 한 개가 입력 지문을 주기적으로
확인하고, 지문이 바뀌었을 때만 대사를 다시 한다. 워커가 하나이므로 같은 계산이 겹치지 않는다.

디스크에는 화면에 필요한 공개 결과와 지문만 저장한다. 미리보기·확정에 필요한 전체 데이터는
메모리에만 있고, 재시작 뒤에는 워커가 한 번 다시 대사해 채운다. 그 전까지는 행동을 받지 않는다.
"""
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "ota-snapshot-v1"
CHECK_SECONDS = 60
FRESH_SECONDS = 150
RETRY_SECONDS = 60
RETRY_CAP_SECONDS = 900
FIRST_WAIT_SECONDS = 3
WORKER_NAME = "ota-snapshot"


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
                 first_wait_seconds=FIRST_WAIT_SECONDS, start=True):
        self._key_fn = key_fn
        self._reconcile_fn = reconcile_fn
        self._persist_path = Path(persist_path) if persist_path else None
        self._log_path = Path(log_path) if log_path else None
        self._clock = clock
        self._check_seconds = check_seconds
        self._fresh_seconds = fresh_seconds
        self._retry_seconds = retry_seconds
        self._first_wait = first_wait_seconds
        self._first_ready = threading.Event()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = False
        self._current = None
        self._checked_key = None
        self._checked_at = None
        self._refreshing = False
        self._checks = 0
        self._error = None
        self._failed_key = None
        self._failed_at = None
        self._failures = 0
        self._thread = None
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
            self._wake.wait(self._check_seconds)
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
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": _now_iso(), "event": event, **fields}, ensure_ascii=False, default=str) + "\n")
        except OSError:
            return

    def _retry_window(self):
        """The wait before retrying the same failed input: doubles per repeat, capped.

        A new input key is never held back by this; only an identical input that keeps failing waits longer.
        """
        return min(self._retry_seconds * 2 ** max(self._failures - 1, 0), RETRY_CAP_SECONDS)

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
            failed = self._failed_key == key and self._clock() - (self._failed_at or 0) < self._retry_window()
            held = current is not None and current["key"] == key and current.get("data") is not None
            if held or failed or self._refreshing or self._stopping:
                self._log("check", key=key[:12], held=held, failed=failed, refreshing=self._refreshing,
                          generation=(current or {}).get("generation", 0))
                return
            self._refreshing = True
        self._log("refresh_start", key=key[:12], generation=(current or {}).get("generation", 0))
        started = self._clock()
        try:
            reconciled = self._reconcile_fn()
        except Exception as exc:
            with self._lock:
                self._refreshing = False
                self._failures = self._failures + 1 if self._failed_key == key else 1
                self._failed_key = key
                self._failed_at = self._clock()
                self._error = {"code": type(exc).__name__, "message": str(exc)[:200], "at": _now_iso()}
            self._log("refresh_failed", key=key[:12], code=type(exc).__name__, message=str(exc)[:200])
            return
        self._log("refresh_done", key=key[:12], seconds=round(self._clock() - started, 2))
        with self._lock:
            generation = (current or {}).get("generation", 0) + 1
            self._current = {"key": key, "generation": generation, "generated_at": _now_iso(), **reconciled}
            self._refreshing = False
            self._error = None
            self._failed_key = None
            self._checked_at = self._clock()
            published = self._current
        self._first_ready.set()
        self._persist(published)

    # reads

    def _fresh_locked(self):
        return (self._current is not None and self._checked_key == self._current["key"]
                and self._checked_at is not None and self._clock() - self._checked_at < self._fresh_seconds)

    def _has_data_locked(self):
        return self._current is not None and self._current.get("data") is not None

    def view(self):
        """What a request sees now. Never computes; `status` tells the screen what it is looking at."""
        self.ensure_started()
        if self._autostart:
            if self._current is None:
                self._first_ready.wait(self._first_wait)
            else:
                # A cheap digest check, never a reconciliation: a changed input shows up on this view.
                self.request_check(wait_seconds=self._first_wait)
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
        public = {key: value for key, value in (current or {}).items() if key != "data"}
        return {"status": status, "stale": not fresh, "refreshing": refreshing,
                "generation": current["generation"] if current else 0,
                "generated_at": current["generated_at"] if current else None,
                "snapshot_key": current["key"][:12] if current else None,
                "last_error": error, "fresh": fresh, "current": public or None}

    def held(self):
        """(current result or None, is_fresh) for holds that must not grant new authority on stale data."""
        self.ensure_started()
        with self._lock:
            current = self._current
            if current is not None and current.get("data") is None:
                # Holds need the in-memory result; before it exists, the caller treats every card as unresolved.
                return None, False
            return current, self._fresh_locked()

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
                    "results": current["results"], "links": current["links"]}
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
        self._current = {"key": str(document["key"]), "generation": int(document.get("generation") or 1),
                         "generated_at": document.get("generated_at"), "public": document.get("public") or {},
                         "results": document.get("results") or [], "links": document.get("links") or {},
                         "authority": document.get("authority"), "data": None}
        self._first_ready.set()
