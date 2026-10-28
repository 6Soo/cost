"""Synthetic tests for pure row read, projection, and record decoding.

Verifies RF-101 row read projections and LedgerStore facade contracts.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

import pytest

from webapp.ledger_store import LedgerStore
from webapp.ledger_store_records import (
    ALLOCATION_ROW_EDITABLE,
    _row_to_record,
    allocation_row_to_dict,
    build_allocation_display_row,
    build_remainder_display_row,
    calculate_display_amount,
    calculate_display_occurred_on,
    calculate_split_remainder,
    count_visible_rows,
    deserialize_row_record,
    format_correction_record,
    format_history_entry,
    project_allocation_history,
    project_record,
    read_active_allocations,
    read_allocation,
    read_board_row,
    read_conflicting_row_ids,
    read_corrections,
    read_history,
    read_latest_allocation_history,
    read_latest_correction,
    read_row_conflict,
    read_split_source_ids,
    read_tab_rows,
)


def test_row_to_record_expense():
    raw = {
        "row_id": "exp-1",
        "display_tab_id": "tab-a",
        "occurred_on": "2026-10-01",
        "item": "호텔",
        "description": "도쿄 호텔",
        "service_period": "2026-10-01~2026-10-03",
        "reservation_no": "HTL-999",
        "evidence_type": "카드",
        "amount_krw": 250000,
        "source_kind": "카드",
        "source_event_id": "APPR-100",
        "classification_state": "confirmed",
        "classification_basis": "exact",
        "source_merchant": "Tokyo Hotel",
        "event_kind": "승인",
        "card_kind": "신용",
        "extra_unknown_field": "ignore_me",
    }
    rec = _row_to_record("expense", raw)
    assert rec["row_id"] == "exp-1"
    assert rec["row_kind"] == "expense"
    assert rec["display_tab_id"] == "tab-a"
    assert rec["revision"] == 1
    assert rec["amount_krw"] == 250000
    assert rec["operator_note"] == ""
    assert "extra_unknown_field" not in rec


def test_row_to_record_expense_decimal_conversion():
    raw = {
        "row_id": "exp-2",
        "display_tab_id": None,
        "occurred_on": "2026-10-02",
        "item": "교통",
        "description": "기차",
        "amount_krw": Decimal("15000"),
        "source_kind": "카드",
        "source_event_id": "APPR-101",
    }
    rec = _row_to_record("expense", raw)
    assert rec["amount_krw"] == 15000
    assert isinstance(rec["amount_krw"], int)


def test_row_to_record_income():
    raw = {
        "row_id": "inc-1",
        "display_tab_id": "tab-b",
        "occurred_on": "2026-10-03",
        "customer_id": "cust-7",
        "customer_name": "홍길동",
        "nickname": "길동",
        "income_kind": "참가비",
        "event_type": "receipt",
        "amount_krw": 100000,
        "source_kind": "은행",
        "source_event_id": "TX-55",
    }
    rec = _row_to_record("income", raw)
    assert rec["row_id"] == "inc-1"
    assert rec["row_kind"] == "income"
    assert rec["customer_id"] == "cust-7"
    assert rec["customer_name"] == "홍길동"
    assert rec["nickname"] == "길동"
    assert rec["revision"] == 1
    assert rec["amount_krw"] == 100000


def test_deserialize_row_record():
    payload = {"occurred_on": "2026-10-05", "item": "식대", "amount_krw": 30000}
    payload_json = json.dumps(payload)
    rec = deserialize_row_record("row-x", "expense", "tab-z", 3, payload_json)
    assert rec["row_id"] == "row-x"
    assert rec["row_kind"] == "expense"
    assert rec["display_tab_id"] == "tab-z"
    assert rec["revision"] == 3
    assert rec["item"] == "식대"
    assert rec["amount_krw"] == 30000


def test_calculate_display_amount_and_occurred_on():
    card_row = {"source_kind": "카드", "amount_krw": 50000, "occurred_on": "2026-10-10"}
    # Card rows are unaffected by corrections
    assert calculate_display_amount(card_row, latest_correction=(1, 99999, "2026-10-11")) == 50000
    assert calculate_display_occurred_on(card_row, latest_correction=(1, 99999, "2026-10-11")) == "2026-10-10"

    # Bank row without correction
    bank_row = {"source_kind": "은행", "amount_krw": 70000, "occurred_on": "2026-10-10"}
    assert calculate_display_amount(bank_row, latest_correction=None) == 70000
    assert calculate_display_occurred_on(bank_row, latest_correction=None) == "2026-10-10"

    # Bank row with tuple correction
    corr_tuple = ("c-1", 65000, "2026-10-12", 2, "수정", "owner", "2026-10-12T00:00:00Z")
    assert calculate_display_amount(bank_row, latest_correction=corr_tuple) == 65000
    assert calculate_display_occurred_on(bank_row, latest_correction=corr_tuple) == "2026-10-12"

    # Bank row with dict correction
    corr_dict = {"corrected_amount_krw": 62000, "corrected_occurred_on": "2026-10-13"}
    assert calculate_display_amount(bank_row, latest_correction=corr_dict) == 62000
    assert calculate_display_occurred_on(bank_row, latest_correction=corr_dict) == "2026-10-13"

    # Bank row with correction lacking date keeps original date
    corr_nodate = ("c-2", 60000, None)
    assert calculate_display_occurred_on(bank_row, latest_correction=corr_nodate) == "2026-10-10"


def test_project_record():
    row = {"row_id": "r-1", "source_kind": "은행", "amount_krw": 100000, "occurred_on": "2026-10-01"}
    corr = ("c-1", 90000, "2026-10-02")
    projected = project_record(row, latest_correction=corr)
    assert projected["display_amount_krw"] == 90000
    assert projected["display_occurred_on"] == "2026-10-02"
    assert projected["amount_krw"] == 100000
    assert projected["occurred_on"] == "2026-10-01"

    # Overridden projection
    custom = project_record(row, display_amount_krw=85000, display_occurred_on="2026-10-05")
    assert custom["display_amount_krw"] == 85000
    assert custom["display_occurred_on"] == "2026-10-05"


def test_allocation_projections():
    raw_alloc = (
        "alloc-1", "inc-source-1", "cust-1", "김철수", "철수", "tab-1", "deposit", 40000, 1, 2
    )
    alloc_dict = allocation_row_to_dict(raw_alloc)
    assert alloc_dict["allocation_id"] == "alloc-1"
    assert alloc_dict["active"] is True
    assert alloc_dict["amount_krw"] == 40000

    source = {
        "row_id": "inc-source-1",
        "revision": 2,
        "occurred_on": "2026-10-01",
        "display_occurred_on": "2026-10-01",
        "source_kind": "은행",
        "source_event_id": "tx-1",
    }
    disp_row = build_allocation_display_row(alloc_dict, source, display_occurred_on="2026-10-01")
    assert disp_row["is_allocation"] is True
    assert disp_row["row_id"] == "alloc-1"
    assert disp_row["display_amount_krw"] == 40000
    assert disp_row["occurred_on"] == "2026-10-01"

    rem_row = build_remainder_display_row(source, remainder_krw=60000, display_occurred_on="2026-10-01")
    assert rem_row["is_remainder"] is True
    assert rem_row["row_id"] == "rem-inc-source-1"
    assert rem_row["display_amount_krw"] == 60000


def test_project_allocation_history():
    alloc = {
        "allocation_id": "alloc-1",
        "customer_id": "cust-1",
        "customer_name": "김철수",
        "nickname": "철수",
        "display_tab_id": "tab-1",
        "income_kind": "deposit",
        "amount_krw": 40000,
        "active": 1,
        "source_revision": 2,
        "internal_note": "secret",
    }
    proj = project_allocation_history(alloc)
    for field in ALLOCATION_ROW_EDITABLE:
        assert field in proj
    assert proj["amount_krw"] == 40000
    assert proj["active"] is True
    assert proj["source_revision"] == 2
    assert "internal_note" not in proj


def test_calculate_split_remainder():
    source = {"row_id": "inc-1"}
    active = [{"amount_krw": 30000}, {"amount_krw": 20000}]
    assert calculate_split_remainder(source, 100000, active) == 50000
    assert calculate_split_remainder(None, 100000, active) == 0


def test_format_history_entry_and_corrections():
    ext_hist = (1, '{"a": 1}', '{"a": 2}', "ev-1", "save", "owner", "2026-10-10", "req-1", "conflict", "ev-0")
    h = format_history_entry(ext_hist, has_extended_columns=True)
    assert h["kind"] == "conflict"
    assert h["reverts_event_id"] == "ev-0"

    leg_hist = (1, '{"a": 1}', '{"a": 2}', "ev-1", "save", "owner", "2026-10-10", "req-1")
    h_leg = format_history_entry(leg_hist, has_extended_columns=False)
    assert h_leg["kind"] == "save"
    assert h_leg["reverts_event_id"] == ""

    ext_corr = ("c-1", 50000, "2026-10-11", 2, "사유", "owner", "2026-10-10")
    c = format_correction_record(ext_corr, has_extended_columns=True)
    assert c["corrected_amount_krw"] == 50000
    assert c["corrected_occurred_on"] == "2026-10-11"


def test_sqlite_read_functions_in_memory():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE board_rows (
            row_id TEXT PRIMARY KEY,
            row_kind TEXT NOT NULL,
            display_tab_id TEXT,
            revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE income_allocations (
            allocation_id TEXT PRIMARY KEY,
            source_row_id TEXT NOT NULL,
            customer_id TEXT,
            customer_name TEXT,
            nickname TEXT,
            display_tab_id TEXT,
            income_kind TEXT,
            amount_krw INTEGER,
            active INTEGER,
            source_revision INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE trip_tabs (
            tab_id TEXT PRIMARY KEY,
            deleted INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE board_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            row_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            prev_json TEXT,
            new_json TEXT,
            event_id TEXT,
            change_mode TEXT,
            actor TEXT,
            created_at TEXT,
            client_request_id TEXT,
            kind TEXT NOT NULL DEFAULT 'save',
            reverts_event_id TEXT NOT NULL DEFAULT ''
        )
    """)

    payload = json.dumps({"item": "교통비", "amount_krw": 10000, "occurred_on": "2026-10-01"})
    conn.execute(
        "INSERT INTO board_rows VALUES (?, ?, ?, ?, ?)",
        ("r-1", "expense", "tab-1", 1, payload),
    )
    conn.execute("INSERT INTO trip_tabs VALUES (?, ?)", ("tab-1", 0))

    # Test read_board_row
    rec = read_board_row(conn, "r-1")
    assert rec is not None
    assert rec["row_id"] == "r-1"
    assert rec["item"] == "교통비"
    assert rec["revision"] == 1

    # Nonexistent row
    assert read_board_row(conn, "r-none") is None

    # Test read_tab_rows
    tab_rows = read_tab_rows(
        conn,
        tab_id="tab-1",
        split_source_ids=set(),
        get_row_fn=lambda rid: rec if rid == "r-1" else None,
        split_remainder_fn=lambda rid: 0,
        display_occurred_on_fn=lambda r: r.get("occurred_on", ""),
    )
    assert len(tab_rows) == 1
    assert tab_rows[0]["row_id"] == "r-1"

    # Test count_visible_rows
    count = count_visible_rows(conn, set(), lambda sid: False)
    assert count == 1

    # Test conflict note
    conn.execute(
        "INSERT INTO board_revisions (row_id, revision, prev_json, new_json, event_id, change_mode, actor, created_at, client_request_id, kind, reverts_event_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("r-1", 1, "{}", json.dumps({"expected_revision": 1, "current_revision": 2}), "ev-c", "conflict", "owner", "now", "req-c", "conflict", ""),
    )
    conflict = read_row_conflict(conn, "r-1")
    assert conflict is not None
    assert conflict["row_id"] == "r-1"
    assert conflict["expected_revision"] == 1
    assert conflict["current_revision"] == 2

    conflicting_ids = read_conflicting_row_ids(conn)
    assert "r-1" in conflicting_ids

    # Test history reading
    history = read_history(conn, "r-1")
    assert len(history) == 1
    assert history[0]["kind"] == "conflict"


def test_facade_monkeypatch_contract(tmp_path, monkeypatch):
    import webapp.ledger_store as ls_module

    # Verify _row_to_record can be monkeypatched on webapp.ledger_store
    call_log = []
    original_row_to_record = ls_module._row_to_record

    def custom_row_to_record(kind: str, row: dict):
        call_log.append(kind)
        return original_row_to_record(kind, row)

    monkeypatch.setattr(ls_module, "_row_to_record", custom_row_to_record)

    store = LedgerStore(tmp_path / "test.db", seed_demo=True)
    try:
        assert len(call_log) > 0  # _seed called the monkeypatched _row_to_record

        # Test facade methods on real store
        rows = store.list_tab_rows(None)
        assert isinstance(rows, list)

        if rows:
            first_id = rows[0]["row_id"]
            single_row = store.get_row(first_id)
            assert single_row is not None
            assert single_row["row_id"] == first_id

            proj = store.projected(single_row)
            assert "display_amount_krw" in proj
            assert "display_occurred_on" in proj

            history = store.list_history(first_id)
            assert isinstance(history, list)
    finally:
        store.close()
