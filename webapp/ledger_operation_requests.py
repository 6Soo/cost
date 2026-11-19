"""Single physical request journal for owner-profile and receipt-apply idempotency.

`owner_profile_requests` and `receipt_apply_requests` stored the same four
facts — request key, input digest, response JSON, timestamp — in two tables.
The unified format keeps them in one `ledger_operation_requests` table keyed
by `(domain, request_id)`, so the same request id in two domains is two
records, never a collision.

The legacy names survive as read-only compatibility views with the legacy
column names, so existing SELECT call sites work unchanged in both formats.
Writes branch through `insert_operation_request`. Legacy init never creates
the unified table; a unified reopen never recreates the legacy tables. Only
the offline conversion tool (`tools/merge_ledger_operation_requests.py`)
switches a database from one format to the other.
"""
from __future__ import annotations

import sqlite3

OWNER_PROFILE_DOMAIN = "owner_profile"
RECEIPT_APPLY_DOMAIN = "receipt_apply"

UNIFIED_TABLE = "ledger_operation_requests"

UNIFIED_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ledger_operation_requests (
    domain TEXT NOT NULL CHECK(domain IN ('owner_profile','receipt_apply')),
    request_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (domain, request_id)
);
"""

OWNER_PROFILE_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS owner_profile_requests AS
    SELECT request_id AS client_request_id, input_digest, result_json, created_at
    FROM ledger_operation_requests WHERE domain='owner_profile';
"""

RECEIPT_APPLY_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS receipt_apply_requests AS
    SELECT request_id, input_digest AS request_hash, result_json, created_at
    FROM ledger_operation_requests WHERE domain='receipt_apply';
"""

COMPAT_VIEW_SQL = (OWNER_PROFILE_VIEW_SQL, RECEIPT_APPLY_VIEW_SQL)

UNIFIED_JOURNAL_SQL = UNIFIED_TABLE_SQL + "".join(COMPAT_VIEW_SQL)

_LEGACY_INSERT_SQL = {
    OWNER_PROFILE_DOMAIN:
        "INSERT INTO owner_profile_requests(client_request_id, input_digest,"
        " result_json, created_at) VALUES (?,?,?,?)",
    RECEIPT_APPLY_DOMAIN:
        "INSERT INTO receipt_apply_requests(request_id,request_hash,result_json,created_at)"
        " VALUES (?,?,?,?)",
}


def journal_is_unified(conn) -> bool:
    """True when the unified physical table owns the request journal."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (UNIFIED_TABLE,)).fetchone() is not None


def ensure_unified_journal(conn) -> None:
    """Create the unified table and compatibility views, idempotently.

    Called by the offline conversion tool and by a unified-mode reopen (which
    restores a missing view without ever recreating a legacy table). Legacy
    init must not call this: creating the table is what switches formats.
    """
    conn.executescript(UNIFIED_JOURNAL_SQL)


def insert_operation_request(conn, *, unified: bool, domain: str, request_id: str,
                             input_digest: str, result_json: str,
                             created_at: str) -> None:
    """Append one idempotency record inside the caller's transaction.

    Never commits or rolls back: replay/conflict decisions and atomicity
    belong to the surrounding write transaction, exactly as with the legacy
    INSERT call sites this replaces.
    """
    if domain not in _LEGACY_INSERT_SQL:
        raise ValueError("unknown request journal domain: " + str(domain))
    if unified:
        conn.execute(
            "INSERT INTO ledger_operation_requests(domain,request_id,"
            "input_digest,result_json,created_at) VALUES (?,?,?,?,?)",
            (domain, request_id, input_digest, result_json, created_at))
    else:
        conn.execute(_LEGACY_INSERT_SQL[domain],
                     (request_id, input_digest, result_json, created_at))
