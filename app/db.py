# -*- coding: utf-8 -*-
"""One SQLite store for the whole cost pipeline.

The store is handed an existing connection. This module never decides which
database file is used and never creates one of its own: the web app owns the
database and its schema migrations, and a second file would be a second truth
about the same money.

Everything here is a plain function plus a small `Store` object. No ORM, no
session layer, no HTTP.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transaction_company_exclusions (
    transaction_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    excluded INTEGER NOT NULL CHECK(excluded IN (0,1)),
    revision INTEGER NOT NULL,
    note TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    content_sha256 TEXT NOT NULL UNIQUE,
    content_bytes BLOB NOT NULL,
    byte_size INTEGER NOT NULL,
    parser TEXT NOT NULL,
    received_at TEXT NOT NULL,
    parsed_at TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'received'
);

CREATE TABLE IF NOT EXISTS import_batch_rows (
    batch_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    PRIMARY KEY(batch_id, transaction_id)
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    issuer TEXT NOT NULL,
    card_tail TEXT NOT NULL,
    card_kind TEXT NOT NULL,
    transaction_direction TEXT NOT NULL,
    transaction_kind TEXT NOT NULL,
    approval_number TEXT NOT NULL,
    original_approval_number TEXT NOT NULL,
    approval_date TEXT NOT NULL,
    posting_date TEXT NOT NULL,
    merchant TEXT NOT NULL,
    merchant_normalized TEXT NOT NULL,
    amount_krw INTEGER,
    foreign_amount TEXT NOT NULL DEFAULT '',
    foreign_currency TEXT NOT NULL DEFAULT '',
    description_raw TEXT NOT NULL DEFAULT '',
    row_index INTEGER NOT NULL,
    raw_row_json TEXT NOT NULL,
    duplicate_of TEXT,
    conflict_reason TEXT NOT NULL DEFAULT '',
    parse_error TEXT NOT NULL DEFAULT '',
    classification_state TEXT NOT NULL DEFAULT 'needs_review',
    classification_source TEXT NOT NULL DEFAULT '',
    classification_basis TEXT NOT NULL DEFAULT '',
    item TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    display_tab_id TEXT NOT NULL DEFAULT '',
    trip_id TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    user_confirmed INTEGER NOT NULL DEFAULT 0,
    decided_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_classification_rules (
    rule_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    conditions_json TEXT NOT NULL,
    effects_json TEXT NOT NULL,
    optional_json TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    rule_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_decisions (
    transaction_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    item TEXT NOT NULL,
    description TEXT NOT NULL,
    display_tab_id TEXT NOT NULL,
    note TEXT NOT NULL,
    reuse_rule INTEGER NOT NULL DEFAULT 0,
    decided_at TEXT NOT NULL,
    PRIMARY KEY (transaction_id, revision)
);

CREATE TABLE IF NOT EXISTS transaction_review_holds (
    transaction_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('cancelled','refund_pending','user_hold','evidence_pending')),
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    transaction_id TEXT NOT NULL UNIQUE,
    batch_id TEXT NOT NULL,
    item TEXT NOT NULL,
    description TEXT NOT NULL,
    display_tab_id TEXT NOT NULL,
    trip_id TEXT NOT NULL DEFAULT '',
    amount_krw INTEGER,
    merchant TEXT NOT NULL,
    occurred_on TEXT NOT NULL,
    transaction_direction TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    committed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 승인내역은 거래 발생의 증거일 뿐 회계 금액이 아니다. transactions(매입 정본)에 넣지 않고 따로 둔다.
CREATE TABLE IF NOT EXISTS approval_evidence (
    approval_key TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    issuer TEXT NOT NULL,
    card_tail TEXT NOT NULL,
    card_kind TEXT NOT NULL,
    transaction_direction TEXT NOT NULL,
    approval_number TEXT NOT NULL,
    approval_date TEXT NOT NULL,
    approval_time TEXT NOT NULL DEFAULT '',
    merchant TEXT NOT NULL,
    amount_krw INTEGER,
    foreign_amount TEXT NOT NULL DEFAULT '',
    foreign_currency TEXT NOT NULL DEFAULT '',
    approval_method TEXT NOT NULL DEFAULT '',
    raw_row_json TEXT NOT NULL,
    conflict_reason TEXT NOT NULL DEFAULT '',
    link_state TEXT NOT NULL DEFAULT 'unreconciled',
    linked_transaction_id TEXT,
    link_group TEXT NOT NULL DEFAULT '',
    link_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_batch_rows (
    batch_id TEXT NOT NULL,
    approval_key TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    PRIMARY KEY(batch_id, approval_key, row_index)
);

CREATE INDEX IF NOT EXISTS approval_evidence_card ON approval_evidence(card_tail, approval_date);
CREATE INDEX IF NOT EXISTS transactions_batch ON transactions(batch_id);
CREATE INDEX IF NOT EXISTS transactions_source_hash ON transactions(source_hash);
CREATE INDEX IF NOT EXISTS transactions_state ON transactions(classification_state);
"""


