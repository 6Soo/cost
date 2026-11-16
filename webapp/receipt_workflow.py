"""Owner API and durable worker for local Paseo receipt analysis."""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import receipt_workflow_store as workflow_db
from .ledger_store import SaveError


ROUTES = {
    "/api/receipts/paseo/models",
    "/api/receipts/workflow",
    "/api/receipts/workflow/batches",
    "/api/receipts/workflow/review",
    "/api/receipts/workflow/apply",
    "/api/receipts/workflow/retry",
}
_REQUEST_ID = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOG = logging.getLogger("cost.receipt_workflow")


class WorkflowError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(code)


def enabled() -> bool:
    """Keep the feature and its startup worker off unless operations enable it."""
    from . import receipt_review
    return (receipt_review.enabled()
            and os.environ.get("WEBLEDGER_RECEIPT_WORKFLOW_ENABLED") == "1")


def owns_route(path: str) -> bool:
    return path in ROUTES


def _runtime(runtime=None):
    if runtime is not None:
        return runtime
    try:
        return importlib.import_module("app.receipt_paseo")
    except ImportError:
        raise WorkflowError("PASEO_RUNTIME_UNAVAILABLE", 503) from None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(value) -> str:
    try:
        raw = workflow_db.canonical(value).encode("utf-8")
    except (TypeError, ValueError):
        raise WorkflowError("INVALID_VALUE") from None
    return hashlib.sha256(raw).hexdigest()


def _workflow_store(receipts_path=None):
    from . import receipt_review
    path = receipts_path or receipt_review._store_path()
    return workflow_db.ReceiptWorkflowStore(workflow_db.configured_path(Path(path)))


def _prompt_metadata(runtime) -> dict:
    """Pin the runtime's exact managed prompt and the locally validated schema."""
    try:
        from app import receipt_vision
        prompt_getter = getattr(runtime, "managed_prompt", None)
        if not callable(prompt_getter):
            raise ValueError("managed prompt getter missing")
        prompt = prompt_getter()
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("managed prompt invalid")
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        schema_hash = hashlib.sha256(receipt_vision.SCHEMA_PATH.read_bytes()).hexdigest()
    except Exception:
        raise WorkflowError("PROMPT_PIN_UNAVAILABLE", 503) from None
    getter = getattr(runtime, "prompt_metadata", None)
    if not callable(getter):
        raise WorkflowError("PASEO_PROMPT_PIN_UNAVAILABLE", 503)
    try:
        metadata = getter()
    except Exception:
        raise WorkflowError("PASEO_PROMPT_PIN_UNAVAILABLE", 503) from None
    if (not isinstance(metadata, dict)
            or not all(isinstance(metadata.get(key), str) and metadata[key]
                       for key in ("prompt_version", "prompt_sha256", "schema_version", "schema_sha256"))
            or not _SHA256.fullmatch(metadata["prompt_sha256"])
            or not _SHA256.fullmatch(metadata["schema_sha256"])):
        raise WorkflowError("PASEO_PROMPT_PIN_INVALID", 503)
    if metadata["prompt_sha256"] != prompt_hash or metadata["schema_sha256"] != schema_hash:
        raise WorkflowError("PASEO_PROMPT_PIN_MISMATCH", 503)
    return {key: metadata[key] for key in
            ("prompt_version", "prompt_sha256", "schema_version", "schema_sha256")}


def _catalog(runtime, provider=None) -> dict:
    try:
        result = runtime.catalog(provider=provider)
    except Exception as error:
        code = getattr(error, "code", "PASEO_CATALOG_UNAVAILABLE")
        raise WorkflowError(str(code), 503) from None
    if not isinstance(result, dict) or type(result.get("connected")) is not bool:
        raise WorkflowError("PASEO_CATALOG_INVALID", 503)
    if not isinstance(result.get("providers"), list) or not isinstance(result.get("models"), list):
        raise WorkflowError("PASEO_CATALOG_INVALID", 503)
    return result


def _select_model(runtime, provider: str, model_id: str) -> tuple[dict, dict]:
    catalog = _catalog(runtime, provider)
    if not catalog.get("connected"):
        raise WorkflowError("PASEO_UNAVAILABLE", 503)
    model = next((item for item in catalog["models"]
                  if isinstance(item, dict) and item.get("provider") == provider
                  and item.get("id") == model_id), None)
    if model is None or model.get("selectable") is not True:
        raise WorkflowError("MODEL_NOT_SELECTABLE", 422)
    if not isinstance(model.get("thinking_options", []), list):
        raise WorkflowError("PASEO_CATALOG_INVALID", 503)
    default_thinking = model.get("default_thinking")
    options = model.get("thinking_options", [])
    if default_thinking is not None and default_thinking not in options:
        raise WorkflowError("PASEO_CATALOG_INVALID", 503)
    return catalog, model


def _source_store(receipts_path):
    from . import receipt_review
    try:
        return receipt_review.load(Path(receipts_path))
    except receipt_review.ReceiptStoreError:
        raise WorkflowError("RECEIPT_STORE_UNAVAILABLE", 503) from None


def _check_images(receipts_path: Path, hashes: list[str]) -> None:
    from . import receipt_review
    saved = _source_store(receipts_path)
    owned = set(saved.get("images", []))
    if any(image not in owned for image in hashes):
        raise WorkflowError("IMAGE_NOT_OWNED", 404)
    for image in hashes:
        try:
            receipt_review.image_bytes(receipts_path, image)
        except (OSError, KeyError, receipt_review.ReceiptStoreError):
            raise WorkflowError("IMAGE_SOURCE_INVALID", 422) from None


def _resolve_selected_catalog(catalog, provider: str, model_id: str) -> dict:
    model = next((item for item in catalog.get("models", [])
                  if isinstance(item, dict) and item.get("provider") == provider
                  and item.get("id") == model_id), None)
    if model is None or model.get("selectable") is not True:
        raise WorkflowError("MODEL_NOT_SELECTABLE", 422)
    if not isinstance(model.get("thinking_options", []), list):
        raise WorkflowError("PASEO_CATALOG_INVALID", 503)
    default_thinking = model.get("default_thinking")
    if default_thinking is not None and default_thinking not in model.get("thinking_options", []):
        raise WorkflowError("PASEO_CATALOG_INVALID", 503)
    return model


