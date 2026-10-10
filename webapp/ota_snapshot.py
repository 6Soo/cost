"""OTA 검토 대사 결과를 요청 경로에서 분리해 보관한다.

요청은 계산하지 않고 마지막으로 성공한 결과를 돌려준다. 워커 한 개가 입력 지문을 주기적으로
확인하고, 지문이 바뀌었을 때만 대사를 다시 한다. 워커가 하나이므로 같은 계산이 겹치지 않는다.
지문이 오래됐거나 마지막 대사가 실패하면 authority 판단은 새 자동 연결을 믿지 않는다.
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
FIRST_WAIT_SECONDS = 3


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


class OtaSnapshotService:
    def __init__(self, *, key_fn, reconcile_fn, persist_path=None, clock=time.monotonic,
                 check_seconds=CHECK_SECONDS, fresh_seconds=FRESH_SECONDS, retry_seconds=RETRY_SECONDS,
                 first_wait_seconds=FIRST_WAIT_SECONDS, start=True):
        self._key_fn = key_fn
        self._reconcile_fn = reconcile_fn
        self._persist_path = Path(persist_path) if persist_path else None
        self._clock = clock
        self._check_seconds = check_seconds
        self._fresh_seconds = fresh_seconds
        self._retry_seconds = retry_seconds
        self._first_wait = first_wait_seconds
        self._first_ready = threading.Event()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._current = None
        self._checked_key = None
        self._checked_at = None
        self._refreshing = False
        self._checks = 0
        self._error = None
        self._failed_key = None
        self._failed_at = None
        self._thread = None
        self._load_persisted()
        self._autostart = start
        if start:
            self.ensure_started()

    def ensure_started(self):
        if not self._autostart:
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="ota-snapshot", daemon=True)
                self._thread.start()

    def _run(self):
        while True:
            self.check_now()
            self._wake.wait(self._check_seconds)
            self._wake.clear()

    def request_check(self, wait_seconds=0):
        """Ask the worker to re-read the input digest soon. Never computes on the caller's thread.

        A caller may wait a bounded time for the worker to publish a newer generation; it never waits for
        more than `wait_seconds`, so a slow reconciliation only means the answer is still the last good one.
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

    def check_now(self):
        """One pass: read the input digest, and reconcile only if it differs from the held snapshot."""
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
            failed = self._failed_key == key and self._clock() - (self._failed_at or 0) < self._retry_seconds
            if (current is not None and current["key"] == key) or failed or self._refreshing:
                return
            self._refreshing = True
        try:
            reconciled = self._reconcile_fn()
        except Exception as exc:
            with self._lock:
                self._refreshing = False
                self._failed_key = key
                self._failed_at = self._clock()
                self._error = {"code": type(exc).__name__, "message": str(exc)[:200], "at": _now_iso()}
            return
        with self._lock:
            generation = (current or {}).get("generation", 0) + 1
            self._current = {"key": key, "generation": generation, "generated_at": _now_iso(), **reconciled}
            self._refreshing = False
            self._error = None
            self._failed_key = None
            self._checked_at = self._clock()
        self._first_ready.set()
        self._persist(self._current)

    def _fresh_locked(self):
        return (self._current is not None and self._checked_key == self._current["key"]
                and self._checked_at is not None and self._clock() - self._checked_at < self._fresh_seconds)

    def view(self):
        """What a request sees now. Never computes; `status` tells the screen what it is looking at.

        With no snapshot yet, a request waits a bounded time for the worker's first result. It never
        computes itself, so a slow first reconciliation still answers `loading` after the bound.
        """
        self.ensure_started()
        if self._autostart:
            if self._current is None:
                self._first_ready.wait(self._first_wait)
            else:
                # A cheap digest check, never a reconciliation: a changed input shows up on this view.
                self.request_check(wait_seconds=self._first_wait)
        with self._lock:
            current, fresh, refreshing, error = self._current, self._fresh_locked(), self._refreshing, self._error
        if current is None:
            status = "error" if error and not refreshing else "loading"
        elif error:
            status = "error"
        elif refreshing or not fresh:
            status = "refreshing"
        else:
            status = "ready"
        return {"status": status, "stale": not fresh, "refreshing": refreshing,
                "generation": current["generation"] if current else 0,
                "generated_at": current["generated_at"] if current else None,
                "snapshot_key": current["key"][:12] if current else None,
                "last_error": error, "fresh": fresh, "current": current}

    def held(self):
        """(current snapshot or None, is_fresh) for holds that must not grant new authority on stale data."""
        self.ensure_started()
        with self._lock:
            return self._current, self._fresh_locked()

    def _persist(self, current):
        if self._persist_path is None:
            return
        document = {"schema": SCHEMA, "key": current["key"], "generation": current["generation"],
                    "generated_at": current["generated_at"], "public": current["public"],
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
                         "results": document.get("results") or [], "links": document.get("links") or {}}
        self._first_ready.set()
