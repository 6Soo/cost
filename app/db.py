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
import os
from pathlib import Path
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
CREATE INDEX IF NOT EXISTS idx_change_log_kind_subject ON change_log(kind, subject);
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


def decided_sql(alias: str = 'transactions') -> str:
    """사용자가 직접 정했거나 이미 장부에 기록된 거래. 자동 분류가 덮어쓰지 않는다."""
    return (f"(COALESCE({alias}.classification_source,'') IN ('user_decision','user_exception')"
            f" OR {alias}.decided_at IS NOT NULL"
            f" OR EXISTS (SELECT 1 FROM ledger_entries _l WHERE _l.transaction_id={alias}.transaction_id))")


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

    def __init__(self, conn: sqlite3.Connection, *, owns_connection: bool = False,
                 schema_policy: str | None = None):
        self.conn = conn
        self._owns = owns_connection
        self.lock = threading.RLock()
        self.schema_policy = (os.environ.get('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
                              if schema_policy is None else schema_policy)
        if self.schema_policy not in ('create', 'require'):
            raise StoreError('SCHEMA_POLICY_INVALID', '카드 스키마 정책을 확인해 주세요')
        if self.schema_policy == 'require':
            self.require_schema(conn)
        else:
            self.ensure_schema()

    @staticmethod
    def schema_differences(conn: sqlite3.Connection) -> list[str]:
        """Read-only comparison with this release's exact table/index contract.

        Extra application objects are preserved. An existing required object's
        different definition needs explicit review, even if it is equivalent SQL.
        No row values or database paths are returned.
        """
        with closing(sqlite3.connect(':memory:')) as reference:
            reference.executescript(SCHEMA_SQL)
            expected = reference.execute(
                "SELECT type, name, sql FROM sqlite_master"
                " WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
        actual = {(kind, name): sql for kind, name, sql in conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL")}
        return sorted(name for kind, name, sql in expected
                      if actual.get((kind, name)) != sql)

    @classmethod
    def require_schema(cls, conn: sqlite3.Connection) -> None:
        if cls.schema_differences(conn):
            raise StoreError('SCHEMA_MIGRATION_REQUIRED',
                             '카드 스키마 준비와 복구 검증이 필요합니다')

    @classmethod
    def require_existing_schema(cls, path: str | Path) -> None:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro',
                                    uri=True)) as conn:
            cls.require_schema(conn)

    @classmethod
    def open(cls, path: str, *, schema_policy: str | None = None) -> "Store":
        """Only for callers that already decided on this file."""
        policy = (os.environ.get('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
                  if schema_policy is None else schema_policy)
        if policy not in ('create', 'require'):
            raise StoreError('SCHEMA_POLICY_INVALID', '카드 스키마 정책을 확인해 주세요')
        target = Path(path).resolve().as_uri() + '?mode=rw' if policy == 'require' else path
        conn = sqlite3.connect(target, uri=policy == 'require', timeout=15, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            return cls(conn, owns_connection=True, schema_policy=policy)
        except BaseException:
            conn.close()
            raise

    def close(self) -> None:
        # `closing(...)` on its own only *calls* the object's close when the
        # block exits, and here there is no block, so the handle stayed open.
        if self._owns:
            self.conn.close()

    def ensure_schema(self) -> None:
        """Additive only.

        Runs on Store construction, including the first CardFlow request.
        A savepoint keeps all DDL atomic without committing a caller's pending
        transaction. Existing tables and their contents are retained.
        """
        if self.schema_policy == 'require':
            self.require_schema(self.conn)
            return
        with self.lock:
            self.conn.execute('SAVEPOINT cost_schema')
            try:
                statement = ''
                for line in SCHEMA_SQL.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        self.conn.execute(statement)
                        statement = ''
                if statement.strip():
                    self.conn.execute(statement)
                self.conn.execute('RELEASE SAVEPOINT cost_schema')
            except BaseException:
                self.conn.execute('ROLLBACK TO SAVEPOINT cost_schema')
                self.conn.execute('RELEASE SAVEPOINT cost_schema')
                raise

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