def _analysis_signature(images, provider, model_id, thinking, pin) -> str:
    return _digest({"images": sorted(images), "provider": provider, "model": model_id,
                    "thinking": thinking,
                    "prompt_version": pin["prompt_version"],
                    "prompt_sha256": pin["prompt_sha256"],
                    "schema_version": pin["schema_version"],
                    "schema_sha256": pin["schema_sha256"]})


def _request_batch(conn, request_id, request_hash, owner_id):
    prior = conn.execute(
        "SELECT r.request_hash,r.batch_id,b.owner_id FROM receipt_workflow_requests r "
        "JOIN receipt_workflow_batches b USING(batch_id) WHERE r.request_id=?",
        (request_id,)).fetchone()
    if prior:
        if prior["owner_id"] != owner_id:
            raise WorkflowError("REQUEST_ID_REUSED", 409)
        if prior["request_hash"] != request_hash:
            raise WorkflowError("REQUEST_ID_REUSED", 409)
        return _batch_payload(conn, prior["batch_id"])
    # Backwards compatibility for a pre-alias DB written by an earlier build.
    prior = conn.execute(
        "SELECT batch_id,request_hash,owner_id FROM receipt_workflow_batches WHERE request_id=?",
        (request_id,)).fetchone()
    if prior:
        if prior["owner_id"] != owner_id:
            raise WorkflowError("REQUEST_ID_REUSED", 409)
        if prior["request_hash"] != request_hash:
            raise WorkflowError("REQUEST_ID_REUSED", 409)
        conn.execute(
            "INSERT OR IGNORE INTO receipt_workflow_requests(request_id,request_hash,batch_id,created_at)"
            " VALUES (?,?,?,?)", (request_id, request_hash, prior["batch_id"], _now()))
        return _batch_payload(conn, prior["batch_id"])
    return None


def _job_public(row, conn=None) -> dict:
    result = {"job_id": row["job_id"], "image": row["image_sha256"],
              "status": row["status"]}
    if row["code"]:
        result["code"] = row["code"]
    if conn is not None:
        result["candidate_ids"] = [item[0] for item in conn.execute(
            "SELECT candidate_id FROM receipt_workflow_job_candidates WHERE job_id=? "
            "ORDER BY result_ordinal,candidate_id", (row["job_id"],))]
    return result


def _candidate_public(row) -> dict:
    review = json.loads(row["review_json"])
    model = json.loads(row["model_json"])
    return {
        "candidate_id": row["candidate_id"], "image": row["image_sha256"],
        "revision": row["revision"], "selected": bool(row["selected"]),
        "merchant": review.get("merchant"), "date": review.get("date"),
        "amount": review.get("amount"), "currency": review.get("currency"),
        "payment": review.get("payment"), "trip_id": review.get("trip_id"),
        "category": review.get("category"), "box": review.get("box"),
        "applied": bool(row["applied"]), "ledger_id": row["ledger_id"],
        "company_expense": review.get("company_expense"),
        "trip_source": review.get("trip_source"),
        "note": model.get("note"), "confidence": model.get("confidence"),
        "uncertain_fields": model.get("uncertain_fields", []),
        "model": model,
    }


def _batch_payload(conn, batch_id: str) -> dict:
    batch = conn.execute("SELECT * FROM receipt_workflow_batches WHERE batch_id=?",
                         (batch_id,)).fetchone()
    if batch is None:
        raise WorkflowError("BATCH_NOT_FOUND", 404)
    jobs = conn.execute("SELECT * FROM receipt_workflow_jobs WHERE batch_id=? ORDER BY created_at,job_id",
                        (batch_id,)).fetchall()
    candidates = conn.execute(
        "SELECT * FROM receipt_workflow_candidates WHERE batch_id=? ORDER BY created_at,candidate_id",
        (batch_id,)).fetchall()
    links = conn.execute(
        "SELECT jc.job_id,jc.result_ordinal,jc.candidate_id,jc.source_identity,"
        "c.batch_id AS canonical_batch_id FROM receipt_workflow_job_candidates jc "
        "JOIN receipt_workflow_jobs j USING(job_id) "
        "JOIN receipt_workflow_candidates c USING(candidate_id) "
        "WHERE j.batch_id=? ORDER BY j.created_at,j.job_id,jc.result_ordinal,jc.candidate_id",
        (batch_id,)).fetchall()
    related = {}
    for link in links:
        if link["canonical_batch_id"] != batch_id:
            related.setdefault(link["candidate_id"], link["canonical_batch_id"])
    reanalyses = []
    for job in jobs:
        job_links = [link for link in links if link["job_id"] == job["job_id"]]
        foreign_links = [link for link in job_links if link["canonical_batch_id"] != batch_id]
        if not foreign_links or not job["result_json"]:
            continue
        result = json.loads(job["result_json"])
        receipts = result.get("receipts", []) if isinstance(result, dict) else []
        observations = []
        for link in foreign_links:
            ordinal = link["result_ordinal"]
            observation = receipts[ordinal] if isinstance(receipts, list) and 0 <= ordinal < len(receipts) else None
            observations.append({
                "candidate_id": link["candidate_id"],
                "canonical_batch_id": link["canonical_batch_id"],
                "result_ordinal": ordinal,
                "receipt": observation,
            })
        reanalyses.append({"job_id": job["job_id"], "image": job["image_sha256"],
                           "result": result, "observations": observations})
    return {"batch_id": batch["batch_id"], "created_at": batch["created_at"],
            "provider": batch["provider"], "model": batch["model"],
            "status": batch["status"], "jobs": [_job_public(job, conn) for job in jobs],
            "candidates": [_candidate_public(candidate) for candidate in candidates],
            "related_candidates": [{"candidate_id": candidate_id,
                                    "canonical_batch_id": canonical_batch_id}
                                   for candidate_id, canonical_batch_id in related.items()],
            "reanalyses": reanalyses}


