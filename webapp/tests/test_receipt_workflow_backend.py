import hashlib
import json
import os
from pathlib import Path

import pytest

from app import receipt_vision
from webapp import receipt_workflow, receipt_workflow_store
from webapp.tests import test_receipt_review as legacy


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.handles = {}
        self.receipts = []
        self.archive_failures = 0
        self.prompt = "synthetic managed receipt prompt"
        self.metadata = {
            "prompt_version": "synthetic-v1",
            "prompt_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
            "schema_version": "synthetic-v1",
            "schema_sha256": hashlib.sha256(receipt_vision.SCHEMA_PATH.read_bytes()).hexdigest(),
        }

    def managed_prompt(self):
        return self.prompt

    def prompt_metadata(self):
        return dict(self.metadata)

    def catalog(self, provider=None):
        return {
            "connected": True,
            "host_label": "synthetic-local-PC",
            "checked_at": "2026-11-16T00:00:00Z",
            "providers": [{"id": "claude", "label": "Synthetic subscription", "available": True}],
            "models": [{"provider": "claude", "id": "synthetic-photo", "label": "Synthetic photo",
                        "selectable": True, "reason": "", "thinking_options": ["medium"],
                        "default_thinking": "medium"}],
        }

    def start(self, image_path, provider, model, *, run_key, **kwargs):
        body = Path(image_path).read_bytes()
        handle = {"agent_id": "synthetic-" + run_key, "workspace_id": "synthetic-only",
                  "provider": provider, "model": model,
                  "source_sha256": hashlib.sha256(body).hexdigest(), **self.metadata}
        self.calls.append((run_key, body))
        self.handles[run_key] = handle
        return handle

    def find_run(self, run_key):
        return self.handles.get(run_key)

    def inspect_run(self, handle):
        return {"status": "done", "result": {"source_sha256": handle["source_sha256"],
                                                "receipts": list(self.receipts)}}

    def archive_run(self, handle):
        if self.archive_failures:
            self.archive_failures -= 1
            raise RuntimeError("synthetic archive failure")


@pytest.fixture
def backend(monkeypatch):
    fixture = legacy.ReceiptReviewTests()
    fixture.setUp()
    from webapp import receipt_review
    workflow_path = Path(fixture._dir.name) / "receipt-workflow.sqlite"
    monkeypatch.setenv("WEBLEDGER_RECEIPT_WORKFLOW_DB", str(workflow_path))
    runtime = FakeRuntime()
    monkeypatch.setattr(receipt_workflow, "_runtime", lambda value=None: runtime)
    worker = receipt_workflow.ReceiptWorkflowWorker(
        receipts_path=fixture.store, board=fixture.server.card_store,
        runtime=runtime, interval=0.01)
    try:
        status, image = fixture.request("/api/receipts/image", raw=legacy.PNG,
                                        token=fixture.csrf())
        assert status == 200
        yield {"fixture": fixture, "runtime": runtime, "worker": worker,
               "image": image["sha256"], "workflow_path": workflow_path,
               "receipt_review": receipt_review}
    finally:
        worker.stop()
        fixture.doCleanups()


def _receipt(merchant="Synthetic shop", amount=1200, currency="JPY"):
    return {"merchant": merchant, "date": "2026-10-12", "amount": amount,
            "currency": currency, "payment": "private_card",
            "box": [0.05, 0.05, 0.45, 0.45], "confidence": 0.95}


def _start_batch(backend, request_id="a" * 32):
    batch = receipt_workflow.create_batch(
        backend["fixture"].server.card_store,
        {"images": [backend["image"]], "provider": "claude", "model": "synthetic-photo",
         "request_id": request_id}, receipts_path=backend["fixture"].store)["batch"]
    assert backend["worker"].process_once() is True  # queued -> starting -> sent
    assert backend["worker"].process_once() in (True, False)  # completion/archive result
    current = receipt_workflow.list_workflow(
        backend["fixture"].server.card_store, receipts_path=backend["fixture"].store)
    return batch, next(item for item in current["batches"]
                       if item["batch_id"] == batch["batch_id"])


def _review(backend, candidate, changes, *, selected=True):
    return receipt_workflow.review_candidate(
        {"candidate_id": candidate["candidate_id"], "expected_revision": candidate["revision"],
         "changes": changes, "selected": selected},
        receipts_path=backend["fixture"].store, board=backend["fixture"].server.card_store)["candidate"]


