"""Pure audit, outbox identification, and canonical serialization rules for LedgerStore.

Extracted under RF-101 (Store decomposition audit & outbox boundary).
Preserves exact execution semantics, canonical JSON sorting, and outbox ownership
proofs of the original store.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


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


__all__ = [
    "canonical_json",
    "owns_outbox_id",
    "source_fact_digest",
]