def _refresh_batch(conn, batch_id: str) -> None:
    statuses = [row[0] for row in conn.execute(
        "SELECT status FROM receipt_workflow_jobs WHERE batch_id=?", (batch_id,))]
    if not statuses:
        status = "failed"
    elif any(value in ("queued", "starting", "running") for value in statuses):
        status = "running" if any(value != "queued" for value in statuses) else "queued"
    elif all(value == "done" for value in statuses):
        status = "done"
    elif all(value == "failed" for value in statuses):
        status = "failed"
    else:
        status = "partial"
    conn.execute("UPDATE receipt_workflow_batches SET status=? WHERE batch_id=?",
                 (status, batch_id))


def create_batch(board, payload: dict, *, owner_id="owner", receipts_path=None) -> dict:
    from . import receipt_review
    if not isinstance(payload, dict) or set(payload) != {"images", "provider", "model", "request_id"}:
        raise WorkflowError("INVALID_VALUE", 422)
    images, provider, model_id, request_id = (payload.get("images"), payload.get("provider"),
                                               payload.get("model"), payload.get("request_id"))
    if (not isinstance(images, list) or not 1 <= len(images) <= 50
            or any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in images)
            or len(set(images)) != len(images)):
        raise WorkflowError("INVALID_VALUE", 422)
    if (not isinstance(provider, str) or not provider or len(provider) > 120
            or not isinstance(model_id, str) or not model_id or len(model_id) > 200
            or not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id)):
        raise WorkflowError("INVALID_VALUE", 422)
    receipts_path = Path(receipts_path or receipt_review._store_path())
    store = _workflow_store(receipts_path)
    request_hash = _digest(payload)
    with store.transaction() as conn:
        prior = _request_batch(conn, request_id, request_hash, owner_id)
        if prior:
            return {"batch": prior}
        runtime = _runtime()
        catalog, model = _select_model(runtime, provider, model_id)
        pin = _prompt_metadata(runtime)
        _check_images(receipts_path, images)
        thinking = model.get("default_thinking")
        signature = _analysis_signature(images, provider, model_id, thinking, pin)
        equivalent = conn.execute(
            "SELECT batch_id FROM receipt_workflow_batches "
            "WHERE owner_id=? AND analysis_signature=? AND explicit_retry=0 "
            "ORDER BY created_at,batch_id LIMIT 1", (owner_id, signature)).fetchone()
        if equivalent:
            conn.execute(
                "INSERT INTO receipt_workflow_requests(request_id,request_hash,batch_id,created_at)"
                " VALUES (?,?,?,?)", (request_id, request_hash, equivalent["batch_id"], _now()))
            return {"batch": _batch_payload(conn, equivalent["batch_id"])}
        batch_id, now = uuid.uuid4().hex, _now()
        conn.execute(
            "INSERT INTO receipt_workflow_batches(batch_id,owner_id,request_id,request_hash,provider,model,"
            "thinking,prompt_version,prompt_sha256,schema_version,schema_sha256,host_label,"
            "catalog_checked_at,analysis_signature,explicit_retry,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, owner_id, request_id, request_hash, provider, model_id,
             thinking, pin["prompt_version"], pin["prompt_sha256"],
             pin["schema_version"], pin["schema_sha256"],
             str(catalog.get("host_label") or ""), str(catalog.get("checked_at") or ""),
             signature, 0, "queued", now))
        conn.execute(
            "INSERT INTO receipt_workflow_requests(request_id,request_hash,batch_id,created_at)"
            " VALUES (?,?,?,?)", (request_id, request_hash, batch_id, now))
        for image in images:
            job_id = uuid.uuid4().hex
            run_key = hashlib.sha256(f"{batch_id}:{job_id}:{image}".encode()).hexdigest()
            conn.execute(
                "INSERT INTO receipt_workflow_jobs(job_id,batch_id,image_sha256,run_key,status,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?)", (job_id, batch_id, image, run_key, "queued", now, now))
        result = {"batch": _batch_payload(conn, batch_id)}
    worker = getattr(board, "_receipt_workflow_worker", None)
    if worker is not None:
        worker.wake()
    return result