def test_candidates_start_unselected_and_reanalysis_keeps_one_canonical_review(backend):
    runtime = backend["runtime"]
    runtime.receipts = [_receipt()]
    first, saved_first = _start_batch(backend)
    original = saved_first["candidates"][0]
    assert original["selected"] is False
    edited = _review(backend, original, {"merchant": "Owner correction", "trip_id": backend["fixture"].trip,
                                         "category": "식비", "payment": "private_card",
                                         "company_expense": True})

    old_job = saved_first["jobs"][0]
    runtime.receipts = [_receipt(merchant="New model reading")]
    retry = receipt_workflow.retry_job(
        backend["fixture"].server.card_store,
        {"job_id": old_job["job_id"], "request_id": "b" * 32},
        receipts_path=backend["fixture"].store)["batch"]
    assert backend["worker"].process_once() is True
    assert backend["worker"].process_once() in (True, False)
    listed = receipt_workflow.list_workflow(
        backend["fixture"].server.card_store, receipts_path=backend["fixture"].store)["batches"]
    original_batch = next(item for item in listed if item["batch_id"] == first["batch_id"])
    retry_batch = next(item for item in listed if item["batch_id"] == retry["batch_id"])

    assert len(original_batch["candidates"]) == 1
    assert original_batch["candidates"][0]["candidate_id"] == edited["candidate_id"]
    assert original_batch["candidates"][0]["merchant"] == "Owner correction"
    assert original_batch["candidates"][0]["revision"] == edited["revision"]
    assert original_batch["candidates"][0]["selected"] is True
    assert retry_batch["candidates"] == []
    assert retry_batch["related_candidates"] == [{
        "candidate_id": edited["candidate_id"], "canonical_batch_id": first["batch_id"]}]
    assert retry_batch["jobs"][0]["candidate_ids"] == [edited["candidate_id"]]
    assert retry_batch["reanalyses"][0]["observations"][0]["receipt"]["merchant"] == "New model reading"
    assert sum(len(batch["candidates"]) for batch in listed) == 1


def test_archive_failure_is_persisted_and_retried_after_completion(backend):
    runtime = backend["runtime"]
    runtime.receipts = [_receipt()]
    runtime.archive_failures = 1
    batch = receipt_workflow.create_batch(
        backend["fixture"].server.card_store,
        {"images": [backend["image"]], "provider": "claude", "model": "synthetic-photo",
         "request_id": "c" * 32}, receipts_path=backend["fixture"].store)["batch"]
    assert backend["worker"].process_once() is True
    assert backend["worker"].process_once() is False
    job_id = batch["jobs"][0]["job_id"]
    store = receipt_workflow_store.ReceiptWorkflowStore(backend["workflow_path"])
    pending = store.read(lambda conn: conn.execute(
        "SELECT status,archive_pending,archive_attempts,archive_error FROM receipt_workflow_jobs "
        "WHERE job_id=?", (job_id,)).fetchone())
    assert tuple(pending) == ("done", 1, 1, "ARCHIVE_FAILED")
    replacement = receipt_workflow.ReceiptWorkflowWorker(
        receipts_path=backend["fixture"].store,
        board=backend["fixture"].server.card_store, runtime=runtime, interval=0.01)
    assert replacement.process_once() is True
    archived = store.read(lambda conn: conn.execute(
        "SELECT archive_pending,archive_attempts,archive_error FROM receipt_workflow_jobs "
        "WHERE job_id=?", (job_id,)).fetchone())
    assert tuple(archived) == (0, 1, "")


def test_private_card_jpy_record_keeps_payment_principal_currency_and_rate(backend):
    runtime = backend["runtime"]
    runtime.receipts = [_receipt()]
    _batch, saved = _start_batch(backend)
    candidate = saved["candidates"][0]
    reviewed = _review(backend, candidate, {
        "trip_id": backend["fixture"].trip,
        "category": "식비",
        "payment": "private_card",
        "company_expense": True,
    })
    board = backend["fixture"].server.card_store
    request = {"request_id": "d" * 32, "selections": [{
        "candidate_id": reviewed["candidate_id"], "expected_revision": reviewed["revision"]}]}
    result = receipt_workflow.apply_selected(
        board, request, receipts_path=backend["fixture"].store)
    assert result["outcome"] == "applied"
    row = json.loads(board.conn.execute(
        "SELECT payload_json FROM board_rows WHERE row_id=?",
        (result["results"][0]["ledger_id"],)).fetchone()[0])
    assert row["amount_krw"] == 12_000
    assert row["pay_method"] == "개인카드"
    assert row["receipt_payment"] == "private_card"
    assert row["receipt_amount_original"] == 1_200
    assert row["receipt_currency"] == "JPY"
    assert row["receipt_exchange_rate_krw_per_unit"] == 10
    assert "개인카드" in row["description"]
    assert "원금 1,200 JPY" in row["description"]
    assert "환산 10 KRW/JPY = 12,000 KRW" in row["description"]

    workflow_store = receipt_workflow_store.ReceiptWorkflowStore(backend["workflow_path"])
    workflow_store.read(lambda conn: conn.execute(
        "UPDATE receipt_workflow_candidates SET applied=0,ledger_id=NULL WHERE candidate_id=?",
        (reviewed["candidate_id"],)))
    with pytest.raises(receipt_workflow.WorkflowError) as error:
        receipt_workflow.review_candidate(
            {"candidate_id": reviewed["candidate_id"],
             "expected_revision": reviewed["revision"],
             "changes": {"merchant": "late stale correction"}, "selected": False},
            receipts_path=backend["fixture"].store, board=board)
    assert error.value.code == "CANDIDATE_ALREADY_APPLIED"
    current = workflow_store.read(lambda conn: conn.execute(
        "SELECT applied,ledger_id,review_json,revision,selected FROM receipt_workflow_candidates "
        "WHERE candidate_id=?", (reviewed["candidate_id"],)).fetchone())
    assert current[0] == 1
    assert current[1] == result["results"][0]["ledger_id"]
    assert json.loads(current[2])["merchant"] == "Synthetic shop"
    assert current[3] == reviewed["revision"]
    assert current[4] == 1


