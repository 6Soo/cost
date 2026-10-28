"""Synthetic tests for RF-101 schema responsibility extraction.

Verifies:
- Exact string identity of SCHEMA_SQL and AST identity of ensure helpers with 2384cfd
- Schema table creation in temporary synthetic DB
- Legacy columns migration on pre-existing tables
- Second execution idempotency
- Preservation of user data across ensure runs
- LedgerStore __init__ initialization and re-export contracts
"""
from __future__ import annotations

import ast
import sqlite3
import subprocess

import pytest

import webapp.ledger_store as ls_module
from webapp.ledger_store import (
    LedgerStore,
    SCHEMA_SQL,
    _ensure_correction_columns,
    _ensure_rule_turn_columns,
    _ensure_trip_tab_columns,
)
from webapp.ledger_store_schema import (
    SCHEMA_SQL as SCHEMA_SQL_DIRECT,
    _ensure_correction_columns as ensure_corr_direct,
    _ensure_rule_turn_columns as ensure_rule_direct,
    _ensure_trip_tab_columns as ensure_trip_direct,
)


def test_schema_sql_and_helper_ast_identical_to_base_commit_2384cfd():
    p = subprocess.run(
        ["git", "show", "2384cfd:webapp/ledger_store.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    base_code = p.stdout

    # Parse base commit AST
    base_tree = ast.parse(base_code)

    def get_node(tree, name, node_type):
        for node in tree.body:
            if node_type == "Assign" and isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == name:
                        return node
            elif node_type == "FunctionDef" and isinstance(node, ast.FunctionDef):
                if node.name == name:
                    return node
        return None

    # Verify SCHEMA_SQL string equality
    base_sql_node = get_node(base_tree, "SCHEMA_SQL", "Assign")
    assert base_sql_node is not None
    assert base_sql_node.value.value == SCHEMA_SQL_DIRECT
    assert SCHEMA_SQL is SCHEMA_SQL_DIRECT

    # Verify ensure functions AST equality
    for fn_name in ["_ensure_correction_columns", "_ensure_rule_turn_columns", "_ensure_trip_tab_columns"]:
        base_fn = get_node(base_tree, fn_name, "FunctionDef")
        curr_fn = getattr(ls_module, fn_name)
        assert base_fn is not None
        # Parse current function source from schema module
        import inspect
        curr_source = inspect.getsource(curr_fn)
        curr_tree = ast.parse(curr_source)
        curr_fn_node = curr_tree.body[0]
        assert ast.dump(base_fn) == ast.dump(curr_fn_node)


def test_schema_creation_in_memory():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "board_rows" in tables
    assert "board_revisions" in tables
    assert "income_allocations" in tables
    assert "trip_tabs" in tables
    assert "rule_turns" in tables
    assert "income_corrections" in tables


def test_legacy_columns_migration_and_user_row_preservation():
    conn = sqlite3.connect(":memory:")
    # Create minimal legacy tables missing the new columns
    conn.execute("CREATE TABLE rule_turns (turn_id TEXT PRIMARY KEY, user_val TEXT)")
    conn.execute("CREATE TABLE trip_tabs (tab_id TEXT PRIMARY KEY, user_val TEXT)")
    conn.execute("CREATE TABLE income_corrections (correction_id TEXT PRIMARY KEY, user_val TEXT)")
    conn.execute("CREATE TABLE board_revisions (id INTEGER PRIMARY KEY, row_id TEXT, user_val TEXT)")

    # Insert user data before ensure calls
    conn.execute("INSERT INTO rule_turns VALUES ('turn-1', 'keep_turn')")
    conn.execute("INSERT INTO trip_tabs VALUES ('tab-1', 'keep_tab')")
    conn.execute("INSERT INTO income_corrections VALUES ('corr-1', 'keep_corr')")
    conn.execute("INSERT INTO board_revisions VALUES (1, 'row-1', 'keep_rev')")

    # Run ensure helpers
    _ensure_correction_columns(conn)
    _ensure_rule_turn_columns(conn)
    _ensure_trip_tab_columns(conn)

    # Verify new columns added
    rule_cols = {row[1] for row in conn.execute("PRAGMA table_info(rule_turns)").fetchall()}
    assert "process_run_id" in rule_cols
    assert "abandoned_reason" in rule_cols

    trip_cols = {row[1] for row in conn.execute("PRAGMA table_info(trip_tabs)").fetchall()}
    assert "event_year" in trip_cols
    assert "tab_kind" in trip_cols
    assert "authority_status" in trip_cols
    assert "source_sha256" in trip_cols
    assert "sort_order" in trip_cols
    assert "assignee_source" in trip_cols

    corr_cols = {row[1] for row in conn.execute("PRAGMA table_info(income_corrections)").fetchall()}
    assert "corrected_occurred_on" in corr_cols
    assert "row_revision" in corr_cols

    rev_cols = {row[1] for row in conn.execute("PRAGMA table_info(board_revisions)").fetchall()}
    assert "kind" in rev_cols
    assert "reverts_event_id" in rev_cols

    # Verify user rows preserved with defaults for new columns
    turn_row = conn.execute("SELECT user_val, process_run_id, abandoned_reason FROM rule_turns WHERE turn_id='turn-1'").fetchone()
    assert turn_row == ("keep_turn", "", "")

    trip_row = conn.execute("SELECT user_val, event_year, tab_kind, authority_status FROM trip_tabs WHERE tab_id='tab-1'").fetchone()
    assert trip_row == ("keep_tab", 0, "trip", "needs_review")

    rev_row = conn.execute("SELECT user_val, kind, reverts_event_id FROM board_revisions WHERE id=1").fetchone()
    assert rev_row == ("keep_rev", "save", "")


def test_ensure_functions_idempotency():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)

    # First run
    _ensure_correction_columns(conn)
    _ensure_rule_turn_columns(conn)
    _ensure_trip_tab_columns(conn)

    # Second run must be completely idempotent (no exception)
    _ensure_correction_columns(conn)
    _ensure_rule_turn_columns(conn)
    _ensure_trip_tab_columns(conn)


def test_ledger_store_init_and_reexports(tmp_path):
    # Verify LedgerStore initialization order and table readiness
    db_path = tmp_path / "schema_test.db"
    store = LedgerStore(db_path, seed_demo=False)
    try:
        tables = {row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "board_rows" in tables
        assert "trip_tabs" in tables

        # Verify re-export on webapp.ledger_store
        assert hasattr(ls_module, "SCHEMA_SQL")
        assert hasattr(ls_module, "_ensure_correction_columns")
        assert hasattr(ls_module, "_ensure_rule_turn_columns")
        assert hasattr(ls_module, "_ensure_trip_tab_columns")
    finally:
        store.close()
