"""SPEC §11.2.1 계약 1: the owner's legacy board and the React API show the same rows.

The legacy board already renders the connected Google income block beside its
own income, but its row lists carried only COST records while React merges the
block into the row set — so the two paths disagreed on row IDs and counts for
the same snapshot, tab and filter. This test drives the real owner entry
questions (``resolve_role`` → ``_selected_rows``) and the real Plush dispatch,
then compares the actual user-visible row sets, not a debug side channel.

Synthetic store and synthetic Google snapshot only.
"""
from __future__ import annotations

import json
import re

import pytest

from webapp import ledger_board, ledger_query, plush_projection as projection
from webapp.tests.test_ledger_parity_spec_11_2_1 import (  # noqa: F401 - shared fixtures
    bound_store, make_expense, make_trip, react_ledger,
)
from webapp.tests.test_trip_google_income import income_context  # noqa: F401


def _owner_request(income_rows: list, *, verified: bool = True) -> None:
    """Put this thread in the owner request state, as resolve_role would."""
    ledger_board._ROLE_LOCAL.role = "owner"
    ledger_board._ROLE_LOCAL.session = None


def _connect_google(tab: str, key: str, monkeypatch, *, verified: bool = True,
                    amount: int = 1000) -> None:
    monkeypatch.setattr("webapp.google_ledger_page.load_mapping", lambda *a: {key: tab})
    monkeypatch.setattr("webapp.google_ledger_page.owner_rows", lambda *a: {
        "income": [dict(row=6, date="2026-11-11", name="합성고객",
                        deposit=amount, balance=0, extra=0, amount=amount)],
        "expense": []})
    from webapp.tests.test_trip_google_income import page
    monkeypatch.setattr(page, 'load_choices', lambda *a: {'choices': {key: 'main'}})


def test_owner_row_ids_and_counts_match_across_entry_paths(bound_store, income_context, monkeypatch):
    store, access = bound_store
    snapshot, key = income_context
    tab = make_trip(store)
    make_expense(store, tab, 12000, desc="합성 식비", day="2026-11-12")
    snapshot["trips"][0]["copies"]["main"]["income"].update(
        total=1000, row_sum=1000, sheet_total=1000, verified=True)
    _connect_google(tab, key, monkeypatch)
    _owner_request([])

    legacy_in, _legacy_ex, _wi, _we = ledger_board_owner_rows(tab, "", "in")
    status, body = react_ledger(store, tab, kind="income", page_size=200)
    assert status == 200, body

    react_ids = [row["id"] for row in body["rows"]]
    legacy_ids = [str(row.get("row_id") or "") for row in legacy_in]
    assert legacy_ids == react_ids, (
        f"owner 행 ID 집합/순서가 두 경로에서 다름: legacy {legacy_ids} != react {react_ids}")
    assert body["total_count"] == len(legacy_ids), (body["total_count"], legacy_ids)

    # The Google row is present on both paths and marked read-only.
    google_ids = [rid for rid in react_ids if rid.startswith("google-income|")]
    assert google_ids, react_ids
    for row in body["rows"]:
        if row["id"] in google_ids:
            assert row["read_only"] is True, row
    assert all(row.get("read_only") is True for row in legacy_in
               if str(row.get("row_id") or "").startswith("google-income|"))


def test_owner_expense_rows_keep_the_cost_only_set(bound_store, income_context, monkeypatch):
    """The Google block is income evidence; it never joins the expense row set."""
    store, access = bound_store
    snapshot, key = income_context
    tab = make_trip(store)
    expense_id = make_expense(store, tab, 12000, desc="합성 식비", day="2026-11-12")
    snapshot["trips"][0]["copies"]["main"]["income"].update(
        total=1000, row_sum=1000, sheet_total=1000, verified=True)
    _connect_google(tab, key, monkeypatch)
    _owner_request([])

    _li, legacy_ex, _wi, _we = ledger_board_owner_rows(tab, "", "ex")
    status, body = react_ledger(store, tab, kind="expense", page_size=200)
    assert status == 200, body
    assert [str(r.get("row_id")) for r in legacy_ex] == [row["id"] for row in body["rows"]]
    assert expense_id in {str(r.get("row_id")) for r in legacy_ex}


def test_unverified_google_block_shows_rows_but_never_confirms_income(bound_store, income_context, monkeypatch):
    """SPEC §11.2.1 계약 4: an unverified block is shown, not hidden — and not counted.

    Both paths keep the rows visible with their unverified state, and neither
    treats the block as confirmed income (GGL-014).
    """
    store, access = bound_store
    snapshot, key = income_context
    tab = make_trip(store)
    make_expense(store, tab, 12000, desc="합성 식비", day="2026-11-12")
    snapshot["trips"][0]["copies"]["main"]["income"].update(
        total=1000, row_sum=1000, sheet_total=1000, verified=False)
    _connect_google(tab, key, monkeypatch, verified=False)
    _owner_request([])

    legacy_in, _ex, _wi, _we = ledger_board_owner_rows(tab, "", "in")
    status, body = react_ledger(store, tab, kind="income", page_size=200)
    assert status == 200, body
    legacy_google = [r for r in legacy_in if str(r.get("row_id") or "").startswith("google-income|")]
    react_google = [r for r in body["rows"] if r["id"].startswith("google-income|")]
    # Same visible rows on both paths.
    assert [str(r.get("row_id")) for r in legacy_google] == [r["id"] for r in react_google], (
        legacy_google, react_google)
    assert len(react_google) == 1, react_google
    # Neither path confirms the block as income. 소유자 결정 2026-11-19 ②: an
    # income this ledger cannot confirm is one em dash.
    assert body["income_source"]["verified"] is False, body["income_source"]
    assert body["source_totals"]["filtered"]["google_verified"] == "False"
    assert body["trip"]["income"] == projection.UNKNOWN_INCOME, body["trip"]


def ledger_board_owner_rows(tab, query, kind):
    """The legacy board's own selection under the owner request state."""
    from webapp import ledger_design

    return ledger_design._selected_rows(tab, query, kind)