class StoreError(Exception):
    """One code per failure. `code` is what a caller switches on."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


CODE_NOT_FOUND = "NOT_FOUND"
CODE_REVISION_CONFLICT = "REVISION_CONFLICT"
CODE_REQUEST_ID_REUSED = "REQUEST_ID_REUSED"
CODE_PREVIEW_STALE = "PREVIEW_STALE"
CODE_REFUND_PAIR_PARTIALLY_BOOKED = "REFUND_PAIR_PARTIALLY_BOOKED"
CODE_REFUND_GROUP_INCOMPLETE = "REFUND_GROUP_INCOMPLETE"
CODE_INVALID_INPUT = "INVALID_INPUT"
CODE_AMOUNT_UNREADABLE = "AMOUNT_UNREADABLE"
CODE_SOURCE_CONFLICT = "SOURCE_CONFLICT"
CODE_ROLLBACK = "ROLLBACK"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value) -> str:
    """Stable text for hashing: sorted keys, no incidental spacing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    """The pipeline's view of one database.

    Built from a connection the caller already owns. `lock` guards the
    in-process writes the pipeline makes while a review is being saved; the
    `BEGIN IMMEDIATE` inside `commit` is what guards the atomic part, so the
    lock is never what makes a commit safe.
    """

    def __init__(self, conn: sqlite3.Connection, *, owns_connection: bool = False):
        self.conn = conn
        self._owns = owns_connection
        self.lock = threading.RLock()
        self.ensure_schema()

    @classmethod
    def open(cls, path: str) -> "Store":
        """Only for callers that already decided on this file."""
        conn = sqlite3.connect(path, timeout=15, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return cls(conn, owns_connection=True)

    def close(self) -> None:
        # `closing(...)` on its own only *calls* the object's close when the
        # block exits, and here there is no block, so the handle stayed open.
        if self._owns:
            self.conn.close()

    def ensure_schema(self) -> None:
        """Additive only.

        Every statement is `IF NOT EXISTS`, so running this against the web
        app's own database adds the pipeline's tables and touches nothing that
        is already there.
        """
        with self.lock:
            self.conn.executescript(SCHEMA_SQL)

    # ------------------------------------------------------------- requests

    def replay_request(self, request_id: str, scope: str, payload_sha256: str):
        """The earlier result for this request id, if it was the same request.

        A request id is an idempotency key, not a content address. Reusing one
        with a different body is a caller bug that would otherwise hand back an
        answer to a question nobody asked, so it is refused rather than served.
        """
        row = self.conn.execute(
            "SELECT scope, payload_sha256, response_json FROM requests"
            " WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return None
        if row[0] != scope or row[1] != payload_sha256:
            raise StoreError(CODE_REQUEST_ID_REUSED,
                             "같은 요청 ID로 다른 내용을 보냈어요")
        return json.loads(row[2])

    def remember_request(self, request_id: str, scope: str, payload_sha256: str,
                         response) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO requests(request_id, scope, payload_sha256,"
            " response_json, created_at) VALUES (?,?,?,?,?)",
            (request_id, scope, payload_sha256, canonical(response), utc_now()))

    # ----------------------------------------------------------- change log

    def log_change(self, kind: str, subject: str, detail: dict) -> None:
        """Append-only. Called inside the caller's transaction when there is one."""
        self.conn.execute(
            "INSERT INTO change_log(at, kind, subject, detail_json)"
            " VALUES (?,?,?,?)",
            (utc_now(), kind, subject, canonical(detail or {})))

    def changes(self, subject: str = ""):
        if subject:
            rows = self.conn.execute(
                "SELECT entry_id, at, kind, subject, detail_json FROM change_log"
                " WHERE subject=? ORDER BY entry_id", (subject,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT entry_id, at, kind, subject, detail_json FROM change_log"
                " ORDER BY entry_id").fetchall()
        return [{"entry_id": r[0], "at": r[1], "kind": r[2], "subject": r[3],
                 "detail": json.loads(r[4])} for r in rows]
