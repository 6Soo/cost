"""Single physical request journal for owner-profile and receipt-apply idempotency.

`owner_profile_requests` and `receipt_apply_requests` stored the same four
facts — request key, input digest, response JSON, timestamp — in two tables.
The unified format keeps them in one `ledger_operation_requests` table keyed
by `(domain, request_id)`, so the same request id in two domains is two
records, never a collision.

The legacy names survive as read-only compatibility views with the legacy
column names, so existing SELECT call sites work unchanged in both formats,
and `CREATE TABLE IF NOT EXISTS` on those names is a no-op while the views
exist — the original schema initialization runs unmodified in both formats.
Writes branch through `insert_operation_request`. Only the offline conversion
tool (`tools/merge_ledger_operation_requests.py`) switches formats; the opener
detects the shape from one sqlite_master read and refuses a mixed shape
instead of guessing or repairing it.
"""
from __future__ import annotations

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

_LEGACY_INSERT_SQL = {
    OWNER_PROFILE_DOMAIN:
        "INSERT INTO owner_profile_requests(client_request_id, input_digest,"
        " result_json, created_at) VALUES (?,?,?,?)",
    RECEIPT_APPLY_DOMAIN:
        "INSERT INTO receipt_apply_requests(request_id,request_hash,result_json,created_at)"
        " VALUES (?,?,?,?)",
}


def request_journal_shape(conn) -> str:
    """'legacy' or 'unified'; any mixed or unknown shape is a refusal.

    The unified marker and BOTH compatibility views must agree. A legacy
    database may still be missing one or both journal tables (schema not run
    yet), but a half-converted database is never opened on a guess.
    """
    kinds = dict(conn.execute(
        "SELECT name, type FROM sqlite_master WHERE name IN (?,?,?)",
        (UNIFIED_TABLE, "owner_profile_requests", "receipt_apply_requests")))
    marker = kinds.get(UNIFIED_TABLE)
    owner = kinds.get("owner_profile_requests")
    receipt = kinds.get("receipt_apply_requests")
    if marker == "table" and owner == "view" and receipt == "view":
        return "unified"
    if marker is None and owner in (None, "table") and receipt in (None, "table"):
        return "legacy"
    raise RuntimeError("REQUEST_JOURNAL_MIXED_SHAPE")


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
