"""Independent HTTP acceptance with synthetic originals and a deterministic runtime.

These tests exercise the real workflow worker and COST ledger. They never call a
provider or use a production store, port, browser, or original.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from unittest.mock import patch

import pytest

from app import receipt_vision
from webapp import ledger_board
from webapp.tests import test_receipt_review as legacy


class SyntheticRuntime:
    def __init__(self, metadata, prompt):
        self.calls = []
        self.runs = {}
        self.release = threading.Event()
        self._metadata = dict(metadata)
        self._prompt = prompt

    def managed_prompt(self):
        return self._prompt

    def prompt_metadata(self):
        return dict(self._metadata)

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
    from webapp.receipt_workflow import ReceiptWorkflowWorker

    runtime = SyntheticRuntime(receipt_paseo.prompt_metadata(), receipt_paseo.managed_prompt())
    workflow_path = tmp_path / "acceptance-workflow.sqlite"
    monkeypatch.setenv("WEBLEDGER_RECEIPT_WORKFLOW_DB", str(workflow_path))
    monkeypatch.setenv("WEBLEDGER_RECEIPT_WORKFLOW_ENABLED", "1")
    for name in ("catalog", "prompt_metadata", "start", "find_run", "inspect_run", "archive_run"):
        monkeypatch.setattr(receipt_paseo, name, getattr(runtime, name))
    fixture = legacy.ReceiptReviewTests()
    fixture.workflow_path = workflow_path
    try:
        fixture.setUp()
        worker = ReceiptWorkflowWorker(receipts_path=fixture.store, board=fixture.server.card_store,
                                       runtime=runtime, interval=0.01)
        worker.start()
        fixture.workflow_worker = worker
        fixture.addCleanup(worker.stop)
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


def _enqueue(fixture, image, request_id="a" * 32):
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


def test_recreated_worker_reconnects_to_saved_run_without_resubmission(receipt_http):
    from webapp.receipt_workflow import ReceiptWorkflowWorker

    fixture, runtime = receipt_http
    batch = _enqueue(fixture, _upload(fixture))
    _wait_until(lambda: len(runtime.calls) == 1)
    fixture.workflow_worker.stop()
    replacement = ReceiptWorkflowWorker(receipts_path=fixture.store, board=fixture.server.card_store,
                                         runtime=runtime, interval=0.01)
    fixture.addCleanup(replacement.stop)
    replacement.start()
    runtime.release.set()
    _wait_until(lambda: _persisted_result(fixture))
    assert len(_candidates(fixture, batch["batch_id"])) == 2
    assert len(runtime.calls) == 1


def test_two_tabs_with_distinct_request_ids_reuse_one_ordinary_analysis(receipt_http):
    fixture, runtime = receipt_http
    image = _upload(fixture)
    first = _enqueue(fixture, image, request_id="1" * 32)
    second = _enqueue(fixture, image, request_id="2" * 32)
    assert second["batch_id"] == first["batch_id"]
    runtime.release.set()
    _wait_until(lambda: _persisted_result(fixture))
    assert len(runtime.calls) == 1


def test_stale_selection_rolls_back_whole_batch_and_replayed_apply_is_one_expense(receipt_http):
    fixture, runtime = receipt_http
    batch = _enqueue(fixture, _upload(fixture))
    runtime.release.set()
    _wait_until(lambda: _persisted_result(fixture))
    reviewed = [_review(fixture, candidate)
                for candidate in _candidates(fixture, batch["batch_id"])]
    first = next(candidate for candidate in reviewed if candidate["currency"] == "JPY")
    second = next(candidate for candidate in reviewed if candidate["currency"] == "KRW")
    stale_second = dict(second)
    second = _review(fixture, second, merchant="합성 교정 상호")
    status, body = fixture.request("/api/receipts/workflow/apply", {
        "request_id": "b" * 32,
        "selections": [{"candidate_id": candidate["candidate_id"],
                        "expected_revision": candidate["revision"]} for candidate in (first, stale_second)],
    }, token=fixture.csrf())
    assert status == 409, body
    assert _ledger_count(fixture) == 0
    payload = {"request_id": "c" * 32, "selections": [
        {"candidate_id": first["candidate_id"], "expected_revision": first["revision"]}]}
    status, outcome = fixture.request("/api/receipts/workflow/apply", payload, token=fixture.csrf())
    assert status == 200, outcome
    assert _ledger_count(fixture) == 1
    assert fixture.request("/api/receipts/workflow/apply", payload, token=fixture.csrf()) == (status, outcome)
    assert _ledger_count(fixture) == 1
    record = json.loads(fixture.server.card_store.conn.execute(
        "SELECT payload_json FROM board_rows WHERE row_id LIKE 'rcpt-%'").fetchone()[0])
    assert record["amount_krw"] == 12000
    stored = _candidates(fixture, batch["batch_id"])
    assert sum(bool(candidate["applied"]) for candidate in stored) == 1


def test_missing_csrf_or_unknown_original_cannot_start_a_model(receipt_http):
    fixture, runtime = receipt_http
    payload = {"images": ["f" * 64], "provider": "claude", "model": "synthetic-opus",
               "request_id": "d" * 32}
    status, body = fixture.request("/api/receipts/workflow/batches", payload)
    assert status == 403, body
    status, body = fixture.request("/api/receipts/workflow/batches", payload, token=fixture.csrf())
    assert status in (400, 404, 409), body
    assert runtime.calls == []


def test_committed_ledger_recovers_when_workflow_acknowledgement_is_lost(receipt_http):
    fixture, runtime = receipt_http
    batch = _enqueue(fixture, _upload(fixture))
    runtime.release.set()
    _wait_until(lambda: _persisted_result(fixture))
    candidate = _review(fixture, _candidates(fixture, batch["batch_id"])[0])
    payload = {"request_id": "8" * 32, "selections": [{
        "candidate_id": candidate["candidate_id"], "expected_revision": candidate["revision"]}]}
    board = fixture.server.card_store
    original_apply = board.apply_receipt_batch

    def committed_without_workflow_ack(**kwargs):
        original_apply(**kwargs)
        raise RuntimeError("synthetic failure after authoritative ledger commit")

    with patch.object(board, "apply_receipt_batch", side_effect=committed_without_workflow_ack):
        status, body = fixture.request("/api/receipts/workflow/apply", payload, token=fixture.csrf())
    assert status == 503, body
    assert _ledger_count(fixture) == 1
    # A direct edit before any GET must also consult the financial authority.
    # Otherwise the workflow could accept changes to an already posted cost.
    status, body = fixture.request("/api/receipts/workflow/review", {
        "candidate_id": candidate["candidate_id"], "expected_revision": candidate["revision"],
        "changes": {"merchant": "교정하면 안 되는 이미 반영된 내역"},
    }, token=fixture.csrf())
    assert status == 409, body
    # A newly read workflow must reconcile from the ledger's committed source,
    # even though its own update rolled back after the injected failure.
    saved = next(item for item in _candidates(fixture, batch["batch_id"])
                 if item["candidate_id"] == candidate["candidate_id"])
    assert saved["applied"] is True
    status, result = fixture.request("/api/receipts/workflow/apply", payload, token=fixture.csrf())
    assert status == 200, result
    assert result["results"][0]["ledger_id"] == saved["ledger_id"]
    assert _ledger_count(fixture) == 1


def test_mixed_photo_batch_preserves_success_failure_and_empty_result(receipt_http, monkeypatch):
    fixture, runtime = receipt_http
    images = []
    for rgb in (b"\xff\x00\x00", b"\x00\xff\x00", b"\x00\x00\xff"):
        status, image = fixture.request("/api/receipts/image", raw=legacy.make_png(rgb),
                                        token=fixture.csrf())
        assert status == 200, image
        images.append(image["sha256"])
    original_inspect = runtime.inspect_run

    def inspect(handle):
        if not runtime.release.is_set():
            return {"status": "running"}
        if handle["source_sha256"] == images[1]:
            return {"status": "failed", "code": "PASEO_RATE_LIMITED"}
        if handle["source_sha256"] == images[2]:
            return {"status": "done", "result": receipt_vision.validate_response(
                {"receipts": []}, image_hash=images[2], model=handle["model"])}
        return original_inspect(handle)

    monkeypatch.setattr(runtime, "inspect_run", inspect)
    status, body = fixture.request("/api/receipts/workflow/batches", {
        "images": images, "provider": "claude", "model": "synthetic-opus",
        "request_id": "e" * 32,
    }, token=fixture.csrf())
    assert status == 202, body
    batch_id = body["batch"]["batch_id"]
    runtime.release.set()

    def finished():
        status, result = fixture.request("/api/receipts/workflow")
        assert status == 200, result
        batch = next(item for item in result["batches"] if item["batch_id"] == batch_id)
        return batch if all(job["status"] in ("done", "failed") for job in batch["jobs"]) else None

    _wait_until(finished)
    batch = finished()
    by_image = {job["image"]: job for job in batch["jobs"]}
    assert by_image[images[0]]["status"] == "done"
    assert by_image[images[1]]["status"] == "failed"
    assert by_image[images[1]]["code"] == "PASEO_RATE_LIMITED"
    assert by_image[images[2]]["status"] == "done"
    assert len(batch["candidates"]) == 2
    assert {candidate["image"] for candidate in batch["candidates"]} == {images[0]}
    assert len(runtime.calls) == 3
    assert _ledger_count(fixture) == 0
    for image in images:
        assert fixture.request("/api/receipts/image/" + image)[0] == 200


def test_result_for_another_original_is_preserved_as_failure_without_candidates(receipt_http, monkeypatch):
    fixture, runtime = receipt_http
    original_inspect = runtime.inspect_run

    def inspect(handle):
        state = original_inspect(handle)
        if state["status"] == "done":
            state["result"]["source_sha256"] = "f" * 64
        return state

    monkeypatch.setattr(runtime, "inspect_run", inspect)
    batch = _enqueue(fixture, _upload(fixture))
    runtime.release.set()

    def failed():
        status, body = fixture.request("/api/receipts/workflow")
        assert status == 200, body
        current = next(item for item in body["batches"] if item["batch_id"] == batch["batch_id"])
        return current if current["jobs"][0]["status"] == "failed" else None

    _wait_until(failed)
    current = failed()
    assert current["jobs"][0]["code"] == "RESULT_SOURCE_MISMATCH"
    assert current["candidates"] == []
    assert len(runtime.calls) == 1
    assert _ledger_count(fixture) == 0


def test_corporate_receipt_attaches_evidence_without_repricing_or_creating_expense(receipt_http):
    from webapp.card_flow import CardFlow

    fixture, runtime = receipt_http
    board = fixture.server.card_store
    flow = CardFlow(board)
    # The fixture owns one synthetic trip and has no live Google workbook.
    flow.trip_valid = lambda value, **kwargs: value == fixture.trip
    card_data = (
        "Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,"
        "Date,Post Date,Authorization Code,Cancel,Status\n"
        "국민,1234,overseas,purchase,합성 식당,12345,1200,JPY,12345,"
        "2026-10-12,2026-10-13,SYNTHETIC123,,매입\n"
    ).encode("utf-8")
    received = flow.pipeline.receive(card_data, "synthetic-corporate-receipt.csv")
    card_batch = flow.pipeline.get_batch(received["batch_id"])
    assert len(card_batch["rows"]) == 1, card_batch
    card = card_batch["rows"][0]
    transaction_id = card["transaction_id"]
    flow.pipeline.save_decision(
        transaction_id, card["revision"], item="식비", display_tab_id=fixture.trip,
        trip_id=fixture.trip, request_id="synthetic-corporate-decision",
        trip_validator=flow.trip_valid, tab_validator=flow.tab_valid)
    assert flow.record_decision(received["batch_id"], transaction_id) == 1
    before_source = tuple(board.conn.execute(
        "SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone())
    before_rows = board.conn.execute(
        "SELECT row_id,payload_json FROM board_rows WHERE row_kind='expense' ORDER BY row_id").fetchall()
    assert len(before_rows) == 1
    batch = _enqueue(fixture, _upload(fixture))
    runtime.release.set()
    _wait_until(lambda: _persisted_result(fixture))
    candidate = next(item for item in _candidates(fixture, batch["batch_id"])
                     if item["currency"] == "JPY")
    candidate = _review(fixture, candidate, payment="corporate_card")
    status, result = fixture.request("/api/receipts/workflow/apply", {
        "request_id": "9" * 32,
        "selections": [{"candidate_id": candidate["candidate_id"],
                        "expected_revision": candidate["revision"]}],
    }, token=fixture.csrf())
    assert status == 200, result
    assert result["results"][0]["outcome"] == "evidence_linked"
    assert result["results"][0]["ledger_id"] == before_rows[0][0]
    assert board.conn.execute(
        "SELECT row_id,payload_json FROM board_rows WHERE row_kind='expense' ORDER BY row_id").fetchall() == before_rows
    assert tuple(board.conn.execute(
        "SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()) == before_source
    assert _ledger_count(fixture) == 0
    assert board.conn.execute("SELECT COUNT(*) FROM receipt_evidence_links").fetchone()[0] == 1


@pytest.mark.parametrize("path", ["/api/receipts/paseo/models", "/api/receipts/workflow",
                                 "/api/receipts/workflow/batches", "/api/receipts/workflow/review",
                                 "/api/receipts/workflow/apply", "/api/receipts/workflow/retry"])
def test_every_workflow_route_refuses_non_owner(receipt_http, path):
    fixture, runtime = receipt_http
    with patch.object(ledger_board, "_receipts_owner_request", return_value=False):
        assert fixture.request(path)[0] == 403
        assert fixture.request(path, {}, token=fixture.csrf())[0] == 403
    assert runtime.calls == []


@pytest.mark.parametrize("path", ["/api/receipts/workflow/batches", "/api/receipts/workflow/review",
                                 "/api/receipts/workflow/apply", "/api/receipts/workflow/retry"])
def test_mutation_routes_do_not_accept_get(receipt_http, path):
    fixture, runtime = receipt_http
    assert fixture.request(path)[0] == 405
    assert runtime.calls == []
