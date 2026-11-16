"""Persistent state for owner-reviewed receipt Paseo runs.

The workflow database contains job and review state only. COST ledger writes
remain authoritative in LedgerStore's database and are reconciled from there.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS receipt_workflow_batches (
    batch_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    thinking TEXT,
    prompt_version TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    schema_sha256 TEXT NOT NULL,
    host_label TEXT NOT NULL DEFAULT '',
    catalog_checked_at TEXT NOT NULL DEFAULT '',
    analysis_signature TEXT NOT NULL DEFAULT '',
    explicit_retry INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipt_workflow_jobs (
    job_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES receipt_workflow_batches(batch_id),
    image_sha256 TEXT NOT NULL,
    run_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    handle_json TEXT,
    result_json TEXT,
    code TEXT,
    archive_pending INTEGER NOT NULL DEFAULT 0,
    archive_attempts INTEGER NOT NULL DEFAULT 0,
    archive_error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 1,
    retry_of_job TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(batch_id, image_sha256)
);
CREATE TABLE IF NOT EXISTS receipt_workflow_candidates (
    candidate_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES receipt_workflow_batches(batch_id),
    job_id TEXT NOT NULL REFERENCES receipt_workflow_jobs(job_id),
    image_sha256 TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    source_ordinal INTEGER NOT NULL DEFAULT 0,
    model_json TEXT NOT NULL,
    review_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0,
    applied INTEGER NOT NULL DEFAULT 0,
    ledger_id TEXT,
    company_expense INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_receipt_workflow_jobs_status
    ON receipt_workflow_jobs(status, created_at);
CREATE TABLE IF NOT EXISTS receipt_workflow_requests (
    request_id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES receipt_workflow_batches(batch_id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_receipt_workflow_candidates_batch
    ON receipt_workflow_candidates(batch_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_receipt_workflow_candidate_source
    ON receipt_workflow_candidates(source_identity);
CREATE TABLE IF NOT EXISTS receipt_workflow_candidate_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES receipt_workflow_candidates(candidate_id),
    revision INTEGER NOT NULL,
    previous_json TEXT NOT NULL,
    current_json TEXT NOT NULL,
    selected INTEGER NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(candidate_id, revision)
);
CREATE TABLE IF NOT EXISTS receipt_workflow_job_candidates (
    job_id TEXT NOT NULL REFERENCES receipt_workflow_jobs(job_id),
    candidate_id TEXT NOT NULL REFERENCES receipt_workflow_candidates(candidate_id),
    result_ordinal INTEGER NOT NULL DEFAULT 0,
    source_identity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(job_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS ix_receipt_workflow_job_candidates_candidate
    ON receipt_workflow_job_candidates(candidate_id, job_id);
"""


def configured_path(receipts_path: Path) -> Path:
    override = os.environ.get("WEBLEDGER_RECEIPT_WORKFLOW_DB")
    return Path(override) if override else receipts_path.parent / "receipt-workflow.sqlite"


class ReceiptWorkflowStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(receipt_workflow_candidates)")}
            if "source_ordinal" not in columns:
                conn.execute(
                    "ALTER TABLE receipt_workflow_candidates "
                    "ADD COLUMN source_ordinal INTEGER NOT NULL DEFAULT 0")
            batch_columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(receipt_workflow_batches)")}
            if "analysis_signature" not in batch_columns:
                conn.execute(
                    "ALTER TABLE receipt_workflow_batches "
                    "ADD COLUMN analysis_signature TEXT NOT NULL DEFAULT ''")
            if "explicit_retry" not in batch_columns:
                conn.execute(
                    "ALTER TABLE receipt_workflow_batches "
                    "ADD COLUMN explicit_retry INTEGER NOT NULL DEFAULT 0")
            job_columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(receipt_workflow_jobs)")}
            if "archive_pending" not in job_columns:
                conn.execute(
                    "ALTER TABLE receipt_workflow_jobs "
                    "ADD COLUMN archive_pending INTEGER NOT NULL DEFAULT 0")
                # Terminal jobs from an older backend may still own a Paseo
                # resource. Reconnect and archive it after restart.
                conn.execute(
                    "UPDATE receipt_workflow_jobs SET archive_pending=1 "
                    "WHERE status IN ('done','failed') AND handle_json IS NOT NULL")
            if "archive_attempts" not in job_columns:
                conn.execute(
                    "ALTER TABLE receipt_workflow_jobs "
                    "ADD COLUMN archive_attempts INTEGER NOT NULL DEFAULT 0")
            if "archive_error" not in job_columns:
                conn.execute(
                    "ALTER TABLE receipt_workflow_jobs "
                    "ADD COLUMN archive_error TEXT NOT NULL DEFAULT ''")
            # Backfill the initial one-job/one-candidate relationship for
            # databases created before retries could link a stable candidate.
            conn.execute(
                "INSERT OR IGNORE INTO receipt_workflow_job_candidates "
                "(job_id,candidate_id,result_ordinal,source_identity,created_at) "
                "SELECT job_id,candidate_id,source_ordinal,source_identity,created_at "
                "FROM receipt_workflow_candidates")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_receipt_workflow_analysis_signature "
                "ON receipt_workflow_batches(analysis_signature, explicit_retry, created_at)")
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def transaction(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def read(self, function):
        with self._lock:
            conn = self._connect()
            try:
                return function(conn)
            finally:
                conn.close()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def row_json(row, *keys):
    return {key: row[key] for key in keys}
