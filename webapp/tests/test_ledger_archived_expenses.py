"""Synthetic coverage for the owner-only archived expense helper.

The operational archive copy demonstrated a nonstandard layout whose normalized
rows the official ``owner_rows`` read still returns, with ``verified`` false.
These tests pin: owner/mapping/closure/source gates, the shared owner_payload
selection basis, normalized nonstandard rows with unconfirmed amounts preserved
as ``None``, no zero coercion, no reservation/participant projection, and the
preserved source date string with its trip ledger year.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from app import google_authority
from webapp import ledger_archived_expenses as helper

TRIP = "trip-a"
KEY = "2026_taipei"
CELLS = {"B": "2026-01-02", "C": "Cafe", "D": None, "E": None, "F": None, "G": "card"}
ROW_KEYS = {"row", "date", "date_year", "payee", "category", "period", "evidence", "amount"}


def _now():
    return dt.datetime.now(google_authority.KST)


def _snapshot(*, layout="nonstandard", status="ok", stale=False, closure="closed",
              closure_current=True, review=None, blocked_by=None, verified=False,
              choices=True):
    stamp = _now().isoformat()
    sources = {
        "main": {"status": status, "error_code": None, "stale": stale,
                 "last_ok_at": stamp, "checked_at": stamp},
        "archive": {"status": status, "error_code": None, "stale": stale,
                    "last_ok_at": stamp, "checked_at": stamp},
    }
    copy = {"sheet": KEY, "layout": layout, "income": {"verified": False}, "expense": None,
            "flags": []}
    if layout == "rev":
        copy["expense"] = {"verified": False, "total": None}
    trip = {"key": KEY, "owner_id": "aslan", "sheet": KEY, "canonical_source": "archive",
            "copies": {"archive": copy},
            "closure": closure, "closure_current": closure_current, "verified": verified,
            "review": review or []}
    if blocked_by is not None:
        trip["blocked_by"] = blocked_by
    return {"synced_at": _now().isoformat(), "sources": sources, "trips": [trip],
            "choices": {KEY: "archive"} if choices else {}}


def _private(amount=100, cells=CELLS):
    return {"archive": {"trips": {KEY: {"income": [],
            "expense": [{"row": 12, "cells": dict(cells), "amount": amount}]}}}}


def _install(monkeypatch, snapshot, private, *, mapping=None):
    calls = []

    def load_consistent(path, rows):
        calls.append((path, rows))
        return snapshot, private

    monkeypatch.setattr(helper.google_authority, "load_consistent", load_consistent)
    monkeypatch.setattr(helper.google_ledger_page, "snapshot_path", lambda: SimpleNamespace())
    monkeypatch.setattr(helper.google_ledger_page, "rows_path", lambda: SimpleNamespace())
    monkeypatch.setattr(helper.google_ledger_page, "load_mapping",
                        lambda path: {KEY: TRIP} if mapping is None else mapping)
    monkeypatch.setattr(helper.google_ledger_page, "load_choices",
                        lambda path: {"choices": snapshot["choices"]})
    return calls


def _load(monkeypatch, snapshot=None, *, private=None, owner=True, native=None, mapping=None):
    snapshot = snapshot if snapshot is not None else _snapshot()
    private = private if private is not None else _private()
    calls = _install(monkeypatch, snapshot, private, mapping=mapping)
    result = helper.load(TRIP, owner=owner, native_expenses=native or [])
    return result, calls


def test_viewer_and_bad_arguments_do_not_read_source(monkeypatch):
    def explode(*args):
        raise AssertionError("source read for a refused request")

    monkeypatch.setattr(helper.google_authority, "load_consistent", explode)
    for owner in (False, None):
        assert helper.load(TRIP, owner=owner, native_expenses=[]) is None
    for tab in ("", "unclassified", None, 7):
        assert helper.load(tab, owner=True, native_expenses=[]) is None


def test_native_expenses_suppress_the_archive_copy(monkeypatch):
    def explode(*args):
        raise AssertionError("source read despite native expenses")

    monkeypatch.setattr(helper.google_authority, "load_consistent", explode)
    assert helper.load(TRIP, owner=True, native_expenses=[{"row_kind": "expense"}]) is None


def test_absent_mapping_is_refused(monkeypatch):
    result, _ = _load(monkeypatch, mapping={})
    assert result is None


def test_ambiguous_mapping_is_refused(monkeypatch):
    result, _ = _load(monkeypatch, mapping={KEY: TRIP, KEY + "b": TRIP})
    assert result is None
    result, _ = _load(monkeypatch, mapping={KEY: "other"})
    assert result is None


def test_nonstandard_archive_rows_are_returned_unverified(monkeypatch):
    snapshot = _snapshot(layout="nonstandard", blocked_by=["COPY_NOT_VERIFIED"])
    result, calls = _load(monkeypatch, snapshot)
    assert result is not None
    assert result["verified"] is False
    assert result["rows"] == [{
        "row": 12, "date": "2026-01-02", "date_year": None, "payee": "Cafe",
        "category": "", "period": "", "evidence": "card", "amount": "100"}]
    assert set(result["rows"][0]) == ROW_KEYS
    assert len(calls) == 1


def test_source_date_string_and_trip_ledger_year_are_preserved(monkeypatch):
    """The common query parses the preserved string with the trip's ledger year."""
    snapshot = _snapshot()
    snapshot["trips"][0]["period"] = {"year": 2027, "starts_on": "2027-01-02",
                                       "ends_on": "2027-01-03"}
    cells = dict(CELLS, B="66.1.2")
    result, _ = _load(monkeypatch, snapshot, private=_private(cells=cells))
    row = result["rows"][0]
    assert row["date"] == "66.1.2"
    assert row["date_year"] == 2027