def retry_job(board, payload: dict, *, owner_id="owner", receipts_path=None) -> dict:
    from . import receipt_review
    if (not isinstance(payload, dict) or set(payload) != {"job_id", "request_id"}
            or not isinstance(payload.get("job_id"), str)
            or not isinstance(payload.get("request_id"), str)
            or not _REQUEST_ID.fullmatch(payload["request_id"])):
        raise WorkflowError("INVALID_VALUE", 422)
    receipts_path = Path(receipts_path or receipt_review._store_path())
    store = _workflow_store(receipts_path)
    request_id, job_id = payload["request_id"], payload["job_id"]
    request_hash = _digest(payload)
    with store.transaction() as conn:
        prior = _request_batch(conn, request_id, request_hash, owner_id)
        if prior:
            return {"batch": prior}
        old = conn.execute(
            "SELECT j.*,b.provider,b.model,b.thinking,b.prompt_version,b.prompt_sha256,"
            "b.schema_version,b.schema_sha256,b.host_label,b.catalog_checked_at,b.analysis_signature "
            "FROM receipt_workflow_jobs j JOIN receipt_workflow_batches b USING(batch_id) "
            "WHERE j.job_id=? AND b.owner_id=?", (job_id, owner_id)).fetchone()
        if old is None:
            raise WorkflowError("JOB_NOT_FOUND", 404)
        if old["status"] not in ("done", "failed"):
            raise WorkflowError("JOB_STILL_ACTIVE", 409)
        runtime = _runtime()
        if old["status"] == "failed" and old["code"] in {
                "RUN_START_UNCERTAIN", "RUNTIME_HANDLE_INVALID"}:
            try:
                found = runtime.find_run(old["run_key"])
            except Exception:
                raise WorkflowError("RUN_STATE_UNKNOWN", 409) from None
            if isinstance(found, dict) and found.get("agent_id"):
                try:
                    remote = runtime.inspect_run(found)
                except Exception:
                    raise WorkflowError("RUN_STATE_UNKNOWN", 409) from None
                if not isinstance(remote, dict) or remote.get("status") not in ("running", "done", "failed"):
                    raise WorkflowError("RUN_STATE_UNKNOWN", 409)
                if remote["status"] == "running":
                    raise WorkflowError("JOB_STILL_ACTIVE", 409)
                if remote["status"] == "done":
                    conn.execute(
                        "UPDATE receipt_workflow_jobs SET handle_json=?,status='running',code=NULL,updated_at=? "
                        "WHERE job_id=? AND status='failed'",
                        (workflow_db.canonical(found), _now(), job_id))
                    _refresh_batch(conn, old["batch_id"])
                    result = {"batch": _batch_payload(conn, old["batch_id"])}
                    worker = getattr(board, "_receipt_workflow_worker", None)
                    if worker is not None:
                        worker.wake()
                    return result
        catalog = _catalog(runtime, old["provider"])
        model = _resolve_selected_catalog(catalog, old["provider"], old["model"])
        pin = _prompt_metadata(runtime)
        stored_pin = {key: old[key] for key in
                      ("prompt_version", "prompt_sha256", "schema_version", "schema_sha256")}
        if pin != stored_pin:
            raise WorkflowError("PASEO_PROMPT_CHANGED", 409)
        _check_images(receipts_path, [old["image_sha256"]])
        batch_id, now, new_job_id = uuid.uuid4().hex, _now(), uuid.uuid4().hex
        signature = _analysis_signature([old["image_sha256"]], old["provider"], old["model"],
                                        old["thinking"], stored_pin)
        conn.execute(
            "INSERT INTO receipt_workflow_batches(batch_id,owner_id,request_id,request_hash,provider,model,"
            "thinking,prompt_version,prompt_sha256,schema_version,schema_sha256,host_label,"
            "catalog_checked_at,analysis_signature,explicit_retry,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, owner_id, request_id, request_hash, old["provider"], old["model"],
             old["thinking"], old["prompt_version"], old["prompt_sha256"],
             old["schema_version"], old["schema_sha256"], old["host_label"],
             old["catalog_checked_at"], signature, 1, "queued", now))
        conn.execute(
            "INSERT INTO receipt_workflow_requests(request_id,request_hash,batch_id,created_at)"
            " VALUES (?,?,?,?)", (request_id, request_hash, batch_id, now))
        run_key = hashlib.sha256(f"{batch_id}:{new_job_id}:{old['image_sha256']}".encode()).hexdigest()
        conn.execute(
            "INSERT INTO receipt_workflow_jobs(job_id,batch_id,image_sha256,run_key,status,attempts,retry_of_job,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (new_job_id, batch_id, old["image_sha256"], run_key, "queued",
             int(old["attempts"]) + 1, job_id, now, now))
        result = {"batch": _batch_payload(conn, batch_id)}
    worker = getattr(board, "_receipt_workflow_worker", None)
    if worker is not None:
        worker.wake()
    return result


def _review_change(value: dict) -> dict:
    if not isinstance(value, dict):
        raise WorkflowError("INVALID_VALUE", 422)
    allowed = {"merchant", "date", "amount", "currency", "payment", "trip_id", "category", "company_expense"}
    if set(value) - allowed:
        raise WorkflowError("FIELD_NOT_EDITABLE", 422)
    result = {}
    for key, item in value.items():
        if key in ("merchant", "date", "trip_id", "category"):
            if item is not None and not isinstance(item, str):
                raise WorkflowError("INVALID_VALUE", 422)
            if isinstance(item, str) and len(item) > (240 if key in ("merchant", "category") else 64):
                raise WorkflowError("INVALID_VALUE", 422)
            result[key] = item.strip() if isinstance(item, str) else None
        elif key == "amount":
            if item is not None and (type(item) is not int or not 0 < item <= 1_000_000_000):
                raise WorkflowError("INVALID_VALUE", 422)
            result[key] = item
        elif key == "currency":
            if item is not None and item not in ("JPY", "KRW"):
                raise WorkflowError("CURRENCY_UNKNOWN", 422)
            result[key] = item
        elif key == "payment":
            if item is not None and item not in ("cash", "private_card", "corporate_card"):
                raise WorkflowError("PAYMENT_UNKNOWN", 422)
            result[key] = item
        elif key == "company_expense":
            if item is not None and type(item) is not bool:
                raise WorkflowError("INVALID_VALUE", 422)
            result[key] = item
    return result


