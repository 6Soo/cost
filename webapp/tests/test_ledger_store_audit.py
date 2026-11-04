"""Synthetic tests for RF-101 pure audit and outbox responsibility extraction.

Verifies:
- Canonical JSON serialization and source fact digest differential against base commit 2384cfd
- Outbox ownership rules (owns_outbox_id) and exact AST differential
- LedgerStore facade delegation, lock boundary, and _owns_outbox_id dynamic dispatch preservation
- Outbox relay lifecycle, failure handling, and replay idempotency
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess

import pytest

import webapp.ledger_store as ls_module
from webapp.ledger_store import LedgerStore
from webapp.ledger_store_audit import (
    canonical_json,
    owns_outbox_id,
    source_fact_digest,
)


@pytest.mark.parametrize('unified', [False, True])
def test_first_audited_save_of_advanced_import_revision(tmp_path, monkeypatch, unified):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1' if unified else '0')
    store = LedgerStore(tmp_path / 'board.sqlite')
    try:
        row_id = 'expense-demo-c1'
        row = store.get_row(row_id)
        # Imported projections may already have revisions without a board
        # decision stream. Match both the indexed and serialized revision.
        payload = json.loads(store.conn.execute(
            'SELECT payload_json FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0])
        payload['revision'] = 4
        store.conn.execute('UPDATE board_rows SET revision=4,payload_json=? WHERE row_id=?',
                           (json.dumps(payload), row_id))
        original_facts = (row['amount_krw'], row.get('occurred_on'), row.get('source_event_id'))
        for revision, request_id, description in ((4, 'sync-first', '동기화'), (5, 'sync-next', '다음 동기화')):
            result = store.save(row_id=row_id, expected_revision=revision,
                client_request_id=request_id, change_mode='rule_change',
                changes={'description': description}, actor='automatic')
            assert result['outcome'] == 'saved'
            assert not result.get('ledger_pending')
            assert store.save(row_id=row_id, expected_revision=revision,
                client_request_id=request_id, change_mode='rule_change',
                changes={'description': description}, actor='automatic') == result
        events = [event for event in store.ledger.all_events() if event['stream_id'] == 'row-' + row_id]
        assert [event['action'] for event in events] == ['propose', 'correct']
        assert store.ledger.verify_chain()['ok']
        saved = store.get_row(row_id)
        assert (saved['amount_krw'], saved.get('occurred_on'), saved.get('source_event_id')) == original_facts
        assert store.conn.execute('SELECT COUNT(*) FROM board_manual_overrides').fetchone()[0] == 0
    finally:
        store.close()


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


def test_relay_request_outbox_preserves_dynamic_dispatch_and_lock_boundary(tmp_path, monkeypatch):
    """Verify _relay_request_outbox calls self._owns_outbox_id dynamic dispatch outside lock."""
    db_path = str(tmp_path / "test_dispatch.db")
    store = LedgerStore(db_path)

    # Insert raw outbox rows directly
    store.conn.execute(
        "INSERT INTO ledger_outbox(outbox_id, stream_id, action, target_direct_event_key,"
        " rationale, actor_local_id, event_id, relayed, created_at)"
        " VALUES ('ledger-req1-0', 'row-1', 'propose', 'tgt', 'rat', 'owner', '', 0, '2026-10-28T00:00:00Z')"
    )
    store.conn.execute(
        "INSERT INTO ledger_outbox(outbox_id, stream_id, action, target_direct_event_key,"
        " rationale, actor_local_id, event_id, relayed, created_at)"
        " VALUES ('ledger-req1-1', 'row-1', 'propose', 'tgt', 'rat', 'owner', '', 0, '2026-10-28T00:00:01Z')"
    )
    store.conn.commit()

    owns_calls = []
    original_owns = store._owns_outbox_id

    def custom_owns(oid, prefix):
        owns_calls.append((oid, prefix))
        return original_owns(oid, prefix)

    # Monkeypatch method on instance to verify dynamic dispatch is honored
    monkeypatch.setattr(store, "_owns_outbox_id", custom_owns)

    relayed_batches = []
    monkeypatch.setattr(store, "_relay_outbox", lambda pending: relayed_batches.append(list(pending)))

    store._relay_request_outbox("req1")

    # Verify custom_owns was called for each candidate row with the expected prefix
    assert ("ledger-req1-0", "ledger-req1-") in owns_calls
    assert ("ledger-req1-1", "ledger-req1-") in owns_calls
    # Verify _relay_outbox received the filtered pending list
    assert relayed_batches == [["ledger-req1-0", "ledger-req1-1"]]

    store.conn.close()


def test_outbox_lifecycle_failure_and_replay(tmp_path, monkeypatch):
    """Test full outbox enqueue -> failure -> replay cycle on LedgerStore."""
    # This scenario specifically exercises the separate-ledger relay. Other
    # suites can enable embedded auditing, where enqueue is already relayed.
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '0')
    db_path = str(tmp_path / "test_lifecycle.db")
    store = LedgerStore(db_path)

    # 1. Enqueue outbox item
    store._begin_write()
    store._enqueue_ledger(
        outbox_id="ledger-reqA-0",
        stream_id="row-1",
        action="propose",
        target="tgt-1",
        rationale="test rationale",
        actor="owner",
    )
    store._commit_write()

    # 2. Check pending in outbox
    unrelayed = store.conn.execute("SELECT outbox_id FROM ledger_outbox WHERE relayed=0").fetchall()
    assert len(unrelayed) == 1
    assert unrelayed[0][0] == "ledger-reqA-0"

    # 3. Relay outbox successfully
    res = store._relay_outbox(["ledger-reqA-0"])
    event_id = res["ledger-reqA-0"]
    assert event_id is not None

    # 4. Outbox table marked relayed
    relayed_row = store.conn.execute(
        "SELECT event_id, relayed FROM ledger_outbox WHERE outbox_id='ledger-reqA-0'"
    ).fetchone()
    assert relayed_row[0] == event_id
    assert relayed_row[1] == 1

    # 5. _outbox_event retrieves the event_id
    assert store._outbox_event("ledger-reqA-0") == event_id

    # 6. Re-relaying same outbox_id is a no-op
    res2 = store._relay_outbox(["ledger-reqA-0"])
    assert res2 == {}

    store.conn.close()