def test_missing_amount_is_null_and_real_zero_stays_zero(monkeypatch):
    result, _ = _load(monkeypatch, private=_private(amount=None))
    assert result["rows"][0]["amount"] is None
    result, _ = _load(monkeypatch, private=_private(amount=0))
    assert result["rows"][0]["amount"] == "0"


def test_copy_must_be_the_selected_archive(monkeypatch):
    snapshot = _snapshot()
    snapshot["trips"][0]["copies"]["main"] = {"sheet": KEY, "layout": "rev",
                                              "income": {"verified": True},
                                              "expense": {"verified": True}}
    # Both copies exist and the archive copy is still the selected one.
    result, _ = _load(monkeypatch, snapshot)
    assert result is not None
    # The owner selected the main copy instead: no archive rows are returned.
    snapshot = _snapshot(choices=False)
    snapshot["choices"] = {KEY: "main"}
    snapshot["trips"][0]["copies"]["main"] = {"sheet": KEY, "layout": "rev",
                                              "income": {"verified": True},
                                              "expense": {"verified": True}}
    result, _ = _load(monkeypatch, snapshot)
    assert result is None


@pytest.mark.parametrize("kwargs", [
    {"closure": "open"}, {"closure_current": False}, {"stale": True}, {"status": "error"},
])
def test_closure_and_source_freshness_are_required(monkeypatch, kwargs):
    result, _ = _load(monkeypatch, _snapshot(**kwargs))
    assert result is None


@pytest.mark.parametrize("code", sorted(helper._ID_BLOCKERS | {"POSSIBLE_DUPLICATE"}))
def test_identity_blockers_refuse_even_a_normalized_read(monkeypatch, code):
    result, _ = _load(monkeypatch, _snapshot(review=[code]))
    assert result is None, code


def test_source_failures_are_unavailable_not_zero(monkeypatch):
    monkeypatch.setattr(helper.google_authority, "load_consistent",
                        lambda *a: (_ for _ in ()).throw(google_authority.SnapshotError("X")))
    assert helper.load(TRIP, owner=True, native_expenses=[]) is None

    def broken(*args):
        raise ValueError("STATE")

    monkeypatch.setattr(helper.google_authority, "load_consistent",
                        lambda *a: (_snapshot(), _private()))
    monkeypatch.setattr(helper.google_ledger_page, "snapshot_for_display", broken)
    assert helper.load(TRIP, owner=True, native_expenses=[]) is None

    monkeypatch.setattr(helper.google_ledger_page, "snapshot_for_display",
                        lambda value: value)
    monkeypatch.setattr(helper.google_ledger_page, "owner_rows", broken)
    assert helper.load(TRIP, owner=True, native_expenses=[]) is None
