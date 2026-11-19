"""Single physical request journal for owner-profile, receipt-apply and
reviewed-source-fact idempotency.

`owner_profile_requests`, `receipt_apply_requests` and `source_fact_applies`
stored the same core facts — request key, input digest, response JSON,
timestamp — in separate tables. The unified format keeps them in one
`ledger_operation_requests` table keyed by `(domain, request_id)`, so the same
request id in two domains is two records, never a collision. The reviewed
source fact additionally carries `binding` and `choices_revision` provenance,
preserved exactly in the unified row and its compatibility view.

The legacy names survive as read-only compatibility views with the legacy
column names, so existing SELECT call sites work unchanged in both formats,
and `CREATE TABLE IF NOT EXISTS` on those names is a no-op while the views
exist — the original schema initialization runs unmodified in both formats.
Writes branch through `insert_operation_request`. Only the offline conversion
tool (`tools/merge_ledger_operation_requests.py`) switches formats; the opener
detects the shape from one sqlite_master read and refuses a mixed shape
instead of guessing or repairing it.

Two unified variants exist: `unified` (owner-profile + receipt-apply converted,
`source_fact_applies` still a legacy table) and `unified_source_facts` (all
three converted). The default conversion keeps the original two-domain
contract; the third domain is only merged on an explicit
`--include-source-facts` run. `reserve_link_saves` is deliberately excluded:
it belongs to the AccessStore contract (SPEC 16.4), not this journal.
"""
from __future__ import annotations

OWNER_PROFILE_DOMAIN = "owner_profile"
RECEIPT_APPLY_DOMAIN = "receipt_apply"
SOURCE_FACT_DOMAIN = "source_fact_apply"

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

UNIFIED_SOURCE_FACTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ledger_operation_requests (
    domain TEXT NOT NULL CHECK(domain IN ('owner_profile','receipt_apply','source_fact_apply')),
    request_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    binding TEXT,
    choices_revision INTEGER,
    PRIMARY KEY (domain, request_id),
    CHECK (domain != 'source_fact_apply' OR (binding IS NOT NULL AND choices_revision IS NOT NULL))
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

SOURCE_FACT_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS source_fact_applies AS
    SELECT request_id, input_digest, binding, choices_revision, result_json, created_at
    FROM ledger_operation_requests WHERE domain='source_fact_apply';
"""

COMPAT_VIEW_SQL = (OWNER_PROFILE_VIEW_SQL, RECEIPT_APPLY_VIEW_SQL)
SOURCE_FACTS_COMPAT_VIEW_SQL = COMPAT_VIEW_SQL + (SOURCE_FACT_VIEW_SQL,)

_LEGACY_INSERT_SQL = {
    OWNER_PROFILE_DOMAIN:
        "INSERT INTO owner_profile_requests(client_request_id, input_digest,"
        " result_json, created_at) VALUES (?,?,?,?)",
    RECEIPT_APPLY_DOMAIN:
        "INSERT INTO receipt_apply_requests(request_id,request_hash,result_json,created_at)"
        " VALUES (?,?,?,?)",
    SOURCE_FACT_DOMAIN:
        "INSERT INTO source_fact_applies(request_id, input_digest,"
        " binding, choices_revision, result_json, created_at)"
        " VALUES (?,?,?,?,?,?)",
}


def request_journal_shape(conn) -> str:
    """'legacy', 'unified' (two domains) or 'unified_source_facts' (three).

    The unified marker and the compatibility views must agree. In the unified
    format `source_fact_applies` is either still a legacy table (only the first
    two domains converted) or the third compatibility view (all three
    converted); an absent or unknown third name is a mixed shape, never a
    guess. A legacy database may still be missing journal tables (schema not
    run yet), but a half-converted database is never opened on a guess.
    """
    kinds = dict(conn.execute(
        "SELECT name, type FROM sqlite_master WHERE name IN (?,?,?,?)",
        (UNIFIED_TABLE, "owner_profile_requests", "receipt_apply_requests",
         "source_fact_applies")))
    marker = kinds.get(UNIFIED_TABLE)
    owner = kinds.get("owner_profile_requests")
    receipt = kinds.get("receipt_apply_requests")
    source_fact = kinds.get("source_fact_applies")
    if marker == "table" and owner == "view" and receipt == "view":
        if source_fact == "view":
            return "unified_source_facts"
        if source_fact == "table":
            return "unified"
        raise RuntimeError("REQUEST_JOURNAL_MIXED_SHAPE")
    if (marker is None and owner in (None, "table")
            and receipt in (None, "table") and source_fact in (None, "table")):
        return "legacy"
    raise RuntimeError("REQUEST_JOURNAL_MIXED_SHAPE")


def insert_operation_request(conn, *, unified: bool, domain: str, request_id: str,
                             input_digest: str, result_json: str,
                             created_at: str, binding: str | None = None,
                             choices_revision: int | None = None) -> None:
    """Append one idempotency record inside the caller's transaction.

    Never commits or rolls back: replay/conflict decisions and atomicity
    belong to the surrounding write transaction, exactly as with the legacy
    INSERT call sites this replaces.

    `binding`/`choices_revision` carry the reviewed-source-fact provenance and
    are only used for that domain; the other two domains ignore them. The
    legacy source_fact INSERT is performed verbatim, preserving the original
    NOT NULL columns and their order. The caller passes `unified=True` for the
    first two domains whenever the shape is not legacy, and for source_fact
    only when the shape is `unified_source_facts`.
    """
    if domain not in _LEGACY_INSERT_SQL:
        raise ValueError("unknown request journal domain: " + str(domain))
    if unified:
        if domain == SOURCE_FACT_DOMAIN:
            conn.execute(
                "INSERT INTO ledger_operation_requests(domain,request_id,"
                "input_digest,result_json,created_at,binding,choices_revision)"
                " VALUES (?,?,?,?,?,?,?)",
                (domain, request_id, input_digest, result_json, created_at,
                 binding, choices_revision))
        else:
            conn.execute(
                "INSERT INTO ledger_operation_requests(domain,request_id,"
                "input_digest,result_json,created_at) VALUES (?,?,?,?,?)",
                (domain, request_id, input_digest, result_json, created_at))
    elif domain == SOURCE_FACT_DOMAIN:
        conn.execute(_LEGACY_INSERT_SQL[domain],
                     (request_id, input_digest, binding, choices_revision,
                      result_json, created_at))
    else:
        conn.execute(_LEGACY_INSERT_SQL[domain],
                     (request_id, input_digest, result_json, created_at))
