"""Pure audit, outbox, and serialization rules for LedgerStore.

Extracted under RF-101 (Store decomposition audit & outbox boundary).
Preserves exact execution semantics, canonical JSON sorting, outbox ownership
proofs, and database row projections of the original store.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


def canonical_json(value: Any) -> str:
    """Canonical JSON serialization with sorted keys and no ASCII escaping."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def source_fact_digest(facts: dict) -> str:
    """A digest of the source facts alone, with no column dropped.

    Deliberately not the ledger's row digest: this covers the seventeen columns
    as they arrived, so an edit a user made on the board afterwards does not make
    the next apply look like a changed source, and a changed source is not hidden
    by an edit.
    """
    canonical = json.dumps(
        facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def owns_outbox_id(outbox_id: Any, prefix: str) -> bool:
    """Is this outbox row one of the request's own events?

    Two things had to be established before this was right, and both were
    wrong at first.

    A `LIKE` pattern built from the request id is not a literal: `_` matches
    any one character and `%` matches any run of them, so `request_a` claimed
    `requestXa`'s events. Escaping the pattern would have fixed that pair and
    left the next one.

    A prefix match alone is not enough either. `request` and `request-child`
    share a prefix, so `ledger-request-` also matches
    `ledger-request-child-0`, and relaying another request's backlog under
    this one is exactly the mistake the scoping exists to prevent.

    So ownership is proved rather than assumed: the row must begin with this
    request's literal prefix, and the remainder must be the decimal index this
    store appends. `child-0` is not a decimal index, so a longer request id is
    not mistaken for this one, and no character of either id is ever a pattern.
    """
    if type(outbox_id) is not str or not outbox_id.startswith(prefix):
        return False
    tail = outbox_id[len(prefix):]
    # `isdigit` alone would accept other scripts' digits, so `isascii` is
    # checked first: the index this store writes is ASCII.
    return bool(tail) and tail.isascii() and tail.isdigit()


def request_outbox_id(client_request_id: str) -> str:
    return f"ledger-{client_request_id}"


def trip_outbox_id(client_request_id: str) -> str:
    return f"ledger-trip-{client_request_id}"


def row_sub_outbox_id(client_request_id: str, row_id: str) -> str:
    return f"ledger-{client_request_id}:{row_id}"


def row_outbox_id(client_request_id: str, row_id: str) -> str:
    return f"ledger-{client_request_id}-{row_id}"


def indexed_outbox_id(request_id: str, index: int) -> str:
    return f"ledger-{request_id}-{index}"


def fetch_unrelayed_outbox_rows(conn, outbox_ids=None) -> list[tuple]:
    """Fetch pending unrelayed entries from ledger_outbox table."""
    if outbox_ids is None:
        return conn.execute(
            "SELECT outbox_id, stream_id, action, target_direct_event_key,"
            " rationale, actor_local_id FROM ledger_outbox WHERE relayed=0"
        ).fetchall()
    rows = []
    for oid in dict.fromkeys(outbox_ids):
        row = conn.execute(
            "SELECT outbox_id, stream_id, action, target_direct_event_key,"
            " rationale, actor_local_id FROM ledger_outbox"
            " WHERE outbox_id=? AND relayed=0",
            (oid,),
        ).fetchone()
        if row:
            rows.append(row)
    return rows


def fetch_request_unrelayed_outbox_ids(conn, request_id: str) -> list[str]:
    """Fetch unrelayed outbox IDs owned strictly by the specified request."""
    prefix = "ledger-" + request_id + "-"
    rows = conn.execute(
        "SELECT outbox_id FROM ledger_outbox WHERE relayed=0"
    ).fetchall()
    return [row[0] for row in rows if owns_outbox_id(row[0], prefix)]


def fetch_outbox_event_id(conn, outbox_id: str) -> Optional[str]:
    """Look up event_id from ledger_outbox when already marked relayed."""
    row = conn.execute(
        "SELECT event_id FROM ledger_outbox WHERE outbox_id=? AND relayed=1",
        (outbox_id,),
    ).fetchone()
    return row[0] if row and row[0] else None


def insert_outbox_entry(
    conn,
    *,
    outbox_id: str,
    stream_id: str,
    action: str,
    target: Any,
    rationale: str,
    actor: str,
    event_id: str = "",
    relayed: int = 0,
    created_at: str,
) -> None:
    """Insert an entry into the ledger_outbox table."""
    conn.execute(
        "INSERT OR IGNORE INTO ledger_outbox(outbox_id, stream_id, action,"
        " target_direct_event_key, rationale, actor_local_id,"
        " event_id, relayed, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            outbox_id,
            stream_id,
            action,
            target,
            rationale,
            actor,
            event_id,
            relayed,
            created_at,
        ),
    )


def update_outbox_relayed(conn, outbox_id: str, event_id: str) -> None:
    """Mark an outbox row as relayed with the corresponding event_id."""
    conn.execute(
        "UPDATE ledger_outbox SET event_id=?, relayed=1 WHERE outbox_id=?",
        (event_id, outbox_id),
    )


def resolve_outbox_event_id(conn, ledger, outbox_id: str) -> Optional[str]:
    """Resolve event_id from outbox table or query the ledger fallback."""
    event_id = fetch_outbox_event_id(conn, outbox_id)
    if event_id:
        return event_id
    if ledger is None:
        return None
    found = None
    try:
        found = ledger.find_by_client_request(outbox_id)
    except Exception:
        found = None
    return found["event_id"] if found else None


__all__ = [
    "canonical_json",
    "fetch_outbox_event_id",
    "fetch_request_unrelayed_outbox_ids",
    "fetch_unrelayed_outbox_rows",
    "indexed_outbox_id",
    "insert_outbox_entry",
    "owns_outbox_id",
    "request_outbox_id",
    "resolve_outbox_event_id",
    "row_outbox_id",
    "row_sub_outbox_id",
    "source_fact_digest",
    "trip_outbox_id",
    "update_outbox_relayed",
]