def review_candidate(payload: dict, *, owner_id="owner", receipts_path=None, board=None) -> dict:
    if (not isinstance(payload, dict)
            or set(payload) - {"candidate_id", "expected_revision", "changes", "selected"}
            or not isinstance(payload.get("candidate_id"), str)
            or type(payload.get("expected_revision")) is not int
            or payload["expected_revision"] < 1
            or "changes" not in payload):
        raise WorkflowError("INVALID_VALUE", 422)
    if "selected" in payload and type(payload["selected"]) is not bool:
        raise WorkflowError("INVALID_VALUE", 422)
    changes = _review_change(payload["changes"])
    from . import receipt_review
    path = Path(receipts_path or receipt_review._store_path())
    store = _workflow_store(path)
    recovered_ledger_id = None
    with store.transaction() as conn:
        row = conn.execute(
            "SELECT c.* FROM receipt_workflow_candidates c "
            "JOIN receipt_workflow_batches b USING(batch_id) "
            "WHERE c.candidate_id=? AND b.owner_id=?",
            (payload["candidate_id"], owner_id)).fetchone()
        if row is None:
            raise WorkflowError("CANDIDATE_NOT_FOUND", 404)
        if row["applied"]:
            raise WorkflowError("CANDIDATE_ALREADY_APPLIED", 409)
        if board is not None:
            from . import receipt_ledger
            authoritative = receipt_ledger.applied_sources(board, [row["candidate_id"]])
            recovered_ledger_id = authoritative.get(row["candidate_id"])
        if recovered_ledger_id:
            # Commit the recovery marker before returning the conflict.
            conn.execute(
                "UPDATE receipt_workflow_candidates SET applied=1,ledger_id=?,updated_at=? "
                "WHERE candidate_id=? AND applied=0",
                (recovered_ledger_id, _now(), row["candidate_id"]))
            fresh = conn.execute(
                "SELECT * FROM receipt_workflow_candidates WHERE candidate_id=?",
                (row["candidate_id"],)).fetchone()
            result = {"candidate": _candidate_public(fresh)}
        else:
            if row["revision"] != payload["expected_revision"]:
                raise WorkflowError("STALE_CANDIDATE", 409)
            before = json.loads(row["review_json"])
            after = dict(before)
            after.update(changes)
            if "trip_id" in changes:
                trip_id = after.get("trip_id")
                if trip_id:
                    valid_trips = ({trip.get("tab_id"): trip for trip in
                                    board.list_trips(include_archived=True)}
                                   if board is not None else {})
                    trip = valid_trips.get(trip_id)
                    if (trip is None or trip.get("tab_kind", "trip") != "trip"
                            or trip.get("deleted") or trip.get("archived")):
                        raise WorkflowError("TRIP_REQUIRED", 422)
                # Keep an explicit clear distinct from a missing automatic inference.
                after["trip_source"] = "manual"
            selected = row["selected"] if "selected" not in payload else int(payload["selected"])
            if after == before and selected == row["selected"]:
                result = {"candidate": _candidate_public(row)}
            else:
                revision = int(row["revision"]) + 1
                now = _now()
                conn.execute(
                    "INSERT INTO receipt_workflow_candidate_revisions(candidate_id,revision,previous_json,"
                    "current_json,selected,actor,created_at) VALUES (?,?,?,?,?,?,?)",
                    (row["candidate_id"], revision, workflow_db.canonical(before),
                     workflow_db.canonical(after), selected, owner_id, now))
                conn.execute(
                    "UPDATE receipt_workflow_candidates SET review_json=?,revision=?,selected=?,company_expense=?,updated_at=? "
                    "WHERE candidate_id=? AND revision=?",
                    (workflow_db.canonical(after), revision, selected,
                     None if after.get("company_expense") is None else int(after["company_expense"]),
                     now, row["candidate_id"], row["revision"]))
                fresh = conn.execute("SELECT * FROM receipt_workflow_candidates WHERE candidate_id=?",
                                     (row["candidate_id"],)).fetchone()
                result = {"candidate": _candidate_public(fresh)}
    if recovered_ledger_id:
        raise WorkflowError("CANDIDATE_ALREADY_APPLIED", 409)
    return result


def list_workflow(board, *, owner_id="owner", receipts_path=None) -> dict:
    from . import receipt_review
    path = Path(receipts_path or receipt_review._store_path())
    store = _workflow_store(path)
    ids = store.read(lambda conn: [row[0] for row in conn.execute(
        "SELECT c.candidate_id FROM receipt_workflow_candidates c "
        "JOIN receipt_workflow_batches b USING(batch_id) WHERE c.applied=0 AND b.owner_id=?",
        (owner_id,))])
    if ids and board is not None:
        from . import receipt_ledger
        reconciled = receipt_ledger.applied_sources(board, ids)
        if reconciled:
            with store.transaction() as conn:
                for candidate_id, ledger_id in reconciled.items():
                    conn.execute(
                        "UPDATE receipt_workflow_candidates SET applied=1,ledger_id=?,updated_at=? "
                        "WHERE candidate_id=? AND applied=0",
                        (ledger_id, _now(), candidate_id))
    batches = store.read(lambda conn: [_batch_payload(conn, row[0]) for row in conn.execute(
        "SELECT batch_id FROM receipt_workflow_batches WHERE owner_id=? ORDER BY created_at DESC,batch_id",
        (owner_id,))])
    return {"batches": batches}


def apply_selected(board, payload: dict, *, owner_id="owner", receipts_path=None) -> dict:
    from . import receipt_review, receipt_ledger
    if (not isinstance(payload, dict) or set(payload) != {"request_id", "selections"}
            or not isinstance(payload.get("request_id"), str)
            or not _REQUEST_ID.fullmatch(payload["request_id"])
            or not isinstance(payload.get("selections"), list)):
        raise WorkflowError("INVALID_VALUE", 422)
    path = Path(receipts_path or receipt_review._store_path())
    store = _workflow_store(path)
    # The workflow snapshot is locked while the authoritative ledger commits.
    # A lost workflow update is recovered from receipt_apply_sources on GET.
    with store.transaction() as conn:
        try:
            result = receipt_ledger.apply(board, request_id=payload["request_id"],
                                          selections=payload["selections"],
                                          workflow_conn=conn, receipts_path=path,
                                          owner_id=owner_id)
        except SaveError as error:
            raise WorkflowError(error.code, _status_for_code(error.code)) from None
        for item in result.get("results", []):
            conn.execute(
                "UPDATE receipt_workflow_candidates SET applied=1,ledger_id=?,updated_at=? "
                "WHERE candidate_id=? AND batch_id IN "
                "(SELECT batch_id FROM receipt_workflow_batches WHERE owner_id=?)",
                (item.get("ledger_id"), _now(), item["candidate_id"], owner_id))
        return result


def _status_for_code(code: str) -> int:
    if code in {"REQUEST_ID_REUSED", "STALE_CANDIDATE", "CANDIDATE_ALREADY_APPLIED",
                "CANDIDATE_NOT_SELECTED", "JOB_STILL_ACTIVE", "CLOSED_PERIOD",
                "CARD_EVIDENCE_ALREADY_LINKED"}:
        return 409
    if code in {"CANDIDATE_NOT_FOUND", "JOB_NOT_FOUND", "IMAGE_NOT_OWNED"}:
        return 404
    if code in {"STORE_UNBOUND", "PASEO_RUNTIME_UNAVAILABLE", "PASEO_UNAVAILABLE",
                "PASEO_CATALOG_UNAVAILABLE", "PASEO_CATALOG_INVALID",
                "PASEO_PROMPT_PIN_UNAVAILABLE", "PROMPT_PIN_UNAVAILABLE",
                "PASEO_PROMPT_PIN_MISMATCH", "PASEO_PROMPT_PIN_INVALID",
                "RECEIPT_STORE_UNAVAILABLE"}:
        return 503
    return 422


