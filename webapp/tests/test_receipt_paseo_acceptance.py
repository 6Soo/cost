"""Independent HTTP acceptance with synthetic originals and a deterministic runtime.

These tests exercise the real workflow worker and COST ledger. They never call a
provider or use a production store, port, browser, or original.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from app import receipt_vision
from webapp.tests import test_receipt_review as legacy


class SyntheticRuntime:
    def __init__(self):
        self.calls = []
        self.runs = {}
        self.release = threading.Event()

    @staticmethod
    def prompt_metadata():
        return {"prompt_version": "acceptance-v1", "prompt_sha256": "a" * 64,
                "schema_version": "acceptance-v1", "schema_sha256": "b" * 64}

    @staticmethod
    def catalog(provider=None):
        return {"connected": True, "host_label": "synthetic-local-PC",
                "checked_at": "2026-11-16T00:00:00Z",
                "providers": [{"id": "claude", "label": "Synthetic subscription", "available": True}],
                "models": [{"provider": "claude", "id": "synthetic-opus", "label": "Synthetic photo model",
                            "selectable": True, "reason": "", "thinking_options": ["medium"],
                            "default_thinking": "medium"}]}

    def start(self, image_path, provider, model, *, run_key, **kwargs):
        data = Path(image_path).read_bytes()
        handle = {"agent_id": "synthetic-" + run_key, "workspace_id": "synthetic-only",
                  "provider": provider, "model": model, "source_sha256": hashlib.sha256(data).hexdigest(),
                  "thinking": "medium", **self.prompt_metadata()}
        self.calls.append((run_key, data))
        self.runs[run_key] = handle
        return handle

    def find_run(self, run_key):
        return self.runs.get(run_key)

    def inspect_run(self, handle):
        if not self.release.is_set():
            return {"status": "running"}
        rows = [{"merchant": "합성 식당", "date": "2026-10-12", "amount": 1200,
                 "currency": "JPY", "payment": "cash", "box": [0.05, 0.05, 0.45, 0.45]},
                {"merchant": "합성 매점", "date": "2026-10-12", "amount": 700,
                 "currency": "KRW", "payment": "cash", "box": [0.55, 0.55, 0.95, 0.95]}]
        result = receipt_vision.validate_response(
            {"receipts": rows}, image_hash=handle["source_sha256"], model=handle["model"])
        return {"status": "done", "result": result}

    @staticmethod
    def archive_run(handle):
        return None


@pytest.fixture
def receipt_http(monkeypatch, tmp_path):
    from app import receipt_paseo

    runtime = SyntheticRuntime()
    workflow_path = tmp_path / "acceptance-workflow.sqlite"
    monkeypatch.setenv("WEBLEDGER_RECEIPT_WORKFLOW_DB", str(workflow_path))
    for name in ("catalog", "prompt_metadata", "start", "find_run", "inspect_run", "archive_run"):
        monkeypatch.setattr(receipt_paseo, name, getattr(runtime, name))
    fixture = legacy.ReceiptReviewTests()
    fixture.workflow_path = workflow_path
    try:
        fixture.setUp()
        yield fixture, runtime
    finally:
        runtime.release.set()
        fixture.doCleanups()


def _wait_until(predicate, *, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("synthetic workflow did not reach the expected persisted state")


def _upload(fixture):
    status, image = fixture.request("/api/receipts/image", raw=legacy.PNG, token=fixture.csrf())
    assert status == 200
    return image["sha256"]


def _enqueue(fixture, image, request_id="acceptance-analysis-1"):
    status, body = fixture.request("/api/receipts/workflow/batches", {
        "images": [image], "provider": "claude", "model": "synthetic-opus", "request_id": request_id,
    }, token=fixture.csrf())
    assert status == 202, body
    return body["batch"]


def _candidates(fixture, batch_id):
    status, body = fixture.request("/api/receipts/workflow")
    assert status == 200, body
    return next(batch for batch in body["batches"] if batch["batch_id"] == batch_id)["candidates"]


def _persisted_result(fixture):
    db = fixture.workflow_path
    if not db.is_file():
        return False
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        return conn.execute("SELECT COUNT(*) FROM receipt_workflow_candidates").fetchone()[0] == 2


def _review(fixture, candidate, **changes):
    status, body = fixture.request("/api/receipts/workflow/review", {
        "candidate_id": candidate["candidate_id"], "expected_revision": candidate["revision"],
        "changes": {"trip_id": fixture.trip, "category": "식비", **changes}, "selected": True,
    }, token=fixture.csrf())
    assert status == 200, body
    return body["candidate"]


def _ledger_count(fixture):
    return fixture.server.card_store.conn.execute(
        "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'rcpt-%'").fetchone()[0]


def test_worker_saves_results_without_browser_polling_and_never_posts_automatically(receipt_http):
    fixture, runtime = receipt_http
    image = _upload(fixture)
    batch = _enqueue(fixture, image)
    _wait_until(lambda: len(runtime.calls) == 1)
    assert _ledger_count(fixture) == 0
    # No workflow HTTP read occurs between release and durable completion.
    runtime.release.set()
    _wait_until(lambda: _persisted_result(fixture))
    candidates = _candidates(fixture, batch["batch_id"])
    assert len(candidates) == 2
    assert all(candidate["image"] == image and not candidate["selected"]
               and not candidate["applied"] for candidate in candidates)
    assert _ledger_count(fixture) == 0
    assert len(runtime.calls) == 1


def test_stale_selection_rolls_back_whole_batch_and_replayed_apply_is_one_expense(receipt_http):
    fixture, runtime = receipt_http
    batch = _enqueue(fixture, _upload(fixture))
    runtime.release.set()
    _wait_until(lambda: _persisted_result(fixture))
    first, second = [_review(fixture, candidate)
                     for candidate in _candidates(fixture, batch["batch_id"])]
    stale_second = dict(second)
    second = _review(fixture, second, merchant="합성 교정 상호")
    status, body = fixture.request("/api/receipts/workflow/apply", {
        "request_id": "acceptance-stale-batch",
        "selections": [{"candidate_id": candidate["candidate_id"],
                        "expected_revision": candidate["revision"]} for candidate in (first, stale_second)],
    }, token=fixture.csrf())
    assert status == 409, body
    assert _ledger_count(fixture) == 0
    payload = {"request_id": "acceptance-once", "selections": [
        {"candidate_id": first["candidate_id"], "expected_revision": first["revision"]}]}
    status, outcome = fixture.request("/api/receipts/workflow/apply", payload, token=fixture.csrf())
    assert status == 200, outcome
    assert _ledger_count(fixture) == 1
    assert fixture.request("/api/receipts/workflow/apply", payload, token=fixture.csrf()) == (status, outcome)
    assert _ledger_count(fixture) == 1
    stored = _candidates(fixture, batch["batch_id"])
    assert sum(bool(candidate["applied"]) for candidate in stored) == 1


def test_missing_csrf_or_unknown_original_cannot_start_a_model(receipt_http):
    fixture, runtime = receipt_http
    payload = {"images": ["f" * 64], "provider": "claude", "model": "synthetic-opus",
               "request_id": "acceptance-forged-image"}
    status, body = fixture.request("/api/receipts/workflow/batches", payload)
    assert status == 403, body
    status, body = fixture.request("/api/receipts/workflow/batches", payload, token=fixture.csrf())
    assert status in (400, 404, 409), body
    assert runtime.calls == []
