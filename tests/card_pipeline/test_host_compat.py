# -*- coding: utf-8 -*-
"""Compatibility with the host web app's own database.

The web app already owns a `classification_rules` table, with different columns,
and it also owns the board the pipeline publishes into. The pipeline must add
its tables beside those without touching them, so this checks the collision and
the coexistence directly against a hand-built legacy schema.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import Pipeline, Store  # noqa: E402
from app.db import StoreError  # noqa: E402
from .fixtures import DOMESTIC_HEADERS, domestic_row, make_xlsx  # noqa: E402

# The legacy table, reduced to the shape that matters: the same name, different
# columns. Creating it first is the whole point — the pipeline has to cope with
# finding it already there.
LEGACY_SCHEMA = """
CREATE TABLE classification_rules (
    rule_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    base_rule_version INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    apply_existing INTEGER NOT NULL DEFAULT 0,
    apply_future INTEGER NOT NULL DEFAULT 0,
    rule_hash TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    learning_case_id TEXT,
    future_boundary_rowid TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE board_rows (
    row_id TEXT PRIMARY KEY,
    display_tab_id TEXT NOT NULL,
    item TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO classification_rules VALUES
 ('legacy-rule', 3, 0, 'active', 1, 1, 'hash', '{}', 'legacy-case', NULL,
  '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
INSERT INTO board_rows VALUES ('board-1', 'trip:seoul-2026', '숙박비', 1);
"""


@pytest.fixture()
def legacy_conn(tmp_path):
    path = str(tmp_path / "host.sqlite")
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript(LEGACY_SCHEMA)
    yield conn
    conn.close()


def test_the_pipeline_adds_its_tables_without_touching_the_hosts(legacy_conn):
    pipe = Pipeline(legacy_conn)
    tables = {r[0] for r in legacy_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "cost_classification_rules" in tables
    assert "classification_rules" in tables  # the host's, untouched

    # The host's row is still exactly as it was.
    row = legacy_conn.execute(
        "SELECT version, base_rule_version, status, rule_hash, rule_json,"
        " learning_case_id, future_boundary_rowid FROM classification_rules"
        " WHERE rule_id='legacy-rule'").fetchone()
    assert row == (3, 0, "active", "hash", "{}", "legacy-case", None)


def test_a_pipeline_rule_does_not_land_in_the_hosts_table(legacy_conn):
    pipe = Pipeline(legacy_conn)
    saved = pipe.save_rule({"conditions": {"merchant_normalized": "합성erei"},
                            "effects": {"item": "식비"},
                            "rule_id": "cost-rule-1"})
    assert saved["action"] == "created"
    # It is in the namespaced table...
    assert legacy_conn.execute(
        "SELECT COUNT(*) FROM cost_classification_rules WHERE rule_id=?",
        ("cost-rule-1",)).fetchone()[0] == 1
    # ...and the host's table still holds only its own row.
    names = [r[0] for r in legacy_conn.execute(
        "SELECT rule_id FROM classification_rules")]
    assert names == ["legacy-rule"]


def test_running_twice_is_still_additive(legacy_conn):
    Pipeline(legacy_conn)
    Pipeline(legacy_conn)  # a second process would do exactly this
    columns = {r[1] for r in legacy_conn.execute("PRAGMA table_info(classification_rules)")}
    assert "base_rule_version" in columns
    assert "conditions_json" not in columns  # never redefined in place


def test_a_projection_can_publish_into_the_hosts_board_rows(legacy_conn):
    """The projection runs inside the commit transaction, so a board row and
    its ledger entry commit together or not at all."""
    pipe = Pipeline(legacy_conn)
    content = make_xlsx([
        domestic_row(merchant="GS25", amount=3000, approval="L1")],
        DOMESTIC_HEADERS)
    batch = pipe.receive(content, "a.xlsx")
    row = pipe.get_batch(batch["batch_id"])["rows"][0]
    pipe.save_decision(row["transaction_id"], row["revision"], item="식비",
                       display_tab_id="trip:seoul-2026",
                       tab_validator=lambda tab: tab == "trip:seoul-2026",
                       request_id="d1")
    result = pipe.preview(batch["batch_id"],
                          tab_validator=lambda tab: tab == "trip:seoul-2026")

    published = []

    def projection(entry):
        legacy_conn.execute(
            "INSERT INTO board_rows(row_id, display_tab_id, item, revision)"
            " VALUES (?,?,?,1)",
            ("board-" + entry["transaction_id"][:8], entry["display_tab_id"],
             entry["item"]))
        published.append(entry["transaction_id"])

    applied = pipe.commit(batch["batch_id"], result["digest"], "c1",
                          projection=projection,
                          tab_validator=lambda tab: tab == "trip:seoul-2026")
    assert applied["applied"] == 1
    assert len(published) == 1
    assert legacy_conn.execute(
        "SELECT COUNT(*) FROM board_rows WHERE row_id <> 'board-1'"
    ).fetchone()[0] == 1

    # A projection that fails takes the board row back with the ledger entry.
    # A *fresh* transaction, because the first one is already booked and would
    # be skipped as idempotent before the projection is ever reached.
    second = pipe.receive(make_xlsx([
        domestic_row(merchant="GS25", amount=4000, approval="L2")],
        DOMESTIC_HEADERS), "b.xlsx")
    row2 = pipe.get_batch(second["batch_id"])["rows"][0]
    pipe.save_decision(row2["transaction_id"], row2["revision"], item="식비",
                       display_tab_id="trip:seoul-2026",
                       tab_validator=lambda tab: tab == "trip:seoul-2026",
                       request_id="d2")
    result2 = pipe.preview(second["batch_id"],
                           tab_validator=lambda tab: tab == "trip:seoul-2026")

    def failing(entry):
        legacy_conn.execute(
            "INSERT INTO board_rows(row_id, display_tab_id, item, revision)"
            " VALUES (?,?,?,1)", ("board-boom", entry["display_tab_id"], "x"))
        raise RuntimeError("board write refused")

    with pytest.raises(RuntimeError):
        pipe.commit(second["batch_id"], result2["digest"], "c2",
                    projection=failing,
                    tab_validator=lambda tab: tab == "trip:seoul-2026")
    assert legacy_conn.execute(
        "SELECT COUNT(*) FROM board_rows WHERE row_id='board-boom'"
    ).fetchone()[0] == 0
    assert legacy_conn.execute(
        "SELECT COUNT(*) FROM ledger_entries WHERE batch_id=?",
        (second["batch_id"],)).fetchone()[0] == 0


def test_store_close_actually_closes_the_handle(tmp_path):
    store = Store.open(str(tmp_path / "own.sqlite"))
    store.ensure_schema()
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.conn.execute("SELECT 1")


def test_a_store_built_on_a_bare_connection_does_not_own_it(tmp_path):
    """The caller keeps its own handle: closing the store must not close it."""
    conn = sqlite3.connect(str(tmp_path / "bare.sqlite"), isolation_level=None)
    store = Store(conn)
    store.close()
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    conn.close()