def _revalidate_result(job, raw_result: dict) -> dict:
    from app import receipt_vision
    if (not isinstance(raw_result, dict)
            or raw_result.get("source_sha256") != job["image_sha256"]
            or not isinstance(raw_result.get("receipts"), list)):
        raise WorkflowError("RESULT_SOURCE_MISMATCH", 422)
    try:
        return receipt_vision.validate_response(
            {"receipts": raw_result["receipts"],
             "header_text": raw_result.get("header_text"),
             "header_confidence": raw_result.get("header_confidence")},
            image_hash=job["image_sha256"], model=job["model"], lesson=False)
    except Exception as error:
        code = getattr(error, "code", "RESULT_INVALID")
        raise WorkflowError(str(code), 422) from None


class ReceiptWorkflowWorker:
    """One server-owned polling loop. Queued work and run handles survive restarts."""
    def __init__(self, *, receipts_path, board, runtime=None, interval=0.5):
        from . import receipt_review
        self.receipts_path = Path(receipts_path or receipt_review._store_path())
        self.db_path = workflow_db.configured_path(self.receipts_path)
        self.board = board
        self.runtime = runtime
        self.interval = max(0.1, float(interval))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._last_job_id = None

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="receipt-workflow", daemon=True)
            self._thread.start()

    def wake(self):
        self._wake.set()

    def stop(self, timeout=5):
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0, timeout))
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _run(self):
        while not self._stop.is_set():
            try:
                progressed = self.process_once()
            except Exception:
                _LOG.exception("receipt workflow worker iteration failed")
                progressed = False
            if not progressed:
                self._wake.wait(self.interval)
                self._wake.clear()

    def _store(self):
        return workflow_db.ReceiptWorkflowStore(self.db_path)

    def process_once(self) -> bool:
        store = self._store()
        tasks = store.read(lambda conn: conn.execute(
            "SELECT j.*,b.provider,b.model,b.thinking,b.prompt_version,b.prompt_sha256,"
            "b.schema_version,b.schema_sha256 FROM receipt_workflow_jobs j "
            "JOIN receipt_workflow_batches b USING(batch_id) "
            "WHERE j.status IN ('queued','starting','running') "
            "ORDER BY CASE j.status WHEN 'queued' THEN 0 WHEN 'starting' THEN 1 ELSE 2 END,"
            "j.created_at,j.job_id").fetchall())
        if not tasks:
            pending_archive = store.read(lambda conn: conn.execute(
                "SELECT * FROM receipt_workflow_jobs WHERE archive_pending=1 "
                "ORDER BY updated_at,job_id LIMIT 1").fetchone())
            if pending_archive is None:
                return False
            try:
                runtime = _runtime(self.runtime)
            except WorkflowError:
                return False
            return self._archive_task(runtime, store, pending_archive)
        # Every active job gets polled; a long-running first photo must not
        # starve a later photo whose result is already ready.
        next_index = 0
        if self._last_job_id is not None:
            previous_index = next((index for index, row in enumerate(tasks)
                                   if row["job_id"] == self._last_job_id), None)
            if previous_index is not None:
                next_index = (previous_index + 1) % len(tasks)
        task = tasks[next_index]
        self._last_job_id = task["job_id"]
        try:
            runtime = _runtime(self.runtime)
        except WorkflowError as error:
            if error.code == "PASEO_RUNTIME_UNAVAILABLE":
                # Keep durable queued work available for a later daemon reconnect.
                return False
            self._fail(task, store, error.code)
            return True
        if task["status"] == "queued":
            with store.transaction() as conn:
                fresh = conn.execute("SELECT status FROM receipt_workflow_jobs WHERE job_id=?",
                                     (task["job_id"],)).fetchone()
                if fresh is None or fresh[0] != "queued":
                    return True
                conn.execute("UPDATE receipt_workflow_jobs SET status='starting',updated_at=? WHERE job_id=?",
                             (_now(), task["job_id"]))
                task = conn.execute(
                    "SELECT j.*,b.provider,b.model,b.thinking,b.prompt_version,b.prompt_sha256,"
                    "b.schema_version,b.schema_sha256 FROM receipt_workflow_jobs j "
                    "JOIN receipt_workflow_batches b USING(batch_id) WHERE j.job_id=?",
                    (task["job_id"],)).fetchone()
            return self._start(task, runtime, store)
        if task["status"] == "starting":
            return self._recover_starting(task, runtime, store)
        return self._inspect(task, runtime, store)

    def _current_pin(self, task, runtime):
        try:
            pin = _prompt_metadata(runtime)
        except WorkflowError as error:
            return None, error.code
        expected = {key: task[key] for key in
                    ("prompt_version", "prompt_sha256", "schema_version", "schema_sha256")}
        return (pin, None) if pin == expected else (None, "PASEO_PROMPT_CHANGED")

    def _start(self, task, runtime, store):
        pin, code = self._current_pin(task, runtime)
        if pin is None:
            self._fail(task, store, code)
            return True
        from . import receipt_review
        try:
            image_path = receipt_review._images_dir(self.receipts_path) / f"{task['image_sha256']}.bin"
            body = receipt_review.image_bytes(self.receipts_path, task["image_sha256"])
            if hashlib.sha256(body).hexdigest() != task["image_sha256"]:
                raise WorkflowError("IMAGE_SOURCE_INVALID", 422)
            handle = runtime.start(
                image_path, task["provider"], task["model"], run_key=task["run_key"],
                expected_prompt_metadata=pin, thinking=task["thinking"])
            if not isinstance(handle, dict) or not handle.get("agent_id"):
                raise WorkflowError("RUNTIME_HANDLE_INVALID", 503)
            handle = dict(handle)
            handle.setdefault("prompt_metadata", pin)
            if task["thinking"] is not None and handle.get("thinking", task["thinking"]) != task["thinking"]:
                raise WorkflowError("RUN_THINKING_MISMATCH", 422)
            with store.transaction() as conn:
                conn.execute("UPDATE receipt_workflow_jobs SET handle_json=?,status='running',code=NULL,updated_at=? "
                             "WHERE job_id=? AND status='starting'",
                             (workflow_db.canonical(handle), _now(), task["job_id"]))
                _refresh_batch(conn, task["batch_id"])
            return True
        except WorkflowError as error:
            self._fail(task, store, error.code)
            return True
        except Exception as error:
            code = getattr(error, "code", "RUN_START_UNCERTAIN")
            try:
                found = runtime.find_run(task["run_key"])
            except Exception:
                # Keep the durable starting state. A later retry of find_run is
                # safe; blindly replaying start here would duplicate transmission.
                return False
            if isinstance(found, dict) and found.get("agent_id"):
                with store.transaction() as conn:
                    conn.execute("UPDATE receipt_workflow_jobs SET handle_json=?,status='running',updated_at=? "
                                 "WHERE job_id=? AND status='starting'",
                                 (workflow_db.canonical(found), _now(), task["job_id"]))
                    _refresh_batch(conn, task["batch_id"])
            else:
                known_refusal = code in {"PASEO_PROMPT_CHANGED", "MODEL_NOT_SELECTABLE",
                                         "PASEO_AUTH_REQUIRED", "PASEO_RATE_LIMITED",
                                         "PASEO_IMAGE_UNSUPPORTED", "PASEO_TOOL_EXECUTION_DETECTED",
                                         "PASEO_BILLING_PATH_REFUSED"}
                self._fail(task, store, str(code) if known_refusal else "RUN_START_UNCERTAIN")
            return True

    def _recover_starting(self, task, runtime, store):
        try:
            handle = runtime.find_run(task["run_key"])
        except Exception:
            return False
        if handle is None:
            self._fail(task, store, "RUN_NOT_FOUND_AFTER_RESTART")
        elif not isinstance(handle, dict) or not handle.get("agent_id"):
            self._fail(task, store, "RUNTIME_HANDLE_INVALID")
        else:
            with store.transaction() as conn:
                conn.execute("UPDATE receipt_workflow_jobs SET handle_json=?,status='running',updated_at=? "
                             "WHERE job_id=? AND status='starting'",
                             (workflow_db.canonical(handle), _now(), task["job_id"]))
                _refresh_batch(conn, task["batch_id"])
        return True

    def _inspect(self, task, runtime, store):
        try:
            handle = json.loads(task["handle_json"] or "{}")
            state = runtime.inspect_run(handle)
        except Exception:
            # A disconnected daemon is not proof that a running agent failed.
            return False
        if not isinstance(state, dict) or state.get("status") not in ("running", "done", "failed"):
            self._fail(task, store, "PASEO_STATUS_INVALID")
            return self._archive_task(runtime, store, task)
        if state["status"] == "running":
            return False
        if state["status"] == "failed":
            self._fail(task, store, str(state.get("code") or "PASEO_RUN_FAILED"))
            return self._archive_task(runtime, store, task)
        try:
            result = _revalidate_result(task, state.get("result"))
        except WorkflowError as error:
            raw = state.get("result")
            self._fail(task, store, error.code, private_result=raw)
            return self._archive_task(runtime, store, task)
        self._complete(task, result, store)
        return self._archive_task(runtime, store, task)

    def _archive_task(self, runtime, store, task):
        try:
            handle = json.loads(task["handle_json"] or "{}")
        except (TypeError, ValueError):
            handle = None
        if not isinstance(handle, dict) or not handle.get("agent_id"):
            with store.transaction() as conn:
                conn.execute(
                    "UPDATE receipt_workflow_jobs SET archive_pending=0,archive_error=? "
                    "WHERE job_id=? AND archive_pending=1",
                    ("ARCHIVE_HANDLE_INVALID", task["job_id"]))
            return True
        try:
            runtime.archive_run(handle)
        except Exception:
            with store.transaction() as conn:
                conn.execute(
                    "UPDATE receipt_workflow_jobs SET archive_pending=1,archive_attempts=archive_attempts+1,"
                    "archive_error=?,updated_at=? WHERE job_id=?",
                    ("ARCHIVE_FAILED", _now(), task["job_id"]))
            _LOG.warning("receipt workflow run archive deferred for job %s", task["job_id"])
            return False
        with store.transaction() as conn:
            conn.execute(
                "UPDATE receipt_workflow_jobs SET archive_pending=0,archive_error='',updated_at=? "
                "WHERE job_id=?",
                (_now(), task["job_id"]))
        return True

    def _fail(self, task, store, code: str, private_result=None):
        encoded = None
        if private_result is not None:
            try:
                encoded = workflow_db.canonical({"unvalidated_result": private_result})
            except (TypeError, ValueError):
                encoded = None
        with store.transaction() as conn:
            conn.execute("UPDATE receipt_workflow_jobs SET status='failed',code=?,result_json=COALESCE(?,result_json),"
                         "archive_pending=CASE WHEN handle_json IS NOT NULL THEN 1 ELSE 0 END,updated_at=? "
                         "WHERE job_id=? AND status IN ('starting','running')",
                         (str(code)[:100], encoded, _now(), task["job_id"]))
            _refresh_batch(conn, task["batch_id"])

    def _complete(self, task, result: dict, store):
        from . import receipt_review
        from app import receipt_trip_match
        trips = []
        if self.board is not None:
            try:
                trips = receipt_review._trip_records(self.board)
            except Exception:
                trips = []
        header = receipt_trip_match.match_header(result.get("header_text"), trips, require_date=False)
        now = _now()
        with store.transaction() as conn:
            fresh = conn.execute("SELECT status FROM receipt_workflow_jobs WHERE job_id=?",
                                 (task["job_id"],)).fetchone()
            if fresh is None or fresh[0] not in ("starting", "running"):
                return
            conn.execute("UPDATE receipt_workflow_jobs SET status='done',code=NULL,result_json=?,"
                         "archive_pending=CASE WHEN handle_json IS NOT NULL THEN 1 ELSE 0 END,updated_at=? "
                         "WHERE job_id=?", (workflow_db.canonical(result), now, task["job_id"]))
            for ordinal, item in enumerate(result["receipts"]):
                # Model content IDs include interpreted fields and can change on
                # reanalysis. Bind identity to the source photo and physical
                # region instead; positionless receipts use their reading ordinal.
                source_marker = ("box:" + workflow_db.canonical(item["box"])
                                 if item.get("box") is not None
                                 else "ordinal:" + str(ordinal))
                source_identity = hashlib.sha256(
                    f"receipt-source-v1:{task['image_sha256']}:{source_marker}".encode("utf-8")).hexdigest()
                trip = receipt_trip_match.decide(header, item.get("date"), trips)
                model = {key: item.get(key) for key in
                         ("id", "merchant", "date", "amount", "currency", "payment", "box",
                          "confidence", "uncertain_fields", "note", "category_hint")}
                review = {"merchant": item.get("merchant"), "date": item.get("date"),
                          "amount": item.get("amount"), "currency": item.get("currency"),
                          "payment": item.get("payment"), "trip_id": trip.get("trip_id"),
                          "category": item.get("category_hint"), "box": item.get("box"),
                          "company_expense": None, "trip_source": trip.get("source")}
                if header.get("raw"):
                    review["trip_header_text"] = header["raw"]
                prior = conn.execute(
                    "SELECT candidate_id FROM receipt_workflow_candidates WHERE source_identity=?",
                    (source_identity,)).fetchone()
                if prior:
                    # A reanalysis observes the same photographed region. Keep
                    # the canonical candidate's review, selection, revision,
                    # and applied state intact; the new validated output remains
                    # on this job and is linked for comparison.
                    candidate_id = prior["candidate_id"]
                else:
                    candidate_id = source_identity
                    conn.execute(
                        "INSERT INTO receipt_workflow_candidates(candidate_id,batch_id,job_id,"
                        "image_sha256,source_identity,source_ordinal,model_json,review_json,revision,selected,applied,"
                        "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,?,?)",
                        (candidate_id, task["batch_id"], task["job_id"], task["image_sha256"],
                         source_identity, ordinal, workflow_db.canonical(model),
                         workflow_db.canonical(review), 1, now, now))
                conn.execute(
                    "INSERT OR IGNORE INTO receipt_workflow_job_candidates "
                    "(job_id,candidate_id,result_ordinal,source_identity,created_at) VALUES (?,?,?,?,?)",
                    (task["job_id"], candidate_id, ordinal, source_identity, now))
            _refresh_batch(conn, task["batch_id"])


