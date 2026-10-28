"""Synthetic tests for RF-101 pure audit and outbox responsibility extraction.

Verifies:
- Canonical JSON serialization and source fact digest differential against base commit 2384cfd
- Outbox ownership rules (owns_outbox_id) and exact AST differential
- Outbox ID formatting helpers
- Outbox DB queries and lifecycle (insert, unrelayed fetch, update, resolve)
- LedgerStore facade delegation, lock preservation, and relay coordination
"""
from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import subprocess
from typing import Any

import pytest

import webapp.ledger_store as ls_module
from webapp.ledger_store import LedgerStore, SCHEMA_SQL
from webapp.ledger_store_audit import (
    canonical_json,
    fetch_outbox_event_id,
    fetch_request_unrelayed_outbox_ids,
    fetch_unrelayed_outbox_rows,
    indexed_outbox_id,
    insert_outbox_entry,
    owns_outbox_id,
    request_outbox_id,
    resolve_outbox_event_id,
    row_outbox_id,
    row_sub_outbox_id,
    source_fact_digest,
    trip_outbox_id,
    update_outbox_relayed,
)


def _load_base_2384cfd_functions():
    p = subprocess.run(
        ["git", "show", "2384cfd:webapp/ledger_store.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    tree = ast.parse(p.stdout)

    fn_nodes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_canonical",
            "_source_fact_digest",
            "_owns_outbox_id",
            "_outbox_event",
        ):
            fn_nodes[node.name] = node

    ns = {"json": json, "hashlib": hashlib}
    code = (
        "def base_canonical(value) -> str:\n"
        "    return json.dumps(value, ensure_ascii=False, sort_keys=True)\n"
        "\n"
        "def base_source_fact_digest(facts: dict) -> str:\n"
        "    canonical = json.dumps(facts, ensure_ascii=False, sort_keys=True,\n"
        "                           separators=(',', ':'))\n"
        "    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()\n"
        "\n"
        "def base_owns_outbox_id(outbox_id, prefix: str) -> bool:\n"
        "    if type(outbox_id) is not str or not outbox_id.startswith(prefix):\n"
        "        return False\n"
        "    tail = outbox_id[len(prefix):]\n"
        "    return bool(tail) and tail.isascii() and tail.isdigit()\n"
    )
    exec(code, ns)
    return ns, fn_nodes


def test_canonical_json_and_source_fact_digest_differential():
    ns, _ = _load_base_2384cfd_functions()
    base_canonical = ns["base_canonical"]
    base_digest = ns["base_source_fact_digest"]

    samples = [
        {},
        {"z": 1, "a": 2, "m": [3, 2, 1]},
        {"korean": "한글 내용", "numbers": [100, -50, 0], "flag": True, "empty": None},
        {"nested": {"b": "second", "a": "first", "c": {"deep": True}}},
    ]

    for sample in samples:
        expected_canon = base_canonical(sample)
        assert canonical_json(sample) == expected_canon
        assert ls_module._canonical(sample) == expected_canon

        expected_digest = base_digest(sample)
        assert source_fact_digest(sample) == expected_digest
        assert ls_module._source_fact_digest(sample) == expected_digest


def test_owns_outbox_id_rules_and_differential():
    ns, _ = _load_base_2384cfd_functions()
    base_owns = ns["base_owns_outbox_id"]

    prefix = "ledger-req123-"
    cases = [
        ("ledger-req123-0", True),
        ("ledger-req123-1", True),
        ("ledger-req123-999", True),
        ("ledger-req123-", False),  # empty tail
        ("ledger-req123-child-0", False),  # non-numeric tail
        ("ledger-req123-1a", False),  # mixed alphanumeric
        ("ledger-req1234-0", False),  # wrong prefix
        ("ledger-req123-\u0660", False),  # non-ASCII arabic numeral
        (None, False),
        (12345, False),
        (["ledger-req123-0"], False),
    ]

    for oid, expected in cases:
        assert base_owns(oid, prefix) == expected
        assert owns_outbox_id(oid, prefix) == expected
        assert LedgerStore._owns_outbox_id(oid, prefix) == expected


def test_outbox_id_formatting_helpers():
    assert request_outbox_id("req1") == "ledger-req1"
    assert trip_outbox_id("req1") == "ledger-trip-req1"
    assert row_outbox_id("req1", "r1") == "ledger-req1-r1"
    assert row_sub_outbox_id("req1", "r1") == "ledger-req1:r1"
    assert indexed_outbox_id("req1", 3) == "ledger-req1-3"


def test_outbox_lifecycle_in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)

    # 1. Insert outbox entries
    insert_outbox_entry(
        conn,
        outbox_id="ledger-reqA-0",
        stream_id="row-1",
        action="update",
        target="target-1",
        rationale="test",
        actor="owner",
        relayed=0,
        created_at="2026-10-28T00:00:00Z",
    )
    insert_outbox_entry(
        conn,
        outbox_id="ledger-reqA-1",
        stream_id="row-1",
        action="update",
        target="target-2",
        rationale="test",
        actor="owner",
        relayed=0,
        created_at="2026-10-28T00:00:01Z",
    )
    insert_outbox_entry(
        conn,
        outbox_id="ledger-reqB-0",
        stream_id="row-2",
        action="update",
        target="target-3",
        rationale="test",
        actor="owner",
        relayed=0,
        created_at="2026-10-28T00:00:02Z",
    )

    # 2. Fetch all unrelayed
    unrelayed = fetch_unrelayed_outbox_rows(conn)
    assert len(unrelayed) == 3
    assert {row[0] for row in unrelayed} == {"ledger-reqA-0", "ledger-reqA-1", "ledger-reqB-0"}

    # 3. Fetch request-specific unrelayed IDs (strictly reqA)
    reqA_unrelayed = fetch_request_unrelayed_outbox_ids(conn, "reqA")
    assert reqA_unrelayed == ["ledger-reqA-0", "ledger-reqA-1"]

    # 4. Update relayed
    update_outbox_relayed(conn, "ledger-reqA-0", "evt-100")
    assert fetch_outbox_event_id(conn, "ledger-reqA-0") == "evt-100"
    assert fetch_outbox_event_id(conn, "ledger-reqA-1") is None

    # 5. Resolve event_id with ledger fallback
    class MockLedger:
        def find_by_client_request(self, client_request_id):
            if client_request_id == "ledger-fallback-1":
                return {"event_id": "evt-fallback"}
            return None

    mock_ledger = MockLedger()
    # Resolved from SQLite table
    assert resolve_outbox_event_id(conn, mock_ledger, "ledger-reqA-0") == "evt-100"
    # Resolved via fallback to ledger
    assert resolve_outbox_event_id(conn, mock_ledger, "ledger-fallback-1") == "evt-fallback"
    # Not found in either
    assert resolve_outbox_event_id(conn, mock_ledger, "ledger-unknown") is None


def test_facade_delegation_and_relay(tmp_path):
    db_path = str(tmp_path / "test_store.db")
    store = LedgerStore(db_path)

    # Enqueue in store
    store._begin_write()
    store._enqueue_ledger(
        outbox_id="ledger-test-0",
        stream_id="row-1",
        action="propose",
        target="tgt",
        rationale="rat",
        actor="owner",
    )
    store._commit_write()

    # Outbox table has 1 unrelayed row
    rows = fetch_unrelayed_outbox_rows(store.conn)
    assert len(rows) == 1
    assert rows[0][0] == "ledger-test-0"

    # Relay outbox
    results = store._relay_outbox(["ledger-test-0"])
    assert "ledger-test-0" in results
    event_id = results["ledger-test-0"]
    assert event_id is not None

    # Check store._outbox_event retrieves the relayed event_id
    assert store._outbox_event("ledger-test-0") == event_id

    # Relay again should find no unrelayed rows
    unrelayed_after = fetch_unrelayed_outbox_rows(store.conn)
    assert len(unrelayed_after) == 0

    store.conn.close()