def test_corporate_card_receipt_links_evidence_without_changing_card_or_ledger(backend):
    from webapp.card_flow import CardFlow

    fixture = backend["fixture"]
    board = fixture.server.card_store
    flow = CardFlow(board)
    flow.trip_valid = lambda value, **kwargs: value == fixture.trip
    card_data = (
        "Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,"
        "Date,Post Date,Authorization Code,Cancel,Status\n"
        "국민,1234,overseas,purchase,합성 식당,12345,1200,JPY,12345,"
        "2026-10-12,2026-10-13,SYNTHETIC123,,매입\n"
    ).encode("utf-8")
    received = flow.pipeline.receive(card_data, "synthetic-corporate-receipt.csv")
    card = flow.pipeline.get_batch(received["batch_id"])["rows"][0]
    transaction_id = card["transaction_id"]
    flow.pipeline.save_decision(
        transaction_id, card["revision"], item="식비", display_tab_id=fixture.trip,
        trip_id=fixture.trip, request_id="synthetic-corporate-decision",
        trip_validator=flow.trip_valid, tab_validator=flow.tab_valid)
    assert flow.record_decision(received["batch_id"], transaction_id) == 1

    before_source = tuple(board.conn.execute(
        "SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone())
    before_ledger = board.conn.execute(
        "SELECT row_id,payload_json FROM board_rows WHERE row_kind='expense' ORDER BY row_id").fetchall()
    assert len(before_ledger) == 1
    card_source = board.conn.execute(
        "SELECT amount_krw,foreign_amount,foreign_currency,raw_row_json FROM transactions "
        "WHERE transaction_id=?", (transaction_id,)).fetchone()
    assert tuple(card_source[:3]) == (12345, "1200", "JPY")

    backend["runtime"].receipts = [_receipt(merchant="합성 식당")]
    batch, saved = _start_batch(backend, request_id="f" * 32)
    candidate = saved["candidates"][0]
    reviewed = _review(backend, candidate, {
        "trip_id": fixture.trip, "category": "식비", "payment": "corporate_card",
    })
    result = receipt_workflow.apply_selected(
        board, {"request_id": "9" * 32, "selections": [{
            "candidate_id": reviewed["candidate_id"],
            "expected_revision": reviewed["revision"],
        }]}, receipts_path=fixture.store)

    assert result["outcome"] == "applied"
    assert result["results"][0]["outcome"] == "evidence_linked"
    assert result["results"][0]["ledger_id"] == before_ledger[0][0]
    assert board.conn.execute(
        "SELECT row_id,payload_json FROM board_rows WHERE row_kind='expense' ORDER BY row_id").fetchall() == before_ledger
    assert tuple(board.conn.execute(
        "SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()) == before_source
    assert board.conn.execute(
        "SELECT amount_krw,foreign_amount,foreign_currency,raw_row_json FROM transactions "
        "WHERE transaction_id=?", (transaction_id,)).fetchone() == card_source
    evidence = board.conn.execute(
        "SELECT candidate_id,transaction_id,ledger_row_id,evidence_json FROM receipt_evidence_links"
    ).fetchall()
    assert len(evidence) == 1
    assert tuple(evidence[0][:3]) == (reviewed["candidate_id"], transaction_id, before_ledger[0][0])
    assert json.loads(evidence[0][3]) == {
        "amount": 1200, "currency": "JPY", "date": "2026-10-12",
        "merchant": "합성 식당", "candidate_id": reviewed["candidate_id"],
        "receipt_image_sha256": backend["image"],
    }
    assert board.conn.execute(
        "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'rcpt-%'").fetchone()[0] == 0
    assert batch["batch_id"] == saved["batch_id"]


def test_candidate_and_request_reads_are_scoped_to_owner(backend):
    runtime = backend["runtime"]
    runtime.receipts = [_receipt()]
    batch, saved = _start_batch(backend)
    candidate = saved["candidates"][0]
    _review(backend, candidate, {"trip_id": backend["fixture"].trip, "category": "식비",
                                 "payment": "cash"})
    board = backend["fixture"].server.card_store
    with pytest.raises(receipt_workflow.WorkflowError) as error:
        receipt_workflow.apply_selected(
            board, {"request_id": "e" * 32, "selections": [{
                "candidate_id": candidate["candidate_id"], "expected_revision": 2}]},
            owner_id="different-owner", receipts_path=backend["fixture"].store)
    assert error.value.code == "CANDIDATE_NOT_FOUND"
    with pytest.raises(receipt_workflow.WorkflowError) as error:
        receipt_workflow.create_batch(
            board, {"images": [backend["image"]], "provider": "claude",
                   "model": "synthetic-photo", "request_id": "a" * 32},
            owner_id="different-owner", receipts_path=backend["fixture"].store)
    assert error.value.code == "REQUEST_ID_REUSED"
    assert batch["batch_id"] == saved["batch_id"]


@pytest.mark.parametrize('code,terminal', [('PASEO_RUN_MISSING', True), ('PASEO_UNAVAILABLE', False)])
def test_inspect_distinguishes_missing_remote_run_from_disconnected_daemon(backend, code, terminal):
    from app.receipt_paseo import PaseoError
    runtime = backend['runtime']
    runtime.inspect_run = lambda handle: (_ for _ in ()).throw(PaseoError(code))
    _batch, saved = _start_batch(backend)
    job = saved['jobs'][0]
    assert job['status'] == ('failed' if terminal else 'running')
    if terminal:
        assert job['code'] == code
    assert len(runtime.calls) == 1
    assert not saved['candidates']


def test_retry_rechecks_late_remote_run_after_starting_recovery_reported_missing(backend):
    runtime = backend['runtime']
    original_inspect = runtime.inspect_run
    runtime.inspect_run = lambda handle: {'status': 'running'}
    _batch, saved = _start_batch(backend)
    job = saved['jobs'][0]
    store = receipt_workflow_store.ReceiptWorkflowStore(backend['workflow_path'])
    store.read(lambda conn: conn.execute(
        "UPDATE receipt_workflow_jobs SET status='starting',handle_json=NULL WHERE job_id=?", (job['job_id'],)))
    handles = dict(runtime.handles)
    runtime.handles.clear()
    assert backend['worker'].process_once() is True
    runtime.handles.update(handles)
    with pytest.raises(receipt_workflow.WorkflowError) as error:
        receipt_workflow.retry_job(backend['fixture'].server.card_store,
            {'job_id': job['job_id'], 'request_id': 'f' * 32}, receipts_path=backend['fixture'].store)
    assert error.value.code == 'JOB_STILL_ACTIVE'
    assert len(runtime.calls) == 1
    runtime.inspect_run = original_inspect


def test_starting_job_waits_through_uncertain_lookup_then_recovers_original_run(backend):
    from app.receipt_paseo import PaseoError
    runtime = backend['runtime']
    runtime.inspect_run = lambda handle: {'status': 'running'}
    _batch, saved = _start_batch(backend)
    job = saved['jobs'][0]
    store = receipt_workflow_store.ReceiptWorkflowStore(backend['workflow_path'])
    store.read(lambda conn: conn.execute(
        "UPDATE receipt_workflow_jobs SET status='starting',handle_json=NULL WHERE job_id=?", (job['job_id'],)))
    find = runtime.find_run
    runtime.find_run = lambda key: (_ for _ in ()).throw(PaseoError('PASEO_START_UNCERTAIN'))
    for _ in range(2):
        assert backend['worker'].process_once() is False
        assert store.read(lambda conn: conn.execute(
            'SELECT status FROM receipt_workflow_jobs WHERE job_id=?', (job['job_id'],)).fetchone()[0]) == 'starting'
        with pytest.raises(receipt_workflow.WorkflowError) as error:
            receipt_workflow.retry_job(backend['fixture'].server.card_store,
                {'job_id': job['job_id'], 'request_id': 'e' * 32}, receipts_path=backend['fixture'].store)
        assert error.value.code == 'JOB_STILL_ACTIVE'
    runtime.find_run = find
    assert backend['worker'].process_once() is True
    assert store.read(lambda conn: conn.execute(
        'SELECT status FROM receipt_workflow_jobs WHERE job_id=?', (job['job_id'],)).fetchone()[0]) == 'running'
    assert len(runtime.calls) == 1