def start_worker(board, *, receipts_path=None, runtime=None, interval=0.5):
    """Start/reuse the one server-owned worker attached to this board store."""
    worker = getattr(board, "_receipt_workflow_worker", None)
    if worker is None:
        worker = ReceiptWorkflowWorker(receipts_path=receipts_path, board=board,
                                       runtime=runtime, interval=interval)
        board._receipt_workflow_worker = worker
    worker.start()
    return worker


def stop_worker(board, timeout=5):
    worker = getattr(board, "_receipt_workflow_worker", None)
    if worker is not None:
        worker.stop(timeout=timeout)


def dispatch(handler, parsed, raw=None, *, csrf="", board=None, is_owner=False, query=None) -> bool:
    if not owns_route(parsed.path):
        return False
    if not is_owner:
        handler._send_json({"code": "OWNER_ONLY"}, 403)
        return True
    if not enabled():
        handler._send_json({"code": "WORKFLOW_DISABLED"}, 404)
        return True
    method = getattr(handler, "command", "GET")
    if method not in ("GET", "POST"):
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if method == "GET":
        if parsed.path not in {"/api/receipts/paseo/models", "/api/receipts/workflow"}:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
            return True
        try:
            from . import receipt_review
            if parsed.path == "/api/receipts/paseo/models":
                query = query or {}
                provider_values = query.get("provider", []) if isinstance(query, dict) else []
                provider = provider_values[0] if provider_values else None
                handler._send_json(_catalog(_runtime(), provider))
                return True
            handler._send_json(list_workflow(board, receipts_path=receipt_review._store_path()))
        except WorkflowError as error:
            handler._send_json({"code": error.code}, error.status)
        except Exception:
            _LOG.exception("receipt workflow read failed")
            handler._send_json({"code": "WORKFLOW_STORE_UNAVAILABLE"}, 503)
        return True
    if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
        handler._send_json({"code": "CSRF_REQUIRED"}, 403)
        return True
    if raw is None or len(raw) > 1_000_000:
        handler._send_json({"code": "INVALID_VALUE"}, 422)
        return True
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise WorkflowError("INVALID_VALUE", 422)
        if parsed.path == "/api/receipts/workflow/batches":
            from . import receipt_review
            result = create_batch(board, payload, receipts_path=receipt_review._store_path())
            handler._send_json(result, 202)
        elif parsed.path == "/api/receipts/workflow/review":
            from . import receipt_review
            handler._send_json(review_candidate(payload, receipts_path=receipt_review._store_path(),
                                                board=board))
        elif parsed.path == "/api/receipts/workflow/apply":
            from . import receipt_review
            handler._send_json(apply_selected(board, payload, receipts_path=receipt_review._store_path()))
        elif parsed.path == "/api/receipts/workflow/retry":
            from . import receipt_review
            handler._send_json(retry_job(board, payload, receipts_path=receipt_review._store_path()), 202)
        else:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
    except UnicodeDecodeError:
        handler._send_json({"code": "INVALID_VALUE"}, 422)
    except json.JSONDecodeError:
        handler._send_json({"code": "INVALID_VALUE"}, 422)
    except WorkflowError as error:
        handler._send_json({"code": error.code}, error.status)
    except Exception:
        _LOG.exception("receipt workflow request failed")
        handler._send_json({"code": "WORKFLOW_STORE_UNAVAILABLE"}, 503)
    return True
