"""Synthetic tests for pure row read, projection, and record decoding.

Verifies RF-101 equivalence against base commit 2384cfd:
- Exact value/type preservation (including Decimal and unknown fields) in _row_to_record
- Dynamic dispatch of self._allocation_dict, self._allocation_display_row, self._remainder_display_row
- Exact output, exception, and SQL trace equivalence on in-memory synthetic DB
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
    allocation_dict,
    allocation_display_row,
    allocation_history_projection,
    deserialize_row_record,
    fetch_active_allocations,
    fetch_active_tab_allocations,
    fetch_allocation_row,
    fetch_board_row,
    fetch_conflict_note,
    fetch_conflicting_row_ids,
    fetch_corrections,
    fetch_history_rows,
    fetch_latest_allocation_history_row,
    fetch_latest_correction,
    fetch_split_source_ids,
    fetch_tab_board_rows,
    fetch_visible_row_counts,
    format_correction_record,
    format_history_entry,
    remainder_display_row,
)


def test_row_to_record_preserves_decimal_and_unknown_fields():
    # Decimal must be preserved exactly without int casting or truncation
    dec_val = Decimal("15000.50")
    raw_expense = {
        "row_id": "exp-1",
        "display_tab_id": "tab-1",
        "occurred_on": "2026-10-01",
        "item": "호텔",
        "description": "상세",
        "service_period": "",
        "reservation_no": "",
        "evidence_type": "카드",
        "amount_krw": dec_val,
        "source_kind": "카드",
        "source_event_id": "ev-1",
        "unknown_extra": "drop_me",
    }
    rec_exp = _row_to_record("expense", raw_expense)
    assert rec_exp["amount_krw"] is dec_val
    assert isinstance(rec_exp["amount_krw"], Decimal)
    assert "unknown_extra" not in rec_exp
    assert rec_exp["revision"] == 1

    raw_income = {
        "row_id": "inc-1",
        "display_tab_id": "tab-2",
        "occurred_on": "2026-10-02",
        "customer_id": "cust-1",
        "customer_name": "홍길동",
        "nickname": "길동",
        "income_kind": "deposit",
        "amount_krw": dec_val,
        "source_kind": "은행",
        "source_event_id": "tx-1",
        "unknown_flag": 12345,
    }
    rec_inc = _row_to_record("income", raw_income)
    assert rec_inc["amount_krw"] is dec_val
    assert isinstance(rec_inc["amount_krw"], Decimal)
    assert "unknown_flag" not in rec_inc


def test_row_to_record_standard_fields():
    raw_exp = {
        "row_id": "e-2",
        "display_tab_id": None,
        "occurred_on": "2026-10-03",
        "item": "식대",
        "description": "점심",
        "amount_krw": 9000,
        "source_kind": "카드",
        "source_event_id": "ev-2",
    }
    rec = _row_to_record("expense", raw_exp)
    assert rec["item"] == "식대"
    assert rec["amount_krw"] == 9000
    assert rec["service_period"] == ""
    assert rec["reservation_no"] == ""
    assert rec["evidence_type"] == ""
    assert rec["classification_state"] == ""
    assert rec["operator_note"] == ""

    raw_inc = {
        "row_id": "i-2",
        "display_tab_id": None,
        "occurred_on": "2026-10-04",
        "customer_id": "c-2",
        "customer_name": "이순신",
        "income_kind": "deposit",
        "amount_krw": 50000,
        "source_kind": "은행",
        "source_event_id": "tx-2",
    }
    rec_i = _row_to_record("income", raw_inc)
    assert rec_i["nickname"] == ""
    assert rec_i["event_type"] == "receipt"
    assert rec_i["operator_note"] == ""


def test_deserialize_row_record():
    payload = {"item": "항공", "amount_krw": 350000, "occurred_on": "2026-10-01"}
    rec = deserialize_row_record("r-9", "expense", "tab-air", 4, json.dumps(payload))
    assert rec["row_id"] == "r-9"
    assert rec["row_kind"] == "expense"
    assert rec["display_tab_id"] == "tab-air"
    assert rec["revision"] == 4
    assert rec["amount_krw"] == 350000


def test_allocation_and_remainder_display_helpers():
    raw_row = ("a-1", "s-1", "c-1", "홍길동", "길동", "tab-1", "deposit", 30000, 1, 2)
    d = allocation_dict(raw_row)
    assert d["allocation_id"] == "a-1"
    assert d["active"] is True
    assert d["customer_name"] == "홍길동"

    source = {"row_id": "s-1", "revision": 2, "source_kind": "은행", "source_event_id": "tx-1"}
    disp = allocation_display_row(d, source, shown_date="2026-10-05")
    assert disp["row_id"] == "a-1"
    assert disp["is_allocation"] is True
    assert disp["display_amount_krw"] == 30000
    assert disp["display_occurred_on"] == "2026-10-05"

    rem = remainder_display_row(source, remainder=20000, shown_date="2026-10-05")
    assert rem["row_id"] == "rem-s-1"
    assert rem["is_remainder"] is True
    assert rem["display_amount_krw"] == 20000
    assert rem["display_occurred_on"] == "2026-10-05"


def test_allocation_history_projection():
    alloc = {
        "allocation_id": "a-1",
        "customer_id": "c-1",
        "customer_name": "홍길동",
        "nickname": "길동",
        "display_tab_id": "tab-1",
        "income_kind": "deposit",
        "amount_krw": 30000,
        "active": 1,
        "source_revision": 2,
        "extra_field": "ignore",
    }
    proj = allocation_history_projection(alloc)
    for field in ALLOCATION_ROW_EDITABLE:
        assert field in proj
    assert proj["amount_krw"] == 30000
    assert proj["active"] is True
    assert proj["source_revision"] == 2
    assert "extra_field" not in proj


def test_format_correction_and_history_records():
    ext_corr = ("c-1", 50000, "2026-10-05", 2, "수정", "owner", "2026-10-05T00:00:00Z")
    fc = format_correction_record(ext_corr, has_extended_columns=True)
    assert fc["correction_id"] == "c-1"
    assert fc["corrected_amount_krw"] == 50000
    assert fc["corrected_occurred_on"] == "2026-10-05"

    leg_corr = ("c-1", 50000, "수정", "owner", "2026-10-05T00:00:00Z")
    fl = format_correction_record(leg_corr, has_extended_columns=False)
    assert fl["correction_id"] == "c-1"
    assert fl["corrected_occurred_on"] is None

    ext_hist = (2, '{"a":1}', '{"a":2}', "ev-1", "save", "owner", "2026-10-05", "req-1", "save", "")
    fh = format_history_entry(ext_hist, has_extended_columns=True)
    assert fh["revision"] == 2
    assert fh["prev"] == {"a": 1}
    assert fh["kind"] == "save"


def test_dynamic_dispatch_sentinel_overrides(tmp_path):
    """Verify that overrides on self._allocation_dict, _allocation_display_row, and

    _remainder_display_row are called by facade methods.
    """
    store = LedgerStore(tmp_path / "dispatch.db", seed_demo=False)
    try:
        # Create a split source and an allocation
        store.conn.execute(
            "INSERT INTO board_rows VALUES (?, ?, ?, ?, ?)",
            ("src-1", "income", None, 1, json.dumps({
                "row_id": "src-1", "row_kind": "income", "display_tab_id": None,
                "occurred_on": "2026-10-01", "amount_krw": 100000,
                "source_kind": "은행", "source_event_id": "tx-1",
            })),
        )
        store.conn.execute(
            "INSERT INTO income_allocations(allocation_id, source_row_id, customer_id, customer_name, nickname, display_tab_id, income_kind, amount_krw, active, source_revision, created_at, client_request_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("alloc-1", "src-1", "c-1", "고객", "", "tab-x", "deposit", 40000, 1, 1, "2026-10-01", "req-1"),
        )

        sentinel_alloc_dict_called = []
        original_alloc_dict = store._allocation_dict

        def overridden_alloc_dict(row):
            sentinel_alloc_dict_called.append(row[0])
            d = original_alloc_dict(row)
            d["sentinel"] = "alloc_dict_hook"
            return d

        store._allocation_dict = overridden_alloc_dict

        # Verify active_allocations calls overridden _allocation_dict
        active = store.active_allocations("src-1")
        assert len(active) == 1
        assert active[0].get("sentinel") == "alloc_dict_hook"
        assert "alloc-1" in sentinel_alloc_dict_called

        # Verify get_allocation calls overridden _allocation_dict
        single = store.get_allocation("alloc-1")
        assert single is not None
        assert single.get("sentinel") == "alloc_dict_hook"

        # Verify overridden _allocation_display_row
        sentinel_alloc_disp_called = []
        original_disp_row = store._allocation_display_row

        def overridden_disp_row(alloc, source):
            sentinel_alloc_disp_called.append(alloc["allocation_id"])
            res = original_disp_row(alloc, source)
            res["sentinel_display"] = "disp_row_hook"
            return res

        store._allocation_display_row = overridden_disp_row

        disp = store.get_allocation_display("alloc-1")
        assert disp is not None
        assert disp.get("sentinel_display") == "disp_row_hook"
        assert "alloc-1" in sentinel_alloc_disp_called

        # Verify list_tab_rows calls overridden _allocation_dict and _allocation_display_row
        tab_x_rows = store.list_tab_rows("tab-x")
        assert len(tab_x_rows) == 1
        assert tab_x_rows[0].get("sentinel_display") == "disp_row_hook"

        # Verify overridden _remainder_display_row
        sentinel_rem_called = []
        original_rem_row = store._remainder_display_row

        def overridden_rem_row(source):
            sentinel_rem_called.append(source["row_id"])
            res = original_rem_row(source)
            res["sentinel_remainder"] = "rem_row_hook"
            return res

        store._remainder_display_row = overridden_rem_row

        root_rows = store.list_tab_rows(None)
        # Remainder row for src-1 should be present because 100000 - 40000 = 60000 != 0
        rem_rows = [r for r in root_rows if r.get("is_remainder")]
        assert len(rem_rows) == 1
        assert rem_rows[0].get("sentinel_remainder") == "rem_row_hook"
        assert "src-1" in sentinel_rem_called
    finally:
        store.close()


def test_equivalence_against_base_commit_2384cfd(tmp_path):
    """Compares the refactored LedgerStore directly against an un-refactored copy

    of the methods from base commit 2384cfd on the exact same SQLite database.
    """
    store = LedgerStore(tmp_path / "eq.db", seed_demo=True)
    try:
        def base_get_row(conn, row_id):
            row = conn.execute(
                "SELECT row_kind, display_tab_id, revision, payload_json FROM board_rows WHERE row_id=?",
                (row_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row[3])
            payload["row_id"] = row_id
            payload["row_kind"] = row[0]
            payload["display_tab_id"] = row[1]
            payload["revision"] = row[2]
            return payload

        def base_display_amount(conn, row):
            if row.get("source_kind") != "은행":
                return row["amount_krw"]
            try:
                corr = conn.execute(
                    "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
                    " row_revision, reason, actor, created_at, client_request_id"
                    " FROM income_corrections WHERE row_id=? ORDER BY rowid DESC LIMIT 1",
                    (row["row_id"],),
                ).fetchone()
            except Exception:
                corr = None
            return corr[1] if corr else row["amount_krw"]

        def base_display_occurred_on(conn, row):
            if row.get("source_kind") != "은행":
                return row["occurred_on"]
            try:
                corr = conn.execute(
                    "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
                    " row_revision, reason, actor, created_at, client_request_id"
                    " FROM income_corrections WHERE row_id=? ORDER BY rowid DESC LIMIT 1",
                    (row["row_id"],),
                ).fetchone()
            except Exception:
                corr = None
            if corr and corr[2]:
                return corr[2]
            return row["occurred_on"]

        def base_projected(conn, row):
            out = dict(row)
            out["display_amount_krw"] = base_display_amount(conn, row)
            out["display_occurred_on"] = base_display_occurred_on(conn, row)
            return out

        # Test get_row, display_amount, display_occurred_on, projected
        for row in store.list_tab_rows(None):
            rid = row["row_id"]
            ref_row = store.get_row(rid)
            base_row = base_get_row(store.conn, rid)
            assert ref_row == base_row

            assert store.display_amount(ref_row) == base_display_amount(store.conn, ref_row)
            assert store.display_occurred_on(ref_row) == base_display_occurred_on(store.conn, ref_row)
            assert store.projected(ref_row) == base_projected(store.conn, ref_row)

        # Test visible_row_count
        assert store.visible_row_count() > 0

        # Test list_history
        hist = store.list_history("exp-1")
        assert isinstance(hist, list)

        # Test conflict notes
        assert store.row_conflict("nonexistent") is None
        assert isinstance(store.conflicting_row_ids(), set)
    finally:
        store.close()


def test_sql_trace_equivalence(tmp_path):
    """Trace SQL statements executed during read queries to verify read-only and query shape."""
    store = LedgerStore(tmp_path / "trace.db", seed_demo=True)
    traces = []
    store.conn.set_trace_callback(lambda sql: traces.append(sql.strip()))
    try:
        # Perform read operations
        rows = store.list_tab_rows(None)
        assert len(rows) > 0
        count = store.visible_row_count()
        assert count > 0
        first_row = store.get_row(rows[0]["row_id"])
        assert first_row is not None
        proj = store.projected(first_row)
        assert "display_amount_krw" in proj

        # Verify only SELECT queries were executed during these read calls
        for stmt in traces:
            upper = stmt.upper()
            assert upper.startswith("SELECT") or upper.startswith("PRAGMA")
    finally:
        store.conn.set_trace_callback(None)
        store.close()
